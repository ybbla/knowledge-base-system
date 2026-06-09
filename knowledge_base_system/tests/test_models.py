import pytest
from app.core.models import (
    Document,
    ParsedElement,
    Asset,
    KnowledgeChunk,
    SearchResult,
    SearchResultItem,
    SourceLocation,
    AssetRef,
    SourceRef,
    AssetRelation,
    ElementType,
    AssetType,
    compute_hash,
    new_id,
)


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


class TestNewId:
    def test_prefix(self):
        id_ = new_id("doc")
        assert id_.startswith("doc_")

    def test_unique(self):
        ids = {new_id("doc") for _ in range(100)}
        assert len(ids) == 100


class TestDocument:
    def test_defaults(self):
        doc = Document(title="Test", source_type="markdown", source_uri="file:///test.md")
        assert doc.doc_id.startswith("doc_")
        assert doc.version == 1
        assert doc.status == "pending"

    def test_serialization(self):
        doc = Document(title="Test", source_type="markdown", source_uri="file:///test.md")
        data = doc.model_dump(mode="json")
        doc2 = Document.model_validate(data)
        assert doc2.title == "Test"
        assert doc2.doc_id == doc.doc_id


class TestParsedElement:
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


class TestKnowledgeChunk:
    def test_asset_refs(self):
        chunk = KnowledgeChunk(
            doc_id="doc_001",
            content="Some content with image.",
            title="Test Chunk",
            asset_refs=[
                AssetRef(
                    asset_id="asset_001",
                    relation=AssetRelation.evidence,
                    caption="A screenshot",
                )
            ],
        )
        assert len(chunk.asset_refs) == 1
        assert chunk.asset_refs[0].relation == AssetRelation.evidence
        assert chunk.content_hash  # auto-computed

    def test_source_refs(self):
        chunk = KnowledgeChunk(
            doc_id="doc_001",
            content="Content",
            title="Test",
            source_refs=[
                SourceRef(
                    doc_id="doc_001",
                    element_id="el_001",
                    source_location=SourceLocation(page=3),
                )
            ],
        )
        assert len(chunk.source_refs) == 1
        assert chunk.source_refs[0].source_location.page == 3


class TestSearchResult:
    def test_empty_result(self):
        sr = SearchResult(query="test")
        assert sr.search_id.startswith("search_")
        assert sr.results == []
        assert sr.total_count == 0

    def test_with_results(self):
        item = SearchResultItem(
            chunk_id="chunk_001",
            title="Test",
            content="Content",
            score=0.95,
        )
        sr = SearchResult(query="test", total_count=1, results=[item])
        assert len(sr.results) == 1
        assert sr.results[0].score == 0.95
