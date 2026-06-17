from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import ingest as ingest_api
from app.api import search as search_api
from app.api import upload as upload_api
from app.core.models import KnowledgeChunk
from app.main import app
from indexing.memory_bm25 import MemoryBM25Index
from indexing.memory_vector import MemoryVectorIndex
from retrieval.pipeline import ChunkStore, RetrievalPipeline
import retrieval.pipeline as retrieval_module


client = TestClient(app)


class _FakeIngestionPipeline:
    def __init__(self) -> None:
        self.submitted = []

    def submit(self, doc, raw_content="", options=None, is_update=False):
        self.submitted.append((doc, options or {}))
        return SimpleNamespace(job_id=doc.doc_id)


def test_upload_defaults_and_writes_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", Path("data/uploads"))
    monkeypatch.setattr(
        upload_api,
        "get_settings",
        lambda reload_env=False: SimpleNamespace(minio_enabled=False),
    )

    response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# Manual\nBody", "text/markdown")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "manual"
    assert data["category"] == "\u901a\u7528"
    assert data["file_name"] == "manual.md"
    assert data["size"] == len(b"# Manual\nBody")
    assert data["source_hash"].startswith("sha256:")
    assert data["source_uri"].startswith("file://data/uploads/")

    stored = Path(data["source_uri"].replace("file://", ""))
    assert stored.exists()
    assert stored.read_bytes() == b"# Manual\nBody"


def test_upload_falls_back_to_local_when_minio_unavailable(monkeypatch, tmp_path):
    class _FailingMinioAssetStore:
        def __init__(self, *_args, **_kwargs) -> None:
            self.client = None

        def ensure_buckets(self) -> None:
            raise RuntimeError("minio unavailable")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upload_api, "UPLOAD_DIR", Path("data/uploads"))
    monkeypatch.setattr(
        upload_api,
        "get_settings",
        lambda reload_env=False: SimpleNamespace(
            minio_enabled=True,
            minio_bucket_input="kb-input",
        ),
    )
    monkeypatch.setattr(upload_api, "MinioAssetStore", _FailingMinioAssetStore)

    response = client.post(
        "/upload",
        files={"file": ("manual.md", b"# Manual\nBody", "text/markdown")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["source_uri"].startswith("file://data/uploads/")
    assert data["size"] == len(b"# Manual\nBody")

    stored = Path(data["source_uri"].replace("file://", ""))
    assert stored.exists()
    assert stored.read_bytes() == b"# Manual\nBody"


def test_ingest_requires_source_uri():
    response = client.post(
        "/ingest",
        json={
            "documents": [
                {
                    "title": "Manual",
                    "source_type": "markdown",
                }
            ]
        },
    )

    assert response.status_code == 422


def test_ingest_defaults_category_and_returns_202(monkeypatch):
    fake = _FakeIngestionPipeline()
    monkeypatch.setattr(ingest_api, "ingestion_pipeline", fake)

    response = client.post(
        "/ingest",
        json={
            "documents": [
                {
                    "title": "Manual",
                    "source_type": "markdown",
                    "source_uri": "file://data/uploads/manual.md",
                    "source_hash": "sha256:test",
                }
            ]
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    [(doc, options)] = fake.submitted
    assert doc.source_uri == "file://data/uploads/manual.md"
    assert doc.category == "\u901a\u7528"
    assert options == {}


class _FakeEmbedder:
    def embed_text(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeRewriter:
    def rewrite(self, query):
        return {"rewritten_query": query, "keywords": [query]}


class _FakeReranker:
    def rerank(self, query, candidates):
        return [
            {"chunk_id": chunk.chunk_id, "relevance_score": 1.0 - index * 0.1}
            for index, chunk in enumerate(candidates)
        ]


def test_search_filters_by_category(monkeypatch):
    monkeypatch.setattr(retrieval_module, "embedding_client", _FakeEmbedder())

    vector_index = MemoryVectorIndex()
    bm25_index = MemoryBM25Index()
    chunk_store = ChunkStore()

    included = KnowledgeChunk(
        chunk_id="chunk_manual",
        doc_id="doc_1",
        title="Manual",
        content="upload status manual",
        category="manuals",
    )
    excluded = KnowledgeChunk(
        chunk_id="chunk_support",
        doc_id="doc_2",
        title="Support",
        content="upload status support",
        category="support",
    )

    for chunk, vector in [(included, [1.0, 0.0]), (excluded, [0.9, 0.1])]:
        chunk_store.put(chunk)
        vector_index.add(
            chunk.chunk_id,
            vector,
            metadata={"category": chunk.category},
        )
        bm25_index.add(
            chunk.chunk_id,
            chunk.content,
            metadata={"category": chunk.category},
        )

    pipeline = RetrievalPipeline(vector_index, bm25_index, chunk_store)
    pipeline._rewriter = _FakeRewriter()
    pipeline._reranker = _FakeReranker()
    monkeypatch.setattr(search_api, "retrieval_pipeline", pipeline)

    response = client.post(
        "/search",
        json={
            "query": "upload",
            "top_k": 5,
            "filters": {"category": "manuals"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert [item["chunk_id"] for item in data["results"]] == ["chunk_manual"]
    assert data["results"][0]["category"] == "manuals"
    assert data["results"][0]["knowledge_type"] == "declarative"
