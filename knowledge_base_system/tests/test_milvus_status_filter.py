"""Milvus status 过滤测试：schema 字段、search expr、update_status_batch。"""

import pytest

from indexing.milvus_vector import (
    DENSE_DIM,
    MilvusCollectionManager,
    MilvusVectorIndex,
    _default_entity,
)


class TestMilvusSchemaStatus:
    def test_default_entity_has_status(self):
        entity = _default_entity("chunk_test")
        assert entity["status"] == "active"

    def test_build_fields_includes_status(self):
        vector = [0.1] * DENSE_DIM
        metadata = {"doc_id": "doc_x", "content": "test", "category": "通用"}
        fields = MilvusVectorIndex._build_fields(vector, metadata)
        assert fields["status"] == "active"

    def test_build_fields_respects_status_in_metadata(self):
        vector = [0.1] * DENSE_DIM
        metadata = {"doc_id": "doc_x", "content": "test", "status": "superseded"}
        fields = MilvusVectorIndex._build_fields(vector, metadata)
        assert fields["status"] == "superseded"


class TestSearchExprStatusFilter:
    """验证 search expr 正确叠加 status 过滤。"""

    def test_vector_search_expr_no_category(self, monkeypatch):
        """无 category 过滤时 expr 应为 status == 'active'"""
        from indexing import milvus_vector as mv

        captured: list = []

        class _FakeCollection:
            def search(self, data, anns_field, param, limit, expr, output_fields):
                captured.append(expr)
                return []

        _fake_mgr = MilvusCollectionManager.__new__(MilvusCollectionManager)
        _fake_mgr.collection = _FakeCollection()

        monkeypatch.setattr(mv, "_escape_expr_value", lambda v: v)

        index = MilvusVectorIndex(_fake_mgr)
        index.search([0.1] * DENSE_DIM, top_k=5)

        assert len(captured) >= 1
        assert "active" in captured[0]

    def test_vector_search_expr_with_category(self, monkeypatch):
        from indexing import milvus_vector as mv

        captured: list = []

        class _FakeCollection:
            def search(self, data, anns_field, param, limit, expr, output_fields):
                captured.append(expr)
                return []

        _fake_mgr = MilvusCollectionManager.__new__(MilvusCollectionManager)
        _fake_mgr.collection = _FakeCollection()

        monkeypatch.setattr(mv, "_escape_expr_value", lambda v: v)

        index = MilvusVectorIndex(_fake_mgr)
        index.search([0.1] * DENSE_DIM, top_k=5, category="产品使用")

        assert len(captured) >= 1
        expr = captured[0]
        assert "active" in expr
        assert "产品使用" in expr
        assert "&&" in expr


class TestUpdateStatusBatch:
    def test_empty_list_noop(self):
        """空列表不报错"""
        mgr = MilvusCollectionManager.__new__(MilvusCollectionManager)
        mgr.collection = None
        # 应该直接返回，不抛异常
        mgr.update_status_batch([], "superseded")
        # 空列表情况下不会进入 query 逻辑
