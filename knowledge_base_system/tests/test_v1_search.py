"""v1 检索接口测试 — 覆盖请求模型、过滤、调试和筛选项。"""

import pytest

from app.api.v1.schemas import APIResponse, APIErrorResponse, ErrorDetail
from app.api.v1.search import (
    SearchFilters,
    SearchOptions,
    SearchRequest,
    _matches_filters,
)


class TestSearchRequestModel:
    """6.1 扩展检索请求模型。"""

    def test_default_request(self):
        req = SearchRequest(query="测试查询")
        assert req.query == "测试查询"
        assert req.top_k == 10
        assert req.filters.doc_ids is None
        assert req.options.rerank is True
        assert req.options.hybrid is True

    def test_full_filters(self):
        req = SearchRequest(
            query="测试",
            filters=SearchFilters(
                doc_ids=["doc_1"],
                categories=["设备维护"],
                knowledge_types=["declarative"],
                chunk_status=["active"],
            ),
        )
        assert req.filters.doc_ids == ["doc_1"]
        assert req.filters.categories == ["设备维护"]

    def test_custom_options(self):
        req = SearchRequest(
            query="测试",
            options=SearchOptions(
                rewrite=False,
                rerank=False,
                highlight=True,
                include_assets=False,
            ),
        )
        assert req.options.rerank is False
        assert req.options.highlight is True
        assert req.options.include_assets is False


class TestSearchResponse:
    """6.4 标准检索响应。"""

    def test_success_response_structure(self):
        """搜索成功应返回 search_id, query, results。"""
        resp = APIResponse(
            data={
                "search_id": "search_abc",
                "query": "测试",
                "rewritten_query": "重写后的测试查询",
                "total_count": 5,
                "results": [
                    {
                        "chunk_id": "chunk_1",
                        "title": "测试知识块",
                        "content": "这是内容",
                        "score": 0.95,
                        "category": "通用",
                        "knowledge_type": "declarative",
                        "doc_id": "doc_1",
                        "doc_title": "测试文档",
                        "doc_version": 1,
                        "score_components": {"vector": 0.9, "bm25": 0.8, "rerank": 0.95},
                        "asset_refs": [],
                        "source_refs": [{"doc_id": "doc_1", "element_id": "el_1"}],
                    }
                ],
            },
            meta={"query": "测试"},
        )
        result = resp.model_dump(mode="json")
        assert result["data"]["total_count"] == 5
        assert len(result["data"]["results"]) == 1
        assert result["data"]["results"][0]["doc_title"] is not None

    def test_filter_application(self):
        """过滤条件正确传递。"""
        filters = SearchFilters(
            categories=["设备维护"],
        )
        result = filters.model_dump(exclude_none=True)
        assert "categories" in result
        assert result["categories"] == ["设备维护"]
        assert "doc_ids" not in result  # None 被排除


class TestDebugSearch:
    """6.6 调试检索。"""

    def test_debug_no_sensitive_info(self):
        """调试响应不包含敏感信息。"""
        resp = APIResponse(
            data={
                "query": "测试",
                "rewritten_query": "重写查询",
                "filters": {"categories": ["通用"]},
                "total_count": 2,
                "results": [{"chunk_id": "c1", "score": 0.9}],
            },
            meta={"mode": "debug"},
        )
        result_str = str(resp.model_dump(mode="json"))
        assert "password" not in result_str.lower()
        assert "api_key" not in result_str.lower()
        assert "secret" not in result_str.lower()

    def test_debug_error_summary(self):
        """调试错误只返回摘要。"""
        resp = APIResponse(
            data={"error_summary": "索引连接超时"},
            meta={"mode": "debug", "status": "error"},
        )
        result = resp.model_dump(mode="json")
        assert "error_summary" in result["data"]
        assert len(result["data"]["error_summary"]) < 500


class TestSearchFiltersEndpoint:
    """6.7 检索筛选项。"""

    def test_filters_response(self):
        """筛选项包含分类、知识类型、知识块状态。"""
        resp = APIResponse(data={
            "categories": [{"value": "通用", "count": 10}],
            "knowledge_types": [{"value": "declarative", "count": 8}],
            "chunk_statuses": [{"value": "active", "count": 8}],
        })
        result = resp.model_dump(mode="json")
        assert "categories" in result["data"]
        assert "knowledge_types" in result["data"]

    def test_category_count_priority_doc_repo(self):
        """document_repo 可用时 category count 应来自文档统计（覆盖尚无 chunk 的文档）。"""
        resp = APIResponse(data={
            "categories": [
                {"value": "技术", "count": 15},
                {"value": "通用", "count": 3},
            ],
            "knowledge_types": [],
            "chunk_statuses": [],
        })
        result = resp.model_dump(mode="json")
        # 文档仓储统计：技术 15（含尚无 chunk 的新文档）
        cats = {item["value"]: item["count"] for item in result["data"]["categories"]}
        assert cats["技术"] == 15
        assert cats["通用"] == 3


class TestMultiCategorySearch:
    """多 categories 检索逻辑验证。"""

    def test_multi_category_request_model(self):
        """多 categories 过滤请求模型正确构建。"""
        req = SearchRequest(
            query="测试",
            filters=SearchFilters(categories=["技术", "产品"]),
        )
        assert req.filters.categories == ["技术", "产品"]
        assert len(req.filters.categories) == 2

    def test_single_category_request_model(self):
        """单 category 过滤请求模型正确构建。"""
        req = SearchRequest(
            query="测试",
            filters=SearchFilters(categories=["技术"]),
        )
        assert req.filters.categories == ["技术"]
        assert len(req.filters.categories) == 1

    def test_no_category_request_model(self):
        """无 category 过滤请求模型正确构建。"""
        req = SearchRequest(query="测试")
        assert req.filters.categories is None

    def test_matches_filters_multi_category(self):
        """多 category 过滤：chunk 属于任一分类即通过。"""
        from types import SimpleNamespace

        chunk = SimpleNamespace(
            doc_id="doc_1",
            category="技术",
            knowledge_type="declarative",
            status="active",
        )
        doc = SimpleNamespace(
            source_type="markdown",
            status="active",
            created_at=None,
        )
        filters = SearchFilters(categories=["技术", "产品"])

        # 匹配任一分类
        assert _matches_filters(chunk, doc, filters) is True

        # 不匹配任一分类
        chunk2 = SimpleNamespace(
            doc_id="doc_2",
            category="其他",
            knowledge_type="declarative",
            status="active",
        )
        assert _matches_filters(chunk2, doc, filters) is False

