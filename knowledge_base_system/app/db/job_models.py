"""入库任务 ORM 模型 — 映射 ingest_jobs 表。

由 app.db.models.Base 统一管理 schema，scripts/setup_services.py 的
Base.metadata.create_all() 会自动创建此表。
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.db.models import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DbIngestJob(Base):
    """入库任务 ORM 模型 — 对应 ingest_jobs 表。

    记录每个异步入库任务的生命周期，供 SSE 端点查询和前端进度展示。
    """

    __tablename__ = "ingest_jobs"
    __table_args__ = (
        Index("idx_ij_doc_id", "doc_id"),
        Index("idx_ij_status", "status"),
    )

    job_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), nullable=False)
    dramatiq_message_id = Column(String(128), default="")
    status = Column(String(32), default="queued")
    stage = Column(String(32), default="")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
