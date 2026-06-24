"""应用级依赖注入与共享状态。"""

import logging

from app.core.config import settings
from assets.minio_store import MinioAssetStore
from ingestion.pipeline import IngestionPipeline
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.docx_parser import DocxParser
from parsers.markdown_parser import MarkdownParser
from parsers.pdf_parser import PdfParser
from parsers.pptx_parser import PptxParser
from parsers.registry import ParserRegistry
from parsers.xlsx_parser import XlsxParser
from retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)

# ── Parser registry ──────────────────────────────────────────────────

parser_registry = ParserRegistry()
parser_registry.register(MarkdownParser(), DocxParser(), XlsxParser(), PptxParser(), PdfParser())

# ── 外部服务后端 ─────────────────────────────────────────────────────

def _init_postgres_backend() -> None:
    """初始化 PostgreSQL 后端；不可用时直接终止启动。"""
    from sqlalchemy import text

    try:
        from app.db.engine import get_engine
        from app.db.engine import create_session_factory as pg_create_session_factory
        from app.db.repositories.assets import PgAssetStore
        from app.db.repositories.chunks import PgChunkStore
        from app.db.repositories.documents import DocumentRepository
        from app.db.repositories.elements import ParsedElementRepository

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        sf = pg_create_session_factory()
        globals()["session_factory"] = sf
        globals()["asset_store"] = PgAssetStore(sf)
        globals()["chunk_store"] = PgChunkStore(sf)
        globals()["document_repo"] = DocumentRepository(sf)
        globals()["element_repo"] = ParsedElementRepository(sf)
    except Exception as exc:
        logger.exception("PostgreSQL 初始化失败")
        raise RuntimeError("PostgreSQL 不可用，服务启动失败") from exc


session_factory = None
asset_store = None
chunk_store = None
document_repo = None
element_repo = None

if settings.backend != "postgres":
    raise RuntimeError(f"仅支持 BACKEND=postgres，当前配置为 {settings.backend!r}")

_init_postgres_backend()

# ── MinIO backend ─────────────────────────────────────────────────────

minio_asset_store = None
if not settings.minio_enabled:
    raise RuntimeError("必须设置 MINIO_ENABLED=true，资源文件仅允许写入 MinIO")

try:
    minio_asset_store = MinioAssetStore(asset_store)
    asset_store = minio_asset_store
except Exception as exc:
    logger.exception("MinIO 初始化失败")
    raise RuntimeError("MinIO 不可用，服务启动失败") from exc

# ── Milvus backend ────────────────────────────────────────────────────

milvus_manager = None
if not settings.milvus_enabled:
    raise RuntimeError("必须设置 MILVUS_ENABLED=true，检索索引仅允许写入 Milvus")

try:
    from indexing.milvus_bm25 import MilvusBM25Index
    from indexing.milvus_vector import MilvusCollectionManager, MilvusVectorIndex

    milvus_manager = MilvusCollectionManager()
    milvus_manager.ensure_collection()
    vector_index = MilvusVectorIndex(milvus_manager)
    bm25_index = MilvusBM25Index(milvus_manager)
except Exception as exc:
    logger.exception("Milvus 初始化失败")
    raise RuntimeError("Milvus 不可用，服务启动失败") from exc

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
    """从 PostgreSQL 持久化知识块重建 Milvus 检索索引。"""
    if not hasattr(chunk_store, "list_all"):
        raise RuntimeError("当前知识块存储不支持重建检索索引")

    chunks = chunk_store.list_all(category=category)

    # 仅索引活跃知识块。
    chunks = [c for c in chunks if c.status.value == "active"]
    if not chunks:
        return 0

    # 批量写入 BM25 索引
    bm25_items = []
    for c in chunks:
        doc_id = c.doc_id or (c.source_refs[0].doc_id if c.source_refs else "")
        metadata = {
            "doc_id": doc_id,
            "title": c.title,
            "category": c.category,
            "knowledge_type": c.knowledge_type.value,
            "status": "active",
            "source_refs": [ref.model_dump(mode="json") for ref in c.source_refs],
            "metadata": c.metadata,
        }
        bm25_items.append((c.chunk_id, c.content, metadata))
    bm25_index.add_batch(bm25_items)

    # 批量写入向量索引
    vectors = embedding_client.embed_text([c.content for c in chunks])
    vector_items = []
    for chunk, vector in zip(chunks, vectors):
        doc_id = chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else "")
        metadata = {
            "doc_id": doc_id,
            "title": chunk.title,
            "content": chunk.content,
            "category": chunk.category,
            "knowledge_type": chunk.knowledge_type.value,
            "status": chunk.status.value,
            "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
            "metadata": chunk.metadata,
        }
        vector_items.append((chunk.chunk_id, vector, metadata))
    vector_index.add_batch(vector_items)

    return len(chunks)


def recover_pending_chunk_indexes(limit: int | None = None) -> int:
    """启动时恢复所有活跃知识块的索引。"""
    if not hasattr(chunk_store, "list_all"):
        return 0

    all_chunks = chunk_store.list_all()
    chunks = [c for c in all_chunks if c.status.value == "active"]
    if limit is not None:
        chunks = chunks[:limit]
    if not chunks:
        return 0

    ingestion_pipeline.index_existing_chunks(chunks)
    return len(chunks)


def shutdown_resources() -> None:
    """FastAPI 关闭时释放外部连接。"""
    if milvus_manager is not None:
        milvus_manager.disconnect()
