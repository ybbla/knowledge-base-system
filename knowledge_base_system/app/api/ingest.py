from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.deps import ingestion_pipeline
from app.core.models import Document

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestDocument(BaseModel):
    title: str
    source_type: str
    source_uri: str
    category: str = "\u901a\u7528"


class IngestRequest(BaseModel):
    documents: list[IngestDocument]
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest(request: IngestRequest):
    """Submit documents for ingestion. Returns job_id for status polling."""
    job_ids: list[str] = []
    doc_ids: list[str] = []

    for item in request.documents:
        doc = Document(
            title=item.title,
            source_type=item.source_type,
            source_uri=item.source_uri,
            category=item.category,
        )
        doc.ingest_job_id = doc.doc_id  # simplify: doc_id as job_id

        job = ingestion_pipeline.submit(
            doc,
            options=request.options,
        )
        job_ids.append(job.job_id)
        doc_ids.append(doc.doc_id)

    return {
        "job_id": job_ids[0] if len(job_ids) == 1 else job_ids,
        "status": "accepted",
        "doc_ids": doc_ids,
        "warnings": [],
    }


@router.get("/{job_id}")
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
    }
