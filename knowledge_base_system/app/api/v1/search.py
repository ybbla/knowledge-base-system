"""检索 API v1 — 标准检索、调试检索和筛选项。

POST /api/v1/search         — 标准检索，支持完整过滤和选项
POST /api/v1/search/debug   — 调试模式，返回分阶段候选
GET  /api/v1/search/filters — 可用筛选项
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.v1.schemas import APIResponse, error_json, response_json
from app.core.deps import (
    chunk_store,
    document_repo,
    retrieval_pipeline,
)

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)


# ── 6.1 扩展检索请求模型 ──────────────────────────────────────────

class SearchFilters(BaseModel):
    """检索过滤条件 — 按知识块字段和文档字段筛选。"""
    doc_ids: list[str] | None = Field(default=None, description="限定文档范围")
    categories: list[str] | None = Field(default=None, description="分类过滤")
    knowledge_types: list[str] | None = Field(default=None, description="知识类型过滤")
    chunk_status: list[str] | None = Field(default=None, description="知识块状态过滤")
    index_status: list[str] | None = Field(default=None, description="索引状态过滤")
    source_types: list[str] | None = Field(default=None, description="来源类型过滤")
    doc_status: list[str] | None = Field(default=None, description="文档状态过滤")
    created_after: str | None = Field(default=None, description="创建时间起 (ISO 8601)")
    created_before: str | None = Field(default=None, description="创建时间止 (ISO 8601)")


class SearchOptions(BaseModel):
    """检索策略和展示选项。"""
    rewrite: bool = Field(default=True, description="是否执行查询改写")
    hybrid: bool = Field(default=True, description="是否使用混合检索")
    rerank: bool = Field(default=True, description="是否执行 LLM 重排")
    highlight: bool = Field(default=False, description="是否返回高亮摘要")
    include_assets: bool = Field(default=True, description="是否包含资源引用")
    include_sources: bool = Field(default=True, description="是否包含来源引用")
    include_score_components: bool = Field(default=True, description="是否包含评分明细")


class SearchRequest(BaseModel):
    """v1 检索请求模型。"""
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    options: SearchOptions = Field(default_factory=SearchOptions)


# ── 辅助函数 ──────────────────────────────────────────────────────

async def _execute_search(request: SearchRequest) -> dict[str, Any]:
    """执行检索 pipeline，返回完整结果。"""
    filters = request.filters
    retrieval_top_k = max(request.top_k * 10, 50)

    result = retrieval_pipeline.search(
        request.query,
        top_k=retrieval_top_k,
        category=filters.categories[0] if filters.categories and len(filters.categories) == 1 else None,
    )

    result_dict = result.model_dump(mode="json")
    return _filter_and_enrich_result(result_dict, request)


def _value(raw: Any) -> str:
    """获取枚举或普通值的字符串形式。"""
    return raw.value if hasattr(raw, "value") else str(raw)


def _get_chunk(chunk_id: str):
    """从 chunk_store 获取知识块。"""
    if hasattr(chunk_store, "get"):
        return chunk_store.get(chunk_id)
    return getattr(chunk_store, "_chunks", {}).get(chunk_id)


def _get_doc(doc_id: str):
    """从 document_repo 获取文档。"""
    if document_repo is not None and hasattr(document_repo, "get"):
        return document_repo.get(doc_id)
    return None


def _parse_dt(raw: str | None) -> datetime | None:
    """解析 ISO 时间字符串。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _matches_filters(chunk, doc, filters: SearchFilters) -> bool:
    """判断知识块和文档是否满足 v1 检索过滤条件。"""
    if filters.doc_ids and chunk.doc_id not in filters.doc_ids:
        return False
    if filters.categories and chunk.category not in filters.categories:
        return False
    if filters.knowledge_types and _value(chunk.knowledge_type) not in filters.knowledge_types:
        return False
    if filters.chunk_status and _value(chunk.status) not in filters.chunk_status:
        return False
    if filters.index_status and _value(chunk.index_status) not in filters.index_status:
        return False

    if filters.source_types:
        source_type = getattr(doc, "source_type", None)
        if source_type not in filters.source_types:
            return False
    if filters.doc_status:
        doc_status = _value(getattr(doc, "status", "")) if doc is not None else ""
        if doc_status not in filters.doc_status:
            return False

    created_after = _parse_dt(filters.created_after)
    created_before = _parse_dt(filters.created_before)
    created_at = getattr(doc, "created_at", None)
    if created_after and (created_at is None or created_at < created_after):
        return False
    if created_before and (created_at is None or created_at > created_before):
        return False

    return True


def _make_highlight(content: str, query: str) -> str:
    """生成简单高亮摘要。"""
    if not content:
        return ""
    idx = content.lower().find(query.lower())
    if idx < 0:
        return content[:160]
    start = max(0, idx - 60)
    end = min(len(content), idx + len(query) + 60)
    return (
        content[start:idx]
        + "<mark>"
        + content[idx: idx + len(query)]
        + "</mark>"
        + content[idx + len(query):end]
    )


def _filter_and_enrich_result(result_dict: dict, request: SearchRequest) -> dict:
    """应用 v1 过滤条件，并补充前端展示字段。"""
    filtered_items: list[dict[str, Any]] = []
    for item in result_dict.get("results", []):
        chunk = _get_chunk(item.get("chunk_id", ""))
        if chunk is None:
            continue
        doc = _get_doc(chunk.doc_id)
        if not _matches_filters(chunk, doc, request.filters):
            continue

        item["doc_id"] = chunk.doc_id
        item["doc_title"] = getattr(doc, "title", None) or chunk.metadata.get("title", chunk.doc_id)
        item["doc_version"] = chunk.doc_version
        if request.options.highlight:
            item["highlight"] = _make_highlight(item.get("content", ""), request.query)
        filtered_items.append(item)
        if len(filtered_items) >= request.top_k:
            break

    result_dict["results"] = filtered_items
    result_dict["total_count"] = len(filtered_items)
    return result_dict


def _enrich_result(result_dict: dict, options: SearchOptions) -> dict:
    """根据选项丰富/裁减结果字段。"""
    for item in result_dict.get("results", []):
        if not options.include_assets:
            item["asset_refs"] = []
        if not options.include_sources:
            item["source_refs"] = []
        if not options.include_score_components:
            item.pop("score_components", None)
    return result_dict


# ── 6.4 标准检索 ──────────────────────────────────────────────────

@router.post("")
async def search(request: SearchRequest):
    """标准检索，支持完整过滤和策略选项。

    返回文档展示字段、高亮、来源、资源和评分明细。
    """
    try:
        result = await _execute_search(request)
        result = _enrich_result(result, request.options)
        return APIResponse(
            data=result,
            meta={
                "search_id": result.get("search_id", ""),
                "query": request.query,
                "rewritten_query": result.get("rewritten_query", ""),
                "total_count": result.get("total_count", 0),
                "filters": request.filters.model_dump(exclude_none=True),
                "options": request.options.model_dump(exclude_none=True),
            },
        ).model_dump(mode="json")
    except Exception as e:
        logger.exception("检索失败")
        return error_json("INTERNAL_ERROR", f"检索失败: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── 6.5 调试检索 ──────────────────────────────────────────────────


def _enrich_candidate_with_title(candidates: list[tuple[str, float]]) -> list[dict]:
    """给候选列表补充知识块标题，方便前端展示。"""
    result: list[dict] = []
    for chunk_id, score in candidates:
        chunk = _get_chunk(chunk_id)
        result.append({
            "chunk_id": chunk_id,
            "score": score,
            "title": chunk.title if chunk else None,
        })
    return result


def _enrich_rerank_results(rerank_results: list[dict]) -> list[dict]:
    """给 Rerank 结果补充标题信息，并统一 score 字段名。

    前端 renderCandidateList 使用 c.score 显示，但 Reranker 返回 relevance_score。
    """
    result: list[dict] = []
    for entry in rerank_results:
        chunk = _get_chunk(entry.get("chunk_id", ""))
        # 将 relevance_score 映射为 score，供前端统一使用
        result.append({
            **entry,
            "score": entry.get("relevance_score", 0.0),
            "title": chunk.title if chunk else None,
        })
    return result


@router.post("/debug")
async def search_debug(request: SearchRequest):
    """调试检索 — 返回查询改写、各阶段候选和 Rerank 结果。

    返回完整的检索链路：
    1. 查询改写阶段（原始查询、改写后查询、关键词）
    2. 向量检索 Top N 候选（含分数、标题）
    3. BM25 检索 Top N 候选（含分数、标题）
    4. RRF 融合后的排序（含分数、标题）
    5. LLM Rerank 后的最终排序（含分数、标题）
    6. 过滤后的最终结果

    安全：不返回密钥、完整提示词或底层堆栈。
    """
    try:
        filters = request.filters
        retrieval_top_k = max(request.top_k * 10, 50)
        category = filters.categories[0] if filters.categories and len(filters.categories) == 1 else None

        # 调用 debug 模式的 pipeline，拿到 (result, debug_info)
        result_tuple = retrieval_pipeline.search(
            request.query,
            top_k=retrieval_top_k,
            category=category,
            debug=True,
        )
        result, debug_info = result_tuple  # type: ignore

        # 对结果应用过滤和 enrich
        result_dict = result.model_dump(mode="json")
        result_dict = _filter_and_enrich_result(result_dict, request)
        result_dict = _enrich_result(result_dict, request.options)

        # 构造完整调试信息
        debug_payload = {
            "query": request.query,
            "rewritten_query": debug_info.rewritten_query,
            "keywords": debug_info.keywords,
            "filters": request.filters.model_dump(exclude_none=True),
            "total_count": result_dict.get("total_count", 0),
            "results": result_dict.get("results", []),
            # 各阶段完整候选（含标题）
            "rewrite": {
                "original_query": debug_info.original_query,
                "rewritten_query": debug_info.rewritten_query,
                "keywords": debug_info.keywords,
            },
            "vector_candidates": _enrich_candidate_with_title(debug_info.vector_candidates),
            "bm25_candidates": _enrich_candidate_with_title(debug_info.bm25_candidates),
            "fused_candidates": _enrich_candidate_with_title(debug_info.fused_candidates),
            "rerank_results": _enrich_rerank_results(debug_info.rerank_results),
            # 统计信息
            "stats": {
                "vector_count": debug_info.vector_count,
                "bm25_count": debug_info.bm25_count,
                "fused_count": debug_info.fused_count,
                "rerank_count": debug_info.rerank_count,
                "used_milvus_hybrid": debug_info.used_milvus_hybrid,
            },
            "errors": debug_info.errors,
        }

        return APIResponse(
            data=debug_payload,
            meta={"mode": "debug"},
        ).model_dump(mode="json")
    except Exception as e:
        logger.exception("调试检索失败")
        return response_json(APIResponse(
            data={"error_summary": str(e)[:500]},
            meta={"mode": "debug", "status": "error"},
        ), status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── 6.7 检索筛选项 ────────────────────────────────────────────────

@router.get("/filters")
async def search_filters():
    """返回可用筛选项：分类、来源类型、知识类型、状态。"""
    filter_options: dict[str, list[dict[str, Any]]] = {
        "categories": [],
        "source_types": [],
        "knowledge_types": [],
        "doc_statuses": [],
        "chunk_statuses": [],
        "index_statuses": [],
    }

    # 从知识块存储收集枚举值
    if hasattr(chunk_store, "list_all"):
        try:
            chunks = chunk_store.list_all()
            cats: dict[str, int] = {}
            kts: dict[str, int] = {}
            ch_stats: dict[str, int] = {}
            idx_stats: dict[str, int] = {}
            for c in chunks:
                cat = c.category or "通用"
                cats[cat] = cats.get(cat, 0) + 1
                kt = c.knowledge_type.value if hasattr(c.knowledge_type, "value") else str(c.knowledge_type)
                kts[kt] = kts.get(kt, 0) + 1
                st = c.status.value if hasattr(c.status, "value") else str(c.status)
                ch_stats[st] = ch_stats.get(st, 0) + 1
                ist = c.index_status.value if hasattr(c.index_status, "value") else str(c.index_status)
                idx_stats[ist] = idx_stats.get(ist, 0) + 1

            filter_options["categories"] = [{"value": k, "count": v} for k, v in cats.items()]
            filter_options["knowledge_types"] = [{"value": k, "count": v} for k, v in kts.items()]
            filter_options["chunk_statuses"] = [{"value": k, "count": v} for k, v in ch_stats.items()]
            filter_options["index_statuses"] = [{"value": k, "count": v} for k, v in idx_stats.items()]
        except Exception:
            pass

    # 补充文档仓储中的分类，覆盖尚未生成知识块的新文档。
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        try:
            existing_categories = {item["value"]: item.get("count", 0) for item in filter_options["categories"]}
            doc_categories: dict[str, int] = {}
            page = 1
            page_size = 200
            while True:
                docs, total = document_repo.list_paginated(page=page, page_size=page_size)
                for doc in docs:
                    category = getattr(doc, "category", None) or "通用"
                    doc_categories[category] = doc_categories.get(category, 0) + 1
                if page * page_size >= total or not docs:
                    break
                page += 1
            for category, count in existing_categories.items():
                doc_categories[category] = max(doc_categories.get(category, 0), count)
            filter_options["categories"] = [
                {"value": value, "count": count}
                for value, count in sorted(doc_categories.items())
            ]
        except Exception:
            pass

    # 来源类型（从文档仓储获取）
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        try:
            for st in ["markdown", "pdf", "docx", "html", "pptx", "xlsx"]:
                _, count = document_repo.list_paginated(source_type=st, page_size=1)
                if count > 0:
                    filter_options["source_types"].append({"value": st, "count": count})
        except Exception:
            filter_options["source_types"] = [
                {"value": "markdown"}, {"value": "pdf"}, {"value": "docx"},
                {"value": "html"}, {"value": "pptx"}, {"value": "xlsx"},
            ]

    # 文档状态（枚举值）
    filter_options["doc_statuses"] = [
        {"value": "active"}, {"value": "pending"}, {"value": "processing"},
        {"value": "failed"}, {"value": "deleted"},
    ]

    return APIResponse(data=filter_options).model_dump(mode="json")

