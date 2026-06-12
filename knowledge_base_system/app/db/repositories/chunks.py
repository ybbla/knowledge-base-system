import logging
from datetime import datetime, timezone

from app.core.models import (
    AssetRef,
    AssetRelation,
    ChunkIndexStatus,
    KnowledgeChunk,
    KnowledgeType,
    Render,
    SourceRef,
    SourceLocation,
)
from app.db.engine import create_session_factory
from app.db.models import DbKnowledgeChunk

logger = logging.getLogger(__name__)


class PgChunkStore:
    """PostgreSQL-backed chunk store matching the ChunkStore interface."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or create_session_factory()

    def _to_db(self, chunk: KnowledgeChunk) -> DbKnowledgeChunk:
        return DbKnowledgeChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            doc_version=chunk.doc_version,
            title=chunk.title,
            content=chunk.content,
            content_hash=chunk.content_hash,
            knowledge_type=chunk.knowledge_type.value,
            category=chunk.category,
            status=chunk.status.value,
            index_status=chunk.index_status.value,
            indexed_at=chunk.indexed_at,
            index_error=chunk.index_error,
            asset_refs=[ref.model_dump(mode="json") for ref in chunk.asset_refs],
            source_refs=[ref.model_dump(mode="json") for ref in chunk.source_refs],
            ingest_job_id=chunk.ingest_job_id,
            meta=chunk.metadata,
        )

    def _from_db(self, db_chunk: DbKnowledgeChunk) -> KnowledgeChunk:
        asset_refs = []
        for raw in db_chunk.asset_refs or []:
            render_data = raw.get("render") or {}
            asset_refs.append(
                AssetRef(
                    asset_id=raw["asset_id"],
                    relation=AssetRelation(raw.get("relation", "evidence")),
                    linked_text=raw.get("linked_text"),
                    caption=raw.get("caption"),
                    render=Render(
                        mode=render_data.get("mode", "inline"),
                        position=render_data.get("position", "after_linked_text"),
                    ),
                )
            )

        source_refs = []
        for raw in db_chunk.source_refs or []:
            source_refs.append(
                SourceRef(
                    doc_id=raw["doc_id"],
                    doc_version=raw.get("doc_version", 1),
                    element_id=raw["element_id"],
                    source_location=SourceLocation.model_validate(
                        raw.get("source_location") or {}
                    ),
                )
            )

        return KnowledgeChunk(
            chunk_id=db_chunk.chunk_id,
            doc_id=db_chunk.doc_id,
            doc_version=db_chunk.doc_version,
            title=db_chunk.title,
            content=db_chunk.content,
            content_hash=db_chunk.content_hash,
            knowledge_type=KnowledgeType(db_chunk.knowledge_type),
            category=db_chunk.category,
            status=db_chunk.status,
            index_status=ChunkIndexStatus(db_chunk.index_status or "pending"),
            indexed_at=db_chunk.indexed_at,
            index_error=db_chunk.index_error,
            asset_refs=asset_refs,
            source_refs=source_refs,
            ingest_job_id=db_chunk.ingest_job_id,
            metadata=db_chunk.meta or {},
        )

    def put(self, chunk: KnowledgeChunk) -> None:
        with self._session_factory() as session:
            db_chunk = self._to_db(chunk)
            session.merge(db_chunk)
            session.commit()

    def get(self, chunk_id: str) -> KnowledgeChunk | None:
        with self._session_factory() as session:
            db_chunk = session.get(DbKnowledgeChunk, chunk_id)
            if db_chunk is None:
                return None
            return self._from_db(db_chunk)

    def get_batch(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        with self._session_factory() as session:
            db_chunks = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.chunk_id.in_(chunk_ids))
                .all()
            )
            return [self._from_db(c) for c in db_chunks]

    def list_all(self, category: str | None = None) -> list[KnowledgeChunk]:
        with self._session_factory() as session:
            query = session.query(DbKnowledgeChunk)
            if category is not None:
                query = query.filter_by(category=category)
            db_chunks = query.order_by(DbKnowledgeChunk.chunk_id).all()
            return [self._from_db(c) for c in db_chunks]

    def list_by_index_status(
        self,
        statuses: list[ChunkIndexStatus | str],
        limit: int | None = None,
    ) -> list[KnowledgeChunk]:
        values = [
            status.value if isinstance(status, ChunkIndexStatus) else status
            for status in statuses
        ]
        with self._session_factory() as session:
            query = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.index_status.in_(values))
                .order_by(DbKnowledgeChunk.chunk_id)
            )
            if limit is not None:
                query = query.limit(limit)
            return [self._from_db(c) for c in query.all()]

    def update_index_status(
        self,
        chunk_ids: list[str],
        status: ChunkIndexStatus | str,
        error: str | None = None,
    ) -> None:
        if not chunk_ids:
            return
        value = status.value if isinstance(status, ChunkIndexStatus) else status
        indexed_at = datetime.now(timezone.utc) if value == ChunkIndexStatus.indexed.value else None
        with self._session_factory() as session:
            rows = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.chunk_id.in_(chunk_ids))
                .all()
            )
            for row in rows:
                row.index_status = value
                row.indexed_at = indexed_at
                row.index_error = error
            session.commit()

    def count(self) -> int:
        with self._session_factory() as session:
            return session.query(DbKnowledgeChunk).count()
