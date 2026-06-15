"""PDF 入库集成测试。

验证 PdfParser 通过 IngestionPipeline 端到端流程：解析 → 语义抽取 → 索引。
"""

import time

import fitz

from app.core.models import Document, ElementType, KnowledgeChunk
from assets.memory_store import MemoryAssetStore
from ingestion.pipeline import IngestionPipeline
import ingestion.pipeline as ingestion_module
from parsers.pdf_parser import PdfParser
from parsers.registry import ParserRegistry


# ── 测试辅助 ────────────────────────────────────────────────────────────

def _simple_pdf_bytes() -> bytes:
    """创建含标题和正文的简单 PDF。"""
    doc = fitz.open()
    page = doc.new_page()

    # 标题（大字体）
    title_rect = fitz.Rect(72, 72, page.rect.width - 72, 110)
    page.insert_textbox(title_rect, "Introduction to Knowledge Base",
                        fontname="hebo", fontsize=18)

    # 正文
    body_rect = fitz.Rect(72, 130, page.rect.width - 72, 300)
    page.insert_textbox(body_rect,
                        "The knowledge base system supports multi-format document ingestion, "
                        "semantic extraction, and hybrid retrieval with vector and BM25 search.",
                        fontname="helv", fontsize=12)

    buf = doc.tobytes()
    doc.close()
    return buf


class _FakeExtractor:
    def __init__(self) -> None:
        self.seen_elements: list = []

    def extract(self, elements, assets, ingest_job_id, category):
        self.seen_elements = list(elements)
        source = elements[0] if elements else None
        return [
            KnowledgeChunk(
                doc_id=source.doc_id if source else "unknown",
                doc_version=source.doc_version if source else 1,
                title="PDF Knowledge Chunk",
                content="The knowledge base system supports multi-format document ingestion.",
                category=category,
                ingest_job_id=ingest_job_id,
            )
        ]


class _RecordingIndex:
    def __init__(self) -> None:
        self.batches: list = []

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
        self.chunks: dict = {}
        self.index_statuses: dict = {}

    def put(self, chunk):
        self.chunks[chunk.chunk_id] = chunk

    def update_index_status(self, chunk_ids, status, error=None):
        for chunk_id in chunk_ids:
            self.index_statuses[chunk_id] = status


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list = []

    def embed_text(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]


# ── 测试 ────────────────────────────────────────────────────────────────

def test_ingestion_pipeline_dispatches_pdf_parser(monkeypatch):
    """验证 PDF 文档通过入库管线完成解析 → 语义抽取 → 索引全流程。"""
    embedder = _FakeEmbedder()
    monkeypatch.setattr(ingestion_module, "embedding_client", embedder)

    registry = ParserRegistry()
    registry.register(PdfParser())
    extractor = _FakeExtractor()
    vector_index = _RecordingIndex()
    bm25_index = _RecordingIndex()
    chunk_store = _RecordingChunkStore()
    asset_store = MemoryAssetStore()
    pipeline = IngestionPipeline(
        parser_registry=registry,
        extractor=extractor,
        vector_index=vector_index,
        bm25_index=bm25_index,
        asset_store=asset_store,
        chunk_store=chunk_store,
    )
    doc = Document(
        title="Knowledge Base Introduction",
        source_type="pdf",
        source_uri="memory://intro.pdf",
        category="技术文档",
        metadata={"raw_content": _simple_pdf_bytes()},
    )
    doc.ingest_job_id = doc.doc_id

    job = pipeline.submit(doc)
    for _ in range(50):
        if job.status in {"completed", "failed"}:
            break
        time.sleep(0.02)

    assert job.status == "completed", job.error
    assert job.doc_ids == [doc.doc_id]
    assert job.chunk_count == 1
    # 验证解析出了标题和段落
    element_types = [el.element_type for el in extractor.seen_elements]
    assert ElementType.title in element_types
    assert ElementType.paragraph in element_types
    assert len(chunk_store.chunks) == 1
    assert len(embedder.calls) == 1
    assert len(vector_index.batches) == 1
    assert len(bm25_index.batches) == 1


def test_ingestion_pipeline_marks_invalid_pdf_failed(monkeypatch):
    """验证无效/损坏 PDF 通过入库管线时 job 标记为 failed。"""
    embedder = _FakeEmbedder()
    monkeypatch.setattr(ingestion_module, "embedding_client", embedder)

    pipeline = IngestionPipeline(
        parser_registry=ParserRegistry(),
        extractor=_FakeExtractor(),
        vector_index=_RecordingIndex(),
        bm25_index=_RecordingIndex(),
        asset_store=MemoryAssetStore(),
        chunk_store=_RecordingChunkStore(),
    )
    pipeline._parser_registry.register(PdfParser())
    doc = Document(
        title="坏文件",
        source_type="pdf",
        source_uri="memory://bad.pdf",
        metadata={"raw_content": b"not a valid pdf file"},
    )
    doc.ingest_job_id = doc.doc_id

    job = pipeline.submit(doc)
    for _ in range(50):
        if job.status in {"completed", "failed"}:
            break
        time.sleep(0.02)

    assert job.status == "failed"
    assert "PDF 解析失败" in job.error
