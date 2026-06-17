"""文档管理 API — 列表、详情、解析元素、知识块查询。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core import deps


def _mark_deprecated(response: Response) -> None:
    """为旧文档接口添加运行时废弃提示。"""
    response.headers["X-Deprecated"] = "Use /api/v1/documents"


router = APIRouter(
    prefix="/documents",
    tags=["documents"],
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
        "ingest_job_id": doc.ingest_job_id,
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


@router.get("", deprecated=True)
async def list_documents(
    category: str | None = Query(default=None, description="按分类过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
):
    """获取所有文档列表。"""
    repo = deps.document_repo
    if repo is not None:
        try:
            docs = repo.list(category=category, status=status)
            return {"documents": [_doc_to_dict(d) for d in docs], "total": len(docs)}
        except Exception as e:
            logger.exception("查询文档列表失败")
            raise HTTPException(status_code=500, detail=f"查询文档列表失败: {e}")

    # 内存后端 — 从 chunk_store 中提取文档信息
    chunk_store = deps.chunk_store
    docs_map = {}
    try:
        if hasattr(chunk_store, "list_all"):
            chunks = chunk_store.list_all()
        else:
            chunks = list(getattr(chunk_store, "_chunks", {}).values())

        for chunk in chunks:
            doc_id = chunk.doc_id
            if doc_id not in docs_map:
                docs_map[doc_id] = {
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
                }
    except Exception as e:
        logger.warning("无法从 chunk_store 获取文档列表: %s", e)

    docs = list(docs_map.values())
    if category:
        docs = [d for d in docs if d.get("category") == category]
    if status:
        docs = [d for d in docs if d.get("status") == status]

    return {"documents": docs, "total": len(docs)}


@router.get("/{doc_id}", deprecated=True)
async def get_document(doc_id: str):
    """获取单个文档详情。"""
    repo = deps.document_repo
    if repo is not None:
        doc = repo.get(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
        return _doc_to_dict(doc)

    # 内存后端 — 从 chunk_store 推断
    chunk_store = deps.chunk_store
    try:
        if hasattr(chunk_store, "list_all"):
            chunks = chunk_store.list_all()
        else:
            chunks = list(getattr(chunk_store, "_chunks", {}).values())
    except Exception:
        chunks = []

    doc_chunks = [c for c in chunks if c.doc_id == doc_id]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在于内存中")

    first = doc_chunks[0]
    return {
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
    }


@router.get("/{doc_id}/elements", deprecated=True)
async def get_document_elements(doc_id: str):
    """获取文档的解析元素列表。"""
    repo = deps.element_repo
    if repo is not None:
        elements = repo.get_by_doc_id(doc_id)
        return {"elements": [_element_to_dict(el) for el in elements], "total": len(elements)}

    # 内存后端暂不支持元素查询
    return {"elements": [], "total": 0}


@router.get("/{doc_id}/chunks", deprecated=True)
async def get_document_chunks(doc_id: str):
    """获取文档的知识块列表。"""
    chunk_store = deps.chunk_store
    try:
        if hasattr(chunk_store, "list_all"):
            all_chunks = chunk_store.list_all()
        else:
            all_chunks = list(getattr(chunk_store, "_chunks", {}).values())
    except Exception:
        all_chunks = []

    chunks = [c for c in all_chunks if c.doc_id == doc_id]
    return {"chunks": [_chunk_to_dict(c) for c in chunks], "total": len(chunks)}
