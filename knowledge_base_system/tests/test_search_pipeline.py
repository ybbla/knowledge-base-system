from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ingest as ingest_api
from app.api import search as search_api
from app.api import upload as upload_api
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


class _CompletedIngestionPipeline:
    def __init__(self) -> None:
        self.job = None

    def submit(self, doc, options=None):
        self.job = SimpleNamespace(
            job_id=doc.doc_id,
            status="completed",
            doc_ids=[doc.doc_id],
            chunk_count=1,
            asset_count=0,
            error=None,
            started_at=None,
            finished_at=None,
        )
        return self.job

    def get_job(self, job_id):
        if self.job and self.job.job_id == job_id:
            return self.job
        return None


class _SearchPipeline:
    def search(self, query, top_k=None, category=None):
        if category != "manuals":
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
        monkeypatch.setattr(upload_api, "UPLOAD_DIR", Path("data/uploads"))
        monkeypatch.setattr(ingest_api, "ingestion_pipeline", _CompletedIngestionPipeline())
        monkeypatch.setattr(search_api, "retrieval_pipeline", _SearchPipeline())

        upload_resp = client.post(
            "/upload",
            files={
                "file": (
                    "manual.md",
                    SAMPLE_MARKDOWN.encode("utf-8"),
                    "text/markdown",
                )
            },
            data={"title": "Product Manual", "category": "manuals"},
        )
        assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
        upload_data = upload_resp.json()

        resp = client.post(
            "/ingest",
            json={
                "documents": [
                    {
                        "title": "Product Manual",
                        "source_type": "markdown",
                        "source_uri": upload_data["source_uri"],
                        "category": "manuals",
                    }
                ],
                "options": {"max_depth": 1},
            },
        )
        assert resp.status_code == 202, f"Ingest failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "accepted"

        job_id = data["job_id"]
        status_resp = client.get(f"/ingest/{job_id}")
        assert status_resp.status_code == 200
        self.job_result = status_resp.json()

    def test_ingest_completed(self):
        assert self.job_result["status"] == "completed"
        assert self.job_result["chunk_count"] == 1
        assert len(self.job_result["doc_ids"]) == 1

    def test_search_returns_results(self):
        resp = client.post(
            "/search",
            json={
                "query": "How do users know document parsing succeeded?",
                "top_k": 5,
                "filters": {"category": "manuals"},
            },
        )
        assert resp.status_code == 200, f"Search failed: {resp.text}"
        data = resp.json()

        assert data["search_id"].startswith("search_")
        assert data["query"]
        assert data["rewritten_query"]
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

    def test_search_category_filter_excludes_other_categories(self):
        resp = client.post(
            "/search",
            json={
                "query": "upload document",
                "top_k": 5,
                "filters": {"category": "support"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
