from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.deps import document_repo, ingestion_pipeline
from app.core.errors import DocumentNotFoundError
from app.core.models import Document

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestDocument(BaseModel):
    title: str
    source_type: str
    source_uri: str
    source_hash: str = ""  # \u4e0a\u4f20\u6d41\u7a0b\u5fc5\u4f20\uff1b\u624b\u52a8\u5165\u5e93\u53ef\u4e3a\u7a7a\uff0c\u7a7a\u503c\u65f6\u7528 source_uri \u53bb\u91cd
    category: str = "\u901a\u7528"
    doc_id: str | None = None  # \u53ef\u9009\uff0c\u6307\u5b9a\u5219\u8d70\u589e\u91cf\u66f4\u65b0\u6d41\u7a0b


class IngestRequest(BaseModel):
    documents: list[IngestDocument]
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_202_ACCEPTED, deprecated=True)
async def ingest(request: IngestRequest):
    """提交文档入库任务。支持新建和增量更新两种模式。"""
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
            if existing.source_hash == item.source_hash:
                # 内容未变化，跳过
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
            doc.ingest_job_id = doc.doc_id
            job = ingestion_pipeline.submit(
                doc,
                options=request.options,
                is_update=True,
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
            doc.ingest_job_id = doc.doc_id
            job = ingestion_pipeline.submit(
                doc,
                options=request.options,
                is_update=False,
            )

        job_ids.append(job.job_id)
        doc_ids.append(doc.doc_id)

    return {
        "job_id": job_ids[0] if len(job_ids) == 1 else job_ids,
        "status": "accepted",
        "doc_ids": doc_ids,
        "warnings": warnings,
    }


@router.get("/{job_id}", deprecated=True)
async def get_ingest_status(job_id: str):
    """Query ingestion job progress."""
    job = ingestion_pipeline.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "doc_ids": job.doc_ids,
        "chunk_count": job.chunk_count,
        "asset_count": job.asset_count,
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "completed_at": job.finished_at.isoformat() if job.finished_at else None,
    }
