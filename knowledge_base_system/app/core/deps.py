"""Application-wide dependency injection / shared state."""

from assets.memory_store import MemoryAssetStore
from indexing.memory_bm25 import MemoryBM25Index
from indexing.memory_vector import MemoryVectorIndex
from ingestion.pipeline import IngestionPipeline
from llm.semantic_extractor import SemanticExtractor
from parsers.markdown_parser import MarkdownParser
from retrieval.pipeline import ChunkStore, RetrievalPipeline

# Shared instances (Phase 1: in-memory)
asset_store = MemoryAssetStore()
vector_index = MemoryVectorIndex()
bm25_index = MemoryBM25Index()
chunk_store = ChunkStore()

parser = MarkdownParser()
extractor = SemanticExtractor()

ingestion_pipeline = IngestionPipeline(
    parser=parser,
    extractor=extractor,
    vector_index=vector_index,
    bm25_index=bm25_index,
    asset_store=asset_store,
    chunk_store=chunk_store,
)

retrieval_pipeline = RetrievalPipeline(
    vector_index=vector_index,
    bm25_index=bm25_index,
    chunk_store=chunk_store,
    asset_store=asset_store,
)
