"""知识块管理 API v1 — 列表、创建、详情、更新、软删除、恢复、重建索引和批量操作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
    error_json,
)
from app.api.v1.services import reindex_chunk, reindex_chunks_batch, sync_index_metadata
from app.core.deps import (
    bm25_index,
    chunk_store,
    document_repo,
    vector_index,
)
from app.core.models import (
    ChunkIndexStatus,
    ChunkStatus,
    KnowledgeChunk,
    KnowledgeType,
    compute_hash,
)
from llm.volcengine_client import embedding_client

router = APIRouter(prefix="/chunks", tags=["chunks"])
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _get_doc_title(doc_id: str) -> str | None:
    """获取文档标题，用于列表展示。"""
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc:
            return doc.title
    return None


def _chunk_to_list_item(chunk: KnowledgeChunk) -> dict[str, Any]:
    """将知识块转为列表条目（含内容摘要和展示字段）。"""
    preview = chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_title": _get_doc_title(chunk.doc_id),
        "doc_version": chunk.doc_version,
        "title": chunk.title,
        "content_preview": preview,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
        "category": chunk.category,
        "status": chunk.status.value if hasattr(chunk.status, "value") else chunk.status,
        "index_status": chunk.index_status.value if hasattr(chunk.index_status, "value") else chunk.index_status,
        "indexed_at": chunk.indexed_at.isoformat() if chunk.indexed_at else None,
        "index_error": chunk.index_error,
        "asset_count": len(chunk.asset_refs) if chunk.asset_refs else 0,
        "source_count": len(chunk.source_refs) if chunk.source_refs else 0,
        "ingest_job_id": chunk.ingest_job_id,
        "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
    }


def _chunk_to_detail(chunk: KnowledgeChunk) -> dict[str, Any]:
    """将知识块转为详情条目（含完整内容、来源、资源）。"""
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_title": _get_doc_title(chunk.doc_id),
        "doc_version": chunk.doc_version,
        "title": chunk.title,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
        "category": chunk.category,
        "status": chunk.status.value if hasattr(chunk.status, "value") else chunk.status,
        "index_status": chunk.index_status.value if hasattr(chunk.index_status, "value") else chunk.index_status,
        "indexed_at": chunk.indexed_at.isoformat() if chunk.indexed_at else None,
        "index_error": chunk.index_error,
        "asset_refs": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in (chunk.asset_refs or [])],
        "source_refs": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in (chunk.source_refs or [])],
        "ingest_job_id": chunk.ingest_job_id,
        "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
    }


def _resolve_chunk(chunk_id: str) -> KnowledgeChunk | None:
    """从 PostgreSQL 知识块存储解析知识块。"""
    if hasattr(chunk_store, "get"):
        return chunk_store.get(chunk_id)
    return None


# ── 5.1 知识块列表 ──────────────────────────────────────────────────

@router.get("")
async def list_chunks(
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    doc_id: str | None = Query(default=None),
    doc_version: int | None = Query(default=None),
    category: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    index_status: str | None = Query(default=None),
    ingest_job_id: str | None = Query(default=None),
    has_assets: bool | None = Query(default=None),
    has_sources: bool | None = Query(default=None),
):
    """获取知识块分页列表，支持多条件筛选。"""
    if hasattr(chunk_store, "list_paginated"):
        chunks, total = chunk_store.list_paginated(
            page=pagination.page,
            page_size=pagination.page_size,
            keyword=search.keyword,
            doc_id=doc_id,
            doc_version=doc_version,
            category=category,
            knowledge_type=knowledge_type,
            status=status,
            index_status=index_status,
            ingest_job_id=ingest_job_id,
            has_assets=has_assets,
            has_sources=has_sources,
            sort_by=pagination.sort_by or "chunk_id",
            sort_order=pagination.sort_order,
        )
        items = [_chunk_to_list_item(c) for c in chunks]
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        meta = PaginationMeta(
            page=pagination.page, page_size=pagination.page_size,
            total=total, total_pages=total_pages,
        )
        return PaginatedResponse(data=items, meta=meta.model_dump()).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 知识块存储不可用",
        503,
    )


# ── 5.2 创建知识块 ──────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_chunk(
    doc_id: str = Query(...),
    title: str = Query(default=""),
    content: str = Query(...),
    knowledge_type: str = Query(default="declarative"),
    category: str = Query(default="通用"),
    metadata: str | None = Query(default=None),
    index_after_create: bool = Query(default=False),
):
    """创建人工知识块，计算 content_hash，可选创建后索引。"""
    # 校验文档存在性
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                status.HTTP_404_NOT_FOUND,
            )

    meta_dict: dict[str, Any] = {"manual": True}
    if metadata:
        try:
            meta_dict.update(json.loads(metadata))
        except json.JSONDecodeError:
            pass

    chunk = KnowledgeChunk(
        doc_id=doc_id,
        title=title,
        content=content,
        knowledge_type=KnowledgeType(knowledge_type),
        category=category,
        metadata=meta_dict,
    )

    # 持久化
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    if document_repo is not None and hasattr(document_repo, "touch_updated_at"):
        try:
            document_repo.touch_updated_at(doc_id)
        except Exception:
            logger.exception("刷新知识块归属文档更新时间失败")

    # 创建后索引
    if index_after_create:
        try:
            chunk.index_status = ChunkIndexStatus.indexing
            if hasattr(chunk_store, "put"):
                chunk_store.put(chunk)
            reindex_chunk(chunk, vector_index, bm25_index, embedding_client)
            chunk.index_status = ChunkIndexStatus.indexed
            if hasattr(chunk_store, "put"):
                chunk_store.put(chunk)
        except Exception as e:
            logger.exception("知识块索引失败")
            chunk.index_status = ChunkIndexStatus.failed
            chunk.index_error = str(e)
            if hasattr(chunk_store, "put"):
                chunk_store.put(chunk)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.3 知识块详情 ──────────────────────────────────────────────────

@router.get("/{chunk_id}")
async def get_chunk(chunk_id: str):
    """获取知识块详情，含完整内容、来源引用、资源引用和索引状态。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.4 & 5.5 更新知识块 ───────────────────────────────────────────

@router.patch("/{chunk_id}")
async def update_chunk(
    chunk_id: str,
    title: str | None = Query(default=None),
    content: str | None = Query(default=None),
    category: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    chunk_status: str | None = Query(default=None, alias="status"),
    metadata: str | None = Query(default=None),
    reindex: bool = Query(default=True, description="内容变化时是否重建索引"),
):
    """更新知识块字段。内容变化时强制重新计算 content_hash 并触发/排队重建索引。

    注意: chunk_status 参数通过 alias="status" 接收前端传递的 status 字段，
    避免参数名遮蔽 `from fastapi import status` 模块。
    """
    from fastapi import status as http_status

    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    content_changed = False
    status_changed = False

    if title is not None:
        chunk.title = title
    if content is not None and content != chunk.content:
        chunk.content = content
        chunk.content_hash = compute_hash(content)
        content_changed = True
    if category is not None:
        chunk.category = category
    if knowledge_type is not None:
        try:
            chunk.knowledge_type = KnowledgeType(knowledge_type)
        except ValueError:
            return error_json(
                ErrorCode.VALIDATION_ERROR,
                f"无效的知识类型: {knowledge_type}，有效值为 {[k.value for k in KnowledgeType]}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    if chunk_status is not None:
        try:
            new_status = ChunkStatus(chunk_status)
        except ValueError:
            return error_json(
                ErrorCode.VALIDATION_ERROR,
                f"无效的知识块状态: {chunk_status}，有效值为 {[s.value for s in ChunkStatus]}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if new_status != chunk.status:
            status_changed = True
        chunk.status = new_status
    if metadata is not None:
        try:
            meta_update = json.loads(metadata)
            chunk.metadata.update(meta_update)
        except json.JSONDecodeError:
            pass

    # 持久化
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 内容变化 → 重建索引
    if content_changed:
        if reindex:
            try:
                chunk.index_status = ChunkIndexStatus.indexing
                if hasattr(chunk_store, "put"):
                    chunk_store.put(chunk)
                reindex_chunk(chunk, vector_index, bm25_index, embedding_client)
                chunk.index_status = ChunkIndexStatus.indexed
                if hasattr(chunk_store, "put"):
                    chunk_store.put(chunk)
            except Exception as e:
                logger.exception("重建索引失败")
                chunk.index_status = ChunkIndexStatus.failed
                chunk.index_error = str(e)
                if hasattr(chunk_store, "put"):
                    chunk_store.put(chunk)
        else:
            # 内容变化但 skip reindex → 标为 pending
            chunk.index_status = ChunkIndexStatus.pending
            if hasattr(chunk_store, "put"):
                chunk_store.put(chunk)

    # 状态变化 → 同步索引元数据
    if status_changed and not content_changed:
        sync_index_metadata(chunk, vector_index, bm25_index)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.6 删除和恢复知识块 ───────────────────────────────────────────

@router.delete("/{chunk_id}")
async def delete_chunk(chunk_id: str):
    """软删除知识块，同步检索索引状态。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    chunk.status = ChunkStatus.deleted
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 同步索引
    sync_index_metadata(chunk, vector_index, bm25_index)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


@router.post("/{chunk_id}/restore")
async def restore_chunk(chunk_id: str):
    """恢复软删除的知识块。如果索引缺失则标记为 pending。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    chunk.status = ChunkStatus.active

    # 如果索引状态不是 indexed，标记为 pending
    if hasattr(chunk.index_status, "value") and chunk.index_status.value != "indexed":
        chunk.index_status = ChunkIndexStatus.pending
    elif chunk.index_status not in (ChunkIndexStatus.indexed, ChunkIndexStatus.pending):
        chunk.index_status = ChunkIndexStatus.pending

    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    sync_index_metadata(chunk, vector_index, bm25_index)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.7 重建索引 ──────────────────────────────────────────────────

@router.post("/batch/reindex")
async def reindex_batch(body: dict[str, list[str]] = Body(...)):
    """批量重建知识块索引。"""
    from app.api.v1.services import reindex_chunks_batch

    chunk_ids = body.get("chunk_ids", [])
    chunks = []
    for cid in chunk_ids:
        chunk = _resolve_chunk(cid)
        if chunk is not None:
            chunks.append(chunk)

    if not chunks:
        return APIResponse(
            data={"succeeded": [], "failed": []},
            meta={"total_submitted": len(chunk_ids)},
        ).model_dump(mode="json")

    result = reindex_chunks_batch(
        chunks, vector_index, bm25_index, embedding_client, chunk_store
    )

    return APIResponse(
        data=result,
        meta={"total_submitted": len(chunk_ids), "total_processed": len(chunks)},
    ).model_dump(mode="json")


@router.post("/{chunk_id}/reindex")
async def reindex_single(chunk_id: str):
    """重建单个知识块的向量索引和 BM25 索引。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    try:
        chunk.index_status = ChunkIndexStatus.indexing
        if hasattr(chunk_store, "put"):
            chunk_store.put(chunk)

        reindex_chunk(chunk, vector_index, bm25_index, embedding_client)

        chunk.index_status = ChunkIndexStatus.indexed
        chunk.indexed_at = datetime.now(timezone.utc)
        chunk.index_error = None
        if hasattr(chunk_store, "put"):
            chunk_store.put(chunk)

        return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")
    except Exception as e:
        logger.exception("重建索引失败")
        chunk.index_status = ChunkIndexStatus.failed
        chunk.index_error = str(e)
        if hasattr(chunk_store, "put"):
            chunk_store.put(chunk)
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            f"重建索引失败: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ── 5.8 批量状态操作 ───────────────────────────────────────────────

@router.post("/batch")
async def batch_chunk_operation(body: dict[str, Any] = Body(...)):
    """对多个知识块执行批量状态操作。"""
    action = body.get("action", "")
    chunk_ids = body.get("chunk_ids", [])
    new_status = body.get("status")

    if not chunk_ids:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "chunk_ids 不能为空",
            status.HTTP_400_BAD_REQUEST,
        )

    if action == "delete":
        # 批量软删除
        if hasattr(chunk_store, "bulk_update_status_by_chunk_ids"):
            updated = chunk_store.bulk_update_status_by_chunk_ids(chunk_ids, "deleted")
        else:
            updated = 0
            for cid in chunk_ids:
                chunk = _resolve_chunk(cid)
                if chunk:
                    chunk.status = ChunkStatus.deleted
                    if hasattr(chunk_store, "put"):
                        chunk_store.put(chunk)
                    updated += 1

        # 同步索引
        vector_index.update_status_batch(chunk_ids, "deleted")
        bm25_index.update_status_batch(chunk_ids, "deleted")

        return APIResponse(
            data={"action": action, "updated": updated},
            meta={"total_submitted": len(chunk_ids)},
        ).model_dump(mode="json")

    elif action == "restore":
        if hasattr(chunk_store, "bulk_update_status_by_chunk_ids"):
            updated = chunk_store.bulk_update_status_by_chunk_ids(chunk_ids, "active")
        else:
            updated = 0
            for cid in chunk_ids:
                chunk = _resolve_chunk(cid)
                if chunk:
                    chunk.status = ChunkStatus.active
                    if hasattr(chunk_store, "put"):
                        chunk_store.put(chunk)
                    updated += 1

        vector_index.update_status_batch(chunk_ids, "active")
        bm25_index.update_status_batch(chunk_ids, "active")

        return APIResponse(
            data={"action": action, "updated": updated},
            meta={"total_submitted": len(chunk_ids)},
        ).model_dump(mode="json")

    elif action == "update_status" and new_status is not None:
        # 校验新状态是否合法
        try:
            ChunkStatus(new_status)
        except ValueError:
            return error_json(
                ErrorCode.VALIDATION_ERROR,
                f"无效的知识块状态: {new_status}，有效值为 {[s.value for s in ChunkStatus]}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if hasattr(chunk_store, "bulk_update_status_by_chunk_ids"):
            updated = chunk_store.bulk_update_status_by_chunk_ids(chunk_ids, new_status)
        else:
            updated = 0
            for cid in chunk_ids:
                chunk = _resolve_chunk(cid)
                if chunk:
                    chunk.status = ChunkStatus(new_status)
                    if hasattr(chunk_store, "put"):
                        chunk_store.put(chunk)
                    updated += 1

        vector_index.update_status_batch(chunk_ids, new_status)
        bm25_index.update_status_batch(chunk_ids, new_status)

        return APIResponse(
            data={"action": action, "new_status": new_status, "updated": updated},
            meta={"total_submitted": len(chunk_ids)},
        ).model_dump(mode="json")

    else:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            f"不支持的操作: {action}",
            status.HTTP_400_BAD_REQUEST,
        )
