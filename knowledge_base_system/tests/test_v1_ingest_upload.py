import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import upload as upload_api
from app.api.v1 import documents as documents_api
from app.api.v1 import ingest as ingest_api
from app.core.models import Document
from app.main import app


client = TestClient(app)


class _FakeDocumentRepo:
    def __init__(self, existing: Document | None = None) -> None:
        self.existing = existing
        self.created: list[Document] = []

    def find_by_hash(self, source_hash: str):
        if self.existing and self.existing.source_hash == source_hash:
            return self.existing
        return None

    def create(self, doc: Document) -> Document:
        self.created.append(doc)
        return doc

    def get(self, doc_id: str):
        for doc in self.created:
            if doc.doc_id == doc_id:
                return doc
        if self.existing and self.existing.doc_id == doc_id:
            return self.existing
        return None


class _FakePipeline:
    def __init__(self) -> None:
        self.jobs = {}
        self.submitted = []

    def submit(self, doc, raw_content="", options=None, is_update=False):
        self.submitted.append((doc, options or {}, is_update))
        job = SimpleNamespace(
            job_id=f"job_{len(self.submitted)}",
            status="pending",
            stage="pending",
            progress=0,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
            doc_ids=[doc.doc_id],
            doc_id=doc.doc_id,
            doc_title=doc.title,
            mode=(options or {}).get("mode") or ("incremental" if is_update else "create"),
            chunk_count=0,
            asset_count=0,
            error=None,
        )
        self.jobs[job.job_id] = job
        return job

    def list_jobs(self):
        return list(self.jobs.values())

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def retry_job(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status != "failed":
            return None
        new_job = SimpleNamespace(**job.__dict__)
        new_job.job_id = f"{job_id}_retry"
        new_job.status = "pending"
        new_job.error = None
        self.jobs[new_job.job_id] = new_job
        return new_job

    def cancel_job(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status != "pending":
            return False
        job.status = "canceled"
        job.stage = "canceled"
        job.progress = 100
        return True


def _disable_minio_and_use_tmp(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", Path("data/uploads"))
    monkeypatch.setattr(
        upload_api,
        "get_settings",
        lambda reload_env=False: SimpleNamespace(minio_enabled=False),
    )


def test_v1_upload_document_creates_doc_and_submits_ingest(monkeypatch, tmp_path):
    _disable_minio_and_use_tmp(monkeypatch, tmp_path)
    repo = _FakeDocumentRepo()
    pipeline = _FakePipeline()
    monkeypatch.setattr(documents_api, "document_repo", repo)
    monkeypatch.setattr(documents_api, "ingestion_pipeline", pipeline)

    response = client.post(
        "/api/v1/documents/upload?ingest_after_create=true&mode=incremental",
        files={"file": ("manual.md", b"# Manual\nBody", "text/markdown")},
        data={"title": "Manual", "category": "Docs"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["error"] is None
    assert body["data"]["title"] == "Manual"
    assert body["data"]["source_type"] == "markdown"
    assert body["data"]["ingest_job_id"] == "job_1"
    assert len(repo.created) == 1
    assert pipeline.submitted[0][2] is False


def test_v1_upload_document_duplicate_does_not_write_file(monkeypatch, tmp_path):
    _disable_minio_and_use_tmp(monkeypatch, tmp_path)
    payload = b"# Manual\nBody"
    source_hash = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    existing = Document(
        doc_id="doc_existing",
        title="Existing",
        source_type="markdown",
        source_uri="file://already-there.md",
        source_hash=source_hash,
    )
    monkeypatch.setattr(documents_api, "document_repo", _FakeDocumentRepo(existing))
    monkeypatch.setattr(documents_api, "ingestion_pipeline", _FakePipeline())

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("manual.md", payload, "text/markdown")},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["duplicate"] is True
    assert data["existing_doc_id"] == "doc_existing"
    assert not Path("data/uploads").exists()


def test_v1_ingest_jobs_list_detail_retry_and_cancel(monkeypatch):
    pipeline = _FakePipeline()
    failed = SimpleNamespace(
        job_id="job_failed",
        status="failed",
        stage="failed",
        progress=100,
        created_at=datetime.now(timezone.utc),
        started_at=None,
        finished_at=None,
        doc_ids=["doc_1"],
        doc_id="doc_1",
        doc_title="Doc 1",
        mode="incremental",
        chunk_count=0,
        asset_count=0,
        error="boom",
    )
    pending = SimpleNamespace(**failed.__dict__)
    pending.job_id = "job_pending"
    pending.status = "pending"
    pending.stage = "pending"
    pending.error = None
    pipeline.jobs = {failed.job_id: failed, pending.job_id: pending}
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", pipeline)
    monkeypatch.setattr(ingest_api, "document_repo", None)

    list_response = client.get("/api/v1/ingest/jobs?status=failed")
    assert list_response.status_code == 200
    assert [item["job_id"] for item in list_response.json()["data"]] == ["job_failed"]

    detail_response = client.get("/api/v1/ingest/jobs/job_failed")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["error"] == "boom"

    retry_response = client.post("/api/v1/ingest/jobs/job_failed/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["data"]["job_id"] == "job_failed_retry"

    cancel_response = client.post("/api/v1/ingest/jobs/job_pending/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "canceled"


def test_legacy_ingest_and_upload_routes_keep_compatibility(monkeypatch, tmp_path):
    _disable_minio_and_use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(upload_api, "document_repo", None)
    upload_response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# Manual\nBody", "text/markdown")},
    )
    assert upload_response.status_code == 200
    assert "x-deprecated" in upload_response.headers

    ingest_response = client.post(
        "/ingest",
        json={
            "documents": [
                    {
                        "title": "Manual",
                        "source_type": "markdown",
                        "source_uri": "file://data/uploads/manual.md",
                        "source_hash": "sha256:removed",
                    }
            ]
        },
    )
    assert ingest_response.status_code == 202
    assert "x-deprecated" in ingest_response.headers
