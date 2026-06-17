"""文档管理 API v1 — 列表、创建、详情、更新、软删除、恢复和入库动作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
    error_json,
)
from app.core import deps
from app.core.deps import (
    asset_store,
    bm25_index,
    chunk_store,
    document_repo,
    element_repo,
    ingestion_pipeline,
    vector_index,
)
from app.core.errors import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    VersionConflictError,
)
from app.core.models import DocStatus, Document, compute_hash

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _build_index_summary(doc_id: str) -> dict[str, int]:
    """构建文档的索引摘要（chunk 按 index_status 的分布）。"""
    if not hasattr(chunk_store, "list_paginated"):
        return {"indexed": 0, "pending": 0, "failed": 0}
    try:
        summary = {"indexed": 0, "pending": 0, "failed": 0, "indexing": 0}
        for idx_status in ["indexed", "pending", "failed", "indexing"]:
            chunks, count = chunk_store.list_paginated(
                doc_id=doc_id, index_status=idx_status, page_size=1
            )
            summary[idx_status] = count
        return summary
    except Exception:
        return {"indexed": 0, "pending": 0, "failed": 0}


def _build_doc_stats(doc_id: str) -> dict[str, int | dict]:
    """构建文档统计信息。"""
    stats: dict[str, Any] = {"chunk_count": 0, "element_count": 0, "asset_count": 0}

    # 统计 chunk 数量
    if hasattr(chunk_store, "count_by_doc_id"):
        stats["chunk_count"] = chunk_store.count_by_doc_id(doc_id)
    elif hasattr(chunk_store, "list_by_doc_id"):
        stats["chunk_count"] = len(chunk_store.list_by_doc_id(doc_id))

    # 统计 element 数量
    if element_repo is not None:
        elements = element_repo.get_by_doc_id(doc_id)
        stats["element_count"] = len(elements)

    stats["index_summary"] = _build_index_summary(doc_id)
    return stats


def _doc_to_item(doc: Document) -> dict[str, Any]:
    """将 Document 转为前端展示条目（含统计）。"""
    item = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "source_type": doc.source_type,
        "source_uri": doc.source_uri,
        "source_hash": doc.source_hash,
        "category": doc.category,
        "version": doc.version,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "parent_doc_id": doc.parent_doc_id,
        "root_doc_id": doc.root_doc_id,
        "ingest_job_id": doc.ingest_job_id,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "metadata": doc.metadata if hasattr(doc, "metadata") else {},
    }
    # 附加统计
    try:
        item.update(_build_doc_stats(doc.doc_id))
    except Exception:
        item.update({"chunk_count": 0, "element_count": 0, "asset_count": 0, "index_summary": {}})
    return item


# ── 4.1 文档列表 ──────────────────────────────────────────────────

@router.get("")
async def list_documents(
    pagination: PaginationParams = Query(),
    search: SearchParams = Query(),
    source_type: str | None = Query(default=None, description="按来源类型过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
    category: str | None = Query(default=None, description="按分类过滤"),
    parent_doc_id: str | None = Query(default=None, description="按父文档过滤"),
    root_doc_id: str | None = Query(default=None, description="按根文档过滤"),
    ingest_job_id: str | None = Query(default=None, description="按入库任务过滤"),
):
    """获取文档分页列表，支持多条件筛选和排序。

    返回统一的 PaginatedResponse 结构，每个文档条目包含统计信息。
    """
    # ── PostgreSQL 后端 ──
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        docs, total = document_repo.list_paginated(
            page=pagination.page,
            page_size=pagination.page_size,
            keyword=search.keyword,
            source_type=source_type,
            status=status,
            category=category,
            parent_doc_id=parent_doc_id,
            root_doc_id=root_doc_id,
            ingest_job_id=ingest_job_id,
            sort_by=pagination.sort_by or "updated_at",
            sort_order=pagination.sort_order,
        )
        items = [_doc_to_item(d) for d in docs]
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=total_pages,
        )
        return PaginatedResponse(data=items, meta=meta.model_dump()).model_dump(mode="json")

    # ── 内存后端 ──
    docs_list: list[dict] = []
    try:
        if hasattr(chunk_store, "list_all"):
            chunks = chunk_store.list_all()
        else:
            chunks = list(getattr(chunk_store, "_chunks", {}).values())

        # 从 chunk 中提取文档信息并去重
        seen: set[str] = set()
        for chunk in chunks:
            doc_id = chunk.doc_id
            if doc_id in seen:
                continue
            seen.add(doc_id)

            doc_item = {
                "doc_id": doc_id,
                "title": chunk.metadata.get("title", doc_id) if hasattr(chunk, "metadata") else doc_id,
                "source_type": chunk.metadata.get("source_type", "unknown") if hasattr(chunk, "metadata") else "unknown",
                "source_uri": "",
                "source_hash": "",
                "category": chunk.category or "通用",
                "version": chunk.doc_version or 1,
                "status": "active",
                "parent_doc_id": None,
                "root_doc_id": None,
                "ingest_job_id": chunk.ingest_job_id,
                "created_at": None,
                "updated_at": None,
                "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
                "chunk_count": 0,
                "element_count": 0,
                "asset_count": 0,
                "index_summary": {},
            }

            # 关键词过滤
            if search.keyword:
                kw = search.keyword.lower()
                if kw not in doc_item["title"].lower() and kw not in doc_item.get("source_uri", "").lower():
                    continue

            # 分类过滤
            if category and doc_item.get("category") != category:
                continue

            # 状态过滤
            if status and doc_item.get("status") != status:
                continue

            docs_list.append(doc_item)

        # 简单分页
        total = len(docs_list)
        start = (pagination.page - 1) * pagination.page_size
        end = start + pagination.page_size
        paged = docs_list[start:end]
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        meta = PaginationMeta(
            page=pagination.page, page_size=pagination.page_size,
            total=total, total_pages=total_pages,
        )
        return PaginatedResponse(data=paged, meta=meta.model_dump()).model_dump(mode="json")

    except Exception as e:
        logger.exception("查询文档列表失败")
        return PaginatedResponse(
            data=[], meta=PaginationMeta(page=1, page_size=20, total=0, total_pages=0).model_dump()
        ).model_dump(mode="json")


# ── 4.2 创建文档 ──────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    title: str = Query(...),
    source_type: str = Query(...),
    source_uri: str = Query(...),
    source_hash: str = Query(default=""),
    category: str = Query(default="通用"),
    metadata: str | None = Query(default=None, description="JSON 格式的元数据"),
    ingest_after_create: bool = Query(default=False),
):
    """创建新文档，支持创建后立即触发入库。

    如果 ingest_after_create=true，创建文档后自动提交入库任务。
    """
    import json

    meta_dict: dict[str, Any] = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            pass

    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        # 去重检查
        if source_hash:
            existing = document_repo.find_by_hash(source_hash)
            if existing is not None:
                return error_json(
                    ErrorCode.DOCUMENT_DUPLICATE,
                    f"相同 source_hash 的文档已存在: {existing.doc_id}",
                    status.HTTP_409_CONFLICT,
                    details={"existing_doc_id": existing.doc_id},
                )

        doc = Document(
            title=title,
            source_type=source_type,
            source_uri=source_uri,
            source_hash=source_hash,
            category=category,
            metadata=meta_dict,
        )
        try:
            created = document_repo.create(doc)
        except DuplicateDocumentError as e:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                str(e),
                status.HTTP_409_CONFLICT,
            )

        response_data = _doc_to_item(created)

        # 创建后入库
        if ingest_after_create:
            try:
                job = ingestion_pipeline.submit(
                    created,
                    options={},
                    is_update=False,
                )
                response_data["ingest_job_id"] = job.job_id
            except Exception as e:
                logger.exception("入库触发失败")
                response_data["ingest_error"] = str(e)

        return APIResponse(data=response_data).model_dump(mode="json")

    # ── 内存后端 ──
    doc = Document(
        title=title,
        source_type=source_type,
        source_uri=source_uri,
        source_hash=source_hash,
        category=category,
        metadata=meta_dict,
    )
    if ingest_after_create:
        try:
            job = ingestion_pipeline.submit(doc, options={}, is_update=False)
            doc.ingest_job_id = job.job_id
        except Exception as e:
            logger.exception("入库触发失败")

    return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")


# ── 4.3 文档详情 ──────────────────────────────────────────────────

@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """获取文档详情、统计信息和元数据。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                status.HTTP_404_NOT_FOUND,
            )

        item = _doc_to_item(doc)
        # 补充聚合统计
        if hasattr(document_repo, "get_stats"):
            item.update(document_repo.get_stats(doc_id))
        return APIResponse(data=item).model_dump(mode="json")

    # ── 内存后端 ──
    try:
        if hasattr(chunk_store, "list_all"):
            chunks = chunk_store.list_all()
        else:
            chunks = list(getattr(chunk_store, "_chunks", {}).values())
    except Exception:
        chunks = []

    doc_chunks = [c for c in chunks if c.doc_id == doc_id]
    if not doc_chunks:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    first = doc_chunks[0]
    item = {
        "doc_id": doc_id,
        "title": first.metadata.get("title", doc_id) if hasattr(first, "metadata") else doc_id,
        "source_type": first.metadata.get("source_type", "unknown") if hasattr(first, "metadata") else "unknown",
        "source_uri": "",
        "source_hash": "",
        "category": first.category or "通用",
        "version": first.doc_version or 1,
        "status": "active",
        "parent_doc_id": None,
        "root_doc_id": None,
        "ingest_job_id": first.ingest_job_id,
        "created_at": None,
        "updated_at": None,
        "metadata": first.metadata if hasattr(first, "metadata") else {},
        "chunk_count": len(doc_chunks),
        "element_count": 0,
        "asset_count": 0,
        "index_summary": {},
    }
    return APIResponse(data=item).model_dump(mode="json")


# ── 4.4 更新文档 ──────────────────────────────────────────────────

@router.patch("/{doc_id}")
async def update_document(
    doc_id: str,
    title: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source_uri: str | None = Query(default=None),
    source_hash: str | None = Query(default=None),
    expected_version: int | None = Query(default=None, description="乐观锁版本号"),
    metadata: str | None = Query(default=None),
):
    """更新文档字段，支持 expected_version 乐观锁。

    如果更新来源字段（source_uri / source_hash），响应提示需要重新入库。
    """
    if document_repo is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            "后端未启用文档仓储",
            status.HTTP_400_BAD_REQUEST,
        )

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    # 乐观锁检查
    if expected_version is not None and doc.version != expected_version:
        return error_json(
            ErrorCode.DOCUMENT_VERSION_CONFLICT,
            f"版本冲突: 期望 {expected_version}，实际 {doc.version}",
            status.HTTP_409_CONFLICT,
            details={"expected": expected_version, "actual": doc.version},
        )

    # 更新字段
    import json
    needs_reingest = False
    if title is not None:
        doc.title = title
    if category is not None:
        doc.category = category
    if status is not None:
        doc.status = DocStatus(status)
    if source_uri is not None and source_uri != doc.source_uri:
        doc.source_uri = source_uri
        needs_reingest = True
    if source_hash is not None and source_hash != doc.source_hash:
        doc.source_hash = source_hash
        needs_reingest = True
    if metadata is not None:
        try:
            doc.metadata = json.loads(metadata)
        except json.JSONDecodeError:
            pass

    try:
        updated = document_repo.update(doc)
    except VersionConflictError as e:
        return error_json(
            ErrorCode.DOCUMENT_VERSION_CONFLICT,
            str(e),
            status.HTTP_409_CONFLICT,
        )
    except DocumentNotFoundError as e:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            str(e),
            status.HTTP_404_NOT_FOUND,
        )

    item = _doc_to_item(updated)
    if needs_reingest:
        item["needs_reingest"] = True
    return APIResponse(data=item).model_dump(mode="json")


# ── 4.5 软删除文档 ────────────────────────────────────────────────

@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """软删除文档，将关联活跃知识块状态设置为 deleted 并同步索引。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        chunks_to_sync = []
        if hasattr(chunk_store, "list_by_doc_id"):
            chunks_to_sync = [
                c for c in chunk_store.list_by_doc_id(doc_id)
                if (c.status.value if hasattr(c.status, "value") else c.status) != "deleted"
            ]
        try:
            doc = document_repo.soft_delete(doc_id)
        except DocumentNotFoundError as e:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                str(e),
                status.HTTP_404_NOT_FOUND,
            )

        # 同步删除关联知识块
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "deleted")

        # 同步索引状态
        if chunks_to_sync:
            chunk_ids = [c.chunk_id for c in chunks_to_sync]
            vector_index.update_status_batch(chunk_ids, "deleted")
            bm25_index.update_status_batch(chunk_ids, "deleted")

        return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")

    # ── 内存后端 ──
    return APIResponse(
        data={"doc_id": doc_id, "status": "deleted", "message": "内存后端仅模拟软删除"}
    ).model_dump(mode="json")


# ── 4.6 恢复文档 ──────────────────────────────────────────────────

@router.post("/{doc_id}/restore")
async def restore_document(doc_id: str):
    """恢复软删除的文档，处理关联知识块恢复策略。"""
    if document_repo is not None:
        try:
            doc = document_repo.restore(doc_id)
        except DocumentNotFoundError as e:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                str(e),
                status.HTTP_404_NOT_FOUND,
            )

        # 恢复关联知识块
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "active")

        restored_chunks_count = 0
        if hasattr(chunk_store, "list_by_doc_id"):
            chunks = chunk_store.list_by_doc_id(doc_id)
            restored_chunks_count = len(chunks)

        return APIResponse(
            data=_doc_to_item(doc),
            meta={"restored_chunks": restored_chunks_count},
        ).model_dump(mode="json")

    return APIResponse(
        data={"doc_id": doc_id, "status": "active", "message": "内存后端仅模拟恢复"}
    ).model_dump(mode="json")


# ── 4.7 触发入库 ──────────────────────────────────────────────────

@router.post("/{doc_id}/ingest")
async def ingest_document(
    doc_id: str,
    mode: str = Query(default="incremental", description="incremental 或 force"),
):
    """对文档触发入库、增量更新或强制重建。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                status.HTTP_404_NOT_FOUND,
            )

        try:
            job = ingestion_pipeline.submit(
                doc,
                options={"force": mode == "force"},
                is_update=(mode == "incremental"),
            )
            return APIResponse(
                data={"job_id": job.job_id, "doc_id": doc_id, "mode": mode},
                meta={"status": "accepted"},
            ).model_dump(mode="json")
        except Exception as e:
            logger.exception("触发入库失败")
            return error_json(
                ErrorCode.INTERNAL_ERROR,
                f"入库触发失败: {e}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── 内存后端 ──
    return APIResponse(
        data={"job_id": f"ingest_{doc_id}", "doc_id": doc_id, "mode": mode},
        meta={"status": "accepted"},
    ).model_dump(mode="json")
