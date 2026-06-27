from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    KnowledgeType,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
    SourceRef,
)
from app.main import app

client = TestClient(app)

SAMPLE_MARKDOWN = """\
# Product Manual

## Upload Knowledge Documents

Users can upload Markdown and TXT files to the knowledge base.
After upload, the system shows parsing status:

| Status | Meaning |
|------|------|
| Processing | The system is parsing the document. |
| Success | The document has entered the knowledge base. |
| Failed | Review the error and upload again. |
"""


class _SearchPipeline:
    def search(self, query, top_k=None, categories=None):
        if not categories or "manuals" not in categories:
            return SearchResult(query=query, rewritten_query=query)
        return SearchResult(
            query=query,
            rewritten_query=query,
            total_count=1,
            results=[
                SearchResultItem(
                    chunk_id="chunk_manual",
                    title="Upload Knowledge Documents",
                    content="Users can upload documents and see parsing status.",
                    score=1.0,
                    category="manuals",
                    knowledge_type=KnowledgeType.declarative,
                    score_components=ScoreComponents(
                        vector=0.9,
                        bm25=0.8,
                        rerank=1.0,
                    ),
                    source_refs=[
                        SourceRef(doc_id="doc_manual", element_id="el_manual")
                    ],
                    metadata={"title_path": ["Product Manual"]},
                )
            ],
        )


class TestSearchPipeline:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "app.api.v1.documents.ingestion_pipeline",
            type("_FakePipeline", (), {"ingest": lambda self, doc, **kw: doc})(),
        )
        monkeypatch.setattr(
            "app.api.v1.documents.upload_api",
            type("_FakeUploadApi", (), {
                "DEFAULT_CATEGORY": "通用",
                "save_upload_file": staticmethod(
                    lambda *a, **kw: {
                        "source_uri": "minio://kb-input/doc_test/manual.md",
                        "doc_id": "doc_test",
                        "file_name": "manual.md",
                        "size": len(SAMPLE_MARKDOWN.encode("utf-8")),
                        "title": "Product Manual",
                        "category": "manuals",
                    }
                ),
            })(),
        )
        monkeypatch.setattr(
            "app.api.v1.documents.document_repo",
            type("_FakeRepo", (), {
                "find_by_hash": lambda self, h: None,
                "find_similar_by_filename": lambda self, n: [],
                "create": lambda self, d: d,
                "update": lambda self, d: d,
                "get": lambda self, did: None,
            })(),
        )

    def test_search_returns_results(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.deps", "retrieval_pipeline", _SearchPipeline()
        )
        resp = client.post(
            "/api/v1/search",
            json={
                "query": "How do users know document parsing succeeded?",
                "top_k": 5,
                "filters": {"categories": ["manuals"]},
            },
        )
        assert resp.status_code == 200, f"Search failed: {resp.text}"
        data = resp.json()

        assert data["search_id"].startswith("search_")
        assert data["query"]
        assert data["total_count"] == 1

        results = data["results"]
        assert len(results) == 1

        r = results[0]
        assert r["chunk_id"] == "chunk_manual"
        assert r["content"]
        assert r["score"] > 0
        assert r["category"] == "manuals"
        assert r["knowledge_type"] == "declarative"

        sc = r["score_components"]
        assert sc["vector"] == 0.9
        assert sc["bm25"] == 0.8
        assert sc["rerank"] == 1.0

        assert len(r["source_refs"]) == 1
        assert r["source_refs"][0]["doc_id"] == "doc_manual"
        assert r["source_refs"][0]["element_id"] == "el_manual"
        assert r["metadata"]["title_path"] == ["Product Manual"]

    def test_search_category_filter_excludes_other_categories(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.deps", "retrieval_pipeline", _SearchPipeline()
        )
        resp = client.post(
            "/api/v1/search",
            json={
                "query": "upload document",
                "top_k": 5,
                "filters": {"categories": ["support"]},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
