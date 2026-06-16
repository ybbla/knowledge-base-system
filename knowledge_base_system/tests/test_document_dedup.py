"""文档去重功能测试：上传去重 + 入库去重。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ingest as ingest_api
from app.api import upload as upload_api
from app.core.deps import ingestion_pipeline
from app.core.models import Document
from app.main import app

client = TestClient(app)

DUMMY_HASH = "sha256:abc123def456"


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

    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def create(self, doc: Document) -> Document:
        if doc.doc_id in self._docs:
            from app.core.errors import DuplicateDocumentError
            raise DuplicateDocumentError(f"Document {doc.doc_id} already exists")
        self._docs[doc.doc_id] = doc
        return doc


class _FakeIngestionPipeline:
    def __init__(self):
        self.submitted: list[tuple[Document, dict, bool]] = []

    def submit(self, doc, options=None, is_update=False):
        self.submitted.append((doc, options or {}, is_update))
        return SimpleNamespace(job_id=doc.doc_id)


# ── 上传去重测试 ──


def test_upload_dedup_hit_returns_duplicate(monkeypatch, tmp_path):
    """已有活跃文档时上传应返回 duplicate"""
    existing = Document(
        title="已有文档", source_type="markdown",
        source_uri="minio://kb-input/old/doc.md",
        source_hash=DUMMY_HASH, category="通用",
    )
    repo = _FakeDocumentRepo(existing)
    monkeypatch.setattr(upload_api, "document_repo", repo)
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        upload_api, "get_settings",
        lambda reload_env=False: SimpleNamespace(minio_enabled=False),
    )

    response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# content", "text/markdown")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["duplicate"] is True
    assert data["existing_doc_id"] == existing.doc_id


def test_upload_new_file_returns_no_duplicate(monkeypatch, tmp_path):
    """新文件上传不应返回 duplicate"""
    monkeypatch.setattr(upload_api, "document_repo", _FakeDocumentRepo())
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        upload_api, "get_settings",
        lambda reload_env=False: SimpleNamespace(minio_enabled=False),
    )

    response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# content", "text/markdown")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("duplicate") is not True


def test_upload_failed_doc_not_intercepted(monkeypatch, tmp_path):
    """status=failed 的文档不拦截上传"""
    from app.core.models import DocStatus

    existing = Document(
        title="失败文档", source_type="markdown",
        source_uri="minio://kb-input/fail/doc.md",
        source_hash=DUMMY_HASH, category="通用",
        status=DocStatus.failed,
    )
    repo = _FakeDocumentRepo(existing)
    monkeypatch.setattr(upload_api, "document_repo", repo)
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        upload_api, "get_settings",
        lambda reload_env=False: SimpleNamespace(minio_enabled=False),
    )

    response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# content", "text/markdown")},
    )
    assert response.status_code == 200
    data = response.json()
    # failed 文档不应触发 duplicate（find_by_hash 只查 active）
    assert data.get("duplicate") is not True


# ── 入库去重测试 ──


def test_ingest_new_activates_dedup(monkeypatch):
    """新建模式下相同 hash 的活跃文档应被跳过"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash=DUMMY_HASH, category="通用",
    )
    repo = _FakeDocumentRepo(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "title": "重复内容", "source_type": "markdown",
            "source_uri": "minio://new/doc.md",
            "source_hash": DUMMY_HASH, "category": "通用",
        }],
    })
    assert response.status_code == 202
    data = response.json()
    # 应有一条 warning
    assert len(data["warnings"]) >= 1
    assert data["warnings"][0]["reason"] == "duplicate_content"


def test_ingest_update_bypasses_dedup(monkeypatch):
    """更新模式下（doc_id 有值）不执行 hash 去重"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash="sha256:oldhash", category="通用",
    )
    repo = _FakeDocumentRepo(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "doc_id": existing.doc_id,
            "title": "更新后的文档", "source_type": "markdown",
            "source_uri": "minio://new/doc.md",
            "source_hash": "sha256:newhash", "category": "通用",
        }],
    })
    assert response.status_code == 202
    data = response.json()
    assert len(data["warnings"]) == 0
    assert len(data["doc_ids"]) == 1
    # 确认走了更新路径
    assert fake_pipeline.submitted[0][2] is True  # is_update=True


def test_ingest_update_no_change_skips(monkeypatch):
    """source_hash 未变化时返回 no_change"""
    existing = Document(
        title="现存", source_type="markdown",
        source_uri="minio://old/doc.md",
        source_hash=DUMMY_HASH, category="通用",
    )
    repo = _FakeDocumentRepo(existing)
    fake_pipeline = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "document_repo", repo)
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake_pipeline)

    response = client.post("/ingest", json={
        "documents": [{
            "doc_id": existing.doc_id,
            "title": "现存", "source_type": "markdown",
            "source_uri": "minio://old/doc.md",
            "source_hash": DUMMY_HASH, "category": "通用",
        }],
    })
    assert response.status_code == 202
    data = response.json()
    assert len(data["warnings"]) >= 1
    assert data["warnings"][0]["reason"] == "no_change"
