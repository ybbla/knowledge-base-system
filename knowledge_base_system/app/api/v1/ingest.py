"""入库任务 API v1 — 任务列表、详情、重试和取消。"""

from __future__ import annotations

from math import ceil
from typing import Any

from fastapi import APIRouter, Query, status

from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    error_json,
)
from app.core.deps import document_repo, ingestion_pipeline

router = APIRouter(prefix="/ingest/jobs", tags=["ingest-jobs"])


def job_to_dict(job: Any) -> dict[str, Any]:
    """将入库任务对象转换为前端可展示的 v1 字典。"""
    doc_id = getattr(job, "doc_id", "") or (getattr(job, "doc_ids", []) or [""])[0]
    raw_title = getattr(job, "doc_title", None)
    doc_title = raw_title if (raw_title is not None and raw_title != "") else doc_id
    if document_repo is not None and doc_id:
        try:
            doc = document_repo.get(doc_id)
            if doc is not None:
                doc_title = doc.title
        except Exception:
            pass

    started_at = getattr(job, "started_at", None)
    finished_at = getattr(job, "finished_at", None)
    created_at = getattr(job, "created_at", None) or started_at
    doc_ids = list(getattr(job, "doc_ids", []) or ([doc_id] if doc_id else []))
    status_value = getattr(job, "status", "unknown")
    stage = getattr(job, "stage", None) or status_value

    return {
        "job_id": getattr(job, "job_id", ""),
        "doc_id": doc_id,
        "doc_ids": doc_ids,
        "doc_title": doc_title,
        "doc_count": len(doc_ids),
        "mode": getattr(job, "mode", ""),
        "status": status_value,
        "stage": stage,
        "progress": getattr(job, "progress", 100 if status_value in {"completed", "failed", "canceled"} else 0),
        "chunk_count": getattr(job, "chunk_count", 0),
        "asset_count": getattr(job, "asset_count", 0),
        "error": getattr(job, "error", None),
        "created_at": created_at.isoformat() if created_at else None,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "completed_at": finished_at.isoformat() if finished_at else None,
    }


def _list_jobs() -> list[Any]:
    if hasattr(ingestion_pipeline, "list_jobs"):
        return ingestion_pipeline.list_jobs()
    jobs = getattr(ingestion_pipeline, "_jobs", {})
    return list(jobs.values())


@router.get("")
async def list_ingest_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    doc_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
):
    """获取入库任务列表，供入库任务页面展示。"""
    items = [job_to_dict(job) for job in _list_jobs()]

    if status_filter:
        items = [item for item in items if item.get("status") == status_filter]
    if doc_id:
        items = [item for item in items if doc_id in (item.get("doc_ids") or [])]
    if mode:
        items = [item for item in items if item.get("mode") == mode]
    if keyword:
        kw = keyword.lower()
        items = [
            item for item in items
            if kw in str(item.get("job_id", "")).lower()
            or kw in str(item.get("doc_id", "")).lower()
            or kw in str(item.get("doc_title", "")).lower()
        ]

    total = len(items)
    start = (page - 1) * page_size
    paged = items[start:start + page_size]
    meta = PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=ceil(total / page_size) if total else 0,
    )
    return PaginatedResponse(data=paged, meta=meta.model_dump()).model_dump(mode="json")


@router.get("/{job_id}")
async def get_ingest_job(job_id: str):
    """获取单个入库任务详情。"""
    job = ingestion_pipeline.get_job(job_id)
    if job is None:
        return error_json(
            ErrorCode.INGEST_JOB_NOT_FOUND,
            f"入库任务 {job_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )
    return APIResponse(data=job_to_dict(job)).model_dump(mode="json")


@router.post("/{job_id}/retry")
async def retry_ingest_job(job_id: str):
    """重试失败的入库任务。"""
    job = ingestion_pipeline.get_job(job_id)
    if job is None:
        return error_json(
            ErrorCode.INGEST_JOB_NOT_FOUND,
            f"入库任务 {job_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )
    if getattr(job, "status", None) != "failed":
        return error_json(
            ErrorCode.INGEST_JOB_CONFLICT,
            "只有失败任务可以重试",
            status.HTTP_409_CONFLICT,
        )

    new_job = ingestion_pipeline.retry_job(job_id) if hasattr(ingestion_pipeline, "retry_job") else None
    if new_job is None:
        return error_json(
            ErrorCode.INGEST_JOB_CONFLICT,
            "任务无法重试",
            status.HTTP_409_CONFLICT,
        )
    return APIResponse(
        data=job_to_dict(new_job),
        meta={"retried_from": job_id},
    ).model_dump(mode="json")


@router.post("/{job_id}/cancel")
async def cancel_ingest_job(job_id: str):
    """取消尚未开始执行的入库任务。"""
    job = ingestion_pipeline.get_job(job_id)
    if job is None:
        return error_json(
            ErrorCode.INGEST_JOB_NOT_FOUND,
            f"入库任务 {job_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )
    canceled = ingestion_pipeline.cancel_job(job_id) if hasattr(ingestion_pipeline, "cancel_job") else False
    if not canceled:
        return error_json(
            ErrorCode.INGEST_JOB_CONFLICT,
            "该任务当前不可取消",
            status.HTTP_409_CONFLICT,
        )
    return APIResponse(data=job_to_dict(job)).model_dump(mode="json")
