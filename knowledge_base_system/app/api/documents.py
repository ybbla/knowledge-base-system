"""旧版文档管理 API — 已废弃，保留仅为向后兼容。

提供文档列表、详情、解析元素、知识块查询等接口。
请使用以下 v1 接口替代：
- 文档列表：       GET  /api/v1/documents
- 文档详情：       GET  /api/v1/documents/{doc_id}
- 解析元素列表：    GET  /api/v1/documents/{doc_id}/elements
- 知识块列表：      GET  /api/v1/documents/{doc_id}/chunks

旧版接口将在后续大版本中移除。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core import deps


def _mark_deprecated(response: Response) -> None:
    """路由级依赖：为所有旧版文档接口添加 X-Deprecated 响应头。"""
    response.headers["X-Deprecated"] = "Use /api/v1/documents"


router = APIRouter(
    prefix="/documents",
    tags=["documents (deprecated)"],
    dependencies=[Depends(_mark_deprecated)],
)
logger = logging.getLogger(__name__)


def _doc_to_dict(doc) -> dict:
    """将 Document 模型转为可 JSON 序列化的字典。"""
    return {
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
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "metadata": doc.metadata if hasattr(doc, "metadata") else {},
    }


def _element_to_dict(el) -> dict:
    """将 ParsedElement 转为可 JSON 序列化的字典。"""
    return {
        "element_id": el.element_id,
        "doc_id": el.doc_id,
        "doc_version": el.doc_version,
        "parent_element_id": el.parent_element_id,
        "sequence_order": el.sequence_order,
        "element_type": el.element_type.value if hasattr(el.element_type, "value") else el.element_type,
        "text": el.text,
        "structured_data": el.structured_data,
        "asset_ids": el.asset_ids,
        "embedded_doc_id": el.embedded_doc_id,
        "source_location": el.source_location.model_dump(mode="json") if hasattr(el.source_location, "model_dump") else el.source_location,
        "metadata": el.metadata if hasattr(el, "metadata") else {},
    }


def _chunk_to_dict(chunk) -> dict:
    """将 KnowledgeChunk 转为可 JSON 序列化的字典。"""
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
        "category": chunk.category,
        "status": chunk.status.value if hasattr(chunk.status, "value") else chunk.status,
        "asset_refs": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in (chunk.asset_refs or [])],
        "source_refs": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in (chunk.source_refs or [])],
        "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
    }


@router.get("", deprecated=True)
async def list_documents(
    category: str | None = Query(default=None, description="按分类过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
):
    """获取所有文档列表。已废弃：请使用 GET /api/v1/documents。"""
    logger.warning("已废弃接口 GET /documents 被调用")
    repo = deps.document_repo
    if repo is None:
        raise HTTPException(status_code=503, detail="PostgreSQL 文档仓储不可用")

    try:
        docs = repo.list(category=category, status=status)
        return {"documents": [_doc_to_dict(d) for d in docs], "total": len(docs)}
    except Exception as e:
        logger.exception("查询文档列表失败")
        raise HTTPException(status_code=500, detail=f"查询文档列表失败: {e}")


@router.get("/{doc_id}", deprecated=True)
async def get_document(doc_id: str):
    """获取单个文档详情。已废弃：请使用 GET /api/v1/documents/{doc_id}。"""
    logger.warning("已废弃接口 GET /documents/%s 被调用", doc_id)
    repo = deps.document_repo
    if repo is None:
        raise HTTPException(status_code=503, detail="PostgreSQL 文档仓储不可用")

    doc = repo.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    return _doc_to_dict(doc)


@router.get("/{doc_id}/elements", deprecated=True)
async def get_document_elements(doc_id: str):
    """获取文档的解析元素列表。已废弃：请使用 GET /api/v1/documents/{doc_id}/elements。"""
    logger.warning("已废弃接口 GET /documents/%s/elements 被调用", doc_id)
    repo = deps.element_repo
    if repo is None:
        raise HTTPException(status_code=503, detail="PostgreSQL 解析元素仓储不可用")

    elements = repo.get_by_doc_id(doc_id)
    return {"elements": [_element_to_dict(el) for el in elements], "total": len(elements)}


@router.get("/{doc_id}/chunks", deprecated=True)
async def get_document_chunks(doc_id: str):
    """获取文档的知识块列表。已废弃：请使用 GET /api/v1/documents/{doc_id}/chunks。"""
    logger.warning("已废弃接口 GET /documents/%s/chunks 被调用", doc_id)
    chunk_store = deps.chunk_store
    if chunk_store is None:
        raise HTTPException(status_code=503, detail="PostgreSQL 知识块存储不可用")

    if hasattr(chunk_store, "list_by_doc_id"):
        chunks = chunk_store.list_by_doc_id(doc_id)
    else:
        chunks = [c for c in chunk_store.list_all() if c.doc_id == doc_id]
    return {"chunks": [_chunk_to_dict(c) for c in chunks], "total": len(chunks)}
