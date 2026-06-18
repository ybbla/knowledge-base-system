import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.models import (
    KnowledgeChunk,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
)


@dataclass
class RetrievalDebugInfo:
    """检索全链路调试信息。"""
    # 查询改写
    original_query: str
    rewritten_query: str
    keywords: list[str] = field(default_factory=list)
    # 各阶段候选 (chunk_id, score)
    vector_candidates: list[tuple[str, float]] = field(default_factory=list)
    bm25_candidates: list[tuple[str, float]] = field(default_factory=list)
    fused_candidates: list[tuple[str, float]] = field(default_factory=list)
    rerank_results: list[dict] = field(default_factory=list)
    # 统计
    vector_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    rerank_count: int = 0
    # 标志位
    used_milvus_hybrid: bool = False
    errors: list[str] = field(default_factory=list)
from assets.base import AssetStore
from indexing.base import BM25Index, VectorIndex
from indexing.fusion import rrf_fusion
from indexing.milvus_hybrid import hybrid_search as milvus_hybrid_search
from llm.query_rewriter import QueryRewriter
from llm.reranker import Reranker
from llm.volcengine_client import embedding_client

logger = logging.getLogger(__name__)


def _renderable_storage_uri(storage_uri: str | None) -> str | None:
    if not storage_uri:
        return storage_uri
    if storage_uri.startswith(("http://", "https://", "file://", "minio://")):
        return storage_uri
    return f"file:///{Path(storage_uri).resolve().as_posix()}"


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

    def search(
        self,
        query: str,
        top_k: int | None = None,
        category: str | None = None,
        debug: bool = False,
    ) -> SearchResult | tuple[SearchResult, RetrievalDebugInfo]:
        """Execute full retrieval pipeline and return SearchResult.

        Args:
            query: 查询词
            top_k: 返回结果数量
            category: 分类过滤
            debug: 是否返回调试信息，True 时返回 (result, debug_info)
        """
        cfg = get_settings(reload_env=True)
        final_k = top_k or cfg.final_top_k

        # 初始化调试信息
        debug_info: RetrievalDebugInfo | None = None
        if debug:
            debug_info = RetrievalDebugInfo(original_query=query, rewritten_query=query)

        # 1. Query rewrite
        rewrite_result = self._rewriter.rewrite(query)
        rewritten = rewrite_result["rewritten_query"]
        keywords = rewrite_result.get("keywords", [query])
        keywords_str = " ".join(keywords)

        if debug and debug_info:
            debug_info.rewritten_query = rewritten
            debug_info.keywords = keywords

        # 2. 双路检索：Milvus 可用时优先走原生 Hybrid Search。
        query_vec: list[float] | None = None
        try:
            query_vecs = embedding_client.embed_text([rewritten])
            query_vec = query_vecs[0]
        except Exception as e:
            err_msg = f"Vector embedding failed: {e}"
            logger.exception(err_msg)
            if debug and debug_info:
                debug_info.errors.append(err_msg)
            query_vec = None

        hybrid_results: list[tuple[str, float]] = []
        if query_vec is not None and cfg.milvus_enabled:
            try:
                manager = getattr(self._vector_index, "manager")
                encode_query = getattr(self._bm25_index, "encode_query")
                sparse_query = encode_query(keywords_str)
                hybrid_results = milvus_hybrid_search(
                    manager,
                    query_vec,
                    sparse_query,
                    top_k=cfg.fusion_top_k,
                    category=category,
                    rrf_k=cfg.rrf_k,
                )
                if debug and debug_info:
                    debug_info.used_milvus_hybrid = True
            except Exception as e:
                err_msg = f"Milvus hybrid retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)

        # 单路检索在 Hybrid 成功时用于补充分数明细；
        # Hybrid 失败时则作为应用层 RRF fallback 的候选来源。
        vec_results: list[tuple[str, float]] = []
        bm25_results: list[tuple[str, float]] = []
        if hybrid_results:
            try:
                vec_results = self._vector_index.search(
                    query_vec,
                    top_k=cfg.vector_top_k,
                    category=category,
                )
            except Exception as e:
                err_msg = f"Vector score detail retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)
                vec_results = []

            try:
                bm25_results = self._bm25_index.search(
                    keywords_str,
                    top_k=cfg.bm25_top_k,
                    category=category,
                )
            except Exception as e:
                err_msg = f"BM25 score detail retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)
                bm25_results = []
        else:
            try:
                if query_vec is None:
                    vec_results = []
                else:
                    vec_results = self._vector_index.search(
                        query_vec,
                        top_k=cfg.vector_top_k,
                        category=category,
                    )
            except Exception as e:
                err_msg = f"Vector retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)
                vec_results = []

            try:
                bm25_results = self._bm25_index.search(
                    keywords_str,
                    top_k=cfg.bm25_top_k,
                    category=category,
                )
            except Exception as e:
                err_msg = f"BM25 retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)
                bm25_results = []

        # 记录召回结果
        if debug and debug_info:
            debug_info.vector_candidates = vec_results
            debug_info.bm25_candidates = bm25_results
            debug_info.vector_count = len(vec_results)
            debug_info.bm25_count = len(bm25_results)

        if hybrid_results:
            top_fused = hybrid_results[: cfg.fusion_top_k]
        else:
            fused = rrf_fusion(vec_results, bm25_results, k=cfg.rrf_k)
            sorted_fused = sorted(fused.items(), key=lambda x: x[1], reverse=True)
            top_fused = sorted_fused[: cfg.fusion_top_k]

        # 记录融合结果
        if debug and debug_info:
            debug_info.fused_candidates = top_fused
            debug_info.fused_count = len(top_fused)

        if not top_fused:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                return result, debug_info
            return result

        # 4. Get chunk objects
        top_chunk_ids = [cid for cid, _ in top_fused]
        candidates = self._chunk_store.get_batch(top_chunk_ids)

        # 5. LLM Rerank
        reranked = self._reranker.rerank(query, candidates)

        # 记录 Rerank 结果
        if debug and debug_info:
            debug_info.rerank_results = reranked
            debug_info.rerank_count = len(reranked)

        # 6. Build result items
        items: list[SearchResultItem] = []
        score_map: dict[str, float] = dict(top_fused)
        vec_map = {cid: score for cid, score in vec_results}
        bm25_map = {cid: score for cid, score in bm25_results}

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
                storage_uri = _renderable_storage_uri(asset.storage_uri if asset else None)
                if (
                    storage_uri
                    and storage_uri.startswith("minio://")
                    and self._asset_store
                    and hasattr(self._asset_store, "presign_uri")
                ):
                    storage_uri = self._asset_store.presign_uri(storage_uri)
                resolved_assets.append(
                    {
                        "asset_id": ref.asset_id,
                        "relation": ref.relation.value,
                        "storage_uri": storage_uri,
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
                    category=chunk.category,
                    knowledge_type=chunk.knowledge_type,
                    score_components=ScoreComponents(
                        vector=vec_map.get(cid, 0.0),
                        bm25=bm25_map.get(cid, 0.0),
                        rerank=rank_entry.get("relevance_score", 0.0),
                    ),
                    asset_refs=resolved_assets,
                    source_refs=chunk.source_refs,
                    metadata={
                        "title_path": chunk.metadata.get("title_path", []),
                    },
                )
            )

        result = SearchResult(
            query=query,
            rewritten_query=rewritten,
            total_count=len(candidates),
            results=items,
        )

        if debug and debug_info:
            return result, debug_info
        return result
