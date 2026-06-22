"""文档去重功能测试：v1 上传去重。"""

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import upload_utils as upload_api
from app.core.models import DocStatus, Document
from app.main import app

client = TestClient(app)

DUMMY_HASH = f"sha256:{hashlib.sha256(b'# content').hexdigest()}"


class _FakeDocumentRepo:
    """模拟 PostgreSQL DocumentRepository。"""

    def __init__(self, existing_doc: Document | None = None):
        self._docs: dict[str, Document] = {}
        if existing_doc:
            self._docs[existing_doc.doc_id] = existing_doc

    def find_by_hash(self, source_hash: str) -> Document | None:
        for doc in self._docs.values():
            if doc.source_hash == source_hash and doc.status.value == "active":
                return doc
        return None

    def find_similar_by_filename(self, filename: str) -> list[Document]:
        return []

    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def create(self, doc: Document) -> Document:
        if doc.doc_id in self._docs:
            from app.core.errors import DuplicateDocumentError
            raise DuplicateDocumentError(f"Document {doc.doc_id} already exists")
        self._docs[doc.doc_id] = doc
        return doc

    def update(self, doc: Document) -> Document:
        self._docs[doc.doc_id] = doc
        return doc


# ── v1 上传去重测试 ──


def test_upload_dedup_hit_returns_duplicate(monkeypatch):
    """已有活跃文档时上传应返回 duplicate"""
    existing = Document(
        title="已有文档", source_type="markdown",
        source_uri="minio://kb-input/old/doc.md",
        source_hash=DUMMY_HASH, category="通用",
        status=DocStatus.active,
    )
    repo = _FakeDocumentRepo(existing)
    monkeypatch.setattr(
        "app.api.v1.documents.document_repo", repo
    )
    monkeypatch.setattr(
        "app.api.v1.documents.ingestion_pipeline",
        type("_FakePipeline", (), {"ingest": lambda self, doc, **kw: doc})(),
    )

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("manual.md", b"# content", "text/markdown")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["duplicate"] is True
    assert data["data"]["existing_doc_id"] == existing.doc_id
