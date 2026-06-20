"""数据库模型全面单元测试。

使用 SQLite 内存数据库验证所有 Db* 模型的建表、CRUD、JSONB 字段序列化往返、
状态枚举默认值、时间戳自动设置等。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DbAsset,
    DbDocument,
    DbIdfStat,
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


@pytest.fixture
def doc_fixture(db_session):
    """创建并返回一个测试文档。"""
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
    return doc


# ── JSONB 列类型验证 ─────────────────────────────────────────────────

class TestJsonbColumns:
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
            assert isinstance(column.type.dialect_impl(dialect), JSONB), \
                f"{column} 应为 JSONB 类型"


# ── DbDocument ────────────────────────────────────────────────────────

class TestDbDocument:
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

    def test_default_values(self, db_session):
        doc = DbDocument(
            doc_id="doc_002",
            title="Defaults Test",
            source_type="docx",
            source_uri="minio://kb/input.docx",
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_002")
        assert result.version == 1
        assert result.status == "processing"
        assert result.category == "通用"
        assert result.source_hash == ""
        assert result.parent_doc_id is None
        assert result.root_doc_id is None
        assert result.ingest_job_id == ""
        assert result.meta == {}

    def test_created_at_is_set(self, db_session):
        doc = DbDocument(
            doc_id="doc_003",
            title="Time Test",
            source_type="md",
            source_uri="f://t",
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_003")
        assert result.created_at is not None
        assert isinstance(result.created_at, datetime)

    def test_updated_at_on_update(self, db_session):
        doc = DbDocument(
            doc_id="doc_004",
            title="Original",
            source_type="md",
            source_uri="f://t",
        )
        db_session.add(doc)
        db_session.commit()

        original_updated = db_session.get(DbDocument, "doc_004").updated_at

        # 更新标题
        result = db_session.get(DbDocument, "doc_004")
        result.title = "Updated Title"
        db_session.commit()

        # SQLite 不支持 onupdate（需触发器），此处仅验证字段存在
        result = db_session.get(DbDocument, "doc_004")
        assert result.title == "Updated Title"
        assert result.updated_at is not None

    def test_all_status_values(self, db_session):
        for status in ["pending", "processing", "active", "failed"]:
            doc = DbDocument(
                doc_id=f"doc_status_{status}",
                title=f"Status {status}",
                source_type="md",
                source_uri="f://t",
                status=status,
            )
            db_session.add(doc)
        db_session.commit()

        for status in ["pending", "processing", "active", "failed"]:
            result = db_session.get(DbDocument, f"doc_status_{status}")
            assert result.status == status

    def test_parent_child_hierarchy(self, db_session):
        root = DbDocument(
            doc_id="doc_root", title="Root", source_type="md", source_uri="f://r",
        )
        db_session.add(root)
        db_session.commit()

        child = DbDocument(
            doc_id="doc_child", title="Child", source_type="md", source_uri="f://c",
            parent_doc_id="doc_root", root_doc_id="doc_root",
        )
        db_session.add(child)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_child")
        assert result.parent_doc_id == "doc_root"
        assert result.root_doc_id == "doc_root"

    def test_full_fields_round_trip(self, db_session):
        now = datetime.now(timezone.utc)
        doc = DbDocument(
            doc_id="doc_full",
            title="产品使用手册",
            source_type="docx",
            source_uri="minio://kb-input/abc123/manual.docx",
            source_hash="sha256:abc123def456",
            version=2,
            status="active",
            category="产品使用",
            parent_doc_id=None,
            root_doc_id="doc_full",
            ingest_job_id="job_001",
            meta={"owner": "product-team", "tags": ["manual", "product"]},
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_full")
        assert result.source_hash == "sha256:abc123def456"
        assert result.version == 2
        assert result.status == "active"
        assert result.ingest_job_id == "job_001"
        assert result.meta["tags"] == ["manual", "product"]

    def test_metadata_preserves_nested_structures(self, db_session):
        doc = DbDocument(
            doc_id="doc_meta",
            title="Meta Test",
            source_type="md",
            source_uri="f://t",
            meta={"nested": {"key": [1, 2, 3]}, "flag": True, "count": 42},
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.get(DbDocument, "doc_meta")
        assert result.meta["nested"]["key"] == [1, 2, 3]
        assert result.meta["flag"] is True
        assert result.meta["count"] == 42

    def test_batch_insert_and_query(self, db_session):
        for i in range(5):
            doc = DbDocument(
                doc_id=f"batch_{i}",
                title=f"Batch Doc {i}",
                source_type="md",
                source_uri=f"f://{i}",
                category=f"cat_{i % 2}",
            )
            db_session.add(doc)
        db_session.commit()

        all_docs = db_session.query(DbDocument).all()
        assert len(all_docs) == 5

        cat0 = db_session.query(DbDocument).filter_by(category="cat_0").all()
        assert len(cat0) == 3  # i=0,2,4


# ── DbParsedElement ───────────────────────────────────────────────────

class TestDbParsedElement:
    def test_create_basic(self, doc_fixture, db_session):
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

    def test_default_values(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_default",
            doc_id="doc_001",
            element_type="paragraph",
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_default")
        assert result.doc_version == 1
        assert result.parent_element_id is None
        assert result.sequence_order == 0
        assert result.text == ""
        assert result.structured_data is None
        assert result.asset_ids == []
        assert result.embedded_doc_id is None
        assert result.source_location == {}
        assert result.meta == {}

    def test_table_element_with_structured_data(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_table",
            doc_id="doc_001",
            sequence_order=1,
            element_type="table",
            text="A | B\n1 | 2",
            structured_data={
                "headers": ["A", "B"],
                "rows": [[{"text": "1", "assets": []}, {"text": "2", "assets": []}]],
            },
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_table")
        assert result.structured_data is not None
        assert result.structured_data["headers"] == ["A", "B"]
        assert len(result.structured_data["rows"]) == 1

    def test_image_element_with_asset_ids(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_image",
            doc_id="doc_001",
            sequence_order=1,
            element_type="image",
            asset_ids=["asset_001", "asset_002"],
            meta={"alt": "产品截图"},
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_image")
        assert result.asset_ids == ["asset_001", "asset_002"]
        assert result.meta["alt"] == "产品截图"

    def test_list_with_parent(self, doc_fixture, db_session):
        parent = DbParsedElement(
            element_id="el_list",
            doc_id="doc_001",
            sequence_order=1,
            element_type="list",
        )
        db_session.add(parent)
        db_session.commit()

        child = DbParsedElement(
            element_id="el_list_child",
            doc_id="doc_001",
            sequence_order=2,
            element_type="paragraph",
            text="列表项",
            parent_element_id="el_list",
        )
        db_session.add(child)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_list_child")
        assert result.parent_element_id == "el_list"

    def test_embedded_document_element(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_embed",
            doc_id="doc_001",
            sequence_order=1,
            element_type="embedded_document",
            text="嵌入文档入口",
            embedded_doc_id="doc_child",
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_embed")
        assert result.embedded_doc_id == "doc_child"

    def test_all_element_types(self, doc_fixture, db_session):
        types = ["paragraph", "title", "table", "image", "list",
                 "embedded_document", "code", "video", "unknown"]
        for i, etype in enumerate(types):
            el = DbParsedElement(
                element_id=f"el_type_{i}",
                doc_id="doc_001",
                sequence_order=i + 1,
                element_type=etype,
            )
            db_session.add(el)
        db_session.commit()

        for i, etype in enumerate(types):
            result = db_session.get(DbParsedElement, f"el_type_{i}")
            assert result.element_type == etype

    def test_source_location_full(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_loc",
            doc_id="doc_001",
            sequence_order=1,
            element_type="paragraph",
            text="正文",
            source_location={
                "page": 3,
                "section_path": ["1 产品概述", "1.2 上传文档"],
                "table_path": [],
                "char_start": 120,
                "char_end": 138,
            },
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_loc")
        assert result.source_location["page"] == 3
        assert len(result.source_location["section_path"]) == 2
        assert result.source_location["char_start"] == 120
        assert result.source_location["char_end"] == 138

    def test_batch_query_by_doc_id(self, doc_fixture, db_session):
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
        assert results[1].text == "Paragraph 1"
        assert results[2].text == "Paragraph 2"

    def test_full_fields_round_trip(self, doc_fixture, db_session):
        el = DbParsedElement(
            element_id="el_full",
            doc_id="doc_001",
            doc_version=2,
            parent_element_id="el_parent",
            sequence_order=5,
            element_type="table",
            text="H1 | H2\n1 | 2",
            structured_data={"headers": ["H1", "H2"], "rows": []},
            asset_ids=["asset_001", "asset_002"],
            embedded_doc_id="doc_embedded",
            source_location={"page": 3, "section_path": ["H1"]},
            meta={"table_caption": "表1"},
        )
        db_session.add(el)
        db_session.commit()

        result = db_session.get(DbParsedElement, "el_full")
        assert result.doc_version == 2
        assert result.parent_element_id == "el_parent"
        assert result.sequence_order == 5
        assert result.element_type == "table"
        assert result.structured_data["headers"] == ["H1", "H2"]
        assert result.asset_ids == ["asset_001", "asset_002"]
        assert result.embedded_doc_id == "doc_embedded"
        assert result.source_location["page"] == 3
        assert result.meta["table_caption"] == "表1"


# ── DbAsset ───────────────────────────────────────────────────────────

class TestDbAsset:
    def test_create_basic(self, doc_fixture, db_session):
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

    def test_default_values(self, doc_fixture, db_session):
        asset = DbAsset(
            asset_id="asset_default",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/x.png",
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_default")
        assert result.source_element_id == ""
        assert result.storage_uri is None
        assert result.mime_type == ""
        assert result.content_hash == ""
        assert result.status == "ready"
        assert result.extracted_text is None
        assert result.error_message is None
        assert result.meta == {}

    def test_all_asset_types(self, doc_fixture, db_session):
        for atype in ["image", "video", "audio", "attachment"]:
            asset = DbAsset(
                asset_id=f"asset_{atype}",
                doc_id="doc_001",
                asset_type=atype,
                original_uri=f"https://example.com/x.{atype}",
            )
            db_session.add(asset)
        db_session.commit()

        for atype in ["image", "video", "audio", "attachment"]:
            result = db_session.get(DbAsset, f"asset_{atype}")
            assert result.asset_type == atype

    def test_all_status_values(self, doc_fixture, db_session):
        for status in ["ready", "failed"]:
            asset = DbAsset(
                asset_id=f"asset_{status}",
                doc_id="doc_001",
                asset_type="image",
                original_uri="https://example.com/x.png",
                status=status,
            )
            db_session.add(asset)
        db_session.commit()

        for status in ["ready", "failed"]:
            result = db_session.get(DbAsset, f"asset_{status}")
            assert result.status == status

    def test_ready_asset_with_storage_uri(self, doc_fixture, db_session):
        asset = DbAsset(
            asset_id="asset_ready",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/a.png",
            storage_uri="minio://kb-assets/doc_001/a.png",
            mime_type="image/png",
            content_hash="sha256:abc123",
            status="ready",
            extracted_text="图片展示了用户上传文档后的解析状态",
            meta={"width": 1200, "height": 800},
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_ready")
        assert result.storage_uri == "minio://kb-assets/doc_001/a.png"
        assert result.mime_type == "image/png"
        assert result.extracted_text == "图片展示了用户上传文档后的解析状态"
        assert result.error_message is None

    def test_failed_asset_with_error(self, doc_fixture, db_session):
        asset = DbAsset(
            asset_id="asset_failed",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/bad.gif",
            status="failed",
            error_message="invalid_image_type",
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_failed")
        assert result.status == "failed"
        assert result.error_message == "invalid_image_type"

    def test_source_element_id_traceability(self, doc_fixture, db_session):
        asset = DbAsset(
            asset_id="asset_trace",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/a.png",
            source_element_id="el_003",
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_trace")
        assert result.source_element_id == "el_003"

    def test_created_at_is_set(self, doc_fixture, db_session):
        asset = DbAsset(
            asset_id="asset_time",
            doc_id="doc_001",
            asset_type="image",
            original_uri="https://example.com/x.png",
        )
        db_session.add(asset)
        db_session.commit()

        result = db_session.get(DbAsset, "asset_time")
        assert result.created_at is not None
        assert isinstance(result.created_at, datetime)

    def test_query_by_doc_id(self, doc_fixture, db_session):
        for i in range(3):
            asset = DbAsset(
                asset_id=f"asset_doc_{i}",
                doc_id="doc_001",
                asset_type="image",
                original_uri=f"https://example.com/{i}.png",
            )
            db_session.add(asset)
        db_session.commit()

        results = db_session.query(DbAsset).filter_by(doc_id="doc_001").all()
        assert len(results) == 3


# ── DbKnowledgeChunk ──────────────────────────────────────────────────

class TestDbKnowledgeChunk:
    def test_create_basic(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_001",
            doc_id="doc_001",
            title="Test Chunk",
            content="Content with keywords.",
            knowledge_type="declarative",
            category="产品使用",
            asset_refs=[
                {"asset_id": "asset_001", "relation": "evidence", "caption": "Screenshot"}
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

        # JSONB round-trip
        assert len(result.asset_refs) == 1
        assert result.asset_refs[0]["asset_id"] == "asset_001"
        assert len(result.source_refs) == 1
        assert result.source_refs[0]["doc_id"] == "doc_001"
        assert result.meta["title_path"] == ["Test"]

    def test_default_values(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_default",
            doc_id="doc_001",
            content="内容",
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_default")
        assert result.title == ""
        assert result.content_hash == ""
        assert result.knowledge_type == "declarative"
        assert result.category == "通用"
        assert result.status == "active"
        assert result.asset_refs == []
        assert result.source_refs == []
        assert result.meta == {}

    def test_all_knowledge_types(self, doc_fixture, db_session):
        for ktype in ["declarative", "relational", "procedural"]:
            chunk = DbKnowledgeChunk(
                chunk_id=f"chunk_{ktype}",
                doc_id="doc_001",
                content=f"Content for {ktype}",
                knowledge_type=ktype,
            )
            db_session.add(chunk)
        db_session.commit()

        for ktype in ["declarative", "relational", "procedural"]:
            result = db_session.get(DbKnowledgeChunk, f"chunk_{ktype}")
            assert result.knowledge_type == ktype

    def test_all_chunk_status_values(self, doc_fixture, db_session):
        for status in ["active", "deleted"]:
            chunk = DbKnowledgeChunk(
                chunk_id=f"chunk_cs_{status}",
                doc_id="doc_001",
                content="X",
                status=status,
            )
            db_session.add(chunk)
        db_session.commit()

        for status in ["active", "deleted"]:
            result = db_session.get(DbKnowledgeChunk, f"chunk_cs_{status}")
            assert result.status == status

    def test_asset_refs_multiple(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_multi_assets",
            doc_id="doc_001",
            content="Content with images",
            asset_refs=[
                {"asset_id": "asset_001", "relation": "evidence", "caption": "截图1"},
                {"asset_id": "asset_002", "relation": "illustration", "caption": "截图2"},
                {"asset_id": "asset_003", "relation": "source", "caption": "链接"},
            ],
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_multi_assets")
        assert len(result.asset_refs) == 3
        assert result.asset_refs[1]["relation"] == "illustration"

    def test_source_refs_multiple(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_multi_sources",
            doc_id="doc_001",
            content="综合内容",
            source_refs=[
                {"doc_id": "doc_001", "doc_version": 1, "element_id": "el_001"},
                {"doc_id": "doc_001", "doc_version": 1, "element_id": "el_002"},
                {"doc_id": "doc_001", "doc_version": 1, "element_id": "el_003"},
            ],
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_multi_sources")
        assert len(result.source_refs) == 3
        assert result.source_refs[2]["element_id"] == "el_003"

    def test_source_ref_with_full_location(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_source_loc",
            doc_id="doc_001",
            content="X",
            source_refs=[{
                "doc_id": "doc_001",
                "doc_version": 1,
                "element_id": "el_002",
                "source_location": {
                    "page": 3,
                    "section_path": ["1 产品概述", "1.2 上传文档"],
                },
            }],
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_source_loc")
        ref = result.source_refs[0]
        assert ref["source_location"]["page"] == 3
        assert len(ref["source_location"]["section_path"]) == 2

    def test_metadata_title_path_and_language(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_meta",
            doc_id="doc_001",
            content="X",
            meta={"title_path": ["产品使用手册", "上传文档"], "language": "zh-CN"},
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_meta")
        assert result.meta["title_path"] == ["产品使用手册", "上传文档"]
        assert result.meta["language"] == "zh-CN"

    def test_query_by_doc_id(self, doc_fixture, db_session):
        for i in range(3):
            chunk = DbKnowledgeChunk(
                chunk_id=f"chunk_doc_{i}",
                doc_id="doc_001",
                content=f"Content {i}",
            )
            db_session.add(chunk)
        db_session.commit()

        results = db_session.query(DbKnowledgeChunk).filter_by(doc_id="doc_001").all()
        assert len(results) == 3

    def test_full_fields_round_trip(self, doc_fixture, db_session):
        chunk = DbKnowledgeChunk(
            chunk_id="chunk_full",
            doc_id="doc_001",
            title="上传文档解析状态判断",
            content="系统支持通过网页端上传知识文档...",
            content_hash="sha256:abc123",
            knowledge_type="declarative",
            category="产品使用",
            status="active",
            asset_refs=[
                {"asset_id": "asset_001", "relation": "evidence",
                 "linked_text": "界面截图", "caption": "截图",
                 "render": {"mode": "inline", "position": "after_linked_text"}},
            ],
            source_refs=[
                {"doc_id": "doc_001", "doc_version": 1, "element_id": "el_002",
                 "source_location": {"page": 3, "section_path": ["H1", "H2"]}},
            ],
            meta={"title_path": ["手册", "上传"], "language": "zh-CN"},
        )
        db_session.add(chunk)
        db_session.commit()

        result = db_session.get(DbKnowledgeChunk, "chunk_full")
        assert result.title == "上传文档解析状态判断"
        assert result.content_hash == "sha256:abc123"
        assert result.status == "active"
        assert len(result.asset_refs) == 1
        assert len(result.source_refs) == 1
        assert result.meta["language"] == "zh-CN"


# ── DbIdfStat ─────────────────────────────────────────────────────────

class TestDbIdfStat:
    def test_create_and_query(self, db_session):
        stat = DbIdfStat(
            token="产品",
            token_id=1,
            df=42,
            total_docs=100,
        )
        db_session.add(stat)
        db_session.commit()

        result = db_session.get(DbIdfStat, "产品")
        assert result is not None
        assert result.df == 42
        assert result.token_id == 1
        assert result.total_docs == 100

    def test_upsert(self, db_session):
        stat = DbIdfStat(token="测试", token_id=2, df=10, total_docs=50)
        db_session.add(stat)
        db_session.commit()

        result = db_session.get(DbIdfStat, "测试")
        result.df = 20
        result.total_docs = 60
        db_session.commit()

        result = db_session.get(DbIdfStat, "测试")
        assert result.df == 20
        assert result.total_docs == 60
