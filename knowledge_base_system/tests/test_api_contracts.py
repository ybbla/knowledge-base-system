from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.v1 import documents as documents_api
from app.main import app


client = TestClient(app)


class _FakeIngestionPipeline:
    def __init__(self) -> None:
        self.submitted = []

    def submit(self, doc, raw_content="", options=None, is_update=False):
        self.submitted.append((doc, options or {}))
        return SimpleNamespace(job_id=doc.doc_id)


class _FakeDocumentRepo:
    def __init__(self) -> None:
        self.created = []

    def find_by_hash(self, source_hash: str):
        return None

    def create(self, doc):
        self.created.append(doc)
        return doc

    def get(self, doc_id: str):
        for doc in self.created:
            if doc.doc_id == doc_id:
                return doc
        return None


def test_create_document_requires_source_uri():
    response = client.post(
        "/api/v1/documents",
        params={"title": "Manual", "source_type": "markdown"},
    )

    assert response.status_code == 422


def test_create_document_defaults_category_and_ingests(monkeypatch):
    fake = _FakeIngestionPipeline()
    repo = _FakeDocumentRepo()
    monkeypatch.setattr(documents_api, "document_repo", repo)
    monkeypatch.setattr(documents_api, "ingestion_pipeline", fake)

    response = client.post(
        "/api/v1/documents",
        params={
            "title": "Manual",
            "source_type": "markdown",
            "source_uri": "file://data/uploads/manual.md",
            "source_hash": "sha256:test",
            "ingest_after_create": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["error"] is None
    [(doc, options)] = fake.submitted
    assert doc.source_uri == "file://data/uploads/manual.md"
    assert doc.category == "\u901a\u7528"
    assert options == {}
