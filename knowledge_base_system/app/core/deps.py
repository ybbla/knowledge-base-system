"""Application-wide dependency injection / shared state."""

from app.core.config import settings
from assets.memory_store import MemoryAssetStore
from indexing.memory_bm25 import MemoryBM25Index
from indexing.memory_vector import MemoryVectorIndex
from ingestion.pipeline import IngestionPipeline
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.docx_parser import DocxParser
from parsers.markdown_parser import MarkdownParser
from parsers.registry import ParserRegistry
from retrieval.pipeline import ChunkStore, RetrievalPipeline

# ── Parser registry ──────────────────────────────────────────────────

parser_registry = ParserRegistry()
parser_registry.register(MarkdownParser(), DocxParser())

# ── Backend selection ─────────────────────────────────────────────────

if settings.backend == "postgres":
    from app.db.engine import get_engine
    from app.db.engine import create_session_factory as pg_create_session_factory
    from app.db.models import Base
    from app.db.repositories.assets import PgAssetStore
    from app.db.repositories.chunks import PgChunkStore
    from app.db.repositories.documents import DocumentRepository
    from app.db.repositories.elements import ParsedElementRepository

    # Create tables on startup
    engine = get_engine()
    Base.metadata.create_all(engine)

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

# ── Shared instances (always in-memory for Phase 2) ───────────────────

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
    """Rebuild in-memory retrieval indexes from the configured chunk store.

    Phase 2 persists chunks in PostgreSQL but still keeps Vector/BM25 indexes
    in memory. This helper is intentionally explicit so evaluation or startup
    checks can repopulate the existing /search path without introducing a
    separate PG-only retrieval implementation.
    """
    if hasattr(chunk_store, "list_all"):
        chunks = chunk_store.list_all(category=category)
    else:
        chunks = list(getattr(chunk_store, "_chunks", {}).values())
        if category is not None:
            chunks = [chunk for chunk in chunks if chunk.category == category]

    for chunk in chunks:
        bm25_index.add(chunk.chunk_id, chunk.content, metadata={"category": chunk.category})

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
