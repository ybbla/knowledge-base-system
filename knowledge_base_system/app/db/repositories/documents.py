from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.errors import DocumentNotFoundError, DuplicateDocumentError, VersionConflictError
from app.core.models import Document
from app.db.models import DbDocument
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository):
    """Persist and query Document records in PostgreSQL."""

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
        """按 source_hash 查找非删除文档，用于去重检查。

        排除 status='deleted' 的文档，active/pending/processing/failed 均视为冲突。
        """
        if not source_hash:
            return None
        with self._session() as session:
            db_doc = (
                session.query(DbDocument)
                .filter(DbDocument.source_hash == source_hash)
                .filter(DbDocument.status != "deleted")
                .first()
            )
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def find_by_source_uri(self, source_uri: str) -> Document | None:
        """按 source_uri 查找文档。"""
        if not source_uri:
            return None
        with self._session() as session:
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
        with self._session() as session:
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
        with self._session() as session:
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
        with self._session() as session:
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
        with self._session() as session:
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

    # ── 扩展查询（2.1） ──────────────────────────────────────────

    def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        category: str | None = None,
        parent_doc_id: str | None = None,
        root_doc_id: str | None = None,
        ingest_job_id: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> tuple[list[Document], int]:
        """分页、关键词、多条件过滤查询文档列表。

        Returns:
            (文档列表, 总条数)
        """
        with self._session() as session:
            query = session.query(DbDocument)

            # ── 关键词搜索 ──
            if keyword:
                kw_pattern = f"%{keyword}%"
                from sqlalchemy import or_
                query = query.filter(
                    or_(
                        DbDocument.title.ilike(kw_pattern),
                        DbDocument.source_uri.ilike(kw_pattern),
                    )
                )

            # ── 条件过滤 ──
            if source_type is not None:
                query = query.filter_by(source_type=source_type)
            if status is not None:
                query = query.filter_by(status=status)
            if category is not None:
                query = query.filter_by(category=category)
            if parent_doc_id is not None:
                query = query.filter_by(parent_doc_id=parent_doc_id)
            if root_doc_id is not None:
                query = query.filter_by(root_doc_id=root_doc_id)
            if ingest_job_id is not None:
                query = query.filter_by(ingest_job_id=ingest_job_id)

            # ── 总数 ──
            total = query.count()

            # ── 排序 ──
            sort_column = getattr(DbDocument, sort_by, DbDocument.updated_at)
            if sort_order == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())

            # ── 分页 ──
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)

            docs = [self._from_db(db_doc) for db_doc in query.all()]
            return docs, total

    # ── 软删除与恢复（2.2） ───────────────────────────────────────

    def soft_delete(self, doc_id: str) -> Document:
        """将文档软删除，设置 status='deleted'。

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"文档 {doc_id} 不存在")
            db_doc.status = "deleted"
            db_doc.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._from_db(db_doc)

    def restore(self, doc_id: str) -> Document:
        """恢复软删除的文档，将状态设置为 'active'。

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"文档 {doc_id} 不存在")
            db_doc.status = "active"
            db_doc.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._from_db(db_doc)

    # ── 聚合统计 ────────────────────────────────────────────────

    def count_by_status(self, doc_id: str | None = None) -> dict[str, int]:
        """按状态统计文档数量。可选按 doc_id 精确计数。"""
        with self._session() as session:
            from sqlalchemy import func
            query = session.query(DbDocument.status, func.count(DbDocument.doc_id))
            if doc_id is not None:
                query = query.filter_by(doc_id=doc_id)
            query = query.group_by(DbDocument.status)
            return {status: count for status, count in query.all()}

    def get_stats(self, doc_id: str) -> dict:
        """获取单个文档的聚合统计信息。

        Returns:
            包含 chunk_count, element_count, asset_count 的字典。
            计数依赖关联仓储，若无关联仓储则返回 0。
        """
        stats = {"chunk_count": 0, "element_count": 0, "asset_count": 0}

        # 文档自身存在性校验
        doc = self.get(doc_id)
        if doc is None:
            return stats

        with self._session() as session:
            from app.db.models import DbAsset, DbKnowledgeChunk, DbParsedElement

            stats["chunk_count"] = (
                session.query(DbKnowledgeChunk)
                .filter_by(doc_id=doc_id)
                .count()
            )
            stats["element_count"] = (
                session.query(DbParsedElement)
                .filter_by(doc_id=doc_id)
                .count()
            )
            stats["asset_count"] = (
                session.query(DbAsset)
                .filter_by(doc_id=doc_id)
                .count()
            )

        return stats
