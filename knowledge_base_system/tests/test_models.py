"""数据模型全面单元测试。

覆盖所有 Pydantic 模型：Document、ParsedElement、Asset、KnowledgeChunk、
SearchResult、SearchResultItem、以及子模型 SourceRef、AssetRef、SourceLocation、
ScoreComponents。验证默认值、序列化/反序列化往返、字段约束、auto-computed 字段。
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.models import (
    Asset,
    AssetData,
    AssetRef,
    AssetStatus,
    AssetType,
    ChunkStatus,
    compute_hash,
    Document,
    DocStatus,
    ElementType,
    KnowledgeChunk,
    KnowledgeType,
    new_id,
    ParsedElement,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
    SourceLocation,
    SourceRef,
)


# ── helpers ──────────────────────────────────────────────────────────

class TestComputeHash:
    def test_string_hash(self):
        h = compute_hash("hello")
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64

    def test_different_content_different_hash(self):
        h1 = compute_hash("hello")
        h2 = compute_hash("world")
        assert h1 != h2

    def test_bytes_hash(self):
        h_str = compute_hash("hello")
        h_bytes = compute_hash(b"hello")
        assert h_str == h_bytes

    def test_empty_string(self):
        h = compute_hash("")
        assert h.startswith("sha256:")


class TestNewId:
    def test_prefix(self):
        id_ = new_id("doc")
        assert id_.startswith("doc_")

    def test_unique(self):
        ids = {new_id("doc") for _ in range(100)}
        assert len(ids) == 100

    def test_various_prefixes(self):
        for prefix in ("doc", "el", "asset", "chunk", "search"):
            id_ = new_id(prefix)
            assert id_.startswith(f"{prefix}_")
            assert len(id_) > len(prefix) + 1  # 至少还有随机部分


# ── SourceLocation ────────────────────────────────────────────────────

class TestSourceLocation:
    def test_defaults(self):
        sl = SourceLocation()
        assert sl.page is None
        assert sl.section_path == []
        assert sl.table_path == []

    def test_full_fields(self):
        sl = SourceLocation(
            page=3,
            section_path=["1 产品概述", "1.2 上传文档"],
            table_path=[{"sheet": "sheet1", "range": "A1:B10"}],
        )
        assert sl.page == 3
        assert len(sl.section_path) == 2
        assert len(sl.table_path) == 1
        assert sl.table_path[0]["sheet"] == "sheet1"

    def test_json_round_trip(self):
        sl = SourceLocation(page=5, section_path=["A", "B"])
        data = sl.model_dump(mode="json")
        restored = SourceLocation.model_validate(data)
        assert restored.page == 5
        assert restored.section_path == ["A", "B"]


# ── AssetRef ──────────────────────────────────────────────────────────

class TestAssetRef:
    def test_minimal(self):
        ref = AssetRef(asset_id="asset_001")
        assert ref.asset_id == "asset_001"
        assert ref.caption is None

    def test_full_fields(self):
        ref = AssetRef(
            asset_id="asset_001",
            caption="上传状态截图",
        )
        assert ref.caption == "上传状态截图"

    def test_json_round_trip(self):
        ref = AssetRef(
            asset_id="asset_001",
            caption="A screenshot",
        )
        data = ref.model_dump(mode="json")
        restored = AssetRef.model_validate(data)
        assert restored.asset_id == "asset_001"
        assert restored.caption == "A screenshot"


# ── SourceRef ─────────────────────────────────────────────────────────

class TestSourceRef:
    def test_minimal(self):
        ref = SourceRef(doc_id="doc_001", element_id="el_001")
        assert ref.doc_id == "doc_001"
        assert ref.doc_version == 1  # 默认值
        assert ref.element_id == "el_001"
        assert ref.source_location.page is None   # SourceLocation.page 默认为 None

    def test_full_fields(self):
        ref = SourceRef(
            doc_id="doc_001",
            doc_version=2,
            element_id="el_002",
            source_location=SourceLocation(page=3, section_path=["H1"]),
        )
        assert ref.doc_version == 2
        assert ref.element_id == "el_002"
        assert ref.source_location.page == 3

    def test_json_round_trip(self):
        ref = SourceRef(doc_id="doc_001", element_id="el_001",
                        source_location=SourceLocation(page=3))
        data = ref.model_dump(mode="json")
        restored = SourceRef.model_validate(data)
        assert restored.element_id == "el_001"
        assert restored.source_location.page == 3


# ── ScoreComponents ───────────────────────────────────────────────────

class TestScoreComponents:
    def test_defaults(self):
        sc = ScoreComponents()
        assert sc.vector == 0.0
        assert sc.bm25 == 0.0
        assert sc.rerank is None  # None 表示 LLM Rerank 未执行

    def test_custom(self):
        sc = ScoreComponents(vector=0.89, bm25=0.73, rerank=0.92)
        assert sc.vector == 0.89
        assert sc.bm25 == 0.73
        assert sc.rerank == 0.92


# ── Document ──────────────────────────────────────────────────────────

class TestDocument:
    def test_defaults(self):
        doc = Document(title="Test", source_type="markdown", source_uri="file:///test.md")
        assert doc.doc_id.startswith("doc_")
        assert doc.version == 1
        assert doc.status == DocStatus.processing
        assert doc.category == "通用"
        assert doc.source_hash == ""
        assert doc.parent_doc_id is None
        assert doc.root_doc_id is None
        assert doc.previous_doc_id is None
        assert isinstance(doc.created_at, datetime)
        assert isinstance(doc.updated_at, datetime)
        assert doc.metadata == {}

    def test_serialization_round_trip(self):
        """完整字段的 JSON 序列化 / 反序列化往返。"""
        doc = Document(
            title="产品使用手册",
            source_type="docx",
            source_uri="minio://kb-input/abc123/manual.docx",
            source_hash="sha256:abc123def456",
            version=1,
            status=DocStatus.active,
            category="产品使用",
            parent_doc_id=None,
            root_doc_id="doc_001",
            metadata={"owner": "product-team", "tags": ["manual"]},
        )
        data = doc.model_dump(mode="json")
        doc2 = Document.model_validate(data)
        assert doc2.title == "产品使用手册"
        assert doc2.source_type == "docx"
        assert doc2.source_uri == "minio://kb-input/abc123/manual.docx"
        assert doc2.source_hash == "sha256:abc123def456"
        assert doc2.version == 1
        assert doc2.status == DocStatus.active
        assert doc2.category == "产品使用"
        assert doc2.parent_doc_id is None
        assert doc2.root_doc_id == "doc_001"
        assert doc2.metadata["owner"] == "product-team"
        # created_at / updated_at 在序列化后应能还原
        assert isinstance(doc2.created_at, datetime)
        assert isinstance(doc2.updated_at, datetime)

    def test_all_status_values(self):
        """验证 DocStatus 枚举的所有值。"""
        for status in DocStatus:
            doc = Document(title="T", source_type="md", source_uri="f://t",
                           status=status)
            assert doc.status == status

    def test_doc_id_auto_generated(self):
        doc = Document(title="T", source_type="md", source_uri="f://t")
        assert doc.doc_id.startswith("doc_")

    def test_explicit_doc_id(self):
        doc = Document(doc_id="my_custom_id", title="T", source_type="md",
                       source_uri="f://t")
        assert doc.doc_id == "my_custom_id"

    def test_parent_child_hierarchy(self):
        root = Document(title="Root", source_type="md", source_uri="f://r")
        child = Document(
            title="Child", source_type="md", source_uri="f://c",
            parent_doc_id=root.doc_id, root_doc_id=root.doc_id,
        )
        assert child.parent_doc_id == root.doc_id
        assert child.root_doc_id == root.doc_id

    def test_metadata_preserves_complex_types(self):
        doc = Document(
            title="T", source_type="md", source_uri="f://t",
            metadata={"nested": {"key": [1, 2, 3]}, "flag": True},
        )
        data = doc.model_dump(mode="json")
        doc2 = Document.model_validate(data)
        assert doc2.metadata["nested"]["key"] == [1, 2, 3]
        assert doc2.metadata["flag"] is True


# ── ParsedElement ─────────────────────────────────────────────────────

class TestParsedElement:
    def test_defaults(self):
        el = ParsedElement(doc_id="doc_001", element_type=ElementType.paragraph)
        assert el.element_id.startswith("el_")
        assert el.doc_version == 1
        assert el.parent_element_id is None
        assert el.sequence_order == 0
        assert el.text == ""
        assert el.structured_data is None
        assert el.asset_data == []
        assert el.source_location.page is None
        assert el.metadata == {}

    def test_paragraph_element(self):
        el = ParsedElement(
            doc_id="doc_001",
            sequence_order=1,
            element_type=ElementType.paragraph,
            text="这是一段正文。",
            source_location=SourceLocation(page=2, section_path=["H1"]),
        )
        assert el.element_type == ElementType.paragraph
        assert el.text == "这是一段正文。"
        assert el.source_location.page == 2
        assert el.structured_data is None  # paragraph 不应有 structured_data

    def test_title_element(self):
        el = ParsedElement(
            doc_id="doc_001",
            sequence_order=1,
            element_type=ElementType.title,
            text="第一章 概述",
            source_location=SourceLocation(page=1, section_path=["第一章 概述"]),
            metadata={"heading_level": 1, "source": "toc"},
        )
        assert el.element_type == ElementType.title
        assert el.metadata["heading_level"] == 1

    def test_table_with_structured_data(self):
        el = ParsedElement(
            doc_id="doc_001",
            sequence_order=1,
            element_type=ElementType.table,
            text="A | B\n1 | 2",
            structured_data={
                "headers": ["A", "B"],
                "rows": [[{"text": "1", "assets": []}, {"text": "2", "assets": []}]],
            },
        )
        assert el.structured_data is not None
        assert len(el.structured_data["headers"]) == 2

    def test_element_with_asset_data(self):
        el = ParsedElement(
            doc_id="doc_001",
            sequence_order=1,
            element_type=ElementType.paragraph,
            text="[图片: 产品截图]",
            asset_data=[AssetData(placeholder="[image1]", asset_id="asset_001")],
            metadata={"alt": "产品截图"},
        )
        assert el.element_type == ElementType.paragraph
        assert len(el.asset_data) == 1
        assert el.asset_data[0].placeholder == "[image1]"
        assert el.asset_data[0].asset_id == "asset_001"
        assert el.metadata["alt"] == "产品截图"

    def test_list_element_with_parent(self):
        parent = ParsedElement(
            doc_id="doc_001", sequence_order=1,
            element_type=ElementType.list,
        )
        child = ParsedElement(
            doc_id="doc_001", sequence_order=2,
            element_type=ElementType.paragraph,
            text="列表项内容",
            parent_element_id=parent.element_id,
        )
        assert child.parent_element_id == parent.element_id

    def test_code_element(self):
        """代码块元素测试。"""
        el = ParsedElement(
            doc_id="doc_root",
            sequence_order=1,
            element_type=ElementType.code,
            text="print('hello')",
        )
        assert el.element_type == ElementType.code

    def test_all_element_types(self):
        """确保所有 ElementType 枚举值都能创建 ParsedElement。"""
        for etype in ElementType:
            el = ParsedElement(doc_id="doc_001", element_type=etype)
            assert el.element_type == etype

    def test_json_round_trip_full(self):
        """全字段的 JSON 序列化往返。"""
        el = ParsedElement(
            doc_id="doc_001",
            doc_version=2,
            parent_element_id="el_parent",
            sequence_order=5,
            element_type=ElementType.table,
            text="H1 | H2\n1 | 2",
            structured_data={"headers": ["H1", "H2"], "rows": []},
            asset_data=[
                AssetData(placeholder="[image1]", asset_id="asset_001"),
                AssetData(placeholder="[doc1]", asset_id="asset_002"),
            ],
            source_location=SourceLocation(page=3, section_path=["H1"]),
            metadata={"table_caption": "表1"},
        )
        data = el.model_dump(mode="json")
        restored = ParsedElement.model_validate(data)
        assert restored.element_id == el.element_id
        assert restored.doc_version == 2
        assert restored.parent_element_id == "el_parent"
        assert restored.sequence_order == 5
        assert restored.element_type == ElementType.table
        assert restored.text == "H1 | H2\n1 | 2"
        assert restored.structured_data == {"headers": ["H1", "H2"], "rows": []}
        assert len(restored.asset_data) == 2
        assert restored.asset_data[0].placeholder == "[image1]"
        assert restored.asset_data[1].placeholder == "[doc1]"
        assert restored.source_location.page == 3
        assert restored.metadata["table_caption"] == "表1"

    def test_sequence_order_is_preserved(self):
        """验证 sequence_order 在批量创建时正确维护。"""
        elements = [
            ParsedElement(doc_id="doc_001", sequence_order=i,
                          element_type=ElementType.paragraph, text=f"P{i}")
            for i in range(10)
        ]
        assert [el.sequence_order for el in elements] == list(range(10))

    def test_element_id_unique(self):
        """验证每个元素的 element_id 都是唯一的。"""
        ids = {
            ParsedElement(doc_id="doc_001",
                          element_type=ElementType.paragraph).element_id
            for _ in range(100)
        }
        assert len(ids) == 100


# ── Asset ─────────────────────────────────────────────────────────────

class TestAsset:
    def test_defaults(self):
        asset = Asset(doc_id="doc_001", asset_type=AssetType.image,
                      original_uri="https://example.com/a.png")
        assert asset.asset_id.startswith("asset_")
        assert asset.element_id == ""
        assert asset.storage_uri is None
        assert asset.content_hash == ""
        assert isinstance(asset.created_at, datetime)
        assert asset.status == AssetStatus.ready
        assert asset.extracted_text is None
        assert asset.error_message is None
        assert asset.metadata == {}

    def test_image_asset_full(self):
        asset = Asset(
            asset_id="asset_001",
            doc_id="doc_001",
            element_id="el_003",
            asset_type=AssetType.image,
            original_uri="https://example.com/a.png",
            storage_uri="minio://kb-assets/doc_001/a.png",
            content_hash="sha256:abc123",
            status=AssetStatus.ready,
            extracted_text="图片展示了用户上传文档后的解析状态",
            metadata={"width": 1200, "height": 800, "mime_type": "image/png"},
        )
        assert asset.asset_type == AssetType.image
        assert asset.storage_uri == "minio://kb-assets/doc_001/a.png"
        assert asset.metadata.get("mime_type") == "image/png"
        assert asset.content_hash == "sha256:abc123"
        assert asset.status == AssetStatus.ready
        assert asset.extracted_text == "图片展示了用户上传文档后的解析状态"
        assert asset.metadata["width"] == 1200

    def test_video_asset(self):
        asset = Asset(doc_id="doc_001", asset_type=AssetType.video_link,
                      original_uri="https://example.com/video.mp4",
                      metadata={"mime_type": "video/mp4"})
        assert asset.asset_type == AssetType.video_link

    def test_url_asset(self):
        asset = Asset(doc_id="doc_001", asset_type=AssetType.document_link,
                      original_uri="https://example.com/page")
        assert asset.asset_type == AssetType.document_link

    def test_file_asset(self):
        asset = Asset(doc_id="doc_001", asset_type=AssetType.document_link,
                      original_uri="file:///data/attachment.pdf")
        assert asset.asset_type == AssetType.document_link

    def test_all_asset_types(self):
        for atype in AssetType:
            asset = Asset(doc_id="doc_001", asset_type=atype,
                          original_uri="https://example.com/x")
            assert asset.asset_type == atype

    def test_all_status_values(self):
        for status in AssetStatus:
            asset = Asset(doc_id="doc_001", asset_type=AssetType.image,
                          original_uri="https://x.com/a.png", status=status)
            assert asset.status == status

    def test_failed_asset_with_error(self):
        asset = Asset(
            doc_id="doc_001", asset_type=AssetType.image,
            original_uri="https://x.com/a.png",
            status=AssetStatus.failed,
            error_message="invalid_image_type",
        )
        assert asset.status == AssetStatus.failed
        assert asset.error_message == "invalid_image_type"

    def test_json_round_trip_full(self):
        asset = Asset(
            doc_id="doc_001",
            element_id="el_003",
            asset_type=AssetType.image,
            original_uri="https://example.com/a.png",
            storage_uri="minio://kb-assets/doc_001/a.png",
            content_hash="sha256:abc123",
            status=AssetStatus.ready,
            extracted_text="图片描述",
            error_message=None,
            metadata={"width": 1200, "height": 800, "mime_type": "image/png"},
        )
        data = asset.model_dump(mode="json")
        restored = Asset.model_validate(data)
        assert restored.asset_id == asset.asset_id
        assert restored.asset_type == AssetType.image
        assert restored.status == AssetStatus.ready
        assert restored.extracted_text == "图片描述"
        assert restored.metadata["width"] == 1200

    def test_element_id_traceability(self):
        """验证 Asset → Element 的溯源关联。"""
        el = ParsedElement(doc_id="doc_001",
                           element_type=ElementType.paragraph)
        asset = Asset(doc_id="doc_001", asset_type=AssetType.image,
                      original_uri="https://x.com/a.png",
                      element_id=el.element_id)
        assert asset.element_id == el.element_id


# ── KnowledgeChunk ────────────────────────────────────────────────────

class TestKnowledgeChunk:
    def test_defaults(self):
        chunk = KnowledgeChunk(content="内容")
        assert chunk.chunk_id.startswith("chunk_")
        assert chunk.title == ""
        assert chunk.knowledge_type == KnowledgeType.declarative
        assert chunk.category == "通用"
        assert chunk.status == ChunkStatus.active
        assert chunk.asset_refs == []
        assert chunk.source_refs == []
        assert chunk.metadata == {}

    def test_content_hash_auto_computed(self):
        chunk = KnowledgeChunk(content="Hello World")
        assert chunk.content_hash
        assert chunk.content_hash.startswith("sha256:")

    def test_content_hash_stable(self):
        """相同内容产生相同 hash。"""
        c1 = KnowledgeChunk(content="same")
        c2 = KnowledgeChunk(content="same")
        assert c1.content_hash == c2.content_hash

    def test_content_hash_different_for_different_content(self):
        c1 = KnowledgeChunk(content="A")
        c2 = KnowledgeChunk(content="B")
        assert c1.content_hash != c2.content_hash

    def test_explicit_content_hash(self):
        """显式设置 content_hash 时不被覆盖。"""
        chunk = KnowledgeChunk(content="X",
                               content_hash="sha256:custom")
        assert chunk.content_hash == "sha256:custom"

    def test_asset_refs(self):
        chunk = KnowledgeChunk(
            content="Some content with image.",
            title="Test Chunk",
            asset_refs=[
                AssetRef(
                    asset_id="asset_001",
                    caption="上传状态列表截图",
                )
            ],
        )
        assert len(chunk.asset_refs) == 1
        assert chunk.asset_refs[0].asset_id == "asset_001"
        assert chunk.asset_refs[0].caption == "上传状态列表截图"

    def test_source_refs(self):
        chunk = KnowledgeChunk(
            content="Content",
            title="Test",
            source_refs=[
                SourceRef(
                    doc_id="doc_001",
                    doc_version=1,
                    element_id="el_002",
                    source_location=SourceLocation(
                        page=3,
                        section_path=["1 产品概述", "1.2 上传文档"],
                    ),
                )
            ],
        )
        assert len(chunk.source_refs) == 1
        assert chunk.source_refs[0].source_location.page == 3
        assert len(chunk.source_refs[0].source_location.section_path) == 2

    def test_multiple_source_refs(self):
        """一个 chunk 引用多个来源元素。"""
        chunk = KnowledgeChunk(
            content="综合内容",
            source_refs=[
                SourceRef(doc_id="doc_001", element_id="el_001"),
                SourceRef(doc_id="doc_001", element_id="el_002"),
                SourceRef(doc_id="doc_001", element_id="el_003"),
            ],
        )
        assert len(chunk.source_refs) == 3

    def test_all_knowledge_types(self):
        for ktype in KnowledgeType:
            chunk = KnowledgeChunk(content="X",
                                   knowledge_type=ktype)
            assert chunk.knowledge_type == ktype

    def test_all_chunk_status_values(self):
        for status in ChunkStatus:
            chunk = KnowledgeChunk(content="X",
                                   status=status)
            assert chunk.status == status

    def test_chunk_status_deleted(self):
        chunk = KnowledgeChunk(content="X",
                               status=ChunkStatus.deleted)
        assert chunk.status == ChunkStatus.deleted

    def test_json_round_trip_full(self):
        """全字段 JSON 序列化往返。"""
        chunk = KnowledgeChunk(
            title="上传文档解析状态判断",
            content="系统支持通过网页端上传知识文档...",
            knowledge_type=KnowledgeType.declarative,
            category="产品使用",
            status=ChunkStatus.active,
            asset_refs=[
                AssetRef(asset_id="asset_001",
                         caption="截图"),
            ],
            source_refs=[
                SourceRef(doc_id="doc_001", element_id="el_002",
                          source_location=SourceLocation(page=3)),
            ],
            metadata={"title_path": ["手册", "上传"], "language": "zh-CN"},
        )
        data = chunk.model_dump(mode="json")
        restored = KnowledgeChunk.model_validate(data)
        assert restored.title == "上传文档解析状态判断"
        assert restored.status == ChunkStatus.active
        assert len(restored.asset_refs) == 1
        assert len(restored.source_refs) == 1
        assert restored.metadata["language"] == "zh-CN"


# ── SearchResult & SearchResultItem ───────────────────────────────────

class TestSearchResult:
    def test_empty_result(self):
        sr = SearchResult(query="test")
        assert sr.search_id.startswith("search_")
        assert sr.rewritten_query == ""
        assert sr.results == []
        assert sr.total_count == 0

    def test_with_rewritten_query(self):
        sr = SearchResult(
            query="上传文档后怎么看解析成功没有？",
            rewritten_query="用户上传知识文档后，如何查看文档解析状态以及成功或失败结果？",
        )
        assert sr.rewritten_query != ""
        assert sr.query == "上传文档后怎么看解析成功没有？"

    def test_with_results(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.95,
            category="通用",
            knowledge_type=KnowledgeType.declarative,
        )
        sr = SearchResult(query="test", total_count=1, results=[item])
        assert len(sr.results) == 1
        assert sr.results[0].score == 0.95
        assert sr.total_count == 1

    def test_multiple_results(self):
        items = [
            SearchResultItem(
                chunk_id=f"chunk_{i:03d}",
                title=f"Result {i}",
                content=f"Content {i}",
                score=1.0 - i * 0.1,
                category="通用",
                knowledge_type=KnowledgeType.declarative,
            )
            for i in range(5)
        ]
        sr = SearchResult(query="test", total_count=5, results=items)
        assert len(sr.results) == 5
        # 分数应递减
        scores = [r.score for r in sr.results]
        assert scores == sorted(scores, reverse=True)

    def test_result_item_score_components(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.92,
            category="产品使用",
            knowledge_type=KnowledgeType.declarative,
            score_components=ScoreComponents(vector=0.89, bm25=0.73, rerank=0.92),
        )
        assert item.score_components.vector == 0.89
        assert item.score_components.bm25 == 0.73
        assert item.score_components.rerank == 0.92

    def test_result_item_with_asset_refs(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.92,
            category="产品使用",
            knowledge_type=KnowledgeType.declarative,
            asset_refs=[
                {
                    "asset_id": "asset_001",
                    "relation": "evidence",
                    "storage_uri": "minio://kb-assets/doc_001/upload-status.png",
                    "linked_text": "界面截图展示了上传状态列表",
                    "caption": "上传状态列表截图",
                    "render": {"mode": "inline", "position": "after_linked_text"},
                }
            ],
        )
        assert len(item.asset_refs) == 1
        assert item.asset_refs[0]["storage_uri"] == "minio://kb-assets/doc_001/upload-status.png"

    def test_result_item_with_source_refs(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.92,
            category="产品使用",
            knowledge_type=KnowledgeType.declarative,
            source_refs=[
                SourceRef(doc_id="doc_001", element_id="el_002",
                          source_location=SourceLocation(page=3)),
            ],
        )
        assert len(item.source_refs) == 1
        assert item.source_refs[0].element_id == "el_002"

    def test_result_item_with_metadata(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.92,
            category="产品使用",
            knowledge_type=KnowledgeType.declarative,
            metadata={"title_path": ["产品使用手册", "上传文档"]},
        )
        assert item.metadata["title_path"] == ["产品使用手册", "上传文档"]

    def test_json_round_trip_full(self):
        """SearchResult 全字段 JSON 序列化往返。"""
        items = [
            SearchResultItem(
                chunk_id="chunk_001",
                title="上传文档解析状态判断",
                content="系统支持通过网页端上传知识文档...",
                score=0.92,
                category="产品使用",
                knowledge_type=KnowledgeType.declarative,
                score_components=ScoreComponents(vector=0.89, bm25=0.73, rerank=0.92),
                asset_refs=[{"asset_id": "asset_001", "storage_uri": "minio://..."}],
                source_refs=[SourceRef(doc_id="doc_001", element_id="el_002")],
                metadata={"title_path": ["产品使用手册", "上传文档"]},
            )
        ]
        sr = SearchResult(
            query="上传文档后怎么看解析成功没有？",
            rewritten_query="用户上传知识文档后，如何查看文档解析状态？",
            total_count=12,
            results=items,
        )
        data = sr.model_dump(mode="json")
        restored = SearchResult.model_validate(data)
        assert restored.query == "上传文档后怎么看解析成功没有？"
        assert restored.rewritten_query != ""
        assert restored.total_count == 12
        assert len(restored.results) == 1
        assert restored.results[0].chunk_id == "chunk_001"
        assert restored.results[0].score_components.vector == 0.89


# ── 枚举完整性 ────────────────────────────────────────────────────────

class TestEnums:
    def test_doc_status_values(self):
        assert {s.value for s in DocStatus} == {"pending", "processing", "active", "failed", "deleted"}

    def test_element_type_values(self):
        values = {t.value for t in ElementType}
        expected = {"paragraph", "title", "table", "list", "code", "unknown"}
        assert values == expected

    def test_asset_type_values(self):
        assert {t.value for t in AssetType} == {"image", "image_link", "video", "video_link", "document_link"}

    def test_asset_status_values(self):
        assert {s.value for s in AssetStatus} == {"downloading", "ready", "failed"}

    def test_asset_relation_removed(self):
        """AssetRelation 枚举已删除，AssetRef 不再有 relation 字段。"""
        ref = AssetRef(asset_id="asset_001")
        data = ref.model_dump(mode="json")
        assert "relation" not in data

    def test_knowledge_type_values(self):
        values = {t.value for t in KnowledgeType}
        assert "declarative" in values
        assert "relational" in values
        assert "procedural" in values

    def test_chunk_status_values(self):
        assert {s.value for s in ChunkStatus} == {"active", "deleted"}

    def test_doc_status_is_string_enum(self):
        """确保 DocStatus 可当字符串比较（继承 str, Enum）。"""
        assert DocStatus.active == "active"
        assert isinstance(DocStatus.active, str)

    def test_element_type_is_string_enum(self):
        assert ElementType.paragraph == "paragraph"
        assert isinstance(ElementType.paragraph, str)

    def test_asset_status_is_string_enum(self):
        assert AssetStatus.ready == "ready"
        assert isinstance(AssetStatus.ready, str)

    def test_chunk_status_is_string_enum(self):
        assert ChunkStatus.active == "active"
        assert isinstance(ChunkStatus.active, str)
