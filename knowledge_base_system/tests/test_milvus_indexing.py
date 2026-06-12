import os

import pytest

from indexing.milvus_sparse import MilvusSparseIndex
from indexing.milvus_vector import DENSE_DIM, MilvusCollectionManager, MilvusVectorIndex


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MILVUS_TESTS") != "1",
    reason="需要 Docker Milvus；设置 RUN_MILVUS_TESTS=1 后运行",
)


class TestMilvusIndexing:
    def test_vector_add_search_delete(self):
        manager = MilvusCollectionManager(collection_name="kb_test_chunks")
        vector_index = MilvusVectorIndex(manager)
        vector_index.ensure_collection()

        chunk_id = "chunk_milvus_vector_test"
        vector = [0.0] * DENSE_DIM
        vector[0] = 1.0
        vector_index.add(chunk_id, vector, metadata={"category": "测试", "content": "向量测试"})

        results = vector_index.search(vector, top_k=5, category="测试")
        assert any(cid == chunk_id for cid, _ in results)

        vector_index.delete(chunk_id)
        assert all(cid != chunk_id for cid, _ in vector_index.search(vector, top_k=5))
        manager.disconnect()

    def test_sparse_add_search_delete(self):
        manager = MilvusCollectionManager(collection_name="kb_test_chunks")
        sparse_index = MilvusSparseIndex(manager)

        chunk_id = "chunk_milvus_sparse_test"
        sparse_index.add(chunk_id, "Milvus 稀疏向量 检索 测试", metadata={"category": "测试"})

        results = sparse_index.search("稀疏向量", top_k=5, category="测试")
        assert any(cid == chunk_id for cid, _ in results)

        sparse_index.delete(chunk_id)
        assert all(cid != chunk_id for cid, _ in sparse_index.search("稀疏向量", top_k=5))
        manager.disconnect()
