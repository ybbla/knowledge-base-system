import asyncio
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
from assets.image_processor import process_image, process_video
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
    def __init__(
        self,
        job_id: str,
        *,
        doc: Document | None = None,
        options: dict[str, Any] | None = None,
        is_update: bool = False,
    ):
        self.job_id = job_id
        self.status = "pending"
        self.stage = "pending"
        self.progress = 0
        self.created_at = datetime.now(timezone.utc)
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.doc_ids: list[str] = [doc.doc_id] if doc is not None else []
        self.doc_id = doc.doc_id if doc is not None else ""
        self.doc_title = doc.title if doc is not None else ""
        self.mode = (options or {}).get("mode") or ("incremental" if is_update else "create")
        if options and options.get("force"):
            self.mode = "force"
        self.options = options or {}
        self.is_update = is_update
        self.doc = doc
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
        is_update: bool = False,
    ) -> JobStatus:
        """提交文档入库任务。is_update=True 时走增量更新流程。"""
        resolved_options = options or {}
        job = JobStatus(
            doc.ingest_job_id or doc.doc_id,
            doc=doc,
            options=resolved_options,
            is_update=is_update,
        )
        self._jobs[job.job_id] = job

        thread = threading.Thread(
            target=self._run,
            args=(doc, raw_content, job, resolved_options, is_update),
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> JobStatus | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobStatus]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def retry_job(self, job_id: str) -> JobStatus | None:
        job = self.get_job(job_id)
        if job is None or job.status != "failed" or job.doc is None:
            return None
        return self.submit(job.doc, options=dict(job.options), is_update=job.is_update)

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job is None or job.status != "pending":
            return False
        job.status = "canceled"
        job.stage = "canceled"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        return True

    def _run(
        self,
        doc: Document,
        raw_content: str,
        job: JobStatus,
        options: dict[str, Any],
        is_update: bool = False,
    ) -> None:
        if job.status == "canceled":
            return
        job.status = "processing"
        job.stage = "parse"
        job.progress = 10
        job.started_at = datetime.now(timezone.utc)

        try:
            doc.status = DocStatus.processing
            doc.updated_at = datetime.now(timezone.utc)

            if is_update and self._document_repo:
                # ── 更新分支：乐观锁检查，旧 chunk 淘汰由 _update_existing_doc 处理 ──
                self._run_update(doc, raw_content, job, options)
            else:
                # ── 新建分支 ──
                self._run_create(doc, raw_content, job, options)

            job.status = "completed"
            job.stage = "completed"
            job.progress = 100

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
            job.stage = "failed"
            job.progress = 100
            job.error = str(exc)

        job.finished_at = datetime.now(timezone.utc)

    def _run_create(
        self,
        doc: Document,
        raw_content: str,
        job: JobStatus,
        options: dict[str, Any],
    ) -> None:
        """新建文档入库流程。"""
        if self._document_repo and self._document_repo.get(doc.doc_id) is None:
            self._document_repo.create(doc)

        # 1. 解析文档
        job.stage = "parse"
        job.progress = 20
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
        if doc.doc_id not in job.doc_ids:
            job.doc_ids.append(doc.doc_id)

        # 2. 递归加载嵌入子文档
        loader = RecursiveLoader(
            parser_fn=parser.parse,
            max_depth=options.get("max_depth"),
            max_elements=options.get("max_elements_per_doc"),
        )
        all_docs, embedded_elements = loader.load_embedded(doc, elements)
        for d in all_docs:
            if d.doc_id not in job.doc_ids:
                job.doc_ids.append(d.doc_id)
            if self._document_repo:
                self._document_repo.create(d)
        elements.extend(embedded_elements)

        if self._element_repo and elements:
            self._element_repo.create_batch(elements)

        # 3. 语义抽取
        job.stage = "extract"
        job.progress = 55
        chunks = self._extractor.extract(
            elements, assets, doc.ingest_job_id, doc.category
        )
        self._attach_unreferenced_video_assets(chunks, assets)
        job.chunk_count = len(chunks)

        # 4. 索引
        job.stage = "index"
        job.progress = 75
        if chunks:
            self._index_chunks(chunks)

        # 5. 更新文档状态
        doc.status = DocStatus.active
        doc.updated_at = datetime.now(timezone.utc)
        if self._document_repo:
            self._document_repo.update(doc)

        # 6. 自动生成评测数据（后台异步）
        if settings.auto_eval_enabled and chunks:
            self._trigger_eval_data_generation(doc, chunks)

    def _run_update(
        self,
        doc: Document,
        raw_content: str,
        job: JobStatus,
        options: dict[str, Any],
    ) -> None:
        """增量更新已有文档，级联处理嵌入子文档。"""
        # 0. 乐观锁：先更新 status 为 processing，version += 1
        job.stage = "parse"
        job.progress = 20
        doc.version += 1
        if self._document_repo:
            self._document_repo.update(doc)

        # 1. 级联查找所有需要更新的文档（root + children）
        docs_to_update: list[Document] = [doc]
        if self._document_repo:
            children = self._document_repo.list(root_doc_id=doc.doc_id)
            for child in children:
                child.version = doc.version
                child.status = DocStatus.processing
                self._document_repo.update(child)
                docs_to_update.append(child)

        all_new_chunks: list[KnowledgeChunk] = []
        all_old_chunk_ids: list[str] = []

        for target_doc in docs_to_update:
            # 收集旧知识块 ID（用于后续 Milvus 状态同步）
            if self._chunk_store and hasattr(self._chunk_store, "list_by_doc_id"):
                old_chunks = self._chunk_store.list_by_doc_id(target_doc.doc_id)
                all_old_chunk_ids.extend(
                    c.chunk_id for c in old_chunks if c.status.value == "active"
                )

            # 2. 解析文档
            if target_doc.source_uri.startswith("minio://"):
                raw = read_uri_bytes(target_doc.source_uri, self._minio_store)
                if target_doc.source_type.lower() in {"markdown", "md", "txt", "text"}:
                    target_doc.metadata["raw_content"] = raw.decode("utf-8")
                else:
                    target_doc.metadata["raw_content"] = raw
            parser = self._parser_registry.get(target_doc.source_type)
            result = parser.parse(target_doc)
            target_doc = result.doc
            elements = result.elements
            assets = result.assets
            assets = self._prepare_assets(assets)
            job.asset_count += len(assets)
            if target_doc.doc_id not in job.doc_ids:
                job.doc_ids.append(target_doc.doc_id)

            # 3. 递归加载嵌入子文档（更新模式下子文档可能变化）
            loader = RecursiveLoader(
                parser_fn=parser.parse,
                max_depth=options.get("max_depth"),
                max_elements=options.get("max_elements_per_doc"),
            )
            all_docs, embedded_elements = loader.load_embedded(target_doc, elements)
            for d in all_docs:
                if d.doc_id not in [td.doc_id for td in docs_to_update]:
                    if d.doc_id not in job.doc_ids:
                        job.doc_ids.append(d.doc_id)
                    if self._document_repo:
                        d.version = doc.version
                        d.status = DocStatus.active
                        self._document_repo.create(d)
            elements.extend(embedded_elements)

            # 4. 持久化解析元素（doc_version 使用新版本号）
            for el in elements:
                el.doc_version = doc.version
            if self._element_repo and elements:
                self._element_repo.create_batch(elements)

            # 5. 语义抽取
            job.stage = "extract"
            job.progress = 55
            chunks = self._extractor.extract(
                elements, assets, target_doc.ingest_job_id, target_doc.category
            )
            self._attach_unreferenced_video_assets(chunks, assets)
            job.chunk_count += len(chunks)
            all_new_chunks.extend(chunks)

        # 6. 索引新知识块（先写后淘汰）
        job.stage = "index"
        job.progress = 75
        if all_new_chunks:
            self._index_chunks(all_new_chunks)

        # 7. 标记旧知识块为 superseded（PostgreSQL + Milvus 双标记，原子操作）
        if all_old_chunk_ids:
            try:
                if self._chunk_store and hasattr(self._chunk_store, "bulk_update_status_by_doc_id"):
                    for target_doc in docs_to_update:
                        self._chunk_store.bulk_update_status_by_doc_id(
                            target_doc.doc_id, "superseded"
                        )
                self._vector_index.update_status_batch(all_old_chunk_ids, "superseded")
                self._bm25_index.update_status_batch(all_old_chunk_ids, "superseded")
            except Exception:
                logger.exception("旧知识块状态同步失败（PG+Milvus），索引中可能残留旧版本块")

        # 8. 更新文档状态
        for target_doc in docs_to_update:
            target_doc.status = DocStatus.active
            target_doc.updated_at = datetime.now(timezone.utc)
            target_doc.version = doc.version
            if self._document_repo:
                self._document_repo.update(target_doc)

        # 9. 自动生成评测数据（后台异步）
        if settings.auto_eval_enabled and all_new_chunks:
            self._trigger_eval_data_generation(doc, all_new_chunks)

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
            elif asset.asset_type == AssetType.video:
                process_video(asset, self._asset_store)
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
            "status": chunk.status.value,
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

    def _trigger_eval_data_generation(self, doc: Document, chunks: list[KnowledgeChunk]) -> None:
        """在后台异步触发评测数据生成。

        失败不影响主流程，仅记录日志。
        """
        def _generate() -> None:
            try:
                import asyncio
                from tests.evaluation.gen_dataset import generate_for_chunks
                from tests.evaluation.storage import save_per_doc_dataset

                # 转换 chunk 格式
                chunk_dicts = [
                    {"chunk_id": c.chunk_id, "title": c.title, "content": c.content}
                    for c in chunks
                ]

                # 生成评测数据
                items, errors = generate_for_chunks(
                    chunks=chunk_dicts,
                    doc_id=doc.doc_id,
                    doc_title=doc.title or doc.doc_id,
                    query_count=settings.auto_eval_queries_per_doc,
                )

                if errors:
                    logger.warning(
                        "评测数据生成有 %d 个警告：%s",
                        len(errors), errors[:3],
                    )

                if not items:
                    logger.warning("没有生成有效的评测数据")
                    return

                # 保存分文档数据集（不自动合并到全局，保持人工标注与自动生成隔离）
                path = save_per_doc_dataset(
                    doc_id=doc.doc_id,
                    doc_title=doc.title or doc.doc_id,
                    items=items,
                    chunk_count=len(chunks),
                )
                logger.info(
                    "文档 %s 评测数据生成完成，%d 条 → %s",
                    doc.doc_id, len(items), path,
                )

            except ImportError:
                # LLM 调用异常，不影响主流程
                logger.exception("评测数据生成失败，已跳过")
            except Exception:
                # 捕获所有异常，确保不影响主流程
                logger.exception("评测数据生成异常，已跳过")

        # 启动后台线程执行
        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()
