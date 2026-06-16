"""乐观锁测试：VersionConflictError 和 DuplicateDocumentError。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import DuplicateDocumentError, VersionConflictError
from app.core.models import Document
from app.db.models import Base
from app.db.repositories.documents import DocumentRepository


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield factory
    Base.metadata.drop_all(engine)


class TestOptimisticLock:
    def test_update_increments_version(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown",
            source_uri="file:///test.md", source_hash="sha256:abc",
        )
        created = repo.create(doc)
        assert created.version == 1

        created.title = "Updated"
        updated = repo.update(created)
        assert updated.version == 2

        fetched = repo.get(created.doc_id)
        assert fetched.version == 2

    def test_version_conflict_raises(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown",
            source_uri="file:///test.md", source_hash="sha256:abc",
        )
        created = repo.create(doc)

        # 第一次更新成功
        created.title = "First Update"
        updated = repo.update(created)
        assert updated.version == 2

        # 用旧 version 再更新应冲突
        with pytest.raises(VersionConflictError):
            repo.update(created)  # version 还是 1

    def test_duplicate_doc_id_raises(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown",
            source_uri="file:///test.md", source_hash="sha256:abc",
        )
        repo.create(doc)

        # 相同 doc_id 再次 create
        with pytest.raises(DuplicateDocumentError):
            repo.create(doc)

    def test_find_by_hash_returns_active_doc(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown",
            source_uri="file:///test.md",
            source_hash="sha256:target",
        )
        repo.create(doc)

        found = repo.find_by_hash("sha256:target")
        assert found is not None
        assert found.title == "Test"

    def test_find_by_hash_returns_none_for_unknown(self, session_factory):
        repo = DocumentRepository(session_factory)
        assert repo.find_by_hash("sha256:nonexistent") is None
