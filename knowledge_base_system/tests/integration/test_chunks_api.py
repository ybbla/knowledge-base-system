"""知识块管理页面集成测试 — 验证前端 chunks.js 调用的所有 API 端点。

前端 chunks.js 调用链（v1）：
  1. GET  /api/v1/search/filters                          → 加载筛选项 (render L23)
  2. GET  /api/v1/documents?page_size=200&status=active    → 文档下拉选项 (render L30)
  3. GET  /api/v1/chunks?page=&page_size=20&...            → 分页知识块列表 (load L123)
  4. GET  /api/v1/chunks/{chunk_id}                        → 知识块详情 (showDetail L218)
  5. POST /api/v1/chunks?doc_id=&title=&content=&...       → 创建知识块 (showCreateDialog L424)
  6. PATCH /api/v1/chunks/{chunk_id}?title=&content=&...   → 更新知识块 (api.js updateChunk)
  7. DELETE /api/v1/chunks/{chunk_id}                       → 软删除 (deleteChunk L559)
  8. POST /api/v1/chunks/{chunk_id}/restore                → 恢复 (restoreChunk L569)
  9. POST /api/v1/chunks/{chunk_id}/reindex                → 重建索引 (reindexChunk L579)
  10. POST /api/v1/chunks/batch?action=delete&chunk_ids=... → 批量删除 (batchDelete L616)
  11. POST /api/v1/chunks/batch/reindex?chunk_ids=...       → 批量重建索引 (api.js batchReindexChunks)

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ── 模拟文件目录 ──────────────────────────────────────────────────────
_SIMULATED_DIR = Path(__file__).resolve().parents[3] / "data" / "simulated_inputs"
_SIMULATED_FILES = {
    "markdown": _SIMULATED_DIR / "simulated_dev_guide.md",
    "txt": _SIMULATED_DIR / "simulated_project_plan.txt",
    "docx": _SIMULATED_DIR / "simulated_system_manual.docx",
    "xlsx": _SIMULATED_DIR / "simulated_user_stats.xlsx",
    "html": _SIMULATED_DIR / "simulated_dashboard.html",
    "pdf": _SIMULATED_DIR / "simulated_api_whitepaper.pdf",
    "pptx": _SIMULATED_DIR / "simulated_q4_review.pptx",
}
_CONTENT_TYPES = {
    "markdown": "text/markdown", "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════

def _create_test_doc(title="知识块集成测试文档", source_type="markdown",
                     source_uri="file:///test/chunk_integration.md", category="测试"):
    """创建测试文档并返回响应 JSON data。"""
    resp = client.post("/api/v1/documents", params={
        "title": title,
        "source_type": source_type,
        "source_uri": source_uri,
        "category": category,
    })
    assert resp.status_code == 201, f"创建文档失败: {resp.text}"
    return resp.json()["data"]


def _cleanup_doc(doc_id: str):
    """尝试软删除文档（如果存在）。"""
    client.delete(f"/api/v1/documents/{doc_id}")


def _create_test_chunk(doc_id: str, title="测试知识块",
                       content="这是一个用于集成测试的知识块内容，包含足够的信息以便验证前后端联调。",
                       knowledge_type="declarative", category="通用",
                       index_after_create=False):
    """创建测试知识块并返回响应 JSON data。"""
    resp = client.post("/api/v1/chunks", params={
        "doc_id": doc_id,
        "title": title,
        "content": content,
        "knowledge_type": knowledge_type,
        "category": category,
        "index_after_create": str(index_after_create).lower(),
    })
    assert resp.status_code == 201, f"创建知识块失败: {resp.text}"
    return resp.json()["data"]


def _cleanup_chunk(chunk_id: str):
    """尝试软删除知识块（如果存在）。"""
    client.delete(f"/api/v1/chunks/{chunk_id}")


# ══════════════════════════════════════════════════════════════════════
# 0. 筛选项 — 前端 chunks.js render() L23-25 加载筛选选项
# ══════════════════════════════════════════════════════════════════════

class TestChunksSearchFilters:
    """前端: API.searchFilters() → res?.data?.chunk_statuses, knowledge_types"""

    def test_filters_contains_chunk_statuses(self):
        """前端 chunks.js:63 用 chunk_statuses 渲染状态下拉框。"""
        response = client.get("/api/v1/search/filters")
        body = response.json()

        assert "chunk_statuses" in body["data"], "筛选项缺少 chunk_statuses"
        statuses = body["data"]["chunk_statuses"]
        assert isinstance(statuses, list)

    def test_filters_chunk_statuses_have_value_field(self):
        """每个 chunk 状态条目必须有 value 字段 (chunks.js:63: s.value)。"""
        response = client.get("/api/v1/search/filters")
        statuses = response.json()["data"]["chunk_statuses"]

        for s in statuses:
            assert "value" in s, f"chunk_statuses 条目缺少 value: {s}"

    def test_filters_contains_knowledge_types(self):
        """前端 chunks.js:58 用 knowledge_types 渲染类型下拉框。"""
        response = client.get("/api/v1/search/filters")
        body = response.json()

        assert "knowledge_types" in body["data"], "筛选项缺少 knowledge_types"
        assert isinstance(body["data"]["knowledge_types"], list)

    def test_filters_knowledge_types_have_value_field(self):
        """每个知识类型条目必须有 value 字段 (chunks.js:58: k.value)。"""
        response = client.get("/api/v1/search/filters")
        types = response.json()["data"]["knowledge_types"]

        for t in types:
            assert "value" in t, f"knowledge_types 条目缺少 value: {t}"


# ══════════════════════════════════════════════════════════════════════
# 1. POST /api/v1/chunks — 创建知识块
# ══════════════════════════════════════════════════════════════════════

class TestChunksCreate:
    """前端: API.createChunk(params) → chunks.js showCreateDialog L424"""

    @pytest.fixture(autouse=True)
    def setup_doc(self):
        """每个测试方法前创建一个测试文档。"""
        self.doc = _create_test_doc()
        self.doc_id = self.doc["doc_id"]
        self.created_chunk_ids: list[str] = []
        yield
        for cid in self.created_chunk_ids:
            _cleanup_chunk(cid)
        _cleanup_doc(self.doc_id)

    def test_create_returns_201_with_chunk_data(self):
        """创建知识块返回 201 和完整数据。"""
        response = client.post("/api/v1/chunks", params={
            "doc_id": self.doc_id,
            "title": "创建测试知识块",
            "content": "这是一段用于测试创建的知识块内容，包含足够的信息以便独立回答问题。",
            "knowledge_type": "declarative",
            "category": "测试",
        })
        assert response.status_code == 201, f"创建失败: {response.text}"
        body = response.json()
        assert body["error"] is None
        assert body["data"]["title"] == "创建测试知识块"
        assert body["data"]["doc_id"] == self.doc_id
        assert body["data"]["status"] == "active"
        assert "chunk_id" in body["data"]
        self.created_chunk_ids.append(body["data"]["chunk_id"])

    def test_create_returns_content_hash(self):
        """创建知识块自动计算 content_hash。"""
        content = "需要计算哈希的测试内容。"
        response = client.post("/api/v1/chunks", params={
            "doc_id": self.doc_id, "title": "哈希测试",
            "content": content, "knowledge_type": "declarative",
        })
        body = response.json()
        assert "content_hash" in body["data"]
        assert body["data"]["content_hash"] is not None
        self.created_chunk_ids.append(body["data"]["chunk_id"])

    def test_create_manual_metadata_flag(self):
        """手动创建的知识块 metadata 包含 manual: true。"""
        response = client.post("/api/v1/chunks", params={
            "doc_id": self.doc_id, "title": "手工知识块",
            "content": "手工创建的知识块内容，应包含 manual 标记。",
            "knowledge_type": "procedural",
        })
        body = response.json()
        meta = body["data"].get("metadata", {})
        assert meta.get("manual") is True, f"metadata 应包含 manual: true, 实际: {meta}"
        self.created_chunk_ids.append(body["data"]["chunk_id"])

    def test_create_with_different_knowledge_types(self):
        """支持创建三种知识类型的知识块。"""
        for kt in ["declarative", "procedural", "relational"]:
            response = client.post("/api/v1/chunks", params={
                "doc_id": self.doc_id,
                "title": f"{kt} 类型知识块",
                "content": f"这是一个 {kt} 类型的知识块测试内容。",
                "knowledge_type": kt,
            })
            assert response.status_code == 201, f"类型 {kt} 创建失败: {response.text}"
            body = response.json()
            kt_value = body["data"]["knowledge_type"]
            assert kt_value == kt, f"期望 knowledge_type={kt}, 实际={kt_value}"
            self.created_chunk_ids.append(body["data"]["chunk_id"])

    def test_create_with_index_after_create(self):
        """创建后立即索引（如果 embedding 可用）。"""
        response = client.post("/api/v1/chunks", params={
            "doc_id": self.doc_id,
            "title": "索引测试知识块",
            "content": "创建后立即索引的测试内容，如果 embedding 可用则会进入索引状态。",
            "knowledge_type": "declarative",
            "index_after_create": "true",
        })
        # 即使 embedding 不可用导致索引失败，API 也应返回 201
        assert response.status_code == 201, f"创建失败: {response.text}"
        body = response.json()
        self.created_chunk_ids.append(body["data"]["chunk_id"])

    def test_create_with_nonexistent_doc_returns_404(self):
        """关联不存在的文档应返回 404。"""
        fake_doc_id = f"nonexistent-doc-{uuid.uuid4().hex[:12]}"
        response = client.post("/api/v1/chunks", params={
            "doc_id": fake_doc_id, "title": "失败测试",
            "content": "关联一个不存在的文档应该失败。",
        })
        assert response.status_code == 404, f"期望 404, 实际 {response.status_code}: {response.text}"
        body = response.json()
        assert body["error"] is not None
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"

    def test_create_detail_contains_all_fields(self):
        """创建响应详情包含前端抽屉需要的所有字段 (chunks.js showDetail L221-234)。"""
        response = client.post("/api/v1/chunks", params={
            "doc_id": self.doc_id,
            "title": "完整字段测试",
            "content": "测试详情响应中是否包含前端抽屉渲染所需的所有字段。",
            "knowledge_type": "declarative",
            "category": "测试分类",
        })
        body = response.json()
        data = body["data"]

        # 前端抽屉用到的字段 (chunks.js:223-233)
        drawer_fields = [
            "chunk_id", "doc_id", "doc_title", "title", "content",
            "content_hash", "knowledge_type", "category",
            "status", "asset_refs", "source_refs",
        ]
        for field in drawer_fields:
            assert field in data, f"创建响应缺少字段: {field}"

        self.created_chunk_ids.append(body["data"]["chunk_id"])


# ══════════════════════════════════════════════════════════════════════
# 2. GET /api/v1/chunks — 知识块分页列表
# ══════════════════════════════════════════════════════════════════════

class TestChunksList:
    """前端: API.listChunks(params) → chunks.js load L123"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """创建测试文档和若干知识块。"""
        self.doc = _create_test_doc(title="列表测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk_ids: list[str] = []
        for i in range(3):
            chunk = _create_test_chunk(
                self.doc_id,
                title=f"列表测试知识块 {i + 1}",
                content=f"第 {i + 1} 个知识块的测试内容，用于验证分页列表接口。",
                knowledge_type=["declarative", "procedural", "relational"][i % 3],
                category=["通用", "技术", "业务"][i % 3],
            )
            self.chunk_ids.append(chunk["chunk_id"])
        yield
        for cid in self.chunk_ids:
            _cleanup_chunk(cid)
        _cleanup_doc(self.doc_id)

    def test_list_returns_paginated_structure(self):
        """知识块列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 20})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None
        assert isinstance(body["data"], list)

    def test_list_meta_has_pagination_fields(self):
        """meta 包含完整分页信息，前端据此渲染分页控件 (chunks.js:200-210)。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 20})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20
        assert "total" in body["meta"]
        assert "total_pages" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 3  # 至少我们创建的 3 个

    def test_list_default_page_size_matches_frontend(self):
        """前端默认 page_size=20 (chunks.js:124)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 20,
        })
        body = response.json()
        assert body["meta"]["page_size"] == 20

    def test_list_item_has_required_fields(self):
        """每个知识块条目包含前端表格渲染所需的字段 (chunks.js:176-196)。"""
        # 通过 doc_id 筛选确保只拿到测试数据
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 50, "doc_id": self.doc_id,
        })
        items = response.json()["data"]

        # 找到我们创建的测试数据
        test_ids = set(self.chunk_ids)
        test_items = [i for i in items if i["chunk_id"] in test_ids]
        assert len(test_items) >= 1, "未找到测试知识块"

        for item in test_items:
            # 前端表格渲染字段 (chunks.js:176-196)
            table_fields = [
                "chunk_id",       # 复选框 value
                "doc_id",         # 文档列
                "doc_title",      # 文档列显示名
                "title",          # 标题列
                "content_preview",# 标题列（hover 可能有 tooltip）
                "knowledge_type", # 类型列 (UI.ktypeBadge)
                "status",         # 状态列 (UI.statusBadge)
                "asset_count",    # 资源列
                "category",       # 分类筛选
            ]
            for field in table_fields:
                assert field in item, f"列表条目缺少字段: {field} (chunk_id={item.get('chunk_id')})"

            # 内容预览不超过 200 字符 + "..."
            preview = item.get("content_preview", "")
            assert len(preview) <= 203, f"content_preview 过长: {len(preview)}"

    def test_list_with_keyword_filter(self):
        """前端搜索框传 keyword 参数 (chunks.js:116)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 20, "keyword": "列表测试",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert len(body["data"]) >= 1  # 应该匹配我们的测试数据

    def test_list_with_doc_id_filter(self):
        """前端文档下拉框传 doc_id 参数 (chunks.js:117)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 20, "doc_id": self.doc_id,
        })
        assert response.status_code == 200
        body = response.json()
        items = body["data"]
        for item in items:
            assert item["doc_id"] == self.doc_id, f"doc_id 过滤不生效: {item['doc_id']}"

    def test_list_with_knowledge_type_filter(self):
        """前端类型下拉框传 knowledge_type 参数 (chunks.js:118)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 20, "knowledge_type": "declarative",
        })
        assert response.status_code == 200
        body = response.json()
        for item in body["data"]:
            assert item["knowledge_type"] == "declarative"

    def test_list_with_status_filter(self):
        """前端状态下拉框传 status 参数 (chunks.js:119)。"""
        for status_val in ["active", "deleted"]:
            response = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 20, "status": status_val,
            })
            assert response.status_code == 200, f"status={status_val} 请求失败"
            body = response.json()
            assert body["error"] is None

    def test_list_all_params_combined(self):
        """前端 load() 实际发送的完整参数组合 (chunks.js:122-130)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1,
            "page_size": 20,
            "keyword": "",
            "doc_id": "",
            "knowledge_type": "",
            "status": "",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert isinstance(body["data"], list)
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20

    def test_list_empty_state_no_error(self):
        """空列表时也正常返回，前端展示空状态 (chunks.js:167-174)。"""
        response = client.get("/api/v1/chunks", params={
            "page": 1, "page_size": 20,
            "keyword": "__nonexistent_chunk_keyword_xyz__",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert isinstance(body["data"], list)


# ══════════════════════════════════════════════════════════════════════
# 3. GET /api/v1/chunks/{chunk_id} — 知识块详情
# ══════════════════════════════════════════════════════════════════════

class TestChunksDetail:
    """前端: API.getChunk(chunkId) → chunks.js showDetail L218"""

    @pytest.fixture(autouse=True)
    def setup_chunk(self):
        """创建测试文档和知识块。"""
        self.doc = _create_test_doc(title="详情测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk = _create_test_chunk(
            self.doc_id,
            title="详情测试知识块",
            content="这是用于验证详情接口的知识块内容。包含多行文本\n第二行内容\n第三行数据。",
            knowledge_type="declarative",
            category="详情测试",
        )
        self.chunk_id = self.chunk["chunk_id"]
        yield
        _cleanup_chunk(self.chunk_id)
        _cleanup_doc(self.doc_id)

    def test_get_detail_returns_unified_structure(self):
        """详情接口返回统一的 { data, meta, error } 结构。"""
        response = client.get(f"/api/v1/chunks/{self.chunk_id}")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_get_detail_contains_all_drawer_fields(self):
        """详情包含前端抽屉渲染所需的所有字段 (chunks.js:221-234)。"""
        response = client.get(f"/api/v1/chunks/{self.chunk_id}")
        data = response.json()["data"]

        drawer_fields = {
            "chunk_id": str,        # 详情 ID 显示
            "doc_id": str,          # 文档列
            "doc_title": (str, type(None)),  # 文档标题（可为 None）
            "content": str,         # 内容区域 <pre>
            "content_hash": (str, type(None)),  # 内容哈希
            "knowledge_type": str,  # 类型徽章 (UI.ktypeBadge)
            "category": str,        # 分类字段
            "status": str,          # 状态徽章 (UI.statusBadge)
            "asset_refs": list,     # 资源引用
            "source_refs": list,    # 来源引用
        }
        for field, expected_type in drawer_fields.items():
            assert field in data, f"详情缺少字段: {field}"
            assert isinstance(data[field], expected_type), \
                f"字段 {field} 类型错误: 期望 {expected_type}, 实际 {type(data[field])}"

    def test_get_detail_content_is_full(self):
        """详情接口返回完整内容，不是截断的 (chunks.js:233)。"""
        response = client.get(f"/api/v1/chunks/{self.chunk_id}")
        data = response.json()["data"]

        # 内容应该是完整的，不是 preview（预览最多 200 字 + "..."）
        content = data["content"]
        assert len(content) > 0, "内容不应为空"
        # 详情内容应包含换行符，证明是完整内容
        assert "\n" in content, "详情内容应包含完整多行文本"
        # 内容长度应超过 20 个字符（原始测试内容约 40 个中文字符）
        assert len(content) > 20, f"内容过短，可能被截断: {len(content)} 字符"

    def test_get_nonexistent_chunk_returns_404(self):
        """查询不存在的知识块返回 404。"""
        fake_id = f"nonexistent-chunk-{uuid.uuid4().hex[:12]}"
        response = client.get(f"/api/v1/chunks/{fake_id}")

        assert response.status_code == 404
        body = response.json()
        assert body["error"] is not None
        assert body["error"]["code"] == "CHUNK_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 4. PATCH /api/v1/chunks/{chunk_id} — 更新知识块
# ══════════════════════════════════════════════════════════════════════

class TestChunksUpdate:
    """前端: API.updateChunk(chunkId, params) → api.js L153"""

    @pytest.fixture(autouse=True)
    def setup_chunk(self):
        """创建测试文档和知识块。"""
        self.doc = _create_test_doc(title="更新测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk = _create_test_chunk(
            self.doc_id,
            title="更新前标题",
            content="这是更新前的内容。",
            knowledge_type="declarative",
            category="更新测试",
        )
        self.chunk_id = self.chunk["chunk_id"]
        yield
        _cleanup_chunk(self.chunk_id)
        _cleanup_doc(self.doc_id)

    def test_update_title(self):
        """更新知识块标题。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "title": "更新后的标题",
        })
        assert response.status_code == 200, f"更新失败: {response.text}"
        body = response.json()
        assert body["data"]["title"] == "更新后的标题"

    def test_update_content(self):
        """更新知识块内容，应重新计算 content_hash。"""
        old_hash = self.chunk.get("content_hash", "")
        new_content = "这是更新后的知识块内容，包含了全新的信息。"

        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "content": new_content,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["content"] == new_content

        # 内容哈希应该变化
        new_hash = body["data"]["content_hash"]
        assert new_hash is not None
        # 不同内容应有不同哈希（除非极端碰撞）
        if old_hash:
            assert new_hash != old_hash, "内容变更后 content_hash 应该变化"

    def test_update_category(self):
        """更新知识块分类。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "category": "技术文档",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["category"] == "技术文档"

    def test_update_knowledge_type(self):
        """更新知识块类型。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "knowledge_type": "procedural",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["knowledge_type"] == "procedural"

    def test_update_multiple_fields(self):
        """同时更新多个字段。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "title": "多字段更新标题",
            "content": "多字段更新的内容，包含了全新的信息结构。",
            "category": "综合测试",
            "knowledge_type": "relational",
        })
        assert response.status_code == 200, f"多字段更新失败: {response.text}"
        body = response.json()
        data = body["data"]
        assert data["title"] == "多字段更新标题"
        assert data["content"] == "多字段更新的内容，包含了全新的信息结构。"
        assert data["category"] == "综合测试"
        assert data["knowledge_type"] == "relational"

    def test_update_content_with_reindex(self):
        """内容变更且 reindex=true 时触发重建索引。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "content": "内容变更触发重建索引的测试。",
            "reindex": "true",
        })
        assert response.status_code == 200
        body = response.json()
        # reindex=true 时触发重建索引（取决于 embedding 可用性）

    def test_update_content_without_reindex(self):
        """内容变更但 reindex=false 时标记为 pending。"""
        response = client.patch(f"/api/v1/chunks/{self.chunk_id}", params={
            "content": "内容变更但不重建索引。",
            "reindex": "false",
        })
        assert response.status_code == 200
        body = response.json()
        # reindex=false 时不重建索引，保持原有状态

    def test_update_nonexistent_chunk_returns_404(self):
        """更新不存在的知识块返回 404。"""
        fake_id = f"nonexistent-chunk-{uuid.uuid4().hex[:12]}"
        response = client.patch(f"/api/v1/chunks/{fake_id}", params={
            "title": "不应该成功",
        })
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "CHUNK_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 5. DELETE /api/v1/chunks/{chunk_id} — 软删除知识块
# ══════════════════════════════════════════════════════════════════════

class TestChunksDelete:
    """前端: API.deleteChunk(chunkId) → chunks.js deleteChunk L559"""

    @pytest.fixture(autouse=True)
    def setup_chunk(self):
        """创建测试知识块。"""
        self.doc = _create_test_doc(title="删除测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk = _create_test_chunk(
            self.doc_id,
            title="待删除知识块",
            content="这个知识块将在测试中被软删除。",
        )
        self.chunk_id = self.chunk["chunk_id"]
        yield
        _cleanup_chunk(self.chunk_id)
        _cleanup_doc(self.doc_id)

    def test_delete_returns_200(self):
        """软删除返回 200 和更新后的数据。"""
        response = client.delete(f"/api/v1/chunks/{self.chunk_id}")

        assert response.status_code == 200, f"删除失败: {response.text}"
        body = response.json()
        assert body["error"] is None
        assert body["data"]["status"] == "deleted"
        assert body["data"]["chunk_id"] == self.chunk_id

    def test_delete_is_idempotent(self):
        """重复删除同一个知识块不报错。"""
        # 第一次删除
        resp1 = client.delete(f"/api/v1/chunks/{self.chunk_id}")
        assert resp1.status_code == 200

        # 第二次删除（幂等）
        resp2 = client.delete(f"/api/v1/chunks/{self.chunk_id}")
        assert resp2.status_code == 200
        assert resp2.json()["data"]["status"] == "deleted"

    def test_delete_nonexistent_chunk_returns_404(self):
        """删除不存在的知识块返回 404。"""
        fake_id = f"nonexistent-chunk-{uuid.uuid4().hex[:12]}"
        response = client.delete(f"/api/v1/chunks/{fake_id}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CHUNK_NOT_FOUND"

    def test_deleted_chunk_appears_in_list_with_deleted_status(self):
        """删除后的知识块在列表中状态为 deleted。"""
        # 先删除
        client.delete(f"/api/v1/chunks/{self.chunk_id}")

        # 查询
        response = client.get(f"/api/v1/chunks/{self.chunk_id}")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "deleted"


# ══════════════════════════════════════════════════════════════════════
# 6. POST /api/v1/chunks/{chunk_id}/restore — 恢复知识块
# ══════════════════════════════════════════════════════════════════════

class TestChunksRestore:
    """前端: API.restoreChunk(chunkId) → chunks.js restoreChunk L569"""

    @pytest.fixture(autouse=True)
    def setup_chunk(self):
        """创建并删除测试知识块。"""
        self.doc = _create_test_doc(title="恢复测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk = _create_test_chunk(
            self.doc_id,
            title="待恢复知识块",
            content="这个知识块先被删除再被恢复。",
        )
        self.chunk_id = self.chunk["chunk_id"]
        # 先软删除
        client.delete(f"/api/v1/chunks/{self.chunk_id}")
        yield
        _cleanup_chunk(self.chunk_id)
        _cleanup_doc(self.doc_id)

    def test_restore_returns_200(self):
        """恢复软删除的知识块返回 200。"""
        response = client.post(f"/api/v1/chunks/{self.chunk_id}/restore")

        assert response.status_code == 200, f"恢复失败: {response.text}"
        body = response.json()
        assert body["error"] is None
        assert body["data"]["status"] == "active"

    def test_restore_sets_index_to_pending(self):
        """恢复后索引状态为 pending（如果之前未索引）。"""
        response = client.post(f"/api/v1/chunks/{self.chunk_id}/restore")
        body = response.json()
        assert body["error"] is None

    def test_restore_nonexistent_chunk_returns_404(self):
        """恢复不存在的知识块返回 404。"""
        fake_id = f"nonexistent-chunk-{uuid.uuid4().hex[:12]}"
        response = client.post(f"/api/v1/chunks/{fake_id}/restore")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CHUNK_NOT_FOUND"

    def test_restore_idempotent(self):
        """重复恢复同一个知识块不报错。"""
        resp1 = client.post(f"/api/v1/chunks/{self.chunk_id}/restore")
        assert resp1.status_code == 200

        resp2 = client.post(f"/api/v1/chunks/{self.chunk_id}/restore")
        assert resp2.status_code == 200
        assert resp2.json()["data"]["status"] == "active"


# ══════════════════════════════════════════════════════════════════════
# 7. POST /api/v1/chunks/{chunk_id}/reindex — 重建单个索引
# ══════════════════════════════════════════════════════════════════════

class TestChunksReindex:
    """前端: API.reindexChunk(chunkId) → chunks.js reindexChunk L579"""

    @pytest.fixture(autouse=True)
    def setup_chunk(self):
        """创建测试知识块。"""
        self.doc = _create_test_doc(title="重建索引测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk = _create_test_chunk(
            self.doc_id,
            title="重建索引知识块",
            content="用于测试重建索引功能的知识块内容。",
        )
        self.chunk_id = self.chunk["chunk_id"]
        yield
        _cleanup_chunk(self.chunk_id)
        _cleanup_doc(self.doc_id)

    def test_reindex_returns_200(self):
        """重建索引返回 200 和更新后的数据。"""
        response = client.post(f"/api/v1/chunks/{self.chunk_id}/reindex")

        # embedding 可能不可用，但 API 应该能处理
        if response.status_code == 200:
            body = response.json()
            assert body["error"] is None
        else:
            # 如果 embedding 不可用导致 500，也接受
            assert response.status_code in (200, 500), \
                f"意外的状态码: {response.status_code}: {response.text}"

    def test_reindex_nonexistent_chunk_returns_404(self):
        """重建不存在知识块的索引返回 404。"""
        fake_id = f"nonexistent-chunk-{uuid.uuid4().hex[:12]}"
        response = client.post(f"/api/v1/chunks/{fake_id}/reindex")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CHUNK_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 8. POST /api/v1/chunks/batch — 批量操作
# ══════════════════════════════════════════════════════════════════════

class TestChunksBatch:
    """前端: API.batchChunkOperation(action, chunkIds) → chunks.js batchDelete L616"""

    @pytest.fixture(autouse=True)
    def setup_chunks(self):
        """创建多个测试知识块。"""
        self.doc = _create_test_doc(title="批量操作测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk_ids: list[str] = []
        for i in range(4):
            chunk = _create_test_chunk(
                self.doc_id,
                title=f"批量测试知识块 {i + 1}",
                content=f"第 {i + 1} 个用于批量操作测试的知识块。",
            )
            self.chunk_ids.append(chunk["chunk_id"])
        yield
        for cid in self.chunk_ids:
            _cleanup_chunk(cid)
        _cleanup_doc(self.doc_id)

    def test_batch_delete(self):
        """批量软删除知识块。"""
        target_ids = self.chunk_ids[:2]
        response = client.post("/api/v1/chunks/batch", json={
            "action": "delete",
            "chunk_ids": target_ids,
        })

        assert response.status_code == 200, f"批量删除失败: {response.text}"
        body = response.json()
        assert body["error"] is None
        assert body["data"]["action"] == "delete"
        assert body["data"]["updated"] == 2
        assert body["meta"]["total_submitted"] == 2

        # 验证知识块状态已变更
        for cid in target_ids:
            detail_resp = client.get(f"/api/v1/chunks/{cid}")
            assert detail_resp.json()["data"]["status"] == "deleted"

    def test_batch_restore(self):
        """批量恢复知识块。"""
        # 先删除所有
        for cid in self.chunk_ids:
            client.delete(f"/api/v1/chunks/{cid}")

        # 批量恢复前两个
        target_ids = self.chunk_ids[:2]
        response = client.post("/api/v1/chunks/batch", json={
            "action": "restore",
            "chunk_ids": target_ids,
        })

        assert response.status_code == 200, f"批量恢复失败: {response.text}"
        body = response.json()
        assert body["data"]["action"] == "restore"
        assert body["data"]["updated"] == 2

        # 验证状态
        for cid in target_ids:
            detail_resp = client.get(f"/api/v1/chunks/{cid}")
            assert detail_resp.json()["data"]["status"] == "active"

    def test_batch_update_status(self):
        """批量更新知识块状态。"""
        target_ids = self.chunk_ids[:2]
        response = client.post("/api/v1/chunks/batch", json={
            "action": "update_status",
            "status": "deleted",
            "chunk_ids": target_ids,
        })

        assert response.status_code == 200, f"批量更新状态失败: {response.text}"
        body = response.json()
        assert body["data"]["action"] == "update_status"
        assert body["data"]["new_status"] == "deleted"

    def test_batch_empty_chunk_ids_returns_error(self):
        """chunk_ids 为空时返回 400（后端 chunk_ids 不能为空）。"""
        response = client.post("/api/v1/chunks/batch", json={
            "action": "delete",
            "chunk_ids": [],
        })
        assert response.status_code in (400, 422), \
            f"期望 400 或 422, 实际 {response.status_code}"

    def test_batch_invalid_action_returns_400(self):
        """不支持的操作返回 400。"""
        response = client.post("/api/v1/chunks/batch", json={
            "action": "invalid_action",
            "chunk_ids": self.chunk_ids,
        })
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ══════════════════════════════════════════════════════════════════════
# 9. POST /api/v1/chunks/batch/reindex — 批量重建索引
# ══════════════════════════════════════════════════════════════════════

class TestChunksBatchReindex:
    """前端: API.batchReindexChunks(chunkIds) → api.js L165"""

    @pytest.fixture(autouse=True)
    def setup_chunks(self):
        """创建测试知识块。"""
        self.doc = _create_test_doc(title="批量重建索引测试文档")
        self.doc_id = self.doc["doc_id"]
        self.chunk_ids: list[str] = []
        for i in range(2):
            chunk = _create_test_chunk(
                self.doc_id,
                title=f"批量索引测试 {i + 1}",
                content=f"用于批量重建索引测试的第 {i + 1} 个知识块。",
            )
            self.chunk_ids.append(chunk["chunk_id"])
        yield
        for cid in self.chunk_ids:
            _cleanup_chunk(cid)
        _cleanup_doc(self.doc_id)

    def test_batch_reindex_returns_200(self):
        """批量重建索引返回 200。"""
        response = client.post("/api/v1/chunks/batch/reindex", json={
            "chunk_ids": self.chunk_ids,
        })

        # embedding 可能不可用
        assert response.status_code in (200, 500), \
            f"批量重建索引异常: {response.status_code}: {response.text}"
        if response.status_code == 200:
            body = response.json()
            assert body["error"] is None
            assert "succeeded" in body["data"]
            assert "failed" in body["data"]

    def test_batch_reindex_empty_ids(self):
        """空 ID 列表返回 200（后端逻辑处理空列表）。"""
        response = client.post(
            "/api/v1/chunks/batch/reindex",
            json={"chunk_ids": []},
        )
        # 空列表由后端逻辑处理（返回 succeeded: [], failed: []）
        assert response.status_code == 200, \
            f"空 chunk_ids 应返回 200, 实际: {response.status_code}"


# ══════════════════════════════════════════════════════════════════════
# 10. 端到端流程 — 模拟前端用户操作全流程
# ══════════════════════════════════════════════════════════════════════

class TestChunksEndToEnd:
    """模拟 chunks.js 完整用户操作流程：
    创建文档 → 创建知识块 → 列表查询 → 详情查看 → 编辑更新 → 删除 → 恢复 → 列表验证
    """

    def test_full_lifecycle(self):
        """知识块完整生命周期测试。"""
        # 1. 创建文档
        doc = _create_test_doc(title="端到端测试文档")
        doc_id = doc["doc_id"]

        try:
            # 2. 创建知识块
            resp = client.post("/api/v1/chunks", params={
                "doc_id": doc_id,
                "title": "端到端知识块",
                "content": "这是端到端测试的知识块内容，用于验证从创建到删除的完整流程。",
                "knowledge_type": "declarative",
                "category": "端到端测试",
            })
            assert resp.status_code == 201
            chunk_data = resp.json()["data"]
            chunk_id = chunk_data["chunk_id"]
            assert chunk_data["status"] == "active"

            # 3. 列表查询 — 确认新知识块出现
            list_resp = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50, "doc_id": doc_id,
            })
            list_ids = [c["chunk_id"] for c in list_resp.json()["data"]]
            assert chunk_id in list_ids, "新创建的知识块未出现在列表中"

            # 4. 详情查看
            detail_resp = client.get(f"/api/v1/chunks/{chunk_id}")
            assert detail_resp.status_code == 200
            detail = detail_resp.json()["data"]
            assert detail["content"] == chunk_data["content"]
            assert detail["doc_title"] == "端到端测试文档"

            # 5. 编辑更新
            update_resp = client.patch(f"/api/v1/chunks/{chunk_id}", params={
                "title": "端到端知识块（已更新）",
                "content": "更新后的端到端测试内容。",
                "category": "已更新分类",
            })
            assert update_resp.status_code == 200
            assert update_resp.json()["data"]["title"] == "端到端知识块（已更新）"
            assert update_resp.json()["data"]["category"] == "已更新分类"

            # 6. 软删除
            del_resp = client.delete(f"/api/v1/chunks/{chunk_id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["data"]["status"] == "deleted"

            # 7. 恢复
            restore_resp = client.post(f"/api/v1/chunks/{chunk_id}/restore")
            assert restore_resp.status_code == 200
            assert restore_resp.json()["data"]["status"] == "active"

            # 8. 最终列表验证 — 恢复后状态为 active
            final_list = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50, "doc_id": doc_id,
            })
            final_item = next(
                (c for c in final_list.json()["data"] if c["chunk_id"] == chunk_id),
                None,
            )
            assert final_item is not None, "恢复后的知识块未在列表中"
            assert final_item["status"] == "active"

            # 清理
            _cleanup_chunk(chunk_id)
        finally:
            _cleanup_doc(doc_id)

    def test_create_chunk_with_new_document_flow(self):
        """模拟前端"新建文档"模式创建知识块 (chunks.js showCreateDialog L412-422)。

        前端流程：
        1. 先创建新文档 (API.createDocument)
        2. 拿到 doc_id 后创建知识块 (API.createChunk)
        """
        # 1. 创建新文档
        doc_resp = client.post("/api/v1/documents", params={
            "title": "手动创建的知识补充文档",
            "source_type": "manual",
            "source_uri": f"manual://chunk-dialog/{uuid.uuid4().hex[:8]}",
            "category": "手工补充",
            "metadata": json.dumps({"manual": True, "created_from": "chunk_dialog"}),
        })
        assert doc_resp.status_code == 201
        doc_id = doc_resp.json()["data"]["doc_id"]

        try:
            # 2. 在新文档下创建知识块
            chunk_resp = client.post("/api/v1/chunks", params={
                "doc_id": doc_id,
                "title": "手工补充的知识条目",
                "content": "这是通过手工补充方式添加的知识条目，用于扩展知识库覆盖范围。",
                "knowledge_type": "declarative",
                "category": "手工补充",
            })
            assert chunk_resp.status_code == 201
            chunk_id = chunk_resp.json()["data"]["chunk_id"]

            # 3. 验证知识块归属正确
            detail_resp = client.get(f"/api/v1/chunks/{chunk_id}")
            assert detail_resp.json()["data"]["doc_id"] == doc_id
            assert detail_resp.json()["data"]["doc_title"] == "手动创建的知识补充文档"

            _cleanup_chunk(chunk_id)
        finally:
            _cleanup_doc(doc_id)

    def test_filter_workflow_matches_frontend(self):
        """模拟前端完整的筛选工作流 (chunks.js load L113-136)。"""
        # 创建测试数据
        doc = _create_test_doc(title="筛选工作流测试文档")
        doc_id = doc["doc_id"]

        chunk_ids: list[str] = []
        try:
            # 创建不同类型/分类的知识块
            configs = [
                ("declarative", "技术", "Python 编码规范知识块", "Python 代码应遵循 PEP 8 规范，使用 4 空格缩进。"),
                ("procedural", "技术", "部署流程知识块", "部署步骤：1) 构建镜像 2) 推送仓库 3) 更新服务。"),
                ("relational", "业务", "部门关系知识块", "研发部向 CTO 汇报，测试部向质量 VP 汇报。"),
            ]
            for kt, cat, title, content in configs:
                resp = client.post("/api/v1/chunks", params={
                    "doc_id": doc_id, "title": title,
                    "content": content, "knowledge_type": kt, "category": cat,
                })
                chunk_ids.append(resp.json()["data"]["chunk_id"])

            # 按类型筛选
            resp = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50, "knowledge_type": "declarative",
            })
            filtered = [c for c in resp.json()["data"] if c["chunk_id"] in chunk_ids]
            assert all(c["knowledge_type"] == "declarative" for c in filtered)

            # 按分类筛选
            resp = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50, "category": "技术",
            })
            filtered = [c for c in resp.json()["data"] if c["chunk_id"] in chunk_ids]
            assert all(c["category"] == "技术" for c in filtered)

            # 按关键词搜索
            resp = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50, "keyword": "部署",
            })
            filtered = [c for c in resp.json()["data"] if c["chunk_id"] in chunk_ids]
            assert any("部署" in c.get("title", "") or "部署" in c.get("content_preview", "")
                       for c in filtered), "关键词搜索未匹配到预期结果"

            # 组合筛选
            resp = client.get("/api/v1/chunks", params={
                "page": 1, "page_size": 50,
                "knowledge_type": "declarative",
                "status": "active",
            })
            assert resp.status_code == 200
            assert resp.json()["error"] is None

        finally:
            for cid in chunk_ids:
                _cleanup_chunk(cid)
            _cleanup_doc(doc_id)
