import json
import logging
import time
from typing import Any

from app.core.config import settings
from indexing.base import VectorIndex

logger = logging.getLogger(__name__)

DENSE_DIM = 1024
JSON_TEXT_FIELDS = {"source_refs", "asset_refs", "metadata"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _escape_expr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _default_entity(chunk_id: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": "",
        "title": "",
        "content": "",
        "dense_vector": [0.0] * DENSE_DIM,
        "category": "",
        "knowledge_type": "",
        "status": "active",
        "source_refs": "[]",
        "asset_refs": "[]",
        "metadata": "{}",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }


class MilvusCollectionManager:
    """统一管理 Milvus 连接、Collection 创建与 upsert 合并。"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
        nlist: int | None = None,
    ) -> None:
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = collection_name or settings.milvus_collection
        self.nlist = nlist or settings.milvus_nlist
        self.alias = f"kb_{self.collection_name}"
        self.collection: Any | None = None
        self._cache: dict[str, dict[str, Any]] = {}

    def connect(self) -> None:
        try:
            from pymilvus import connections
        except ImportError as exc:
            raise RuntimeError("pymilvus is not installed") from exc

        connections.connect(alias=self.alias, host=self.host, port=str(self.port))

    def ensure_collection(self) -> None:
        self.connect()
        from pymilvus import (Collection, CollectionSchema, DataType, FieldSchema,
                              Function, FunctionType, utility)

        if utility.has_collection(self.collection_name, using=self.alias):
            self.collection = Collection(self.collection_name, using=self.alias)
            # ── Schema 迁移检测：不含 title 字段或 sparse_vector 索引非 BM25 则重建 ──
            existing_fields = {f.name for f in self.collection.schema.fields}
            sparse_has_bm25 = False
            for idx in getattr(self.collection, "indexes", []) or []:
                if getattr(idx, "field_name", "") == "sparse_vector":
                    if getattr(idx, "params", {}).get("metric_type") == "BM25":
                        sparse_has_bm25 = True
                    break
            if "status" not in existing_fields or not sparse_has_bm25 or "title" not in existing_fields:
                logger.warning(
                    "Milvus Collection '%s' schema 不兼容（缺少 status/BM25/title），自动重建...",
                    self.collection_name,
                )
                utility.drop_collection(self.collection_name, using=self.alias)
                self.collection = None
            else:
                self.ensure_sparse_index()
                self.collection.load()
                return

        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=128,
            ),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params={"type": "chinese"},
            ),
            FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=DENSE_DIM),
            FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="knowledge_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="source_refs", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="asset_refs", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="created_at", dtype=DataType.INT64),
            FieldSchema(name="updated_at", dtype=DataType.INT64),
        ]
        # BM25 Function：content 自动生成 sparse_vector
        bm25_func = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names="sparse_vector",
        )
        schema = CollectionSchema(
            fields,
            description="知识库知识块混合检索索引（HNSW + BM25）",
            functions=[bm25_func],
        )
        self.collection = Collection(
            self.collection_name,
            schema=schema,
            using=self.alias,
        )
        self.collection.create_index(
            "dense_vector",
            {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {
                    "M": settings.milvus_hnsw_M,
                    "efConstruction": settings.milvus_hnsw_ef_construction,
                },
            },
        )
        self.ensure_sparse_index()
        self.collection.load()

    def ensure_sparse_index(self) -> None:
        if self.collection is None:
            return
        for index in getattr(self.collection, "indexes", []) or []:
            if getattr(index, "field_name", "") == "sparse_vector":
                return
        self.collection.create_index(
            "sparse_vector",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {},
            },
        )

    def disconnect(self) -> None:
        """断开 Milvus 连接（使用 remove_connection 替代已弃用的 disconnect）。"""
        try:
            from pymilvus import connections

            connections.remove_connection(self.alias)
        except Exception:
            logger.exception("断开 Milvus 连接失败")

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        self.upsert_fields_batch([(chunk_id, fields)])

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        if not items:
            return
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        # sparse_vector 是 BM25 Function 自动生成的输出字段，不能手动写入
        _FUNCTION_OUTPUT_FIELDS = {"sparse_vector"}

        entities = []
        for chunk_id, fields in items:
            entity = dict(self._cache.get(chunk_id) or _default_entity(chunk_id))
            entity.update(fields)
            # 移除 Function 输出字段——它们由 Milvus 自动生成
            for f in _FUNCTION_OUTPUT_FIELDS:
                entity.pop(f, None)
            self._cache[chunk_id] = entity
            entities.append(entity)
        self.collection.upsert(entities)
        self.collection.flush()

    def delete(self, chunk_id: str) -> None:
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")
        self._cache.pop(chunk_id, None)
        self.collection.delete(expr=f'chunk_id == "{_escape_expr_value(chunk_id)}"')
        self.collection.flush()


class MilvusVectorIndex(VectorIndex):
    """基于 Milvus 的 dense vector 索引实现。"""

    def __init__(self, manager: MilvusCollectionManager | None = None) -> None:
        self._manager = manager or MilvusCollectionManager()

    @property
    def manager(self) -> MilvusCollectionManager:
        return self._manager

    def connect(self) -> None:
        self._manager.connect()

    def ensure_collection(self) -> None:
        self._manager.ensure_collection()

    def disconnect(self) -> None:
        self._manager.disconnect()

    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        self.add_batch([(chunk_id, vector, metadata)])

    def add_batch(
        self,
        items: list[tuple[str, list[float], dict | None]],
    ) -> None:
        fields_items = [
            (chunk_id, self._build_fields(vector, metadata))
            for chunk_id, vector, metadata in items
        ]
        self._manager.upsert_fields_batch(fields_items)

    @staticmethod
    def _build_fields(
        vector: list[float],
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        if len(vector) != DENSE_DIM:
            raise ValueError(f"dense vector dimension must be {DENSE_DIM}")

        fields = {
            "dense_vector": [float(v) for v in vector],
            "doc_id": str(metadata.get("doc_id", "")),
            "title": str(metadata.get("title", ""))[:512],
            "content": str(metadata.get("content", ""))[:65535],
            "category": str(metadata.get("category", "")),
            "knowledge_type": str(metadata.get("knowledge_type", "")),
            "status": str(metadata.get("status", "active")),
            "created_at": metadata.get("created_at", int(time.time())),
            "updated_at": metadata.get("updated_at", int(time.time())),
        }
        for key in JSON_TEXT_FIELDS:
            fields[key] = _json_dumps(metadata.get(key, {} if key == "metadata" else []))
        return fields

    def delete(self, chunk_id: str) -> None:
        self._manager.delete(chunk_id)

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        """更新 Milvus 中知识块的标量字段。"""
        self._manager.upsert_fields(chunk_id, fields)

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """批量更新 Milvus 中标量字段。"""
        self._manager.upsert_fields_batch(items)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        category: str | None = None,
        knowledge_type: str | None = None,
    ) -> list[tuple[str, float]]:
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
            data=[[float(v) for v in query_vector]],
            anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {"ef": settings.milvus_hnsw_ef}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )
        if not results:
            return []
        return [(hit.entity.get("chunk_id"), float(hit.score)) for hit in results[0]]
