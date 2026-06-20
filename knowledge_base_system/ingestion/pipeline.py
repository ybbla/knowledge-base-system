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


class IngestionPipeline:
    """编排完整的文档入库流程。"""

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

    def ingest(
        self,
        doc: Document,
        raw_content: str = "",
        options: dict[str, Any] | None = None,
    ) -> Document:
        """同步执行文档入库，返回更新后的 Document（status=active 或 failed）。"""
        try:
            doc.status = DocStatus.processing
            doc.updated_at = datetime.now(timezone.utc)

            self._run_create(doc, raw_content, options or {})

            doc.status = DocStatus.active
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                self._document_repo.update(doc)
        except Exception as exc:
            logger.exception("文档 %s 入库失败", doc.doc_id)
            doc.status = DocStatus.failed
            doc.error_message = str(exc)[:2000]
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                try:
                    self._document_repo.update(doc)
                except Exception:
                    logger.exception("持久化文档失败状态时出错")
        return doc

    def _run_create(
        self,
        doc: Document,
        raw_content: str,
        options: dict[str, Any],
    ) -> None:
        """文档入库流程（解析 → 递归 → 抽取 → 索引）。"""
        if self._document_repo and self._document_repo.get(doc.doc_id) is None:
            self._document_repo.create(doc)

        # 1. 解析文档
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

        # 2. 递归加载嵌入子文档
        loader = RecursiveLoader(
            parser_fn=parser.parse,
            max_depth=options.get("max_depth"),
            max_elements=options.get("max_elements_per_doc"),
        )
        all_docs, embedded_elements = loader.load_embedded(doc, elements)
        for d in all_docs:
            if self._document_repo:
                self._document_repo.create(d)
        elements.extend(embedded_elements)

        if self._element_repo and elements:
            self._element_repo.create_batch(elements)

        # 3. 语义抽取
        chunks = self._extractor.extract(
            elements, assets, doc.doc_id, doc.category
        )
        self._attach_unreferenced_video_assets(chunks, assets)

        # 4. 索引
        if chunks:
            self._index_chunks(chunks)

        # 5. 自动生成评测数据（后台异步）
        if settings.auto_eval_enabled and chunks:
            self._trigger_eval_data_generation(doc, chunks)

    def _prepare_assets(self, assets: list[Asset]) -> list[Asset]:
        """应用资源数量限制，并处理图片资源生命周期。超限资源标记为 failed。"""
        for idx, asset in enumerate(assets):
            if idx >= settings.max_assets_per_doc:
                asset.status = AssetStatus.failed
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
        """生成 embedding，写入 dense/sparse 索引，并持久化知识块。"""
        if self._chunk_store and persist_chunks:
            for chunk in chunks:
                self._chunk_store.put(chunk)

        for batch in _batched(chunks, settings.embedding_batch_size):
            texts = [chunk.content for chunk in batch]
            vectors = embedding_client.embed_text(texts)
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"embedding count mismatch: chunks={len(batch)}, vectors={len(vectors)}"
                )

            vector_items = []
            bm25_items = []
            for chunk, vector in zip(batch, vectors):
                metadata = self._chunk_index_metadata(chunk)
                vector_items.append((chunk.chunk_id, vector, metadata))
                bm25_items.append((chunk.chunk_id, chunk.content, metadata))

            zipped_items = list(zip(batch, vector_items, bm25_items))
            for write_batch in _batched(zipped_items, settings.index_upsert_batch_size):
                self._vector_index.add_batch([item[1] for item in write_batch])
                self._bm25_index.add_batch([item[2] for item in write_batch])

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
