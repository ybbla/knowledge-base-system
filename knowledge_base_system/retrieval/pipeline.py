import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.models import (
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
    errors: list[str] = field(default_factory=list)
from assets.base import AssetStore
from indexing.base import BM25Index, VectorIndex
from indexing.fusion import rrf_fusion
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


class RetrievalPipeline:
    """Orchestrate the full retrieval flow."""

    def __init__(
        self,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        chunk_store: Any,
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
        knowledge_type: str | None = None,
        debug: bool = False,
    ) -> SearchResult | tuple[SearchResult, RetrievalDebugInfo]:
        """Execute full retrieval pipeline and return SearchResult.

        Args:
            query: 查询词
            top_k: 返回结果数量
            category: 分类过滤（Milvus expr）
            knowledge_type: 知识类型过滤（Milvus expr）
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

        # 2. Embedding
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

        # 3. 并行双路检索
        vec_results: list[tuple[str, float]] = []
        bm25_results: list[tuple[str, float]] = []

        def _search_vector():
            if query_vec is None:
                return []
            return self._vector_index.search(
                query_vec,
                top_k=cfg.vector_top_k,
                category=category,
                knowledge_type=knowledge_type,
            )

        def _search_bm25():
            return self._bm25_index.search(
                keywords_str,
                top_k=cfg.bm25_top_k,
                category=category,
                knowledge_type=knowledge_type,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_vec = executor.submit(_search_vector) if query_vec is not None else None
            future_bm25 = executor.submit(_search_bm25)

            try:
                bm25_results = future_bm25.result()
            except Exception as e:
                err_msg = f"BM25 retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)

            if future_vec is not None:
                try:
                    vec_results = future_vec.result()
                except Exception as e:
                    err_msg = f"Vector retrieval failed: {e}"
                    logger.exception(err_msg)
                    if debug and debug_info:
                        debug_info.errors.append(err_msg)

        # 记录召回结果
        if debug and debug_info:
            debug_info.vector_candidates = vec_results
            debug_info.bm25_candidates = bm25_results
            debug_info.vector_count = len(vec_results)
            debug_info.bm25_count = len(bm25_results)

        # 4. 外部 RRF 融合（唯一路径）
        if not vec_results and not bm25_results:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                return result, debug_info
            return result

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

        # 5. Get chunk objects from PG
        top_chunk_ids = [cid for cid, _ in top_fused]
        candidates = self._chunk_store.get_batch(top_chunk_ids)

        # 6. LLM Rerank
        reranked = self._reranker.rerank(query, candidates)

        # 记录 Rerank 结果
        if debug and debug_info:
            debug_info.rerank_results = reranked
            debug_info.rerank_count = len(reranked)

        # 7. Build result items
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
                        rrf=score_map.get(cid, 0.0),
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
