import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.core.models import (
    Asset,
    DocStatus,
    Document,
    KnowledgeChunk,
    ParsedElement,
)
from assets.base import AssetStore
from indexing.base import BM25Index, VectorIndex
from ingestion.recursive_loader import RecursiveLoader
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.base import DocumentParser

logger = logging.getLogger(__name__)


class JobStatus:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "pending"
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.doc_ids: list[str] = []
        self.chunk_count = 0
        self.asset_count = 0
        self.error: str | None = None


class IngestionPipeline:
    """Orchestrate the full ingestion pipeline."""

    def __init__(
        self,
        parser: DocumentParser,
        extractor: SemanticExtractor,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        asset_store: AssetStore,
        chunk_store: Any = None,
    ) -> None:
        self._parser = parser
        self._extractor = extractor
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._asset_store = asset_store
        self._chunk_store = chunk_store
        self._jobs: dict[str, JobStatus] = {}

    def submit(
        self,
        doc: Document,
        raw_content: str = "",
        options: dict[str, Any] | None = None,
    ) -> JobStatus:
        """Submit a document for ingestion. Returns immediately with job status."""
        job = JobStatus(doc.ingest_job_id or doc.doc_id)
        self._jobs[job.job_id] = job

        thread = threading.Thread(
            target=self._run,
            args=(doc, raw_content, job, options or {}),
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> JobStatus | None:
        return self._jobs.get(job_id)

    def _run(
        self,
        doc: Document,
        raw_content: str,
        job: JobStatus,
        options: dict[str, Any],
    ) -> None:
        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)

        try:
            # 1. Parse document
            result = self._parser.parse(doc)
            doc = result.doc
            elements = result.elements
            assets = result.assets
            job.asset_count = len(assets)
            job.doc_ids.append(doc.doc_id)

            # Store assets
            for asset in assets:
                self._asset_store.put(asset)

            # 2. Recursive loading for embedded docs
            loader = RecursiveLoader(
                parser_fn=self._parser.parse,
                max_depth=options.get("max_depth"),
                max_elements=options.get("max_elements_per_doc"),
            )
            all_docs, all_elements = loader.load(doc, raw_content)
            for d in all_docs:
                if d.doc_id != doc.doc_id:
                    job.doc_ids.append(d.doc_id)
            elements.extend(all_elements)  # include elements from embedded docs

            # 3. Semantic extraction
            chunks = self._extractor.extract(
                elements, assets, doc.ingest_job_id
            )
            job.chunk_count = len(chunks)

            # 4. Embedding and indexing
            if chunks:
                self._index_chunks(chunks)

            # Update doc status
            doc.status = DocStatus.active
            doc.updated_at = datetime.now(timezone.utc)
            job.status = "completed"

        except Exception as exc:
            logger.exception("Ingestion job %s failed", job.job_id)
            doc.status = DocStatus.failed
            job.status = "failed"
            job.error = str(exc)

        job.finished_at = datetime.now(timezone.utc)

    def _index_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """Generate embeddings and write to both indices + chunk store."""
        # Embedding input is the semantic chunk content only. Metadata is kept
        # for filtering/display/BM25/rerank so it does not dilute embeddings.
        texts = [chunk.content for chunk in chunks]

        # Write to chunk store for retrieval
        if self._chunk_store:
            for chunk in chunks:
                self._chunk_store.put(chunk)

        # Generate embeddings in batch
        try:
            vectors = embedding_client.embed_text(texts)
        except Exception:
            logger.exception("Embedding generation failed, skipping indexing")
            return

        # Write to indices
        for chunk, vector in zip(chunks, vectors):
            self._vector_index.add(
                chunk.chunk_id,
                vector,
                metadata={
                    "doc_id": chunk.doc_id,
                    "knowledge_type": chunk.knowledge_type.value,
                    "title_path": chunk.metadata.get("title_path", []),
                    "source_refs": [
                        ref.model_dump(mode="json")
                        for ref in chunk.source_refs
                    ],
                    "asset_refs": [
                        ref.model_dump(mode="json")
                        for ref in chunk.asset_refs
                    ],
                    "metadata": chunk.metadata,
                },
            )
            self._bm25_index.add(chunk.chunk_id, chunk.content)
