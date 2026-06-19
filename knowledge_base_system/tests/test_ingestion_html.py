import time

from app.core.models import (
    AssetType,
    Document,
    ElementType,
    KnowledgeChunk,
)
from ingestion.pipeline import IngestionPipeline
import ingestion.pipeline as ingestion_module
from parsers.html_parser import HtmlParser
from parsers.registry import ParserRegistry


class _FakeExtractor:
    def __init__(self) -> None:
        self.seen_elements = []
        self.seen_assets = []

    def extract(self, elements, assets, ingest_job_id, category):
        self.seen_elements = list(elements)
        self.seen_assets = list(assets)
        source = next(
            (el for el in elements if el.element_type == ElementType.paragraph),
            elements[0],
        )
        return [
            KnowledgeChunk(
                doc_id=source.doc_id,
                doc_version=source.doc_version,
                title="HTML 入库",
                content="HTML 文档解析后进入语义抽取流程。",
                category=category,
                ingest_job_id=ingest_job_id,
            )
        ]


class _RecordingIndex:
    def __init__(self) -> None:
        self.batches = []

    def add_batch(self, items):
        self.batches.append(items)

    def add(self, *_args, **_kwargs):
        raise AssertionError("入库管线应使用批量索引写入")

    def delete(self, _chunk_id):
        return None

    def search(self, *_args, **_kwargs):
        return []


class _RecordingChunkStore:
    def __init__(self) -> None:
        self.chunks = {}
        self.index_statuses = {}

    def put(self, chunk):
        self.chunks[chunk.chunk_id] = chunk

    def update_index_status(self, chunk_ids, status, error=None):
        for chunk_id in chunk_ids:
            self.index_statuses[chunk_id] = status


class _RecordingAssetStore:
    def __init__(self) -> None:
        self.assets = {}

    def put(self, asset):
        self.assets[asset.asset_id] = asset

    def get(self, asset_id):
        return self.assets.get(asset_id)

    def delete(self, asset_id):
        self.assets.pop(asset_id, None)


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls = []

    def embed_text(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]


def _pipeline(monkeypatch, *, max_assets_per_doc=None):
    embedder = _FakeEmbedder()
    monkeypatch.setattr(ingestion_module, "embedding_client", embedder)
    if max_assets_per_doc is not None:
        monkeypatch.setattr(ingestion_module.settings, "max_assets_per_doc", max_assets_per_doc)

    registry = ParserRegistry()
    registry.register(HtmlParser())
    extractor = _FakeExtractor()
    vector_index = _RecordingIndex()
    bm25_index = _RecordingIndex()
    chunk_store = _RecordingChunkStore()
    asset_store = _RecordingAssetStore()
    pipeline = IngestionPipeline(
        parser_registry=registry,
        extractor=extractor,
        vector_index=vector_index,
        bm25_index=bm25_index,
        asset_store=asset_store,
        chunk_store=chunk_store,
    )
    return pipeline, extractor, embedder, vector_index, bm25_index, chunk_store, asset_store


def _wait(job):
    for _ in range(50):
        if job.status in {"completed", "failed"}:
            break
        time.sleep(0.02)


def test_ingestion_pipeline_dispatches_html_parser(monkeypatch):
    pipeline, extractor, embedder, vector_index, bm25_index, chunk_store, _asset_store = _pipeline(monkeypatch)
    doc = Document(
        title="HTML",
        source_type="html",
        source_uri="memory://sample.html",
        category="验收",
        metadata={
            "raw_content": """
            <article>
              <h1>HTML 手册</h1>
              <p>HTML 文档可以入库。</p>
              <table><tr><th>状态</th></tr><tr><td>成功</td></tr></table>
              <iframe src="https://www.youtube.com/embed/demo"></iframe>
            </article>
            """
        },
    )
    doc.ingest_job_id = doc.doc_id

    job = pipeline.submit(doc)
    _wait(job)

    assert job.status == "completed", job.error
    assert job.doc_ids == [doc.doc_id]
    assert job.chunk_count == 1
    assert {el.element_type for el in extractor.seen_elements} >= {
        ElementType.title,
        ElementType.paragraph,
        ElementType.table,
        ElementType.video,
    }
    assert [asset.asset_type for asset in extractor.seen_assets] == [AssetType.video]
    assert len(chunk_store.chunks) == 1
    assert len(embedder.calls) == 1
    assert len(vector_index.batches) == 1
    assert len(bm25_index.batches) == 1


def test_ingestion_pipeline_marks_invalid_html_failed(monkeypatch):
    pipeline, _extractor, *_rest = _pipeline(monkeypatch)
    doc = Document(
        title="HTML",
        source_type="html",
        source_uri="memory://empty.html",
        metadata={"raw_content": ""},
    )
    doc.ingest_job_id = doc.doc_id

    job = pipeline.submit(doc)
    _wait(job)

    assert job.status == "failed"
    assert "HTML 解析失败" in job.error


def test_html_assets_respect_max_assets_per_doc(monkeypatch):
    pipeline, _extractor, *_rest, asset_store = _pipeline(monkeypatch, max_assets_per_doc=1)
    doc = Document(
        title="HTML",
        source_type="html",
        source_uri="memory://assets.html",
        metadata={
            "raw_content": """
            <article>
              <p>资源</p>
              <a href="https://example.com/a.pdf">A</a>
              <a href="https://example.com/b.pdf">B</a>
            </article>
            """
        },
    )
    doc.ingest_job_id = doc.doc_id

    job = pipeline.submit(doc)
    _wait(job)

    assert job.status == "completed", job.error
    stored = list(asset_store._store.values())
    assert len(stored) == 2
    assert stored[0].status.value == "pending"
    assert stored[1].status.value == "skipped"
    assert stored[1].error_message == "max_assets_per_doc_exceeded"
