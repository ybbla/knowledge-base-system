import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DbAsset,
    DbDocument,
    DbKnowledgeChunk,
    DbParsedElement,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


class TestDbModels:
    def test_postgresql_uses_jsonb_for_nested_fields(self):
        dialect = postgresql.dialect()
        jsonb_columns = [
            DbDocument.__table__.c.metadata,
            DbParsedElement.__table__.c.structured_data,
            DbParsedElement.__table__.c.asset_ids,
            DbParsedElement.__table__.c.source_location,
            DbParsedElement.__table__.c.metadata,
            DbAsset.__table__.c.metadata,
            DbKnowledgeChunk.__table__.c.asset_refs,
            DbKnowledgeChunk.__table__.c.source_refs,
            DbKnowledgeChunk.__table__.c.metadata,
        ]
        for column in jsonb_columns:
            assert isinstance(column.type.dialect_impl(dialect), JSONB)

    def test_create_document(self, db_session):
        doc = DbDocument(
            doc_id="doc_001",
            title="Test Document",
            source_type="markdown",
            source_uri="file:///test.md",
            category="产品使用",
            meta={"owner": "test", "tags": ["manual"]},
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_001")
        assert result is not None
        assert result.title == "Test Document"
        assert result.category == "产品使用"
        assert result.meta["owner"] == "test"

    def test_create_parsed_element(self, db_session):
        doc = DbDocument(
            doc_id="doc_001", title="Test", source_type="markdown",
            source_uri="file:///test.md",
        )
        db_session.add(doc)

        el = DbParsedElement(
            element_id="el_001",
            doc_id="doc_001",
            sequence_order=1,
            element_type="paragraph",
            text="Sample paragraph text.",
            source_location={"page": 1, "section_path": ["Heading"]},
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_001")
        assert result is not None
        assert result.text == "Sample paragraph text."
        assert result.source_location["page"] == 1

    def test_create_asset(self, db_session):
        doc = DbDocument(
            doc_id="doc_001", title="Test", source_type="markdown",
            source_uri="file:///test.md",
        )
        db_session.add(doc)

        asset = DbAsset(
            asset_id="asset_001",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/img.png",
            content_hash="sha256:abc123",
            meta={"width": 800, "height": 600},
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_001")
        assert result is not None
        assert result.asset_type == "image"
        assert result.meta["width"] == 800

    def test_create_chunk_with_jsonb_fields(self, db_session):
        doc = DbDocument(
            doc_id="doc_001", title="Test", source_type="markdown",
            source_uri="file:///test.md",
        )
        db_session.add(doc)

        chunk = DbKnowledgeChunk(
            chunk_id="chunk_001",
            doc_id="doc_001",
            title="Test Chunk",
            content="Content with keywords.",
            knowledge_type="declarative",
            category="产品使用",
            asset_refs=[
                {
                    "asset_id": "asset_001",
                    "relation": "evidence",
                    "caption": "Screenshot",
                }
            ],
            source_refs=[
                {"doc_id": "doc_001", "element_id": "el_001"}
            ],
            meta={"title_path": ["Test"], "language": "zh-CN"},
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_001")
        assert result is not None
        assert result.content == "Content with keywords."
        assert result.category == "产品使用"
        assert result.knowledge_type == "declarative"
        assert result.index_status == "pending"
        assert result.indexed_at is None
        assert result.index_error is None

        # JSONB round-trip
        assert len(result.asset_refs) == 1
        assert result.asset_refs[0]["asset_id"] == "asset_001"
        assert len(result.source_refs) == 1
        assert result.source_refs[0]["doc_id"] == "doc_001"
        assert result.meta["title_path"] == ["Test"]

    def test_batch_query_by_doc_id(self, db_session):
        doc = DbDocument(
            doc_id="doc_001", title="Test", source_type="markdown",
            source_uri="file:///test.md",
        )
        db_session.add(doc)

        for i in range(3):
            el = DbParsedElement(
                element_id=f"el_{i:03d}",
                doc_id="doc_001",
                sequence_order=i + 1,
                element_type="paragraph",
                text=f"Paragraph {i}",
            )
            db_session.add(el)
        db_session.commit()

        results = (
            db_session.query(DbParsedElement)
            .filter_by(doc_id="doc_001")
            .order_by(DbParsedElement.sequence_order)
            .all()
        )
        assert len(results) == 3
        assert results[0].text == "Paragraph 0"
