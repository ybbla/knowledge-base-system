"""Milvus 2.5 原生 BM25 索引实现。

基于 Milvus Function(FunctionType.BM25) + chinese 分析器，
稀疏向量由 Milvus 内置 Tantivy 引擎自动生成，无需应用层分词或 IDF 统计。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from indexing.base import BM25Index
from indexing.milvus_vector import (
    MilvusCollectionManager,
    _escape_expr_value,
    _json_dumps,
)

logger = logging.getLogger(__name__)

JSON_TEXT_FIELDS = {"source_refs", "asset_refs", "metadata"}


class MilvusBM25Index(BM25Index):
    """基于 Milvus 原生 BM25 Function 的 BM25Index 实现。

    稀疏向量由 BM25 Function 从 content 字段自动生成，
    检索时直接传入原始查询文本，无需手动编码。
    """

    def __init__(self, manager: MilvusCollectionManager | None = None) -> None:
        self._manager = manager or MilvusCollectionManager()

    @property
    def manager(self) -> MilvusCollectionManager:
        return self._manager

    def add(
        self,
        chunk_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        self.add_batch([(chunk_id, text, metadata)])

    def add_batch(
        self,
        items: list[tuple[str, str, dict | None]],
    ) -> None:
        """批量写入 content + 标量字段，BM25 Function 自动生成 sparse_vector。"""
        if not items:
            return

        self._manager.ensure_collection()
        fields_items = []
        for chunk_id, text, metadata in items:
            meta = metadata or {}
            fields = {
                "doc_id": str(meta.get("doc_id", "")),
                "title": str(meta.get("title", ""))[:512],
                "content": text[:65535],
                "category": str(meta.get("category", "")),
                "knowledge_type": str(meta.get("knowledge_type", "")),
                "status": str(meta.get("status", "active")),
                "created_at": meta.get("created_at", 0),
                "updated_at": meta.get("updated_at", 0),
            }
            for key in JSON_TEXT_FIELDS:
                fields[key] = _json_dumps(meta.get(key, {} if key == "metadata" else []))
            fields_items.append((chunk_id, fields))
        self._manager.upsert_fields_batch(fields_items)

    def delete(self, chunk_id: str) -> None:
        self._manager.delete(chunk_id)

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        """更新标量字段（如 status），不重建稀疏向量。"""
        self._manager.upsert_fields(chunk_id, fields)

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """批量更新标量字段。"""
        self._manager.upsert_fields_batch(items)

    def search(
        self,
        query: str,
        top_k: int,
        category: str | None = None,
        knowledge_type: str | None = None,
    ) -> list[tuple[str, float]]:
        """BM25 关键词检索，直接传入原始查询文本。"""
        self._manager.ensure_collection()
        collection = self._manager.collection
        if collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        expr_parts = ['status == "active"']
        if category is not None:
            expr_parts.append(f'category == "{_escape_expr_value(category)}"')
        if knowledge_type is not None:
            expr_parts.append(f'knowledge_type == "{_escape_expr_value(knowledge_type)}"')
        expr = " && ".join(expr_parts)

        results = collection.search(
            data=[query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {"ef": settings.milvus_sparse_ef}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )
        if not results:
            return []
        return [(hit.entity.get("chunk_id"), float(hit.score)) for hit in results[0]]
