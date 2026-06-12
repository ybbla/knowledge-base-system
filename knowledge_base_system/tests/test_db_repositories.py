import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models import (
    Asset,
    AssetRef,
    AssetRelation,
    AssetType,
    ChunkIndexStatus,
    Document,
    ElementType,
    KnowledgeChunk,
    KnowledgeType,
    ParsedElement,
    SourceLocation,
    SourceRef,
)
from app.db.models import Base
from app.db.repositories.assets import PgAssetStore
from app.db.repositories.chunks import PgChunkStore
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.elements import ParsedElementRepository


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield factory
    Base.metadata.drop_all(engine)


class TestDocumentRepository:
    def test_create_and_get(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test Document",
            source_type="markdown",
            source_uri="file:///test.md",
            category="产品使用",
        )
        created = repo.create(doc)
        assert created.doc_id.startswith("doc_")

        fetched = repo.get(created.doc_id)
        assert fetched is not None
        assert fetched.title == "Test Document"
        assert fetched.category == "产品使用"

    def test_update(self, session_factory):
        repo = DocumentRepository(session_factory)
        doc = Document(
            title="Original",
            source_type="markdown",
            source_uri="file:///test.md",
        )
        created = repo.create(doc)

        created.title = "Updated Title"
        created.source_hash = "sha256:newhash"
        updated = repo.update(created)
        assert updated.title == "Updated Title"

        fetched = repo.get(created.doc_id)
        assert fetched.title == "Updated Title"


class TestParsedElementRepository:
    def test_create_batch_and_get_by_doc_id(self, session_factory):
        # Create parent document first
        doc_repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown", source_uri="file:///test.md"
        )
        doc_repo.create(doc)

        repo = ParsedElementRepository(session_factory)
        elements = [
            ParsedElement(
                doc_id=doc.doc_id, sequence_order=1,
                element_type=ElementType.title, text="Heading",
                source_location=SourceLocation(section_path=["Heading"]),
            ),
            ParsedElement(
                doc_id=doc.doc_id, sequence_order=2,
                element_type=ElementType.paragraph, text="Body text.",
            ),
        ]
        repo.create_batch(elements)

        results = repo.get_by_doc_id(doc.doc_id)
        assert len(results) == 2
        assert results[0].text == "Heading"
        assert results[0].element_type == ElementType.title
        assert results[1].text == "Body text."


class TestPgChunkStore:
    def test_put_get_and_get_batch(self, session_factory):
        doc_repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown", source_uri="file:///test.md"
        )
        doc_repo.create(doc)

        store = PgChunkStore(session_factory)
        chunk = KnowledgeChunk(
            doc_id=doc.doc_id,
            title="Test Chunk",
            content="Sample content for retrieval.",
            knowledge_type=KnowledgeType.declarative,
            category="产品使用",
            asset_refs=[
                AssetRef(
                    asset_id="asset_001",
                    relation=AssetRelation.evidence,
                    caption="Test image",
                )
            ],
            source_refs=[
                SourceRef(doc_id=doc.doc_id, element_id="el_001")
            ],
            metadata={"title_path": ["Heading"]},
        )
        store.put(chunk)

        fetched = store.get(chunk.chunk_id)
        assert fetched is not None
        assert fetched.content == "Sample content for retrieval."
        assert fetched.knowledge_type == KnowledgeType.declarative
        assert fetched.index_status == ChunkIndexStatus.pending
        assert len(fetched.asset_refs) == 1
        assert fetched.asset_refs[0].relation == AssetRelation.evidence
        assert len(fetched.source_refs) == 1
        assert fetched.metadata["title_path"] == ["Heading"]

        # get_batch
        batch = store.get_batch([chunk.chunk_id, "nonexistent"])
        assert len(batch) == 1

    def test_list_and_update_index_status(self, session_factory):
        doc_repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown", source_uri="file:///test.md"
        )
        doc_repo.create(doc)

        store = PgChunkStore(session_factory)
        chunk = KnowledgeChunk(
            doc_id=doc.doc_id,
            title="C1",
            content="First chunk.",
        )
        store.put(chunk)

        pending = store.list_by_index_status([ChunkIndexStatus.pending])
        assert [item.chunk_id for item in pending] == [chunk.chunk_id]

        store.update_index_status([chunk.chunk_id], ChunkIndexStatus.indexed)
        fetched = store.get(chunk.chunk_id)
        assert fetched.index_status == ChunkIndexStatus.indexed
        assert fetched.indexed_at is not None
        assert fetched.index_error is None

    def test_count(self, session_factory):
        doc_repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown", source_uri="file:///test.md"
        )
        doc_repo.create(doc)

        store = PgChunkStore(session_factory)
        assert store.count() == 0

        store.put(KnowledgeChunk(
            doc_id=doc.doc_id, title="C1", content="First chunk."
        ))
        store.put(KnowledgeChunk(
            doc_id=doc.doc_id, title="C2", content="Second chunk."
        ))
        assert store.count() == 2


class TestPgAssetStore:
    def test_put_get_delete(self, session_factory):
        doc_repo = DocumentRepository(session_factory)
        doc = Document(
            title="Test", source_type="markdown", source_uri="file:///test.md"
        )
        doc_repo.create(doc)

        store = PgAssetStore(session_factory)
        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=AssetType.image,
            original_uri="https://example.com/img.png",
            content_hash="sha256:abc123",
            metadata={"width": 800},
        )
        store.put(asset)

        fetched = store.get(asset.asset_id)
        assert fetched is not None
        assert fetched.asset_type == AssetType.image
        assert fetched.original_uri == "https://example.com/img.png"
        assert fetched.metadata["width"] == 800

        store.delete(asset.asset_id)
        assert store.get(asset.asset_id) is None
