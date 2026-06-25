"""文档管理 API v1 — 列表、创建、详情、更新、软删除、恢复和入库动作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi import status as http_status

from app.api import upload_utils as upload_api
from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
    error_json,
)
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
from app.utils.thread_pool import upload_executor

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

    # 统计 asset 数量
    if asset_store is not None and hasattr(asset_store, "count_by_doc_id"):
        stats["asset_count"] = asset_store.count_by_doc_id(doc_id)
    elif asset_store is not None and hasattr(asset_store, "get_by_doc_id"):
        stats["asset_count"] = len(asset_store.get_by_doc_id(doc_id))

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
        "asset_data": [ad.model_dump(mode="json") for ad in element.asset_data],
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
        return PaginatedResponse(data=items, metadata=meta.model_dump()).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.2 创建文档 ──────────────────────────────────────────────────

@router.post("", status_code=http_status.HTTP_201_CREATED)
async def create_document(
    title: str = Body(...),
    source_type: str = Body(...),
    source_uri: str = Body(...),
    source_hash: str = Body(default=""),
    category: str = Body(default="通用"),
    metadata: str | None = Body(default=None, description="JSON 格式的元数据"),
    ingest_after_create: bool = Body(default=False),
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
    replace_doc_id: str | None = None,
    confirm_replace: bool = False,
):
    """上传文件，创建文档并立即入库。

    支持同名文件检测和更新：
    - 检测到同名文档且未确认替换 → 返回 suggested_replace 提示
    - 提供 replace_doc_id 且 confirm_replace=True → 更新流程

    上传必定触发入库（ingest），不可跳过。
    热路径在 upload 线程池中执行，不阻塞事件循环。

    流程：
    1-3) 参数解析 + 重复/同名检测（事件循环中，轻量 DB 查询）
    4-9) 预占位 → MinIO → 旧文档清理 → ingest（线程池，I/O 密集）
    """
    original_name = file.filename or "upload"
    file.file.seek(0)
    file_content = file.file.read()
    source_hash = compute_hash(file_content)
    size = len(file_content)
    content_type = file.content_type or "application/octet-stream"

    # ── 参数解析：title/category 默认值 ──
    resolved_title = title or Path(original_name).stem
    resolved_category = category or upload_api.DEFAULT_CATEGORY

    # ── 重复内容检测（事件循环中快速返回） ──
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
                metadata={"duplicate": True},
            ).model_dump(mode="json")

    # ── 同名文档检测（仅上传新文件时） ──
    if document_repo is not None and not replace_doc_id:
        similar_docs = document_repo.find_similar_by_filename(original_name)
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
                metadata={"suggested_replace": True},
            ).model_dump(mode="json")

    # ── 更新场景：旧文档校验 + 默认值回填 ──
    if replace_doc_id and confirm_replace and document_repo is not None:
        old_doc = document_repo.get(replace_doc_id)
        if old_doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"要替换的文档 {replace_doc_id} 不存在",
                http_status.HTTP_404_NOT_FOUND,
            )
        if old_doc.status != DocStatus.active:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {replace_doc_id} 状态不是 active，无法替换",
                http_status.HTTP_409_CONFLICT,
            )
        # 更新时 title/category 未填 → 沿用旧文档的值
        resolved_title = title or old_doc.title
        resolved_category = category or old_doc.category
        replace_doc_id_typed: str | None = replace_doc_id
    else:
        old_doc = None
        replace_doc_id_typed = None

    # ── 热路径：提交到 upload 线程池 ──
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        upload_executor,
        _do_upload,
        file_content,
        original_name,
        size,
        source_hash,
        resolved_title,
        resolved_category,
        content_type,
        old_doc,
        replace_doc_id_typed,
    )


# ═══════════════════════════════════════════════════════════════════════
# 上传热路径（在线程池中同步执行）
# ═══════════════════════════════════════════════════════════════════════


def _do_upload(
    file_content: bytes,
    original_name: str,
    size: int,
    source_hash: str,
    resolved_title: str,
    resolved_category: str,
    content_type: str,
    old_doc: Document | None,
    replace_doc_id: str | None,
) -> dict[str, Any]:
    """上传热路径：预占位 → MinIO → 旧文档清理 → ingest。

    在 upload 线程池中同步执行，不阻塞事件循环。
    返回完整的 API 响应 dict（success 或 error）。
    """
    # ── [5] 创建 Document 预占位 ──
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

    # ── [6] 写文件到 MinIO ──
    upload_data: dict[str, Any] = {}
    try:
        upload_data = upload_api.save_upload_file(
            file_content,
            original_name,
            size,
            title=resolved_title,
            category=resolved_category,
            content_type=content_type,
            doc_id=pre_doc_id,
        )
    except Exception:
        logger.exception("文件写入 MinIO 失败: %s", pre_doc_id)
        if document_repo is not None:
            try:
                document_repo.hard_delete(pre_doc_id)
            except Exception:
                logger.exception("回滚预占位失败: %s", pre_doc_id)
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            "文件保存失败",
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── [7] 更新 source_uri ──
    doc.source_uri = upload_data["source_uri"]
    if document_repo is not None:
        try:
            doc = document_repo.update(doc)
        except Exception:
            logger.exception("更新 source_uri 失败: %s", pre_doc_id)

    # ── [8] 软删除旧文档（更新场景，MinIO 成功后执行） ──
    replaced = old_doc is not None
    if old_doc is not None:
        try:
            document_repo.soft_delete(old_doc.doc_id)
            if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
                chunk_store.bulk_update_status_by_doc_id(old_doc.doc_id, "deleted")
            if hasattr(chunk_store, "list_by_doc_id"):
                old_chunks = chunk_store.list_by_doc_id(old_doc.doc_id)
                if old_chunks:
                    for c in old_chunks:
                        try:
                            sync_index_metadata(c, vector_index, bm25_index)
                        except Exception:
                            logger.exception("同步旧 chunk 删除状态失败: %s", c.chunk_id)
        except Exception:
            logger.exception("软删除旧文档失败: %s（新文档已就位，可手动清理）", old_doc.doc_id)

    # ── [9] 入库（必定执行，失败标记 failed 不抛异常） ──
    try:
        doc = ingestion_pipeline.ingest(doc, raw_content=file_content)
        response_data = _doc_to_item(doc)
    except Exception:
        logger.exception("入库失败: %s", pre_doc_id)
        doc.status = DocStatus.failed
        doc.error_message = "入库失败，可稍后重试"
        if document_repo is not None:
            try:
                document_repo.update(doc)
            except Exception:
                logger.exception("持久化失败状态时出错: %s", pre_doc_id)
        response_data = _doc_to_item(doc)
        response_data["ingest_error"] = True

    response_data.update({
        "duplicate": False,
        "suggested_replace": False,
        "replaced": replaced,
        "replaced_doc_id": replace_doc_id if replaced else None,
        "file_name": original_name,
        "size": upload_data["size"],
    })
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
        metadata=meta.model_dump(),
    ).model_dump(mode="json")


# ── 4.4 软删除文档 ────────────────────────────────────────────────

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


# ── 4.5 恢复文档 ──────────────────────────────────────────────────

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

    # 只有 deleted 状态的文档才能恢复
    if doc.status != DocStatus.deleted:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            f"文档 {doc_id} 当前状态为 {doc.status.value}，只能恢复已删除的文档",
            400,
        )

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


# ── 4.5.1 重试失败文档 ─────────────────────────────────────────────

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


# ── 4.6 版本历史 ──────────────────────────────────────────────────

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
