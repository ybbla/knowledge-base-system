"""旧版入库 API — 保留仅为向后兼容，将于后续版本移除。

请使用以下 v1 接口替代：
- 上传并入库：POST /api/v1/documents/upload
- 文档更新：POST /api/v1/documents/upload（带上 replace_doc_id + confirm_replace=true）
- 文档详情：GET /api/v1/documents/{doc_id}
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.deps import document_repo, ingestion_pipeline
from app.core.models import Document

router = APIRouter(prefix="/ingest", tags=["ingest (deprecated)"])
logger = logging.getLogger(__name__)


class IngestDocument(BaseModel):
    title: str
    source_type: str
    source_uri: str
    source_hash: str = ""  # 上传流程必传；手动入库可为空，空值时用 source_uri 去重
    category: str = "通用"
    doc_id: str | None = None  # 可选，指定则走增量更新流程


class IngestRequest(BaseModel):
    documents: list[IngestDocument]
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_202_ACCEPTED, deprecated=True)
async def ingest(request: IngestRequest, response: Response):
    """提交文档入库任务。支持新建和增量更新两种模式。"""
    response.headers["X-Deprecated"] = "Use /api/v1/documents/upload or /api/v1/documents/{doc_id}/ingest"
    logger.warning("Deprecated endpoint POST /ingest called")
    job_ids: list[str] = []
    doc_ids: list[str] = []
    warnings: list[dict] = []

    for item in request.documents:
        if item.doc_id:
            # ── 更新分支：doc_id 有值 → 查找已有文档并执行增量更新 ──
            existing = document_repo.get(item.doc_id) if document_repo else None
            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document {item.doc_id} not found",
                )
            if item.source_hash and existing.source_hash == item.source_hash:
                # 内容未变化，跳过（空 hash 表示未计算，不能作为 no_change 依据）
                warnings.append({
                    "doc_id": item.doc_id,
                    "reason": "no_change",
                    "existing_doc_id": item.doc_id,
                })
                continue

            doc = Document(
                doc_id=item.doc_id,
                title=item.title,
                source_type=item.source_type,
                source_uri=item.source_uri,
                source_hash=item.source_hash,
                category=item.category,
                version=existing.version,
                status=existing.status,
                parent_doc_id=existing.parent_doc_id,
                root_doc_id=existing.root_doc_id,
                metadata=existing.metadata,
            )
            doc = ingestion_pipeline.ingest(
                doc,
                options=request.options,
            )
        else:
            # ── 新建分支：doc_id 为空 → 去重检查后创建新文档 ──
            if document_repo is not None:
                # 优先按 source_hash 去重，hash 为空时降级为 source_uri 去重
                dup = document_repo.find_by_hash(item.source_hash) if item.source_hash else None
                if dup is None and not item.source_hash:
                    dup = document_repo.find_by_source_uri(item.source_uri)
                if dup is not None:
                    warnings.append({
                        "doc_id": "",
                        "reason": "duplicate_content",
                        "existing_doc_id": dup.doc_id,
                    })
                    continue

            doc = Document(
                title=item.title,
                source_type=item.source_type,
                source_uri=item.source_uri,
                source_hash=item.source_hash,
                category=item.category,
            )
            doc = ingestion_pipeline.ingest(
                doc,
                options=request.options,
            )

        job_ids.append(doc.doc_id)
        doc_ids.append(doc.doc_id)

    return {
        "job_id": job_ids[0] if len(job_ids) == 1 else job_ids,
        "status": "accepted",
        "doc_ids": doc_ids,
        "warnings": warnings,
    }


@router.get("/{job_id}", deprecated=True)
async def get_ingest_status(job_id: str, response: Response):
    """Query ingestion job progress. Deprecated: use GET /api/v1/documents/{doc_id} instead."""
    response.headers["X-Deprecated"] = "Use GET /api/v1/documents/{doc_id}"
    logger.warning("Deprecated endpoint GET /ingest/%s called", job_id)
    doc = document_repo.get(job_id) if document_repo else None
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    # Return simplified response based on document status
    return {
        "job_id": doc.doc_id,
        "status": "completed" if doc.status.value == "active" else doc.status.value,
        "doc_ids": [doc.doc_id],
        "chunk_count": 0,
        "error": doc.error_message,
    }
