"""检索 API v1 — 标准检索和筛选项。

POST /api/v1/search         — 标准检索，支持完整过滤和选项
GET  /api/v1/search/filters — 可用筛选项
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.v1.schemas import APIResponse, error_json
from app.core.deps import (
    asset_store,
    chunk_store,
    retrieval_pipeline,
)
from app.utils.thread_pool import search_executor

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)


# ── 6.1 扩展检索请求模型 ──────────────────────────────────────────

class SearchFilters(BaseModel):
    """检索过滤条件 — 全部走 Milvus 标量字段，无需查询 PG。"""
    doc_ids: list[str] | None = Field(default=None, description="限定文档范围")
    categories: list[str] | None = Field(default=None, description="分类过滤")
    knowledge_types: list[str] | None = Field(default=None, description="知识类型过滤")
    chunk_status: list[str] | None = Field(default=None, description="知识块状态过滤")


class SearchOptions(BaseModel):
    """检索策略和展示选项。"""
    rewrite: bool = Field(default=True, description="是否执行查询改写")
    hybrid: bool = Field(default=True, description="是否使用混合检索")
    rerank: bool = Field(default=True, description="是否执行 LLM 重排")
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

def _matches_chunk_filters(item: dict, filters: SearchFilters) -> bool:
    """纯 Milvus 标量字段过滤，零 PG 查询。"""
    if filters.doc_ids and item.get("doc_id", "") not in filters.doc_ids:
        return False
    if filters.categories and item.get("category", "") not in filters.categories:
        return False
    if filters.knowledge_types and item.get("knowledge_type", "") not in filters.knowledge_types:
        return False
    if filters.chunk_status and item.get("status", "") not in filters.chunk_status:
        return False
    return True


def _enrich_result(result_dict: dict, options: SearchOptions) -> dict:
    """根据选项丰富/裁减结果字段，并为 asset_refs 补充 storage_uri。"""
    for item in result_dict.get("results", []):
        if not options.include_assets:
            item["asset_refs"] = []
        else:
            enriched = []
            for ref in item.get("asset_refs", []):
                entry = dict(ref)
                asset_id = entry.get("asset_id", "")
                if asset_store is not None and asset_id:
                    asset = asset_store.get(asset_id)
                    if asset:
                        entry["asset_type"] = (
                            asset.asset_type.value
                            if hasattr(asset.asset_type, "value")
                            else str(asset.asset_type)
                        )
                        entry["storage_uri"] = asset.storage_uri or ""
                    else:
                        entry["asset_type"] = "unknown"
                        entry["storage_uri"] = ""
                else:
                    entry["asset_type"] = "unknown"
                    entry["storage_uri"] = ""
                enriched.append(entry)
            item["asset_refs"] = enriched
        if not options.include_sources:
            item["source_refs"] = []
        if not options.include_score_components:
            item.pop("score_components", None)
    return result_dict


# ── 6.4 标准检索 ──────────────────────────────────────────────────

@router.post("")
async def search(request: SearchRequest):
    """标准检索，支持完整过滤和策略选项。

    检索链路完全在 Milvus 内闭环：标量过滤 + 向量/BF25 双路召回，
    返回字段全量来自 Milvus 标量列，无需查询 PostgreSQL。
    """
    try:
        filters = request.filters
        categories: list[str] | None = list(filters.categories) if filters.categories else None
        ktypes: list[str] | None = list(filters.knowledge_types) if filters.knowledge_types else None

        # 通过专用线程池隔离并发搜索，pipeline 内自行管理 Vector+BM25 双路并行
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            search_executor,
            retrieval_pipeline.search,
            request.query,
            request.top_k,
            categories,
            ktypes,
            False,                      # debug
            request.options.rewrite,
            request.options.hybrid,
            request.options.rerank,
        )
        result_dict = result.model_dump(mode="json")

        # 后置过滤：doc_ids、chunk_status（Milvus 存储了这些字段但 pipeline 未传参）
        filtered = []
        for item in result_dict.get("results", []):
            if _matches_chunk_filters(item, filters):
                filtered.append(item)
                if len(filtered) >= request.top_k:
                    break

        result_dict["results"] = filtered
        result_dict["total_count"] = len(filtered)

        result_dict = _enrich_result(result_dict, request.options)
        return APIResponse(
            data={"results": result_dict.get("results", [])},
            metadata={
                "search_id": result_dict.get("search_id", ""),
                "query": request.query,
                "rewritten_query": result_dict.get("rewritten_query", ""),
                "total_count": result_dict.get("total_count", 0),
                "filters": request.filters.model_dump(exclude_none=True),
                "options": request.options.model_dump(exclude_none=True),
            },
        ).model_dump(mode="json")
    except Exception as e:
        logger.exception("检索失败")
        return error_json("INTERNAL_ERROR", f"检索失败: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── 6.5 检索筛选项 ────────────────────────────────────────────────

@router.get("/filters")
async def search_filters():
    """返回可用筛选项：分类、知识类型、知识块状态。"""
    filter_options: dict[str, list[dict[str, Any]]] = {
        "categories": [],
        "knowledge_types": [],
        "chunk_statuses": [],
    }

    cats: dict[str, int] = {}
    if hasattr(chunk_store, "list_all"):
        try:
            chunks = chunk_store.list_all()
            kts: dict[str, int] = {}
            ch_stats: dict[str, int] = {}
            for c in chunks:
                cat = c.category or "通用"
                cats[cat] = cats.get(cat, 0) + 1
                kt = c.knowledge_type.value if hasattr(c.knowledge_type, "value") else str(c.knowledge_type)
                kts[kt] = kts.get(kt, 0) + 1
                st = c.status.value if hasattr(c.status, "value") else str(c.status)
                ch_stats[st] = ch_stats.get(st, 0) + 1

            filter_options["knowledge_types"] = [{"value": k, "count": v} for k, v in kts.items()]
            filter_options["chunk_statuses"] = [{"value": k, "count": v} for k, v in ch_stats.items()]
        except Exception:
            pass

    # 分类统计优先从 PG 文档表获取（覆盖所有文档，含尚无 chunk 的新文档），不可用时回退 chunk_store
    from app.core.deps import document_repo  # noqa: E402
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        try:
            doc_categories: dict[str, int] = {}
            page = 1
            page_size = 200
            while True:
                docs, total = document_repo.list_paginated(page=page, page_size=page_size)
                for doc in docs:
                    cat_name = getattr(doc, "category", None) or "通用"
                    doc_categories[cat_name] = doc_categories.get(cat_name, 0) + 1
                if page * page_size >= total or not docs:
                    break
                page += 1
            filter_options["categories"] = [
                {"value": value, "count": count}
                for value, count in sorted(doc_categories.items())
            ]
        except Exception:
            pass

    if not filter_options["categories"]:
        filter_options["categories"] = [{"value": k, "count": v} for k, v in cats.items()]

    return APIResponse(data=filter_options).model_dump(mode="json")
