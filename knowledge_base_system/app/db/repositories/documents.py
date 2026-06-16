import logging
from datetime import datetime, timezone

from app.core.errors import DocumentNotFoundError, DuplicateDocumentError, VersionConflictError
from app.core.models import Document
from app.db.engine import create_session_factory
from app.db.models import DbDocument

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Persist and query Document records in PostgreSQL."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or create_session_factory()

    def _to_db(self, doc: Document) -> DbDocument:
        return DbDocument(
            doc_id=doc.doc_id,
            title=doc.title,
            source_type=doc.source_type,
            source_uri=doc.source_uri,
            source_hash=doc.source_hash,
            version=doc.version,
            status=doc.status.value,
            category=doc.category,
            parent_doc_id=doc.parent_doc_id,
            root_doc_id=doc.root_doc_id,
            ingest_job_id=doc.ingest_job_id,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            meta=doc.metadata,
        )

    def _from_db(self, db_doc: DbDocument) -> Document:
        return Document(
            doc_id=db_doc.doc_id,
            title=db_doc.title,
            source_type=db_doc.source_type,
            source_uri=db_doc.source_uri,
            source_hash=db_doc.source_hash,
            version=db_doc.version,
            status=db_doc.status,
            category=db_doc.category,
            parent_doc_id=db_doc.parent_doc_id,
            root_doc_id=db_doc.root_doc_id,
            ingest_job_id=db_doc.ingest_job_id,
            created_at=db_doc.created_at,
            updated_at=db_doc.updated_at,
            metadata=db_doc.meta or {},
        )

    def find_by_hash(self, source_hash: str) -> Document | None:
        """按 source_hash 查找活跃文档（status='active'），用于去重检查。"""
        if not source_hash:
            return None
        with self._session_factory() as session:
            db_doc = (
                session.query(DbDocument)
                .filter_by(source_hash=source_hash, status="active")
                .first()
            )
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def find_by_source_uri(self, source_uri: str) -> Document | None:
        """按 source_uri 查找文档。"""
        if not source_uri:
            return None
        with self._session_factory() as session:
            db_doc = (
                session.query(DbDocument)
                .filter_by(source_uri=source_uri)
                .first()
            )
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def create(self, doc: Document) -> Document:
        """创建新文档。先检查 doc_id 是否已存在，存在则抛出 DuplicateDocumentError。"""
        with self._session_factory() as session:
            existing = session.get(DbDocument, doc.doc_id)
            if existing is not None:
                raise DuplicateDocumentError(
                    f"Document {doc.doc_id} already exists"
                )
            db_doc = self._to_db(doc)
            session.add(db_doc)
            session.commit()
            return self._from_db(db_doc)

    def get(self, doc_id: str) -> Document | None:
        with self._session_factory() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def update(self, doc: Document) -> Document:
        """更新文档，使用乐观锁防止并发覆盖。

        只在 version 匹配时才执行更新并递增 version，
        影响行数为 0 则抛出 VersionConflictError。
        """
        expected_version = doc.version
        doc.updated_at = datetime.now(timezone.utc)
        with self._session_factory() as session:
            db_doc = session.get(DbDocument, doc.doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"Document {doc.doc_id} not found")
            if db_doc.version != expected_version:
                raise VersionConflictError(
                    f"Document {doc.doc_id} version mismatch: "
                    f"expected {expected_version}, got {db_doc.version}"
                )
            db_doc.title = doc.title
            db_doc.source_type = doc.source_type
            db_doc.source_uri = doc.source_uri
            db_doc.source_hash = doc.source_hash
            db_doc.version = doc.version + 1
            db_doc.status = doc.status.value
            db_doc.category = doc.category
            db_doc.parent_doc_id = doc.parent_doc_id
            db_doc.root_doc_id = doc.root_doc_id
            db_doc.ingest_job_id = doc.ingest_job_id
            db_doc.updated_at = doc.updated_at
            db_doc.meta = doc.metadata
            session.commit()
            result = self._from_db(db_doc)
            result.version = db_doc.version
            return result

    def list(
        self,
        *,
        category: str | None = None,
        status: str | None = None,
        ingest_job_id: str | None = None,
        root_doc_id: str | None = None,
    ) -> list[Document]:
        with self._session_factory() as session:
            query = session.query(DbDocument)
            if category is not None:
                query = query.filter_by(category=category)
            if status is not None:
                query = query.filter_by(status=status)
            if ingest_job_id is not None:
                query = query.filter_by(ingest_job_id=ingest_job_id)
            if root_doc_id is not None:
                query = query.filter_by(root_doc_id=root_doc_id)
            return [self._from_db(db_doc) for db_doc in query.all()]
