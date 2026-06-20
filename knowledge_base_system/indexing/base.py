from abc import ABC, abstractmethod


class VectorIndex(ABC):
    """Abstract vector index for similarity search."""

    @abstractmethod
    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None: ...

    def add_batch(
        self,
        items: list[tuple[str, list[float], dict | None]],
    ) -> None:
        """批量添加向量；默认逐条写入，具体实现可覆盖为真正批量写入。"""
        for chunk_id, vector, metadata in items:
            self.add(chunk_id, vector, metadata)

    @abstractmethod
    def delete(self, chunk_id: str) -> None: ...

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int,
        category: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return list of (chunk_id, score) sorted by score descending."""


class BM25Index(ABC):
    """Abstract BM25 keyword index."""

    @abstractmethod
    def add(
        self,
        chunk_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None: ...

    def add_batch(
        self,
        items: list[tuple[str, str, dict | None]],
    ) -> None:
        """批量添加文本索引；默认逐条写入，具体实现可覆盖为真正批量写入。"""
        for chunk_id, text, metadata in items:
            self.add(chunk_id, text, metadata)

    @abstractmethod
    def delete(self, chunk_id: str) -> None: ...

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int,
        category: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return list of (chunk_id, score) sorted by score descending."""
