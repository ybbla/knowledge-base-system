import logging
import math
from collections import Counter
from typing import Any

try:
    import jieba_fast as jieba
except ImportError:
    import jieba

from app.core.config import settings
from indexing.base import BM25Index
from indexing.milvus_vector import (
    MilvusCollectionManager,
    _escape_expr_value,
    _json_dumps,
)

logger = logging.getLogger(__name__)


class MilvusSparseIndex(BM25Index):
    """基于 jieba + TF-IDF 稀疏向量的 Milvus BM25 近似索引。"""

    def __init__(
        self,
        manager: MilvusCollectionManager | None = None,
        session_factory: Any = None,
        max_vocab: int | None = None,
    ) -> None:
        self._manager = manager or MilvusCollectionManager()
        self._session_factory = session_factory
        self._max_vocab = max_vocab or settings.milvus_sparse_max_vocab
        self._token_df: dict[str, int] = {}
        self._token_to_id: dict[str, int] = {}
        self._chunk_tokens: dict[str, set[str]] = {}
        self._total_docs = 0
        self._loaded = False

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
        if not items:
            return

        self._load_idf_stats()
        tokenized_items = [
            (chunk_id, text, metadata or {}, self._tokenize(text))
            for chunk_id, text, metadata in items
        ]

        for chunk_id, _text, _metadata, tokens in tokenized_items:
            unique_tokens = set(tokens)
            old_tokens = self._chunk_tokens.get(chunk_id, set())

            if not old_tokens:
                self._total_docs += 1
            for token in old_tokens - unique_tokens:
                self._token_df[token] = max(0, self._token_df.get(token, 0) - 1)
            for token in unique_tokens - old_tokens:
                self._token_df[token] = self._token_df.get(token, 0) + 1
            self._chunk_tokens[chunk_id] = unique_tokens
        self._rebuild_vocab()

        fields_items = []
        for chunk_id, text, metadata, tokens in tokenized_items:
            fields_items.append(
                (
                    chunk_id,
                    {
                        "sparse_vector": self._encode(tokens),
                        "content": text[:65535],
                        "doc_id": str(metadata.get("doc_id", "")),
                        "category": str(metadata.get("category", "")),
                        "knowledge_type": str(metadata.get("knowledge_type", "")),
                        "status": str(metadata.get("status", "active")),
                        "title_path": _json_dumps(metadata.get("title_path", [])),
                        "source_refs": _json_dumps(metadata.get("source_refs", [])),
                        "asset_refs": _json_dumps(metadata.get("asset_refs", [])),
                        "metadata": _json_dumps(metadata.get("metadata", {})),
                    },
                )
            )
        self._manager.ensure_sparse_index()
        self._manager.upsert_fields_batch(fields_items)
        self._persist_idf_stats()

    def delete(self, chunk_id: str) -> None:
        self._load_idf_stats()
        old_tokens = self._chunk_tokens.pop(chunk_id, set())
        if old_tokens:
            self._total_docs = max(0, self._total_docs - 1)
            for token in old_tokens:
                self._token_df[token] = max(0, self._token_df.get(token, 0) - 1)
            self._rebuild_vocab()
            self._persist_idf_stats()
        self._manager.delete(chunk_id)

    def update_status_batch(self, chunk_ids: list[str], status: str) -> None:
        """将一批知识块的 status 更新为指定值（保留原有向量和元数据）。"""
        self._manager.update_status_batch(chunk_ids, status)

    def search(
        self,
        query: str,
        top_k: int,
        category: str | None = None,
    ) -> list[tuple[str, float]]:
        self._load_idf_stats()
        self._manager.ensure_collection()
        collection = self._manager.collection
        if collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        sparse_vector = self._encode(self._tokenize(query))
        if not sparse_vector:
            return []

        expr = 'status == "active"'
        if category is not None:
            expr = f'(category == "{_escape_expr_value(category)}") && (status == "active")'

        results = collection.search(
            data=[sparse_vector],
            anns_field="sparse_vector",
            param={"metric_type": "IP", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )
        if not results:
            return []
        return [(hit.entity.get("chunk_id"), float(hit.score)) for hit in results[0]]

    def encode_query(self, query: str) -> dict[int, float]:
        self._load_idf_stats()
        return self._encode(self._tokenize(query))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.strip() for token in jieba.cut(text.lower()) if token.strip()]

    def _encode(self, tokens: list[str]) -> dict[int, float]:
        tf = Counter(tokens)
        sparse: dict[int, float] = {}
        for token, count in tf.items():
            token_id = self._token_to_id.get(token)
            if token_id is None:
                continue
            df = max(1, self._token_df.get(token, 1))
            idf = math.log((self._total_docs + 1) / df) + 1.0
            sparse[token_id] = float(count) * idf
        return sparse

    def _rebuild_vocab(self) -> None:
        ranked = sorted(
            ((token, df) for token, df in self._token_df.items() if df > 0),
            key=lambda item: (-item[1], item[0]),
        )[: self._max_vocab]
        self._token_df = dict(ranked)
        self._token_to_id = {token: idx for idx, (token, _) in enumerate(ranked)}

    def _load_idf_stats(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._session_factory is None:
            return
        try:
            from app.db.models import DbIdfStat

            with self._session_factory() as session:
                rows = session.query(DbIdfStat).all()
                self._token_df = {row.token: row.df for row in rows}
                self._token_to_id = {row.token: row.token_id for row in rows}
                self._total_docs = max((row.total_docs for row in rows), default=0)
        except Exception:
            logger.exception("加载 IDF 统计失败，使用内存状态继续")

    def _persist_idf_stats(self) -> None:
        if self._session_factory is None:
            return
        try:
            from app.db.models import DbIdfStat

            with self._session_factory() as session:
                if self._token_to_id:
                    session.query(DbIdfStat).filter(
                        ~DbIdfStat.token.in_(list(self._token_to_id.keys()))
                    ).delete(synchronize_session=False)
                for token, token_id in self._token_to_id.items():
                    session.merge(
                        DbIdfStat(
                            token=token,
                            token_id=token_id,
                            df=self._token_df.get(token, 0),
                            total_docs=self._total_docs,
                        )
                    )
                session.commit()
        except Exception:
            logger.exception("持久化 IDF 统计失败")
