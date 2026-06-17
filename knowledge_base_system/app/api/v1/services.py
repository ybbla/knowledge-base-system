"""v1 API 支撑服务 — 索引元数据同步和知识块重建索引。

这些服务作为 API 层与底层索引/仓储之间的中继，确保:
- 知识块状态变更后同步到向量索引和 BM25 索引元数据
- 内容变更后触发或排队重建索引（复用现有 embedding + 索引写入流程）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.models import ChunkIndexStatus, KnowledgeChunk

if TYPE_CHECKING:
    from app.db.repositories.chunks import PgChunkStore
    from indexing.base import BM25Index, VectorIndex

logger = logging.getLogger(__name__)


# ── 2.5 索引元数据同步服务 ───────────────────────────────────────

def sync_index_metadata(
    chunk: KnowledgeChunk,
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
) -> None:
    """同步单个知识块的元数据到向量索引和 BM25 索引。

    只更新索引中的元数据字段（status、category、knowledge_type），
    不重新生成 embedding 或 BM25 分词。

    参数:
        chunk: 已持久化的知识块
        vector_index: 向量索引实例（内存或 Milvus）
        bm25_index: BM25 索引实例（内存或 Milvus）
    """
    metadata = {
        "status": chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status),
        "category": chunk.category,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else str(chunk.knowledge_type),
    }

    _sync_vector_metadata(chunk.chunk_id, metadata, vector_index)
    _sync_bm25_metadata(chunk.chunk_id, metadata, bm25_index)


def sync_index_metadata_batch(
    chunks: list[KnowledgeChunk],
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
) -> int:
    """批量同步知识块元数据到检索索引。

    返回:
        同步的知识块数量
    """
    if not chunks:
        return 0

    # 批量更新索引中的 status 字段
    chunk_ids = [c.chunk_id for c in chunks]
    status_value = chunks[0].status.value if hasattr(chunks[0].status, "value") else str(chunks[0].status)

    vector_index.update_status_batch(chunk_ids, status_value)
    bm25_index.update_status_batch(chunk_ids, status_value)

    return len(chunks)


def _sync_vector_metadata(chunk_id: str, metadata: dict, vector_index: "VectorIndex") -> None:
    """在向量索引中更新 chunk 的元数据。"""
    # 内存索引：直接更新 _metadata 字典
    if hasattr(vector_index, "_metadata") and isinstance(getattr(vector_index, "_metadata"), dict):
        meta_dict = getattr(vector_index, "_metadata")
        if chunk_id in meta_dict:
            meta_dict[chunk_id].update(metadata)
            return

    # Milvus 索引：使用 update_status_batch
    status = metadata.get("status", "active")
    if hasattr(vector_index, "update_status_batch"):
        vector_index.update_status_batch([chunk_id], status)


def _sync_bm25_metadata(chunk_id: str, metadata: dict, bm25_index: "BM25Index") -> None:
    """在 BM25 索引中更新 chunk 的元数据。"""
    # 内存索引
    if hasattr(bm25_index, "_metadata") and isinstance(getattr(bm25_index, "_metadata"), dict):
        meta_dict = getattr(bm25_index, "_metadata")
        if chunk_id in meta_dict:
            meta_dict[chunk_id].update(metadata)
            return

    # Milvus 索引
    status = metadata.get("status", "active")
    if hasattr(bm25_index, "update_status_batch"):
        bm25_index.update_status_batch([chunk_id], status)


# ── 2.6 知识块重建索引服务 ─────────────────────────────────────

def reindex_chunk(
    chunk: KnowledgeChunk,
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
    embedding_client=None,
) -> None:
    """对单个知识块重建向量索引和 BM25 索引。

    复用现有 embedding、向量索引和 BM25 写入流程：
    1. 删除旧索引条目
    2. 重新生成 embedding
    3. 写入向量索引和 BM25 索引

    参数:
        chunk: 需要重建索引的知识块
        vector_index: 向量索引实例
        bm25_index: BM25 索引实例
        embedding_client: embedding 客户端，需要 embed_text 方法
    """
    # 删除旧索引
    vector_index.delete(chunk.chunk_id)
    bm25_index.delete(chunk.chunk_id)

    # 重新生成 embedding（如果提供了客户端）
    if embedding_client is not None and hasattr(embedding_client, "embed_text"):
        try:
            vectors = embedding_client.embed_text([chunk.content])
            if vectors:
                vector = vectors[0]
                vector_index.add(
                    chunk.chunk_id,
                    vector,
                    metadata={
                        "doc_id": chunk.doc_id,
                        "category": chunk.category,
                        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else str(chunk.knowledge_type),
                        "status": chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status),
                        "title_path": chunk.metadata.get("title_path", []),
                        "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
                        "asset_refs": [ref.model_dump(mode="json") for ref in chunk.asset_refs],
                        "metadata": chunk.metadata,
                    },
                )
        except Exception:
            logger.exception("知识块 %s embedding 失败", chunk.chunk_id)
            raise

    # 写入 BM25 索引
    bm25_index.add(
        chunk.chunk_id,
        chunk.content,
        metadata={
            "category": chunk.category,
            "status": chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status),
        },
    )


def reindex_chunks_batch(
    chunks: list[KnowledgeChunk],
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
    embedding_client=None,
    chunk_store: "PgChunkStore | None" = None,
) -> dict[str, list[str]]:
    """批量重建知识块索引。

    参数:
        chunks: 需要重建索引的知识块列表
        vector_index: 向量索引实例
        bm25_index: BM25 索引实例
        embedding_client: embedding 客户端
        chunk_store: 知识块仓储，用于更新索引状态

    返回:
        {"succeeded": [...], "failed": [...]}
    """
    succeeded: list[str] = []
    failed: list[str] = []

    for chunk in chunks:
        try:
            # 更新状态为 indexing
            if chunk_store is not None and hasattr(chunk_store, "update_index_status"):
                chunk_store.update_index_status(
                    [chunk.chunk_id],
                    ChunkIndexStatus.indexing,
                )

            reindex_chunk(chunk, vector_index, bm25_index, embedding_client)

            # 更新状态为 indexed
            if chunk_store is not None and hasattr(chunk_store, "update_index_status"):
                chunk_store.update_index_status(
                    [chunk.chunk_id],
                    ChunkIndexStatus.indexed,
                )

            succeeded.append(chunk.chunk_id)
        except Exception as exc:
            logger.exception("知识块 %s 重建索引失败", chunk.chunk_id)
            if chunk_store is not None and hasattr(chunk_store, "update_index_status"):
                chunk_store.update_index_status(
                    [chunk.chunk_id],
                    ChunkIndexStatus.failed,
                    error=str(exc),
                )
            failed.append(chunk.chunk_id)

    return {"succeeded": succeeded, "failed": failed}
