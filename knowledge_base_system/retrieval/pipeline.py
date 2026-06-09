import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.models import (
    KnowledgeChunk,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
)
from assets.base import AssetStore
from indexing.base import BM25Index, VectorIndex
from indexing.fusion import rrf_fusion
from llm.query_rewriter import QueryRewriter
from llm.reranker import Reranker
from llm.volcengine_client import embedding_client

logger = logging.getLogger(__name__)


@dataclass
class ChunkStore:
    """Simple in-memory chunk store for lookup by ID."""
    _chunks: dict[str, KnowledgeChunk] = field(default_factory=dict)

    def put(self, chunk: KnowledgeChunk) -> None:
        self._chunks[chunk.chunk_id] = chunk

    def get(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._chunks.get(chunk_id)

    def get_batch(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        return [c for cid in chunk_ids if (c := self._chunks.get(cid))]

    def count(self) -> int:
        return len(self._chunks)


class RetrievalPipeline:
    """Orchestrate the full retrieval flow."""

    def __init__(
        self,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        chunk_store: ChunkStore,
        asset_store: AssetStore | None = None,
    ) -> None:
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._chunk_store = chunk_store
        self._asset_store = asset_store
        self._rewriter = QueryRewriter()
        self._reranker = Reranker()

    def search(self, query: str, top_k: int | None = None) -> SearchResult:
        """Execute full retrieval pipeline and return SearchResult."""
        final_k = top_k or settings.final_top_k

        # 1. Query rewrite
        rewrite_result = self._rewriter.rewrite(query)
        rewritten = rewrite_result["rewritten_query"]
        keywords_str = " ".join(rewrite_result.get("keywords", [query]))

        # 2. Dual-path retrieval
        # Vector
        try:
            query_vecs = embedding_client.embed_text([rewritten])
            query_vec = query_vecs[0]
            vec_results = self._vector_index.search(
                query_vec, top_k=settings.vector_top_k
            )
        except Exception:
            logger.exception("Vector retrieval failed")
            vec_results = []

        # BM25
        try:
            bm25_results = self._bm25_index.search(
                keywords_str, top_k=settings.bm25_top_k
            )
        except Exception:
            logger.exception("BM25 retrieval failed")
            bm25_results = []

        # 3. RRF fusion
        fused = rrf_fusion(vec_results, bm25_results)

        # Sort by fused score and take top 20
        sorted_fused = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        top_fused = sorted_fused[: settings.fusion_top_k]

        if not top_fused:
            return SearchResult(query=query, rewritten_query=rewritten)

        # 4. Get chunk objects
        top_chunk_ids = [cid for cid, _ in top_fused]
        candidates = self._chunk_store.get_batch(top_chunk_ids)

        # 5. LLM Rerank
        reranked = self._reranker.rerank(query, candidates)
        rerank_map = {r["chunk_id"]: r for r in reranked}

        # 6. Build result items
        items: list[SearchResultItem] = []
        score_map: dict[str, float] = dict(top_fused)
        vec_map: dict[str, float] = {
            cid: score for cid, score in vec_results
        }
        bm25_map: dict[str, float] = {
            cid: score for cid, score in bm25_results
        }

        # Follow reranked order
        for rank_entry in reranked[:final_k]:
            cid = rank_entry["chunk_id"]
            chunk = self._chunk_store.get(cid)
            if not chunk:
                continue

            # Resolve asset refs for SearchResult (add storage_uri)
            resolved_assets: list[dict[str, Any]] = []
            for ref in chunk.asset_refs:
                asset = self._asset_store.get(ref.asset_id) if self._asset_store else None
                resolved_assets.append(
                    {
                        "asset_id": ref.asset_id,
                        "relation": ref.relation.value,
                        "storage_uri": asset.storage_uri if asset else None,
                        "original_uri": asset.original_uri if asset else None,
                        "linked_text": ref.linked_text or "",
                        "caption": ref.caption or "",
                        "render": {
                            "mode": ref.render.mode,
                            "position": ref.render.position,
                        },
                    }
                )

            items.append(
                SearchResultItem(
                    chunk_id=chunk.chunk_id,
                    title=chunk.title,
                    content=chunk.content,
                    score=rank_entry.get("relevance_score", score_map.get(cid, 0.0)),
                    score_components=ScoreComponents(
                        vector=vec_map.get(cid, 0.0),
                        bm25=bm25_map.get(cid, 0.0),
                        rerank=rank_entry.get("relevance_score", 0.0),
                    ),
                    asset_refs=resolved_assets,
                    source_refs=chunk.source_refs,
                    metadata={
                        "title_path": chunk.metadata.get("title_path", []),
                        "knowledge_type": chunk.knowledge_type.value,
                    },
                )
            )

        return SearchResult(
            query=query,
            rewritten_query=rewritten,
            total_count=len(candidates),
            results=items,
        )
