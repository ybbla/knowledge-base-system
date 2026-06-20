from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()
JSONBType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── DB Models ──────────────────────────────────────────────────────


class DbDocument(Base):
    __tablename__ = "documents"

    doc_id = Column(String(64), primary_key=True)
    title = Column(String(512), nullable=False)
    source_type = Column(String(32), nullable=False, default="markdown")
    source_uri = Column(Text, nullable=False)
    source_hash = Column(String(128), default="")
    version = Column(Integer, default=1)
    status = Column(String(32), default="processing")
    category = Column(String(128), default="通用")
    parent_doc_id = Column(String(64), nullable=True)
    root_doc_id = Column(String(64), nullable=True)
    ingest_job_id = Column(String(64), default="")  # 保留旧字段用于向后兼容
    previous_doc_id = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    meta = Column("metadata", JSONBType, default=dict)


class DbParsedElement(Base):
    __tablename__ = "parsed_elements"

    element_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id"), nullable=False)
    doc_version = Column(Integer, default=1)
    parent_element_id = Column(String(64), nullable=True)
    sequence_order = Column(Integer, default=0)
    element_type = Column(String(32), nullable=False)
    text = Column(Text, default="")
    structured_data = Column(JSONBType, nullable=True)
    asset_ids = Column(JSONBType, default=list)
    embedded_doc_id = Column(String(64), nullable=True)
    source_location = Column(JSONBType, default=dict)
    meta = Column("metadata", JSONBType, default=dict)


class DbAsset(Base):
    __tablename__ = "assets"

    asset_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id"), nullable=False)
    source_element_id = Column(String(64), default="")
    asset_type = Column(String(32), nullable=False)
    original_uri = Column(Text, nullable=False)
    storage_uri = Column(Text, nullable=True)
    mime_type = Column(String(128), default="")
    content_hash = Column(String(128), default="")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    status = Column(String(32), default="ready")
    extracted_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    meta = Column("metadata", JSONBType, default=dict)


class DbKnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    chunk_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id"), nullable=False)
    doc_version = Column(Integer, default=1)  # 已废弃 — 不再在代码层读写
    title = Column(String(512), default="")
    content = Column(Text, nullable=False)
    content_hash = Column(String(128), default="")
    knowledge_type = Column(String(32), default="declarative")
    category = Column(String(128), default="通用")
    status = Column(String(32), default="active")
    index_status = Column(String(32), default="pending")  # 已废弃 — 不再在代码层读写
    indexed_at = Column(DateTime(timezone=True), nullable=True)  # 已废弃 — 不再在代码层读写
    index_error = Column(Text, nullable=True)  # 已废弃 — 不再在代码层读写
    asset_refs = Column(JSONBType, default=list)
    source_refs = Column(JSONBType, default=list)
    ingest_job_id = Column(String(64), default="")  # 已废弃 — 不再在代码层读写
    meta = Column("metadata", JSONBType, default=dict)


class DbIdfStat(Base):
    __tablename__ = "idf_stats"

    token = Column(String(256), primary_key=True)
    token_id = Column(Integer, nullable=False)
    df = Column(Integer, default=0)
    total_docs = Column(Integer, default=0)
