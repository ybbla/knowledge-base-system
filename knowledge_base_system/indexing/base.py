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
