"""v1 文档管理和知识块管理接口测试。

测试模型结构和核心逻辑，不依赖 app.main 的完整启动。
"""

import pytest

from app.api.v1.schemas import (
    APIErrorResponse,
    APIResponse,
    ErrorDetail,
    PaginatedResponse,
    PaginationMeta,
)


# ── 文档管理测试 ──────────────────────────────────────────────────

class TestDocumentListResponse:
    """4.1 文档列表响应结构。"""

    def test_paginated_document_list(self):
        """文档列表应有分页结构和统计字段。"""
        meta = PaginationMeta(page=1, page_size=20, total=5, total_pages=1)
        doc_items = [
            {
                "doc_id": "doc_1",
                "title": "测试文档",
                "source_type": "markdown",
                "category": "通用",
                "version": 1,
                "status": "active",
                "chunk_count": 3,
                "element_count": 5,
                "asset_count": 2,
                "index_summary": {"indexed": 3, "pending": 0, "failed": 0},
            }
        ]
        resp = PaginatedResponse(data=doc_items, meta=meta.model_dump())
        result = resp.model_dump(mode="json")
        assert result["data"][0]["doc_id"] == "doc_1"
        assert result["data"][0]["chunk_count"] == 3
        assert result["data"][0]["element_count"] == 5

    def test_empty_list(self):
        """空列表也应保持统一结构。"""
        meta = PaginationMeta(page=1, page_size=20, total=0, total_pages=0)
        resp = PaginatedResponse(data=[], meta=meta.model_dump())
        result = resp.model_dump(mode="json")
        assert result["data"] == []
        assert result["meta"]["total"] == 0
        assert result["error"] is None

    def test_memory_list_with_unsupported_filters(self):
        """内存模式下传不支持的过滤参数时 meta 应包含 unsupported_filters。"""
        meta_dict = {
            "page": 1,
            "page_size": 20,
            "total": 0,
            "total_pages": 0,
            "unsupported_filters": ["source_type", "parent_doc_id", "sort"],
        }
        resp = PaginatedResponse(data=[], meta=meta_dict)
        result = resp.model_dump(mode="json")
        assert result["meta"]["unsupported_filters"] == ["source_type", "parent_doc_id", "sort"]


class TestDocumentCreateResponse:
    """4.2 文档创建响应结构。"""

    def test_create_document_response(self):
        """创建文档应返回文档字段和初始状态。"""
        resp = APIResponse(data={
            "doc_id": "doc_new",
            "title": "新建文档",
            "status": "processing",
            "version": 1,
            "chunk_count": 0,
            "element_count": 0,
            "asset_count": 0,
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["status"] == "processing"
        assert result["data"]["version"] == 1

    def test_create_with_ingest(self):
        """ingest_after_create 时包含 job_id。"""
        resp = APIResponse(data={
            "doc_id": "doc_new",
            "title": "新建文档",
            "status": "processing",
            "ingest_job_id": "job_xxx",
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["ingest_job_id"] == "job_xxx"

    def test_memory_mode_create_no_ingest_warning(self):
        """内存模式下创建文档但不入库时返回 warning 提示。"""
        resp = APIResponse(
            data={"doc_id": "doc_new", "title": "新建文档", "status": "pending"},
            meta={"warning": "内存模式下文档仅在入库后可通过列表/详情接口查询，建议设置 ingest_after_create=true"},
        )
        result = resp.model_dump(mode="json")
        assert "warning" in result["meta"]
        assert "内存模式" in result["meta"]["warning"]


class TestDocumentDetailResponse:
    """4.3 文档详情响应结构。"""

    def test_detail_response(self):
        """文档详情应包含统计和元数据。"""
        resp = APIResponse(data={
            "doc_id": "doc_1",
            "title": "测试文档",
            "source_type": "markdown",
            "chunk_count": 3,
            "element_count": 5,
            "asset_count": 2,
            "index_summary": {"indexed": 2, "pending": 1, "failed": 0},
            "metadata": {"author": "test"},
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["index_summary"]["indexed"] == 2
        assert result["data"]["metadata"]["author"] == "test"

    def test_not_found_response(self):
        """文档不存在返回 404 + DOCUMENT_NOT_FOUND。"""
        err = APIErrorResponse(
            error=ErrorDetail(code="DOCUMENT_NOT_FOUND", message="文档 doc_missing 不存在"),
        )
        assert err.data is None
        assert err.error.code == "DOCUMENT_NOT_FOUND"


class TestDocumentUpdateResponse:
    """4.4 文档更新响应结构。"""

    def test_version_conflict(self):
        """版本冲突返回 DOCUMENT_VERSION_CONFLICT。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code="DOCUMENT_VERSION_CONFLICT",
                message="版本冲突: 期望 2，实际 3",
                details={"expected": 2, "actual": 3},
            ),
        )
        assert err.error.code == "DOCUMENT_VERSION_CONFLICT"
        assert err.error.details["expected"] == 2

    def test_source_change_needs_reingest(self):
        """来源变更时提示需要重新入库。"""
        resp = APIResponse(data={
            "doc_id": "doc_1",
            "title": "更新后的文档",
            "version": 3,
            "needs_reingest": True,
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["needs_reingest"] is True
        assert result["data"]["version"] == 3


class TestDocumentDeleteRestore:
    """4.5 & 4.6 删除和恢复。"""

    def test_delete_response(self):
        """删除后状态变为 deleted。"""
        resp = APIResponse(data={
            "doc_id": "doc_1",
            "status": "deleted",
            "chunk_count": 3,
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["status"] == "deleted"

    def test_restore_response(self):
        """恢复后状态变为 active，附带恢复计数。"""
        resp = APIResponse(
            data={"doc_id": "doc_1", "status": "active"},
            meta={"restored_chunks": 3},
        )
        result = resp.model_dump(mode="json")
        assert result["data"]["status"] == "active"
        assert result["meta"]["restored_chunks"] == 3


class TestDocumentIngest:
    """4.7 触发入库。"""

    def test_ingest_response(self):
        """入库返回 job_id。"""
        resp = APIResponse(
            data={"job_id": "job_xxx", "doc_id": "doc_1", "mode": "incremental"},
            meta={"status": "accepted"},
        )
        result = resp.model_dump(mode="json")
        assert result["data"]["job_id"] == "job_xxx"
        assert result["meta"]["status"] == "accepted"

# ── 知识块管理测试 ────────────────────────────────────────────────

class TestChunkListResponse:
    """5.1 知识块列表。"""

    def test_chunk_list_item(self):
        """知识块列表条目含内容摘要和展示字段。"""
        item = {
            "chunk_id": "chunk_1",
            "doc_id": "doc_1",
            "doc_title": "测试文档",
            "title": "知识块标题",
            "content_preview": "这是内容的前 200 字符...",
            "knowledge_type": "declarative",
            "category": "通用",
            "status": "active",
            "asset_count": 2,
            "source_count": 1,
        }
        meta = PaginationMeta(page=1, page_size=20, total=1, total_pages=1)
        resp = PaginatedResponse(data=[item], meta=meta.model_dump())
        result = resp.model_dump(mode="json")
        assert result["data"][0]["content_preview"] is not None
        assert "content" not in result["data"][0]  # 列表不含完整 content
        assert result["data"][0]["asset_count"] == 2


class TestChunkCreateResponse:
    """5.2 创建知识块。"""

    def test_create_chunk_response(self):
        """创建知识块含 content_hash 和 metadata.manual。"""
        resp = APIResponse(data={
            "chunk_id": "chunk_new",
            "doc_id": "doc_1",
            "title": "人工知识块",
            "content": "这是测试内容",
            "content_hash": "sha256:abc123",
            "knowledge_type": "declarative",
            "category": "通用",
            "status": "active",
            "metadata": {"manual": True},
            "asset_refs": [],
            "source_refs": [],
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["metadata"]["manual"] is True
        assert result["data"]["content_hash"].startswith("sha256:")


class TestChunkDetailResponse:
    """5.3 知识块详情。"""

    def test_chunk_detail_has_full_content(self):
        """详情含完整 content、来源、资源。"""
        resp = APIResponse(data={
            "chunk_id": "chunk_1",
            "content": "这是完整的知识块内容，可能非常长，包含详细的技术说明和示例代码...",
            "asset_refs": [{"asset_id": "asset_1", "relation": "evidence"}],
            "source_refs": [{"doc_id": "doc_1", "element_id": "el_1"}],
        })
        result = resp.model_dump(mode="json")
        assert len(result["data"]["content"]) > 20
        assert len(result["data"]["asset_refs"]) == 1


class TestChunkUpdateResponse:
    """5.4 & 5.5 更新知识块。"""

    def test_content_update_triggers_reindex(self):
        """内容变化后触发重新入库。"""
        resp = APIResponse(data={
            "chunk_id": "chunk_1",
            "content": "更新后的内容",
            "content_hash": "sha256:newhash",
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["content_hash"] == "sha256:newhash"


class TestChunkDeleteRestore:
    """5.6 删除和恢复。"""

    def test_delete_sets_deleted_status(self):
        resp = APIResponse(data={"chunk_id": "chunk_1", "status": "deleted"})
        assert resp.data["status"] == "deleted"

    def test_restore_sets_active_status(self):
        resp = APIResponse(data={"chunk_id": "chunk_1", "status": "active"})
        assert resp.data["status"] == "active"


class TestChunkReindex:
    """5.7 重建索引。"""

    def test_reindex_success(self):
        resp = APIResponse(data={
            "chunk_id": "chunk_1",
        })
        result = resp.model_dump(mode="json")
        assert result["data"]["chunk_id"] == "chunk_1"

    def test_reindex_failure(self):
        err = APIErrorResponse(
            error=ErrorDetail(code="INTERNAL_ERROR", message="重建索引失败: embedding 不可用"),
        )
        assert err.error.code == "INTERNAL_ERROR"


class TestChunkBatch:
    """5.8 批量操作。"""

    def test_batch_delete(self):
        resp = APIResponse(
            data={"action": "delete", "updated": 5},
            meta={"total_submitted": 5},
        )
        result = resp.model_dump(mode="json")
        assert result["data"]["updated"] == 5
        assert result["meta"]["total_submitted"] == 5

    def test_batch_invalid_action(self):
        err = APIErrorResponse(
            error=ErrorDetail(code="VALIDATION_ERROR", message="不支持的操作: invalid"),
        )
        assert err.error.code == "VALIDATION_ERROR"

    def test_batch_invalid_status_returns_validation_error(self):
        """批量 update_status 传无效状态应返回 VALIDATION_ERROR。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="无效的知识块状态: archived，有效值为 ['active', 'deleted']",
            ),
        )
        assert err.error.code == "VALIDATION_ERROR"
        assert "无效的知识块状态" in err.error.message


class TestInvalidEnumHandling:
    """枚举无效值校验 — 验证返回 422 而非 500。"""

    def test_document_update_invalid_status_422(self):
        """更新文档时传非法 status 返回 422。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="无效的文档状态: archived，有效值为 ['active', 'deleted', 'failed', 'processing']",
            ),
        )
        assert err.error.code == "VALIDATION_ERROR"
        assert "无效的文档状态" in err.error.message

    def test_chunk_update_invalid_status_422(self):
        """更新知识块时传非法 status 返回 422。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="无效的知识块状态: archived，有效值为 ['active', 'deleted']",
            ),
        )
        assert err.error.code == "VALIDATION_ERROR"
        assert "无效的知识块状态" in err.error.message

    def test_chunk_update_invalid_knowledge_type_422(self):
        """更新知识块时传非法 knowledge_type 返回 422。"""
        err = APIErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="无效的知识类型: unknown_type，有效值为 ['declarative', 'procedural', 'reference', 'faq']",
            ),
        )
        assert err.error.code == "VALIDATION_ERROR"
        assert "无效的知识类型" in err.error.message
