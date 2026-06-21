import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.models import (
    KnowledgeChunk,
    KnowledgeType,
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


def _parse_json_field(raw: Any, default: Any = None) -> Any:
    """解析 Milvus VARCHAR 存储的 JSON 字符串字段。"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default
    return raw if raw is not None else default


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

        # 3. 并行双路检索（返回 (chunk_id, score, fields) — Milvus 全量标量字段）
        vec_results: list[tuple[str, float, dict]] = []
        bm25_results: list[tuple[str, float, dict]] = []

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

        # 从 Milvus 返回字段构建 chunk 数据（无需查 PG）
        fields_map: dict[str, dict] = {}
        for cid, score, fields in vec_results + bm25_results:
            fields_map[cid] = fields

        # 记录召回结果（debug 用）
        if debug and debug_info:
            debug_info.vector_candidates = [(c, s) for c, s, _ in vec_results]
            debug_info.bm25_candidates = [(c, s) for c, s, _ in bm25_results]
            debug_info.vector_count = len(vec_results)
            debug_info.bm25_count = len(bm25_results)

        # 4. RRF 融合
        if not vec_results and not bm25_results:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                return result, debug_info
            return result

        fused = rrf_fusion(
            [(c, s) for c, s, _ in vec_results],
            [(c, s) for c, s, _ in bm25_results],
            k=cfg.rrf_k,
        )
        sorted_fused = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        top_fused = sorted_fused[: cfg.fusion_top_k]

        if debug and debug_info:
            debug_info.fused_candidates = top_fused
            debug_info.fused_count = len(top_fused)

        if not top_fused:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                return result, debug_info
            return result

        # 5. LLM Rerank（用 Milvus 字段构建轻量 chunk 对象）
        top_chunk_ids = [cid for cid, _ in top_fused]
        candidates = [
            KnowledgeChunk(
                chunk_id=cid,
                doc_id=fields_map.get(cid, {}).get("doc_id", ""),
                title=fields_map.get(cid, {}).get("title", ""),
                content=fields_map.get(cid, {}).get("content", ""),
                knowledge_type=KnowledgeType(fields_map.get(cid, {}).get("knowledge_type", "declarative")),
                category=fields_map.get(cid, {}).get("category", "通用"),
            )
            for cid in top_chunk_ids if cid in fields_map
        ]
        reranked = self._reranker.rerank(query, candidates)

        if debug and debug_info:
            debug_info.rerank_results = reranked
            debug_info.rerank_count = len(reranked)

        # Rerank 全部成功才用 LLM 分排序，否则统一回退 RRF 分（避免不同量纲混排）
        all_reranked = all("relevance_score" in r for r in reranked) if reranked else False

        # 6. 构建结果（直接用 Milvus 字段，不查 PG）
        items: list[SearchResultItem] = []
        score_map: dict[str, float] = dict(top_fused)
        vec_map = {c: s for c, s, _ in vec_results}
        bm25_map = {c: s for c, s, _ in bm25_results}

        # 排序：Rerank 全成功按 LLM 分降序，否则按 RRF 分降序
        sorted_items = sorted(
            reranked,
            key=lambda r: r.get("relevance_score", score_map.get(r["chunk_id"], 0.0)) if all_reranked
                     else score_map.get(r["chunk_id"], 0.0),
            reverse=True,
        )

        for rank_entry in sorted_items[:final_k]:
            cid = rank_entry["chunk_id"]
            fields = fields_map.get(cid)
            if not fields:
                continue

            # Milvus VARCHAR 字段需解析 JSON
            src_refs = _parse_json_field(fields.get("source_refs"), [])
            meta = _parse_json_field(fields.get("metadata"), {})

            items.append(
                SearchResultItem(
                    chunk_id=cid,
                    title=fields.get("title", ""),
                    content=fields.get("content", ""),
                    score=rank_entry.get("relevance_score") if all_reranked else score_map.get(cid, 0.0),
                    category=fields.get("category", "通用"),
                    knowledge_type=KnowledgeType(fields.get("knowledge_type", "declarative")),
                    score_components=ScoreComponents(
                        vector=vec_map.get(cid, 0.0),
                        bm25=bm25_map.get(cid, 0.0),
                        rrf=score_map.get(cid, 0.0),
                        rerank=rank_entry.get("relevance_score"),
                    ),
                    source_refs=src_refs,
                    metadata=meta,
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
