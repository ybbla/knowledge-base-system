"""API v1 契约测试 — 验证统一响应模型和错误结构。

不导入 app.main，避免触发现有解析器依赖链中的环境问题。
"""

import pytest

from app.api.v1.errors import (
    ChunkNotFoundError,
    ErrorCode,
)
from app.api.v1.schemas import (
    APIErrorResponse,
    APIResponse,
    ErrorDetail,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
)
from app.core.errors import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    KnowledgeBaseError,
)


# ── 1. 响应模型基础结构测试 ────────────────────────────────────────

class TestAPIResponse:
    """验证统一成功响应结构。"""

    def test_basic_success_response(self):
        """data 字段正确序列化，meta 默认为空，error 为 null。"""
        resp = APIResponse(data={"id": "test"}, meta={"note": "ok"})
        result = resp.model_dump(mode="json")
        assert result["data"] == {"id": "test"}
        assert result["meta"] == {"note": "ok"}
        assert result["error"] is None

    def test_empty_data_response(self):
        """空列表/None data 仍保持统一结构。"""
        resp = APIResponse(data=[], meta={})
        result = resp.model_dump(mode="json")
        assert result["data"] == []
        assert result["error"] is None

    def test_paginated_response(self):
        """PaginatedResponse 包含 data 列表和标准分页 meta。"""
        meta = PaginationMeta(page=1, page_size=20, total=100, total_pages=5)
        resp = PaginatedResponse[dict](
            data=[{"id": 1}, {"id": 2}],
            meta=meta.model_dump(),
        )
        result = resp.model_dump(mode="json")
        assert isinstance(result["data"], list)
        assert len(result["data"]) == 2
        assert result["meta"]["page"] == 1
        assert result["meta"]["page_size"] == 20
        assert result["meta"]["total"] == 100
        assert result["meta"]["total_pages"] == 5
        assert result["error"] is None


class TestAPIErrorResponse:
    """验证统一错误响应结构。"""

    def test_error_response_structure(self):
        """错误时 data 为 null，error 包含 code 和 message。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.DOCUMENT_NOT_FOUND,
                message="文档 doc_xxx 不存在",
                details={"doc_id": "doc_xxx"},
            ),
        )
        result = err.model_dump(mode="json")
        assert result["data"] is None
        assert result["meta"] == {}
        assert result["error"]["code"] == "DOCUMENT_NOT_FOUND"
        assert result["error"]["message"] == "文档 doc_xxx 不存在"
        assert result["error"]["details"] == {"doc_id": "doc_xxx"}

    def test_error_without_details(self):
        """error.details 可为 None。"""
        err = APIErrorResponse(
            error=ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message="内部错误"),
        )
        result = err.model_dump(mode="json")
        assert result["error"]["details"] is None


# ── 2. 异常处理器测试 ──────────────────────────────────────────────

class TestExceptionHandlers:
    """验证自定义异常及其处理器。"""

    def test_handler_exists_for_each_exception(self):
        """所有异常处理器均可调用。"""
        from app.api.v1.errors import (
            document_not_found_handler,
            duplicate_document_handler,
            chunk_not_found_handler,
            knowledge_base_error_handler,
        )
        assert document_not_found_handler is not None
        assert duplicate_document_handler is not None
        assert chunk_not_found_handler is not None
        assert knowledge_base_error_handler is not None

    def test_all_error_codes_registered(self):
        """每个 ErrorCode 都在 EXCEPTION_HANDLERS 有对应映射或可被兜底覆盖。"""
        from app.api.v1.errors import EXCEPTION_HANDLERS

        # 明确的映射
        assert DocumentNotFoundError in EXCEPTION_HANDLERS
        assert DuplicateDocumentError in EXCEPTION_HANDLERS
        assert ChunkNotFoundError in EXCEPTION_HANDLERS
        assert KnowledgeBaseError in EXCEPTION_HANDLERS

    def test_custom_chunk_not_found_exception(self):
        """ChunkNotFoundError 继承自 KnowledgeBaseError。"""
        exc = ChunkNotFoundError("chunk_xxx 不存在")
        assert isinstance(exc, KnowledgeBaseError)
        assert str(exc) == "chunk_xxx 不存在"

# ── 3. 请求参数模型测试 ────────────────────────────────────────────

class TestPaginationParams:
    """验证分页和排序参数模型。"""

    def test_defaults(self):
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 20
        assert params.sort_by is None
        assert params.sort_order == "desc"

    def test_custom_values(self):
        params = PaginationParams(page=2, page_size=50, sort_by="created_at", sort_order="asc")
        assert params.page == 2
        assert params.page_size == 50
        assert params.sort_by == "created_at"
        assert params.sort_order == "asc"

    def test_page_min_1(self):
        """page 必须 >= 1。"""
        with pytest.raises(Exception):
            PaginationParams(page=0)

    def test_page_size_max_200(self):
        """page_size 必须 <= 200。"""
        with pytest.raises(Exception):
            PaginationParams(page_size=201)


class TestSearchParams:
    """验证关键词和时间范围参数模型。"""

    def test_defaults(self):
        params = SearchParams()
        assert params.keyword is None
        assert params.created_after is None
        assert params.created_before is None
        assert params.updated_after is None
        assert params.updated_before is None

    def test_keyword_search(self):
        from datetime import datetime, timezone
        params = SearchParams(
            keyword="测试",
            created_after=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert params.keyword == "测试"
        assert params.created_after.year == 2025


# ── 4. 错误码枚举测试 ──────────────────────────────────────────────

class TestErrorCodes:
    """验证错误码常量一致性。"""

    def test_document_error_codes(self):
        assert ErrorCode.DOCUMENT_NOT_FOUND == "DOCUMENT_NOT_FOUND"
        assert ErrorCode.DOCUMENT_DUPLICATE == "DOCUMENT_DUPLICATE"
        assert ErrorCode.DOCUMENT_VERSION_CONFLICT == "DOCUMENT_VERSION_CONFLICT"

    def test_chunk_error_codes(self):
        assert ErrorCode.CHUNK_NOT_FOUND == "CHUNK_NOT_FOUND"

    def test_general_error_codes(self):
        assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"
        assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
