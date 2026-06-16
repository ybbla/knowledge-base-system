"""Application-wide dependency injection / shared state."""

import logging

from app.core.config import settings
from app.core.models import ChunkIndexStatus
from assets.memory_store import MemoryAssetStore
from assets.minio_store import MinioAssetStore
from indexing.memory_bm25 import MemoryBM25Index
from indexing.memory_vector import MemoryVectorIndex
from ingestion.pipeline import IngestionPipeline
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.docx_parser import DocxParser
from parsers.html_parser import HtmlParser
from parsers.markdown_parser import MarkdownParser
from parsers.pdf_parser import PdfParser
from parsers.pptx_parser import PptxParser
from parsers.registry import ParserRegistry
from parsers.xlsx_parser import XlsxParser
from retrieval.pipeline import ChunkStore, RetrievalPipeline

logger = logging.getLogger(__name__)

# ── Parser registry ──────────────────────────────────────────────────

parser_registry = ParserRegistry()
parser_registry.register(MarkdownParser(), DocxParser(), XlsxParser(), HtmlParser(), PptxParser(), PdfParser())

# ── Backend selection ─────────────────────────────────────────────────

if settings.backend == "postgres":
    from app.db.engine import get_engine
    from app.db.engine import create_session_factory as pg_create_session_factory
    from app.db.engine import ensure_runtime_schema
    from app.db.models import Base
    from app.db.repositories.assets import PgAssetStore
    from app.db.repositories.chunks import PgChunkStore
    from app.db.repositories.documents import DocumentRepository
    from app.db.repositories.elements import ParsedElementRepository

    # Create tables on startup
    engine = get_engine()
    Base.metadata.create_all(engine)
    ensure_runtime_schema()

    session_factory = pg_create_session_factory()
    asset_store = PgAssetStore(session_factory)
    chunk_store = PgChunkStore(session_factory)
    document_repo = DocumentRepository(session_factory)
    element_repo = ParsedElementRepository(session_factory)
else:
    asset_store = MemoryAssetStore()
    chunk_store = ChunkStore()
    document_repo = None
    element_repo = None
    session_factory = None

# ── Optional MinIO backend ─────────────────────────────────────────────

minio_asset_store = None
if settings.minio_enabled:
    try:
        minio_asset_store = MinioAssetStore(asset_store)
        minio_asset_store.ensure_buckets()
        asset_store = minio_asset_store
    except Exception:
        logger.exception("MinIO 初始化失败，回退到原 AssetStore")
        minio_asset_store = None

# ── Optional Milvus backend ────────────────────────────────────────────

milvus_manager = None
if settings.milvus_enabled:
    try:
        from indexing.milvus_sparse import MilvusSparseIndex
        from indexing.milvus_vector import MilvusCollectionManager, MilvusVectorIndex

        milvus_manager = MilvusCollectionManager()
        vector_index = MilvusVectorIndex(milvus_manager)
        bm25_index = MilvusSparseIndex(milvus_manager, session_factory=session_factory)
    except Exception:
        logger.exception("Milvus 初始化失败，回退到内存索引")
        milvus_manager = None
        vector_index = MemoryVectorIndex()
        bm25_index = MemoryBM25Index()
else:
    vector_index = MemoryVectorIndex()
    bm25_index = MemoryBM25Index()

extractor = SemanticExtractor()

ingestion_pipeline = IngestionPipeline(
    parser_registry=parser_registry,
    extractor=extractor,
    vector_index=vector_index,
    bm25_index=bm25_index,
    asset_store=asset_store,
    chunk_store=chunk_store,
    document_repo=document_repo,
    element_repo=element_repo,
)

retrieval_pipeline = RetrievalPipeline(
    vector_index=vector_index,
    bm25_index=bm25_index,
    chunk_store=chunk_store,
    asset_store=asset_store,
)


def rebuild_retrieval_indexes_from_chunks(category: str | None = None) -> int:
    """从已持久化的知识块重建内存检索索引。仅恢复 status='active' 的块。"""
    if hasattr(chunk_store, "list_all"):
        chunks = chunk_store.list_all(category=category)
    else:
        chunks = list(getattr(chunk_store, "_chunks", {}).values())
        if category is not None:
            chunks = [chunk for chunk in chunks if chunk.category == category]

    # ── 仅索引活跃知识块 ──
    chunks = [c for c in chunks if c.status.value == "active"]

    for chunk in chunks:
        bm25_index.add(chunk.chunk_id, chunk.content, metadata={"category": chunk.category, "status": "active"})

    if chunks:
        vectors = embedding_client.embed_text([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors):
            vector_index.add(
                chunk.chunk_id,
                vector,
                metadata={
                    "doc_id": chunk.doc_id,
                    "category": chunk.category,
                    "knowledge_type": chunk.knowledge_type.value,
                    "status": chunk.status.value,
                    "title_path": chunk.metadata.get("title_path", []),
                    "source_refs": [
                        ref.model_dump(mode="json") for ref in chunk.source_refs
                    ],
                    "asset_refs": [
                        ref.model_dump(mode="json") for ref in chunk.asset_refs
                    ],
                    "metadata": chunk.metadata,
                },
            )

    return len(chunks)


def recover_pending_chunk_indexes(limit: int | None = None) -> int:
    """恢复已经持久化但还没完成 Milvus 索引写入的知识块。"""
    if not settings.milvus_enabled or not hasattr(chunk_store, "list_by_index_status"):
        return 0

    chunks = chunk_store.list_by_index_status(
        [ChunkIndexStatus.pending, ChunkIndexStatus.indexing],
        limit=limit,
    )
    # ── 仅恢复活跃知识块（superseded 的不应被重新索引） ──
    chunks = [c for c in chunks if c.status.value == "active"]
    if not chunks:
        return 0

    ingestion_pipeline.index_existing_chunks(chunks)
    return len(chunks)


def startup_resources() -> None:
    """FastAPI 启动时确认外部资源可用。"""
    if minio_asset_store is not None:
        minio_asset_store.ensure_buckets()
    if milvus_manager is not None:
        milvus_manager.ensure_collection()
        try:
            recovered = recover_pending_chunk_indexes()
            if recovered:
                logger.info("Recovered %d pending chunk indexes", recovered)
        except Exception:
            logger.exception("恢复未完成知识块索引失败")


def shutdown_resources() -> None:
    """FastAPI 关闭时释放外部连接。"""
    if milvus_manager is not None:
        milvus_manager.disconnect()
