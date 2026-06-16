"""文档增量更新测试：version 递增、旧 chunk 标记、no_change、404。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ingest as ingest_api
from app.core.models import Document
from app.main import app

client = TestClient(app)


class _FakeDocumentRepo:
    def __init__(self):
        self._docs: dict[str, Document] = {}

    def add_doc(self, doc: Document):
        self._docs[doc.doc_id] = doc
        return doc

    def find_by_hash(self, source_hash: str) -> Document | None:
        for doc in self._docs.values():
            if doc.source_hash == source_hash and doc.status.value == "active":
                return doc
        return None

    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def update(self, doc: Document):
        if doc.doc_id not in self._docs:
            raise ValueError("not found")
        self._docs[doc.doc_id] = doc


class _FakeIngestionPipeline:
    def __init__(self):
        self.submitted: list[tuple[Document, dict, bool]] = []

    def submit(self, doc, options=None, is_update=False):
        self.submitted.append((doc, options or {}, is_update))
        return SimpleNamespace(job_id=doc.doc_id)


def test_update_returns_404_for_unknown_doc_id(monkeypatch):
    """不存在的 doc_id 返回 404"""
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", _FakeDocumentRepo())
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "doc_id": "doc_nonexistent",
            "title": "文档", "source_type": "markdown",
            "source_uri": "minio://x/doc.md",
            "source_hash": "sha256:abc", "category": "通用",
        }],
    })
    assert response.status_code == 404


def test_update_no_change_skips(monkeypatch):
    """hash 未变时跳过"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash="sha256:samehash", category="通用",
    )
    repo = _FakeDocumentRepo()
    repo.add_doc(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "doc_id": existing.doc_id,
            "title": "现存", "source_type": "markdown",
            "source_uri": "minio://old/doc.md",
            "source_hash": "sha256:samehash", "category": "通用",
        }],
    })
    assert response.status_code == 202
    data = response.json()
    assert len(data["warnings"]) >= 1
    assert data["warnings"][0]["reason"] == "no_change"


def test_update_triggers_is_update_flag(monkeypatch):
    """hash 变化时走 is_update=True"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash="sha256:oldhash", category="通用",
    )
    repo = _FakeDocumentRepo()
    repo.add_doc(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "doc_id": existing.doc_id,
            "title": "更新", "source_type": "markdown",
            "source_uri": "minio://new/doc.md",
            "source_hash": "sha256:newhash", "category": "通用",
        }],
    })
    assert response.status_code == 202
    assert fake_pipeline.submitted[0][2] is True  # is_update=True


def test_update_preserves_existing_fields(monkeypatch):
    """更新时传入的 doc 应保留 existing 的 parent/root/metadata"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash="sha256:oldhash", category="产品使用",
        parent_doc_id="doc_parent",
        root_doc_id="doc_root",
        metadata={"tags": ["important"]},
    )
    repo = _FakeDocumentRepo()
    repo.add_doc(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    client.post("/ingest", json={
        "documents": [{
            "doc_id": existing.doc_id,
            "title": "更新后标题", "source_type": "docx",
            "source_uri": "minio://new/doc.docx",
            "source_hash": "sha256:newhash", "category": "产品使用",
        }],
    })

    submitted_doc = fake_pipeline.submitted[0][0]
    assert submitted_doc.parent_doc_id == "doc_parent"
    assert submitted_doc.root_doc_id == "doc_root"
    assert submitted_doc.metadata.get("tags") == ["important"]
