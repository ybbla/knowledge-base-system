"""文档管理 API v1 — 列表、创建、详情、更新、软删除、恢复和入库动作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import status as http_status

from app.api import upload as upload_api
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
from app.api.v1.services import sync_index_metadata
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
)
from app.core.models import DocStatus, Document, compute_hash, new_id

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _build_index_summary(doc_id: str) -> dict[str, int]:
    """构建文档的知识块统计摘要。"""
    if hasattr(chunk_store, "count_by_doc_id"):
        try:
            total = chunk_store.count_by_doc_id(doc_id)
            return {"total": total}
        except Exception:
            pass
    return {"total": 0}


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
        "previous_doc_id": doc.previous_doc_id,
        "error_message": doc.error_message,
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


def _element_to_item(element: Any) -> dict[str, Any]:
    """将解析元素转为前端可展示条目。"""
    return {
        "element_id": element.element_id,
        "doc_id": element.doc_id,
        "doc_version": element.doc_version,
        "parent_element_id": element.parent_element_id,
        "sequence_order": element.sequence_order,
        "element_type": element.element_type.value if hasattr(element.element_type, "value") else element.element_type,
        "text": element.text,
        "structured_data": element.structured_data,
        "asset_ids": element.asset_ids,
        "embedded_doc_id": element.embedded_doc_id,
        "source_location": (
            element.source_location.model_dump(mode="json")
            if hasattr(element.source_location, "model_dump")
            else element.source_location
        ),
        "metadata": element.metadata if hasattr(element, "metadata") else {},
    }


def _source_type_from_filename(filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return {
        "md": "markdown",
        "markdown": "markdown",
        "txt": "txt",
        "docx": "docx",
        "xlsx": "xlsx",
        "html": "html",
        "htm": "html",
        "pdf": "pdf",
        "pptx": "pptx",
    }.get(ext, "unknown")


# ── 4.1 文档列表 ──────────────────────────────────────────────────

@router.get("/ids")
async def list_document_ids(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
):
    """只返回符合条件的 doc_id 列表，供全选等批量操作使用。"""
    if document_repo is None or not hasattr(document_repo, "list_paginated"):
        return error_json(ErrorCode.SERVICE_UNAVAILABLE, "不可用", http_status.HTTP_503_SERVICE_UNAVAILABLE)

    all_ids = []
    page = 1
    while True:
        docs, total = document_repo.list_paginated(
            page=page, page_size=1000,
            keyword=keyword, status=status, category=category,
            sort_by="created_at", sort_order="desc",
        )
        for d in docs:
            all_ids.append(d.doc_id)
        if page * 1000 >= total:
            break
        page += 1

    return APIResponse(data=all_ids).model_dump(mode="json")


@router.get("")
async def list_documents(
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    source_type: str | None = Query(default=None, description="按来源类型过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
    category: str | None = Query(default=None, description="按分类过滤"),
    parent_doc_id: str | None = Query(default=None, description="按父文档过滤"),
    root_doc_id: str | None = Query(default=None, description="按根文档过滤"),
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

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.2 创建文档 ──────────────────────────────────────────────────

@router.post("", status_code=http_status.HTTP_201_CREATED)
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
        http_status.HTTP_409_CONFLICT,
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
    http_status.HTTP_409_CONFLICT,
            )

        response_data = _doc_to_item(created)

        # 创建后入库
        if ingest_after_create:
            try:
                created = ingestion_pipeline.ingest(created)
                response_data = _doc_to_item(created)
            except Exception as e:
                logger.exception("入库触发失败")
                response_data["ingest_error"] = str(e)

        return APIResponse(data=response_data).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.post("/upload", status_code=http_status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default=upload_api.DEFAULT_CATEGORY),
    ingest_after_create: bool = Query(default=True),
    replace_doc_id: str | None = Query(default=None, description="要替换的文档 ID"),
    confirm_replace: bool = Query(default=False, description="确认替换同名文档"),
):
    """上传文件，创建文档，并立即提交入库任务。

    支持同名文件检测和更新：
    - 如果检测到同名文档且没有确认替换，返回 suggested_replace 提示
    - 如果提供 replace_doc_id 且 confirm_replace=True，则执行更新流程

    流程：先创建 Document 预占位（利用数据库唯一索引防竞态），
    再写文件；文件写入失败时回滚已创建的 Document 记录，
    杜绝并发重复上传产生的孤儿文件。
    """
    original_name = file.filename or "upload"
    source_hash, size = upload_api._hash_upload(file)
    resolved_title = title or Path(original_name).stem
    resolved_category = category or upload_api.DEFAULT_CATEGORY

    # 检查重复内容
    if document_repo is not None:
        existing = document_repo.find_by_hash(source_hash)
        if existing is not None:
            return APIResponse(
                data={
                    "duplicate": True,
                    "existing_doc_id": existing.doc_id,
                    "source_uri": existing.source_uri,
                    "source_hash": source_hash,
                    "doc_id": existing.doc_id,
                    "file_name": original_name,
                    "size": size,
                    "title": existing.title,
                    "category": existing.category,
                },
                meta={"duplicate": True},
            ).model_dump(mode="json")

    # 检查同名文档
    similar_docs = []
    if document_repo is not None and not replace_doc_id:
        similar_docs = document_repo.find_similar_by_filename(original_name)
        # 如果只有一个同名文档且没有确认替换，返回提示
        if len(similar_docs) == 1 and not confirm_replace:
            suggested_doc = similar_docs[0]
            return APIResponse(
                data={
                    "suggested_replace": True,
                    "suggested_doc_id": suggested_doc.doc_id,
                    "suggested_doc_title": suggested_doc.title,
                    "source_hash": source_hash,
                    "file_name": original_name,
                    "size": size,
                    "title": resolved_title,
                    "category": resolved_category,
                },
                meta={"suggested_replace": True},
            ).model_dump(mode="json")

    # ── 处理替换流程 ──
    old_doc = None
    if replace_doc_id and confirm_replace and document_repo is not None:
        old_doc = document_repo.get(replace_doc_id)
        if old_doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"要替换的文档 {replace_doc_id} 不存在",
                http_status.HTTP_404_NOT_FOUND,
            )
        # 软删除旧文档及其知识块
        try:
            document_repo.soft_delete(replace_doc_id)
            # 同时软删除知识块并同步索引
            if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
                chunk_store.bulk_update_status_by_doc_id(replace_doc_id, "deleted")
            if hasattr(chunk_store, "list_by_doc_id"):
                chunks_to_sync = chunk_store.list_by_doc_id(replace_doc_id)
                if chunks_to_sync:
                    for c in chunks_to_sync:
                        try:
                            sync_index_metadata(c, vector_index, bm25_index)
                        except Exception:
                            logger.exception("同步删除状态失败: %s", c.chunk_id)
        except Exception:
            logger.exception("软删除旧文档失败")

    # ── 先创建 Document 预占位，再写文件 ──
    pre_doc_id = new_id("doc")
    doc = Document(
        doc_id=pre_doc_id,
        title=resolved_title,
        source_type=_source_type_from_filename(original_name),
        source_uri="",  # 文件写入后更新
        source_hash=source_hash,
        category=resolved_category,
        previous_doc_id=replace_doc_id if old_doc else None,
    )

    if document_repo is not None:
        try:
            doc = document_repo.create(doc)
        except DuplicateDocumentError as e:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                str(e),
                http_status.HTTP_409_CONFLICT,
            )

    # ── 写文件 ──
    try:
        upload_data = upload_api.save_upload_file(
            file,
            title=resolved_title,
            category=resolved_category,
            doc_id=pre_doc_id,
            check_duplicate=False,
        )
    except Exception:
        logger.exception("文件写入失败")
        # 回滚已创建的 Document 记录
        if document_repo is not None:
            try:
                document_repo.soft_delete(pre_doc_id)
            except Exception:
                logger.exception("回滚 Document 记录失败")
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            "文件保存失败",
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 更新 source_uri（文件写入后的真实路径）
    doc.source_uri = upload_data["source_uri"]
    if document_repo is not None:
        try:
            doc = document_repo.update(doc)
        except Exception:
            logger.exception("更新文档 source_uri 失败")

    response_data = _doc_to_item(doc)
    response_data.update({
        "duplicate": False,
        "suggested_replace": False,
        "replaced": old_doc is not None,
        "replaced_doc_id": replace_doc_id if old_doc else None,
        "file_name": original_name,
        "size": upload_data["size"],
    })

    if ingest_after_create:
        doc = ingestion_pipeline.ingest(doc)
        response_data = _doc_to_item(doc)

    return APIResponse(data=response_data).model_dump(mode="json")


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
    http_status.HTTP_404_NOT_FOUND,
            )

        item = _doc_to_item(doc)
        # 补充聚合统计
        if hasattr(document_repo, "get_stats"):
            item.update(document_repo.get_stats(doc_id))
        return APIResponse(data=item).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.3.1 更新文档元数据 ───────────────────────────────────────────

@router.patch("/{doc_id}")
async def update_document(
    doc_id: str,
    title: str | None = Query(default=None),
    category: str | None = Query(default=None),
):
    """更新文档的标题和分类等元数据，并同步到关联知识块的 PG 和 Milvus。"""
    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    # ── 构建变更字段 ──
    chunk_updates: dict = {}
    if title is not None:
        doc.title = title
        chunk_updates["title"] = title
    if category is not None:
        doc.category = category
        chunk_updates["category"] = category

    try:
        updated = document_repo.update(doc)
    except DocumentNotFoundError as e:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            str(e),
            http_status.HTTP_404_NOT_FOUND,
        )

    # ── 同步关联知识块：PG 批量更新 + Milvus 逐条同步 ──
    if chunk_updates and hasattr(chunk_store, "bulk_update_fields_by_doc_id"):
        try:
            synced_chunks = chunk_store.bulk_update_fields_by_doc_id(doc_id, chunk_updates)
            for c in synced_chunks:
                try:
                    sync_index_metadata(c, vector_index, bm25_index)
                except Exception:
                    logger.exception("同步 chunk 元数据到索引失败: %s", c.chunk_id)
        except Exception:
            logger.exception("批量更新 chunk 元数据失败")

    return APIResponse(data=_doc_to_item(updated)).model_dump(mode="json")


@router.get("/{doc_id}/elements")
async def list_document_elements(
    doc_id: str,
    pagination: PaginationParams = Depends(),
):
    """获取文档解析元素分页列表。"""
    if document_repo is not None and document_repo.get(doc_id) is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    if element_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 解析元素仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    elements = sorted(
        element_repo.get_by_doc_id(doc_id),
        key=lambda element: element.sequence_order,
    )
    total = len(elements)
    start = (pagination.page - 1) * pagination.page_size
    end = start + pagination.page_size
    total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
    meta = PaginationMeta(
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        total_pages=total_pages,
    )
    return PaginatedResponse(
        data=[_element_to_item(element) for element in elements[start:end]],
        meta=meta.model_dump(),
    ).model_dump(mode="json")


# ── 4.4 软删除文档 ────────────────────────────────────────────────


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
    http_status.HTTP_404_NOT_FOUND,
            )

        # 同步删除关联知识块
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "deleted")

        # 在索引中标记知识块为已删除
        if chunks_to_sync:
            for c in chunks_to_sync:
                try:
                    sync_index_metadata(c, vector_index, bm25_index)
                except Exception:
                    logger.exception("同步删除状态失败: %s", c.chunk_id)

        return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.6 恢复文档 ──────────────────────────────────────────────────

@router.post("/{doc_id}/restore")
async def restore_document(doc_id: str):
    """恢复软删除的文档到删前状态。

    - active → 改状态 + 知识块回索引（轻量）
    - failed / processing → 重走入库流程（全量重建）
    """
    if document_repo is None:
        return error_json(ErrorCode.SERVICE_UNAVAILABLE, "PostgreSQL 文档仓储不可用", 503)

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(ErrorCode.DOCUMENT_NOT_FOUND, f"文档 {doc_id} 不存在", 404)

    # 读取删前状态（由 soft_delete 写入 metadata）
    previous_status = (doc.metadata or {}).get("previous_status", "active")

    # 解决 source_hash 唯一约束
    if doc.source_hash:
        existing = document_repo.find_by_hash(doc.source_hash)
        if existing and existing.doc_id != doc_id:
            doc.source_hash = f"restored:{doc_id}"
            document_repo.update(doc)

    if previous_status == "active":
        # 活跃删除恢复：只改状态 + 知识块回索引（轻量，不重入库）
        doc = document_repo.restore(doc_id)
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "active")
        if hasattr(chunk_store, "list_by_doc_id"):
            for c in chunk_store.list_by_doc_id(doc_id):
                try:
                    sync_index_metadata(c, vector_index, bm25_index)
                except Exception:
                    logger.exception("同步恢复状态失败: %s", c.chunk_id)

    elif previous_status == "failed":
        # 失败删除恢复：重走入库（ingest 内部清理旧 chunks → 解析 → 抽取 → 索引）
        doc = ingestion_pipeline.ingest(doc)

    elif previous_status == "processing":
        # 处理中删除恢复：同上，重走入库
        doc = ingestion_pipeline.ingest(doc)

    return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")


# ── 4.6.1 重试失败文档 ─────────────────────────────────────────────

@router.post("/{doc_id}/retry")
async def retry_document(doc_id: str):
    """重新触发失败文档的入库流水线。"""
    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )
    if doc.status != DocStatus.failed:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "只能重试失败状态的文档",
            http_status.HTTP_400_BAD_REQUEST,
        )

    # 检查是否已有同名活跃文档
    if doc.source_hash:
        active_dup = document_repo.find_by_hash(doc.source_hash)
        if active_dup is not None and active_dup.doc_id != doc_id:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                f"已存在内容相同的活跃文档「{active_dup.title}」，无法重试",
                http_status.HTTP_409_CONFLICT,
                details={"existing_doc_id": active_dup.doc_id},
            )

    # 重新入库（ingest 内部清理旧 chunks：PG hard_delete + Milvus/BM25 delete）
    try:
        doc = ingestion_pipeline.ingest(doc)
    except Exception:
        logger.exception("重试入库失败")
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            "重试入库失败",
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")


# ── 4.7 版本历史 ──────────────────────────────────────────────────

@router.get("/{doc_id}/history")
async def get_document_history(doc_id: str):
    """获取文档的版本历史。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        try:
            history = document_repo.get_version_history(doc_id)
        except DocumentNotFoundError:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                http_status.HTTP_404_NOT_FOUND,
            )

        # 返回简化的版本信息
        history_items = []
        for doc in history:
            history_items.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "version": doc.version,
                "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "previous_doc_id": doc.previous_doc_id,
            })

        return APIResponse(data=history_items).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )
