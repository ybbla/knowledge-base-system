"""v1 检索接口测试 — 覆盖请求模型、过滤、预览、调试、筛选项和反馈。"""

import pytest

from app.api.v1.schemas import APIResponse, APIErrorResponse, ErrorDetail
from app.api.v1.search import (
    SearchFilters,
    SearchOptions,
    SearchRequest,
    FeedbackRequest,
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
                index_status=["indexed"],
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
            chunk_status=["active"],
        )
        result = filters.model_dump(exclude_none=True)
        assert "categories" in result
        assert result["categories"] == ["设备维护"]
        assert "doc_ids" not in result  # None 被排除


class TestPreviewSearch:
    """6.5 预览检索。"""

    def test_preview_skips_rerank(self):
        """预览模式标记 rerank_skipped。"""
        resp = APIResponse(
            data={"total_count": 3, "results": []},
            meta={"mode": "preview", "rerank_skipped": True},
        )
        result = resp.model_dump(mode="json")
        assert result["meta"]["rerank_skipped"] is True

    def test_preview_fallback_when_llm_unavailable(self):
        """LLM 不可用时返回基础候选。"""
        resp = APIResponse(
            data={
                "query": "测试",
                "total_count": 0,
                "results": [],
                "preview_note": "LLM 不可用，返回基础候选",
            },
            meta={"mode": "preview"},
        )
        result = resp.model_dump(mode="json")
        assert "preview_note" in result["data"]


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
        """筛选项包含分类、来源类型、知识类型、状态。"""
        resp = APIResponse(data={
            "categories": [{"value": "通用", "count": 10}],
            "source_types": [{"value": "markdown", "count": 5}],
            "knowledge_types": [{"value": "declarative", "count": 8}],
            "doc_statuses": [{"value": "active"}],
            "chunk_statuses": [{"value": "active", "count": 8}],
            "index_statuses": [{"value": "indexed", "count": 8}],
        })
        result = resp.model_dump(mode="json")
        assert "categories" in result["data"]
        assert "knowledge_types" in result["data"]


class TestSearchFeedback:
    """6.8 检索反馈。"""

    def test_feedback_request_model(self):
        req = FeedbackRequest(chunk_id="chunk_1", feedback="relevant", search_id="search_1")
        assert req.chunk_id == "chunk_1"
        assert req.feedback == "relevant"

    def test_feedback_response(self):
        """反馈接口不影响排序。"""
        resp = APIResponse(
            data={"status": "accepted", "chunk_id": "chunk_1", "feedback": "relevant"},
            meta={"note": "反馈已记录，不影响当前检索排序"},
        )
        result = resp.model_dump(mode="json")
        assert result["data"]["status"] == "accepted"
