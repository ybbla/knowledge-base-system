import jieba
from rank_bm25 import BM25Okapi

from indexing.base import BM25Index


class MemoryBM25Index(BM25Index):
    """In-memory BM25 index with jieba Chinese tokenization."""

    def __init__(self) -> None:
        self._chunk_ids: list[str] = []
        self._corpus: list[list[str]] = []
        self._metadata: dict[str, dict] = {}
        self._bm25: BM25Okapi | None = None
        self._dirty = False

    def add(
        self,
        chunk_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        self.delete(chunk_id)
        tokens = self._tokenize(text)
        self._chunk_ids.append(chunk_id)
        self._corpus.append(tokens)
        self._metadata[chunk_id] = metadata or {}
        self._dirty = True

    def delete(self, chunk_id: str) -> None:
        try:
            idx = self._chunk_ids.index(chunk_id)
            self._chunk_ids.pop(idx)
            self._corpus.pop(idx)
            self._metadata.pop(chunk_id, None)
            self._dirty = True
        except ValueError:
            pass

    def search(
        self,
        query: str,
        top_k: int,
        category: str | None = None,
    ) -> list[tuple[str, float]]:
        if not self._corpus:
            return []

        if self._dirty or self._bm25 is None:
            self._bm25 = BM25Okapi(self._corpus)
            self._dirty = False

        assert self._bm25 is not None
        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)

        eligible_indices = [
            i
            for i, chunk_id in enumerate(self._chunk_ids)
            if category is None
            or self._metadata.get(chunk_id, {}).get("category") == category
        ]
        sorted_indices = sorted(
            eligible_indices, key=lambda i: scores[i], reverse=True
        )[:top_k]

        return [
            (self._chunk_ids[i], float(scores[i]))
            for i in sorted_indices
            if float(scores[i]) > 0
        ]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # jieba cut for Chinese + lowercase
        tokens = list(jieba.cut(text.lower()))
        # Filter out single-char whitespace tokens
        return [t.strip() for t in tokens if t.strip()]
