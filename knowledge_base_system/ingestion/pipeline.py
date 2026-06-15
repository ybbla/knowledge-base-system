import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.models import (
    Asset,
    AssetRef,
    AssetRelation,
    AssetStatus,
    AssetType,
    ChunkIndexStatus,
    DocStatus,
    Document,
    ElementType,
    KnowledgeChunk,
    ParsedElement,
)
from assets.base import AssetStore
from assets.image_processor import process_image
from assets.minio_store import MinioAssetStore, read_uri_bytes
from indexing.base import BM25Index, VectorIndex
from ingestion.recursive_loader import RecursiveLoader
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.registry import ParserRegistry

logger = logging.getLogger(__name__)


def _batched(items: list[Any], size: int) -> list[list[Any]]:
    """按固定大小切分列表，避免单次 embedding 或 upsert 过大。"""
    batch_size = max(1, size)
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


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
        parser_registry: ParserRegistry,
        extractor: SemanticExtractor,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        asset_store: AssetStore,
        chunk_store: Any = None,
        document_repo: Any = None,
        element_repo: Any = None,
    ) -> None:
        self._parser_registry = parser_registry
        self._extractor = extractor
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._asset_store = asset_store
        self._chunk_store = chunk_store
        self._document_repo = document_repo
        self._element_repo = element_repo
        self._minio_store = asset_store if isinstance(asset_store, MinioAssetStore) else None
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
            doc.status = DocStatus.processing
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                self._document_repo.create(doc)

            # 1. 解析文档。MinIO 源文件先读取为 raw_content 交给现有解析器。
            if doc.source_uri.startswith("minio://"):
                raw = read_uri_bytes(doc.source_uri, self._minio_store)
                if doc.source_type.lower() in {"markdown", "md", "txt", "text"}:
                    doc.metadata["raw_content"] = raw.decode("utf-8")
                else:
                    doc.metadata["raw_content"] = raw
            parser = self._parser_registry.get(doc.source_type)
            result = parser.parse(doc)
            doc = result.doc
            elements = result.elements
            assets = result.assets
            assets = self._prepare_assets(assets)
            job.asset_count = len(assets)
            job.doc_ids.append(doc.doc_id)

            # 2. Recursive loading for embedded docs
            loader = RecursiveLoader(
                parser_fn=parser.parse,
                max_depth=options.get("max_depth"),
                max_elements=options.get("max_elements_per_doc"),
            )
            all_docs, embedded_elements = loader.load_embedded(doc, elements)
            for d in all_docs:
                job.doc_ids.append(d.doc_id)
                if self._document_repo:
                    self._document_repo.create(d)
            elements.extend(embedded_elements)

            if self._element_repo and elements:
                self._element_repo.create_batch(elements)

            # 3. Semantic extraction
            chunks = self._extractor.extract(
                elements, assets, doc.ingest_job_id, doc.category
            )
            self._attach_unreferenced_video_assets(chunks, assets)
            job.chunk_count = len(chunks)

            # 4. Embedding and indexing
            if chunks:
                self._index_chunks(chunks)

            # Update doc status
            doc.status = DocStatus.active
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                self._document_repo.update(doc)
            job.status = "completed"

        except Exception as exc:
            logger.exception("Ingestion job %s failed", job.job_id)
            doc.status = DocStatus.failed
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                try:
                    self._document_repo.update(doc)
                except Exception:
                    logger.exception("Failed to persist failed document status")
            job.status = "failed"
            job.error = str(exc)

        job.finished_at = datetime.now(timezone.utc)

    def _prepare_assets(self, assets: list[Asset]) -> list[Asset]:
        """应用资源数量限制，并处理图片资源生命周期。"""
        for idx, asset in enumerate(assets):
            if idx >= settings.max_assets_per_doc:
                asset.status = AssetStatus.skipped
                asset.error_message = "max_assets_per_doc_exceeded"
                self._asset_store.put(asset)
                continue

            if asset.asset_type == AssetType.image:
                process_image(asset, self._asset_store, self._minio_store)
            else:
                self._asset_store.put(asset)
        return assets

    @staticmethod
    def _attach_unreferenced_video_assets(
        chunks: list[KnowledgeChunk],
        assets: list[Asset],
    ) -> None:
        """将未被 LLM 显式引用的视频资源兜底关联到同文档第一个知识块。"""
        referenced = {
            ref.asset_id
            for chunk in chunks
            for ref in chunk.asset_refs
        }
        for asset in assets:
            if asset.asset_type != AssetType.video or asset.asset_id in referenced:
                continue
            for chunk in chunks:
                if chunk.doc_id == asset.doc_id:
                    chunk.asset_refs.append(
                        AssetRef(
                            asset_id=asset.asset_id,
                            relation=AssetRelation.demonstration,
                            caption=asset.original_uri,
                        )
                    )
                    referenced.add(asset.asset_id)
                    break

    def index_existing_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """重新索引已持久化的知识块，用于启动恢复或人工补偿。"""
        self._index_chunks(chunks, persist_chunks=False)

    def _index_chunks(
        self,
        chunks: list[KnowledgeChunk],
        *,
        persist_chunks: bool = True,
    ) -> None:
        """生成 embedding，并将 dense/sparse 索引写入检索后端。"""
        if self._chunk_store:
            if persist_chunks:
                for chunk in chunks:
                    chunk.index_status = ChunkIndexStatus.pending
                    chunk.indexed_at = None
                    chunk.index_error = None
                    self._chunk_store.put(chunk)

        for batch in _batched(chunks, settings.embedding_batch_size):
            self._mark_index_status(batch, ChunkIndexStatus.indexing)
            try:
                texts = [chunk.content for chunk in batch]
                vectors = embedding_client.embed_text(texts)
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"embedding count mismatch: chunks={len(batch)}, vectors={len(vectors)}"
                    )
            except Exception as exc:
                self._mark_index_status(batch, ChunkIndexStatus.failed, str(exc))
                logger.exception("Embedding generation failed")
                raise

            vector_items = []
            bm25_items = []
            for chunk, vector in zip(batch, vectors):
                metadata = self._chunk_index_metadata(chunk)
                vector_items.append((chunk.chunk_id, vector, metadata))
                bm25_items.append((chunk.chunk_id, chunk.content, metadata))

            zipped_items = list(zip(batch, vector_items, bm25_items))
            for write_batch in _batched(zipped_items, settings.index_upsert_batch_size):
                write_chunks = [item[0] for item in write_batch]
                try:
                    self._vector_index.add_batch([item[1] for item in write_batch])
                    self._bm25_index.add_batch([item[2] for item in write_batch])
                    self._mark_index_status(write_chunks, ChunkIndexStatus.indexed)
                except Exception as exc:
                    self._mark_index_status(write_chunks, ChunkIndexStatus.failed, str(exc))
                    logger.exception("Index write failed")
                    raise

    def _mark_index_status(
        self,
        chunks: list[KnowledgeChunk],
        status: ChunkIndexStatus,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc) if status == ChunkIndexStatus.indexed else None
        for chunk in chunks:
            chunk.index_status = status
            chunk.indexed_at = now
            chunk.index_error = error

        if self._chunk_store and hasattr(self._chunk_store, "update_index_status"):
            self._chunk_store.update_index_status(
                [chunk.chunk_id for chunk in chunks],
                status,
                error[:2000] if error else None,
            )

    @staticmethod
    def _chunk_index_metadata(chunk: KnowledgeChunk) -> dict[str, Any]:
        """构造写入检索索引的知识块元数据。"""
        return {
            "doc_id": chunk.doc_id,
            "content": chunk.content,
            "category": chunk.category,
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
        }
