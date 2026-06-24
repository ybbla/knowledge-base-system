from indexing.milvus_bm25 import MilvusBM25Index
from indexing.milvus_vector import DENSE_DIM, MilvusCollectionManager, MilvusVectorIndex
from app.core.models import KnowledgeChunk
from ingestion.pipeline import IngestionPipeline
import ingestion.pipeline as ingestion_module


class _FakeCollection:
    def __init__(self) -> None:
        self.upsert_calls = []
        self.flush_count = 0

    def upsert(self, entities):
        self.upsert_calls.append(entities)

    def flush(self):
        self.flush_count += 1


class _NoConnectManager(MilvusCollectionManager):
    def __init__(self) -> None:
        self.collection = _FakeCollection()
        self._cache = {}

    def ensure_collection(self) -> None:
        return None


class _FakeManager:
    def __init__(self) -> None:
        self.batches = []
        self.sparse_index_ensured = 0

    def upsert_fields_batch(self, items):
        self.batches.append(items)

    def ensure_sparse_index(self) -> None:
        self.sparse_index_ensured += 1


class _RecordingIndex:
    def __init__(self) -> None:
        self.batches = []

    def add_batch(self, items):
        self.batches.append(items)

    def add(self, *_args, **_kwargs):
        raise AssertionError("应使用批量写入")

    def delete(self, _chunk_id):
        return None

    def search(self, *_args, **_kwargs):
        return []


class _RecordingChunkStore:
    def __init__(self) -> None:
        self.stored_chunks = {}

    def put(self, chunk):
        self.stored_chunks[chunk.chunk_id] = chunk


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.calls = []

    def embed_text(self, texts):
        self.calls.append(list(texts))
        return [[1.0] * DENSE_DIM for _ in texts]


def test_manager_upsert_fields_batch_flushes_once():
    manager = _NoConnectManager()

    manager.upsert_fields_batch(
        [
            ("chunk_a", {"content": "A"}),
            ("chunk_b", {"content": "B"}),
        ]
    )

    assert len(manager.collection.upsert_calls) == 1
    assert len(manager.collection.upsert_calls[0]) == 2
    assert manager.collection.flush_count == 1


def test_milvus_vector_add_batch_uses_single_manager_batch():
    manager = _FakeManager()
    index = MilvusVectorIndex(manager)
    vector = [0.0] * DENSE_DIM

    index.add_batch(
        [
            ("chunk_a", vector, {"content": "A", "category": "demo"}),
            ("chunk_b", vector, {"content": "B", "category": "demo"}),
        ]
    )

    assert len(manager.batches) == 1
    assert [chunk_id for chunk_id, _fields in manager.batches[0]] == [
        "chunk_a",
        "chunk_b",
    ]


def test_milvus_sparse_add_batch_uses_single_manager_batch():
    manager = _FakeManager()
    index = MilvusBM25Index(manager)

    index.add_batch(
        [
            ("chunk_a", "Milvus 批量写入测试", {"category": "demo"}),
            ("chunk_b", "Milvus 稀疏向量测试", {"category": "demo"}),
        ]
    )

    assert manager.sparse_index_ensured == 1
    assert len(manager.batches) == 1
    assert [chunk_id for chunk_id, _fields in manager.batches[0]] == [
        "chunk_a",
        "chunk_b",
    ]


def test_ingestion_indexes_chunks_in_limited_batches(monkeypatch):
    embedder = _RecordingEmbedder()
    monkeypatch.setattr(ingestion_module, "embedding_client", embedder)
    monkeypatch.setattr(ingestion_module.settings, "embedding_batch_size", 2)
    monkeypatch.setattr(ingestion_module.settings, "index_upsert_batch_size", 1)

    vector_index = _RecordingIndex()
    bm25_index = _RecordingIndex()
    chunk_store = _RecordingChunkStore()
    pipeline = IngestionPipeline(
        parser_registry=None,
        extractor=None,
        vector_index=vector_index,
        bm25_index=bm25_index,
        asset_store=None,
        chunk_store=chunk_store,
    )
    chunks = [
        KnowledgeChunk(title=f"C{idx}", content=f"content {idx}")
        for idx in range(3)
    ]

    pipeline._index_chunks(chunks)

    assert [len(call) for call in embedder.calls] == [2, 1]
    assert [len(batch) for batch in vector_index.batches] == [1, 1, 1]
    assert [len(batch) for batch in bm25_index.batches] == [1, 1, 1]
    assert len(chunk_store.stored_chunks) == 3
