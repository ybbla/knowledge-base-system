import numpy as np

from indexing.base import VectorIndex


class MemoryVectorIndex(VectorIndex):
    """In-memory vector index using numpy cosine similarity."""

    def __init__(self) -> None:
        self._chunk_ids: list[str] = []
        self._vectors: list[np.ndarray] = []
        self._metadata: dict[str, dict] = {}

    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        # Remove if already exists
        self.delete(chunk_id)
        self._chunk_ids.append(chunk_id)
        self._vectors.append(np.array(vector, dtype=np.float32))
        self._metadata[chunk_id] = metadata or {}

    def delete(self, chunk_id: str) -> None:
        try:
            idx = self._chunk_ids.index(chunk_id)
            self._chunk_ids.pop(idx)
            self._vectors.pop(idx)
            self._metadata.pop(chunk_id, None)
        except ValueError:
            pass

    def get_metadata(self, chunk_id: str) -> dict:
        return self._metadata.get(chunk_id, {})

    def update_status_batch(self, chunk_ids: list[str], status: str) -> None:
        """批量更新知识块的 status 字段（保留向量和其余元数据）。"""
        for chunk_id in chunk_ids:
            if chunk_id in self._metadata:
                self._metadata[chunk_id]["status"] = status

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        category: str | None = None,
    ) -> list[tuple[str, float]]:
        if not self._vectors:
            return []

        q = np.array(query_vector, dtype=np.float32)
        matrix = np.stack(self._vectors)

        # Cosine similarity
        norms = np.linalg.norm(matrix, axis=1)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        # Avoid division by zero for zero-norm vectors
        safe_norms = np.where(norms == 0, 1.0, norms)
        cosine = np.dot(matrix, q) / (safe_norms * q_norm)

        eligible_indices = [
            i
            for i, chunk_id in enumerate(self._chunk_ids)
            if (
                self._metadata.get(chunk_id, {}).get("status", "active") == "active"
                and (
                    category is None
                    or self._metadata.get(chunk_id, {}).get("category") == category
                )
            )
        ]
        if not eligible_indices:
            return []

        sorted_indices = sorted(
            eligible_indices,
            key=lambda i: float(cosine[i]),
            reverse=True,
        )
        top_indices = sorted_indices[:top_k]

        return [
            (self._chunk_ids[int(i)], float(cosine[i]))
            for i in top_indices
            if float(cosine[i]) > 0
        ]
