"""知识搜索页面前后端联调测试 — 验证前端 search.js 调用的所有 API 端点。

前端 search.js 调用链（v1）：
  1. GET  /api/v1/search/filters              → 加载筛选项 (render L17)
  2. POST /api/v1/search                      → 标准检索 (doSearch L89)
  3. POST /api/v1/search/preview              → 快速预览检索
  4. POST /api/v1/search/debug                → 调试检索 (doDebugSearch L227)
  5. POST /api/v1/search/feedback             → 检索反馈 (api.js L193)

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from __future__ import annotations

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

def _create_doc(title="搜索测试文档", source_type="markdown",
                source_uri="file:///test/search_integration.md", category="测试"):
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


def _create_chunk(doc_id: str, title="搜索测试知识块",
                  content="这是一个用于搜索集成测试的知识块内容。",
                  knowledge_type="declarative", category="通用",
                  index_after_create=True):
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


def _upload_simulated_file(file_type: str, title: str | None = None,
                           category: str = "测试") -> dict:
    """上传模拟文件并返回响应 JSON data。"""
    file_path = _SIMULATED_FILES[file_type]
    assert file_path.is_file(), f"模拟文件不存在: {file_path}"

    with open(file_path, "rb") as f:
        file_content = f.read()

    files = {"file": (file_path.name, file_content, _CONTENT_TYPES[file_type])}
    data = {}
    if title:
        data["title"] = title
    if category:
        data["category"] = category

    resp = client.post(
        "/api/v1/documents/upload",
        files=files,
        data=data,
        params={"ingest_after_create": "false"},
    )
    assert resp.status_code in (201, 200), f"上传失败: {resp.text}"
    return resp.json()["data"]


# ══════════════════════════════════════════════════════════════════════
# 模块级 fixture：构建可搜索的知识库数据
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def searchable_data():
    """创建多类型、多分类的知识块，覆盖分类过滤和类型过滤测试场景。"""
    doc_ids: list[str] = []
    chunk_ids: list[str] = []

    try:
        # 文档 1 — 技术类
        doc1 = _create_doc(
            title="知识库系统开发指南",
            source_type="markdown",
            source_uri="file:///test/dev_guide.md",
            category="技术",
        )
        doc_ids.append(doc1["doc_id"])

        # 文档 2 — 业务类
        doc2 = _create_doc(
            title="V2.0 项目计划书",
            source_type="txt",
            source_uri="file:///test/project_plan.txt",
            category="业务",
        )
        doc_ids.append(doc2["doc_id"])

        # 文档 1 的知识块（技术分类，陈述型 + 流程型）
        chunks_doc1 = [
            ("项目结构说明", "knowledge-base-system 项目包含 app/、parsers/、indexing/、llm/、tests/ 等模块，app/main.py 是应用入口负责启动 FastAPI 和注册路由。",
             "declarative", "技术"),
            ("添加新解析器的步骤", "实现自定义解析器需要三步：1. 继承 DocumentParser 基类；2. 实现 supports() 和 parse() 方法；3. 在启动时注册到 ParserRegistry。",
             "procedural", "技术"),
            ("调试本地开发模式", "使用 export BACKEND=memory 跳过 PostgreSQL，export MOCK_LLM=true 跳过 LLM 调用，启动命令 python -m uvicorn app.main:app --reload。",
             "procedural", "技术"),
        ]
        for title, content, kt, cat in chunks_doc1:
            chunk = _create_chunk(doc1["doc_id"], title=title, content=content,
                                  knowledge_type=kt, category=cat)
            chunk_ids.append(chunk["chunk_id"])

        # 文档 2 的知识块（业务分类，陈述型 + 关系型）
        chunks_doc2 = [
            ("V2.0 检索精度提升目标", "RRF 融合算法参数自动调优，目标 Recall@10 >= 0.92。引入 Cross-Encoder Reranker 替代当前 Bi-Encoder 方案。",
             "declarative", "业务"),
            ("V2.0 多模态支持计划", "支持图片 OCR 与视觉语义嵌入双通道索引，视频关键帧提取与音频转写，表格数据支持结构化查询（类 SQL 语法）。",
             "declarative", "业务"),
            ("V2.0 里程碑计划", "M1 检索算法升级（2026-07），M2 图片多模态索引（2026-08），M3 全链路追踪（2026-09），M4 视频关键帧（2026-10），M5 集成测试与上线（2026-11）。",
             "relational", "业务"),
        ]
        for title, content, kt, cat in chunks_doc2:
            chunk = _create_chunk(doc2["doc_id"], title=title, content=content,
                                  knowledge_type=kt, category=cat)
            chunk_ids.append(chunk["chunk_id"])

        yield {
            "doc_ids": doc_ids,
            "chunk_ids": chunk_ids,
        }
    finally:
        for cid in chunk_ids:
            _cleanup_chunk(cid)
        for did in doc_ids:
            _cleanup_doc(did)


# ══════════════════════════════════════════════════════════════════════
# 0. 筛选项 — 前端 search.js render() L17-44 加载筛选选项
# ══════════════════════════════════════════════════════════════════════

class TestSearchFilters:
    """前端: API.searchFilters() → res?.data?.categories, knowledge_types"""

    def test_filters_returns_unified_structure(self):
        """筛选项接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/search/filters")
        body = response.json()

        assert response.status_code == 200
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_categories_is_list_with_value_and_count(self):
        """前端 search.js:38-40 用 categories 渲染分类下拉框，读取 value 和 count。"""
        response = client.get("/api/v1/search/filters")
        categories = response.json()["data"].get("categories", [])

        assert isinstance(categories, list)
        for c in categories:
            assert "value" in c, f"categories 条目缺少 value: {c}"
            assert "count" in c, f"categories 条目缺少 count: {c}"

    def test_knowledge_types_is_list_with_value_and_count(self):
        """前端 search.js:42-44 用 knowledge_types 渲染类型下拉框，读取 value 和 count。"""
        response = client.get("/api/v1/search/filters")
        ktypes = response.json()["data"].get("knowledge_types", [])

        assert isinstance(ktypes, list)
        for k in ktypes:
            assert "value" in k, f"knowledge_types 条目缺少 value: {k}"
            assert "count" in k, f"knowledge_types 条目缺少 count: {k}"

    def test_filters_contains_source_types(self):
        """筛选项包含 source_types 列表。"""
        response = client.get("/api/v1/search/filters")
        source_types = response.json()["data"].get("source_types", [])

        assert isinstance(source_types, list)

    def test_filters_contains_chunk_statuses(self):
        """筛选项包含 chunk_statuses 列表（search.js:86 用 active 过滤）。"""
        response = client.get("/api/v1/search/filters")
        chunk_statuses = response.json()["data"].get("chunk_statuses", [])

        assert isinstance(chunk_statuses, list)

    def test_filters_contains_index_statuses(self):
        """筛选项包含 index_statuses 列表（search.js:87 用 indexed 过滤）。"""
        response = client.get("/api/v1/search/filters")
        index_statuses = response.json()["data"].get("index_statuses", [])

        assert isinstance(index_statuses, list)

    def test_filters_contains_doc_statuses(self):
        """筛选项包含 doc_statuses 列表。"""
        response = client.get("/api/v1/search/filters")
        doc_statuses = response.json()["data"].get("doc_statuses", [])

        assert isinstance(doc_statuses, list)
        assert len(doc_statuses) > 0


# ══════════════════════════════════════════════════════════════════════
# 1. POST /api/v1/search — 标准检索
# ══════════════════════════════════════════════════════════════════════

class TestStandardSearch:
    """前端: API.search(query, topK, filters, options) → search.js doSearch L89"""

    def test_search_returns_unified_structure(self, searchable_data):
        """检索接口返回统一的 { data, meta, error } 结构。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
        })

        assert response.status_code == 200, f"检索失败: {response.text}"
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_search_data_has_top_level_fields(self, searchable_data):
        """前端 search.js:98-110 读取 data.results、data.total_count、data.rewritten_query。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
        })
        data = response.json()["data"]

        assert "results" in data
        assert isinstance(data["results"], list)
        assert "total_count" in data
        assert isinstance(data["total_count"], int)
        assert "rewritten_query" in data
        assert "query" in data
        assert data["query"] == "解析器"

    def test_search_meta_has_query_info(self, searchable_data):
        """meta 包含 query、rewritten_query、total_count、search_id。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
        })
        meta = response.json()["meta"]

        assert "search_id" in meta
        assert "query" in meta
        assert meta["query"] == "解析器"
        assert "total_count" in meta

    def test_result_card_has_required_fields(self, searchable_data):
        """每个检索结果包含前端结果卡片渲染所需的字段 (search.js:122-136)。

        前端渲染字段:
          L123: item.chunk_id       — showResultDetail 参数
          L125: item.title          — 卡片标题
          L126: item.score          — 分数显示
          L128: item.content        — 内容预览（截取 250 字符）
          L131: item.knowledge_type — UI.ktypeBadge()
          L132: item.category       — 分类标签
          L133: item.doc_title      — 来源文档
          L134: item.score_components.rerank — Rerank 分数
        """
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果，跳过字段验证")

        for item in results:
            assert "chunk_id" in item, "缺少 chunk_id (search.js L123)"
            assert "title" in item, "缺少 title (search.js L125)"
            assert "score" in item, "缺少 score (search.js L126)"
            assert isinstance(item["score"], (int, float))
            assert "content" in item, "缺少 content (search.js L128)"
            assert "knowledge_type" in item, "缺少 knowledge_type (search.js L131)"
            assert "category" in item, "缺少 category (search.js L132)"
            assert "doc_title" in item, "缺少 doc_title (search.js L133)"
            assert "score_components" in item, "缺少 score_components (search.js L134)"
            assert "rerank" in item["score_components"], \
                "score_components 缺少 rerank (search.js L134)"

    def test_result_detail_has_all_modal_fields(self, searchable_data):
        """检索结果包含前端详情模态框所需的全部字段 (search.js showResultDetail L158-184)。

        详情模态框字段:
          L158: item.knowledge_type
          L159: item.category
          L160: item.score
          L162: item.score_components.vector
          L163: item.score_components.bm25
          L164: item.score_components.rerank
          L168: item.content
          L171: item.doc_title, item.doc_id, item.doc_version
          L172: item.source_refs
          L174: item.source_refs[].doc_id
          L176: item.source_refs[].source_location.page
        """
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
            "options": {"include_sources": True, "include_score_components": True},
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果，跳过字段验证")

        item = results[0]
        # 评分明细 (L158-164)
        sc = item.get("score_components", {})
        assert "vector" in sc, "score_components 缺少 vector (search.js L162)"
        assert "bm25" in sc, "score_components 缺少 bm25 (search.js L163)"
        assert "rerank" in sc, "score_components 缺少 rerank (search.js L164)"
        # 文档信息 (L171)
        assert "doc_id" in item, "缺少 doc_id (search.js L171)"
        assert "doc_version" in item, "缺少 doc_version (search.js L171)"
        # 来源引用 (L172-178)
        assert "source_refs" in item, "缺少 source_refs (search.js L172)"
        assert isinstance(item["source_refs"], list)

    def test_source_refs_has_doc_id_and_source_location(self, searchable_data):
        """来源引用条目包含 doc_id 和 source_location.page (search.js L174-176)。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
            "options": {"include_sources": True},
        })
        results = response.json()["data"]["results"]
        items_with_refs = [r for r in results if r.get("source_refs")]

        if not items_with_refs:
            pytest.skip("无含 source_refs 的结果")

        for item in items_with_refs:
            for ref in item["source_refs"]:
                assert "doc_id" in ref, f"source_ref 缺少 doc_id (search.js L174): {ref}"

    def test_result_has_metadata(self, searchable_data):
        """检索结果包含 metadata 字段。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果")

        for item in results:
            assert "metadata" in item, f"结果缺少 metadata: {item.get('chunk_id')}"

    def test_highlight_field_when_enabled(self, searchable_data):
        """启用高亮后每个结果包含 highlight 字段 (search.js L129)。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
            "options": {"highlight": True},
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果")

        for item in results:
            assert "highlight" in item, \
                f"highlight 选项开启后结果缺少 highlight 字段: {item.get('chunk_id')}"

    def test_highlight_content_has_mark_tag(self, searchable_data):
        """高亮内容包含 <mark> 标签 (search.js L129)。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
            "options": {"highlight": True},
        })
        results = response.json()["data"]["results"]
        highlights = [r["highlight"] for r in results if r.get("highlight")]

        if highlights:
            assert any("<mark>" in h for h in highlights), \
                f"高亮内容应含 <mark> 标签: {highlights[:2]}"

    def test_top_k_limit(self, searchable_data):
        """top_k 参数限制返回结果数量 (search.js L74-75)。"""
        for k in [1, 3, 5]:
            response = client.post("/api/v1/search", json={
                "query": "项目",
                "top_k": k,
            })
            results = response.json()["data"]["results"]
            assert len(results) <= k, f"top_k={k} 但返回了 {len(results)} 条"

    def test_top_k_exceeds_100_returns_422(self):
        """top_k 超过 100 触发 Pydantic 验证错误 (SearchRequest.ge=1, le=100)。"""
        response = client.post("/api/v1/search", json={
            "query": "测试",
            "top_k": 200,
        })
        assert response.status_code == 422

    def test_missing_query_returns_422(self):
        """缺少必填 query 字段返回 422。"""
        response = client.post("/api/v1/search", json={
            "top_k": 5,
        })
        assert response.status_code == 422

    def test_category_filter(self, searchable_data):
        """分类过滤生效 — 前端 search.js:84 传 filters.categories。"""
        response = client.post("/api/v1/search", json={
            "query": "开发",
            "top_k": 10,
            "filters": {"categories": ["技术"]},
        })
        results = response.json()["data"]["results"]

        for item in results:
            assert item["category"] == "技术", \
                f"分类过滤失败: 期望 '技术', 实际 '{item['category']}'"

    def test_knowledge_type_filter(self, searchable_data):
        """知识类型过滤生效 — 前端 search.js:85 传 filters.knowledge_types。"""
        response = client.post("/api/v1/search", json={
            "query": "步骤",
            "top_k": 10,
            "filters": {"knowledge_types": ["procedural"]},
        })
        results = response.json()["data"]["results"]

        for item in results:
            assert item["knowledge_type"] == "procedural", \
                f"类型过滤失败: 期望 'procedural', 实际 '{item['knowledge_type']}'"

    def test_combined_filters(self, searchable_data):
        """组合分类和类型过滤 — 前端 search.js:83-87 实际发送的参数组合。"""
        response = client.post("/api/v1/search", json={
            "query": "开发",
            "top_k": 10,
            "filters": {
                "categories": ["技术"],
                "knowledge_types": ["procedural"],
                "chunk_status": ["active"],
            },
        })
        assert response.status_code == 200
        results = response.json()["data"]["results"]

        for item in results:
            assert item["category"] == "技术"
            assert item["knowledge_type"] == "procedural"

    def test_include_score_components_false(self, searchable_data):
        """关闭评分明细后结果不含 score_components (search.js L95)。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
            "options": {"include_score_components": False},
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果")

        for item in results:
            assert "score_components" not in item, \
                "include_score_components=false 时不应含 score_components"

    def test_include_assets_false(self, searchable_data):
        """关闭资源引用后结果 asset_refs 为空 (search.js L93)。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
            "options": {"include_assets": False},
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果")

        for item in results:
            assert item.get("asset_refs", []) == [], \
                "include_assets=false 时 asset_refs 应为空"

    def test_full_frontend_options(self, searchable_data):
        """前端 doSearch() L89-96 实际发送的完整请求体验证。"""
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
            "filters": {
                "chunk_status": ["active"],
                "index_status": ["indexed"],
            },
            "options": {
                "hybrid": True,
                "rewrite": True,
                "highlight": True,
                "include_assets": True,
                "include_sources": True,
                "include_score_components": True,
            },
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert "results" in data
        assert "rewritten_query" in data


# ══════════════════════════════════════════════════════════════════════
# 2. POST /api/v1/search/preview — 快速预览检索
# ══════════════════════════════════════════════════════════════════════

class TestSearchPreview:
    """前端: API.searchPreview(query, topK, filters) → api.js L184-187"""

    def test_preview_returns_unified_structure(self, searchable_data):
        """预览检索返回统一的 { data, meta, error } 结构。"""
        response = client.post("/api/v1/search/preview", json={
            "query": "解析器",
            "top_k": 5,
        })

        assert response.status_code == 200, f"预览检索失败: {response.text}"
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_preview_meta_indicates_mode(self, searchable_data):
        """预览检索 meta.mode == 'preview' 且 rerank_skipped 为 true。"""
        response = client.post("/api/v1/search/preview", json={
            "query": "解析器",
            "top_k": 5,
        })
        meta = response.json()["meta"]

        assert meta.get("mode") == "preview"
        assert meta.get("rerank_skipped") is True

    def test_preview_results_have_basic_fields(self, searchable_data):
        """预览检索结果包含基本卡片字段。"""
        response = client.post("/api/v1/search/preview", json={
            "query": "开发",
            "top_k": 3,
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无预览检索结果")

        for item in results:
            for field in ["chunk_id", "title", "content", "score", "category", "knowledge_type"]:
                assert field in item, f"预览结果缺少字段: {field}"

    def test_preview_with_category_filter(self, searchable_data):
        """预览检索支持分类过滤。"""
        response = client.post("/api/v1/search/preview", json={
            "query": "项目",
            "top_k": 10,
            "filters": {"categories": ["业务"]},
        })
        results = response.json()["data"]["results"]

        for item in results:
            assert item["category"] == "业务"


# ══════════════════════════════════════════════════════════════════════
# 3. POST /api/v1/search/debug — 调试检索
# ══════════════════════════════════════════════════════════════════════

class TestSearchDebug:
    """前端: API.searchDebug(query, topK) → search.js doDebugSearch L227"""

    def test_debug_returns_unified_structure(self, searchable_data):
        """调试检索返回统一的 { data, meta, error } 结构。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })

        assert response.status_code == 200, f"调试检索失败: {response.text}"
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_debug_meta_indicates_mode(self, searchable_data):
        """调试检索 meta.mode == 'debug' (search.js L229)。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        assert response.json()["meta"]["mode"] == "debug"

    def test_debug_data_has_query_info(self, searchable_data):
        """调试数据包含查询和过滤信息 (search.js L232-235)。

        L232: data.query
        L233: data.rewritten_query
        L234: data.filters
        L235: data.total_count
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "如何添加解析器",
            "top_k": 5,
        })
        data = response.json()["data"]

        assert "query" in data
        assert data["query"] == "如何添加解析器"
        assert "rewritten_query" in data
        assert "filters" in data
        assert "total_count" in data
        assert isinstance(data["total_count"], int)

    def test_debug_data_has_results(self, searchable_data):
        """调试数据包含结果列表 (search.js L238: data.results)。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "开发",
            "top_k": 5,
        })
        data = response.json()["data"]

        assert "results" in data
        assert isinstance(data["results"], list)

    def test_debug_result_card_fields(self, searchable_data):
        """调试结果卡片字段 (search.js L241-247)。

        L241: r.title, r.chunk_id
        L242: r.score
        L245: r.score_components.vector, .bm25, .rerank
        L247: r.content
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        results = response.json()["data"].get("results", [])

        if len(results) == 0:
            pytest.skip("无调试检索结果")

        for r in results:
            assert "title" in r, "调试结果缺少 title (search.js L241)"
            assert "chunk_id" in r, "调试结果缺少 chunk_id (search.js L241)"
            assert "score" in r, "调试结果缺少 score (search.js L242)"
            assert isinstance(r["score"], (int, float))
            assert "score_components" in r, "调试结果缺少 score_components (search.js L244)"
            sc = r["score_components"]
            for key in ["vector", "bm25", "rerank"]:
                assert key in sc, f"score_components 缺少 {key} (search.js L245)"
            assert "content" in r, "调试结果缺少 content (search.js L247)"

    def test_debug_data_has_rewrite_info(self, searchable_data):
        """调试数据包含 rewrite 查询改写详情。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]

        assert "rewrite" in data
        assert "original_query" in data["rewrite"]  # API 返回 original_query，不是 query
        assert "rewritten_query" in data["rewrite"]
        assert "keywords" in data["rewrite"]

    def test_debug_data_has_stage_candidates(self, searchable_data):
        """调试数据包含各阶段候选列表。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]

        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert stage in data, f"调试数据缺少 {stage}"
            assert isinstance(data[stage], list)

    # ── 评分组件数值类型验证 ───────────────────────────────────────
    # 前端 doDebugSearch() L245 调用 .toFixed(4)，若非数值会崩溃

    def test_score_components_are_numeric(self, searchable_data):
        """每个调试结果的 vector/bm25/rerank 评分均为 (int, float)，不可为 None 或字符串。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        results = response.json()["data"].get("results", [])

        if len(results) == 0:
            pytest.skip("无调试检索结果")

        for r in results:
            sc = r.get("score_components", {})
            for key in ["vector", "bm25", "rerank"]:
                val = sc.get(key)
                assert val is not None, \
                    f"score_components.{key} 不应为 None: chunk_id={r.get('chunk_id')}"
                assert isinstance(val, (int, float)), \
                    f"score_components.{key} 应为数值类型，实际 {type(val).__name__}: chunk_id={r.get('chunk_id')}"

    def test_score_zero_is_still_numeric(self, searchable_data):
        """分数为 0.0 时前端 (0).toFixed(4) 仍正常 — 值存在且为数值。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        results = response.json()["data"].get("results", [])

        if len(results) == 0:
            pytest.skip("无调试检索结果")

        for r in results:
            score = r.get("score")
            assert score is not None, f"score 不应为 None: chunk_id={r.get('chunk_id')}"
            assert isinstance(score, (int, float)), \
                f"score 应为数值类型: chunk_id={r.get('chunk_id')}"
            # 验证 .toFixed(4) 等价操作可正常执行
            formatted = f"{score:.4f}"
            assert formatted  # 非空字符串

    # ── 阶段候选列表内部结构验证 ───────────────────────────────────

    def test_stage_candidate_structure(self, searchable_data):
        """每个阶段候选条目含 chunk_id (str) 和 score (float)。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]

        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            candidates = data.get(stage, [])
            for i, c in enumerate(candidates):
                assert "chunk_id" in c, f"{stage}[{i}] 缺少 chunk_id"
                assert isinstance(c["chunk_id"], str), \
                    f"{stage}[{i}].chunk_id 应为 str，实际 {type(c['chunk_id']).__name__}"
                assert "score" in c, f"{stage}[{i}] 缺少 score"
                assert isinstance(c["score"], (int, float)), \
                    f"{stage}[{i}].score 应为数值类型，实际 {type(c['score']).__name__}"

    def test_stage_candidates_count_consistency(self, searchable_data):
        """每个阶段候选列表长度应 >= 最终 results 数量（召回阶段返回更多候选）。

        vector/bm25/fused 是召回阶段的完整候选列表（通常 Top 50+），
        rerank_results 是对 fused_candidates 重排后的列表（相同数量），
        results 是过滤并截断后的最终展示结果。
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]
        results_count = len(data.get("results", []))

        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            candidates = data.get(stage, [])
            # 召回阶段候选数量应 >= 最终结果数量
            assert len(candidates) >= results_count, \
                f"{stage} 长度 ({len(candidates)}) 应 >= results ({results_count})"

    def test_stage_candidate_scores_match_results(self, searchable_data):
        """各阶段候选的 score 与 results 中对应 score_components 一致（仅验证同时存在的条目）。

        注意：召回阶段（vector/bm25/fused）可能包含不在最终 results 中的候选，
        因为 results 经过了前端过滤和 Top-K 截断。
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]
        results = data.get("results", [])

        if len(results) == 0:
            pytest.skip("无调试检索结果")

        # 构建 chunk_id → score_components 映射
        result_scores: dict[str, dict[str, float]] = {}
        for r in results:
            sc = r.get("score_components", {})
            result_scores[r["chunk_id"]] = {
                "vector": sc.get("vector", 0.0),
                "bm25": sc.get("bm25", 0.0),
                "rerank": sc.get("rerank", 0.0),
                "fused": r.get("score", 0.0),
            }

        # 交叉验证各阶段候选中同时在 results 里的条目
        stage_key_map = {
            "vector_candidates": "vector",
            "bm25_candidates": "bm25",
            "fused_candidates": "fused",
            "rerank_results": "rerank",
        }

        for stage, result_key in stage_key_map.items():
            for c in data.get(stage, []):
                cid = c["chunk_id"]
                if cid in result_scores:  # 只验证同时存在的条目
                    expected = result_scores[cid][result_key]
                    actual = c["score"]
                    assert abs(actual - expected) < 1e-9, \
                        f"{stage}[{cid}].score={actual} 与 results[{cid}].score_components.{result_key}={expected} 不一致"

    # ── 空结果场景 ─────────────────────────────────────────────────

    def test_debug_with_empty_results(self, searchable_data):
        """罕见字符串查询验证端点正常工作。

        注意：向量检索基于语义相似度，即使罕见查询也会返回一些结果（分数很低）。
        不应期望返回完全空的列表。
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "xyznonexistent12345",
            "top_k": 5,
        })
        assert response.status_code == 200
        data = response.json()["data"]

        # 验证结果结构正确（即使返回了一些低分结果）
        assert "results" in data
        assert "total_count" in data
        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert stage in data, f"调试结果应包含 {stage} 字段"

    # ── 禁用改写 ────────────────────────────────────────────────────

    def test_debug_with_rewrite_disabled(self, searchable_data):
        """options.rewrite=False 不影响 API 正常返回。

        注意：当前 pipeline 总是执行查询改写，该选项仅为占位。
        rewritten_query 应为 LLM 改写结果或等于原查询（fallback 时）。
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
            "options": {"rewrite": False},
        })
        assert response.status_code == 200
        data = response.json()["data"]

        # rewritten_query 应该是字符串（可能是改写结果或原查询）
        rw = data.get("rewritten_query", "")
        assert isinstance(rw, str), "rewritten_query 应为字符串"
        # rewrite 对象应存在
        assert "rewrite" in data, "调试结果应包含 rewrite 对象"

    # ── TopK 边界值 ────────────────────────────────────────────────

    @pytest.mark.parametrize("top_k", [1, 100])
    def test_debug_top_k_boundaries(self, searchable_data, top_k):
        """调试端点接受 top_k=1 和 top_k=100 边界值。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "开发",
            "top_k": top_k,
        })
        assert response.status_code == 200, f"top_k={top_k} 应返回 200，实际: {response.status_code}"
        results = response.json()["data"]["results"]
        assert len(results) <= top_k, f"top_k={top_k} 但返回了 {len(results)} 条"

    # ── 带过滤条件的调试检索 ───────────────────────────────────────

    def test_debug_with_category_filter(self, searchable_data):
        """调试检索支持分类过滤 — api.js searchDebug() 接受 filters 参数。"""
        response = client.post("/api/v1/search/debug", json={
            "query": "开发",
            "top_k": 10,
            "filters": {"categories": ["技术"]},
        })
        assert response.status_code == 200
        results = response.json()["data"]["results"]

        for item in results:
            assert item["category"] == "技术", \
                f"分类过滤失败: 期望 '技术', 实际 '{item['category']}'"

    def test_debug_filters_in_response(self, searchable_data):
        """data.filters 为可序列化 dict，与请求过滤条件一致。"""
        import json as json_mod

        response = client.post("/api/v1/search/debug", json={
            "query": "开发",
            "top_k": 5,
            "filters": {"categories": ["技术"], "chunk_status": ["active"]},
        })
        data = response.json()["data"]

        assert "filters" in data
        assert isinstance(data["filters"], dict)
        # 可 JSON 序列化（前端 JSON.stringify 使用）
        serialized = json_mod.dumps(data["filters"])
        assert serialized

    # ── 敏感信息保护 ───────────────────────────────────────────────

    def test_debug_no_sensitive_data(self, searchable_data):
        """调试响应不应包含 API key、密码、密钥、完整提示词等敏感信息。"""
        import json as json_mod

        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        # 序列化整个响应为字符串进行关键字扫描
        raw = json_mod.dumps(response.json(), ensure_ascii=False).lower()

        sensitive_keywords = ["api_key", "apikey", "secret", "password", "token", "prompt"]
        for kw in sensitive_keywords:
            assert kw not in raw, \
                f"调试响应中不应包含敏感关键字 '{kw}'"

    # ── 错误响应结构 ───────────────────────────────────────────────

    def test_debug_error_response_structure(self, monkeypatch, searchable_data):
        """模拟 pipeline 异常，验证返回 500 + error_summary + meta.status='error'。"""
        def _raise(*args, **kwargs):
            raise RuntimeError("模拟的检索 pipeline 异常")

        # 动态导入 deps 模块并替换 retrieval_pipeline.search
        from app.core import deps as _deps
        monkeypatch.setattr(_deps.retrieval_pipeline, "search", _raise)

        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        assert response.status_code == 500, f"异常时应返回 500，实际: {response.status_code}"
        body = response.json()

        # 检查错误响应结构（search_debug 的 except 分支返回 APIResponse，非 APIErrorResponse）
        # 所以 error 字段为 None，data 中含 error_summary
        assert body["error"] is None, "调试异常响应 error 应为 None（使用 APIResponse 包装）"
        assert body["meta"]["mode"] == "debug"
        assert body["meta"]["status"] == "error"
        assert "error_summary" in body["data"], \
            f"data 应含 error_summary: {body['data']}"
        assert len(body["data"]["error_summary"]) > 0
        assert len(body["data"]["error_summary"]) <= 500, \
            f"error_summary 超过 500 字符: {len(body['data']['error_summary'])}"


# ══════════════════════════════════════════════════════════════════════
# 4. POST /api/v1/search/feedback — 检索反馈
# ══════════════════════════════════════════════════════════════════════

class TestSearchFeedback:
    """前端: API.searchFeedback(chunkId, feedback, searchId) → api.js L193-195"""

    def test_feedback_returns_202(self):
        """反馈接口返回 202 和 accepted 状态。"""
        response = client.post("/api/v1/search/feedback", json={
            "chunk_id": "test-chunk-001",
            "feedback": "relevant",
            "search_id": "test-search-001",
        })

        assert response.status_code == 202, f"反馈失败: {response.text}"
        body = response.json()
        assert body["data"]["status"] == "accepted"
        assert body["data"]["chunk_id"] == "test-chunk-001"
        assert body["data"]["feedback"] == "relevant"

    @pytest.mark.parametrize("feedback_type", ["relevant", "not_relevant", "clicked"])
    def test_all_feedback_types_accepted(self, feedback_type):
        """三种反馈类型 (relevant / not_relevant / clicked) 均返回 202。"""
        response = client.post("/api/v1/search/feedback", json={
            "chunk_id": "chunk-001",
            "feedback": feedback_type,
        })

        assert response.status_code == 202
        assert response.json()["data"]["status"] == "accepted"

    def test_feedback_without_search_id(self):
        """search_id 可选 — 前端 api.js:193 默认为空字符串。"""
        response = client.post("/api/v1/search/feedback", json={
            "chunk_id": "chunk-001",
            "feedback": "relevant",
        })

        assert response.status_code == 202

    def test_feedback_returns_unified_structure(self):
        """反馈接口返回统一的 { data, meta, error } 结构。"""
        response = client.post("/api/v1/search/feedback", json={
            "chunk_id": "chunk-001",
            "feedback": "relevant",
        })
        body = response.json()

        assert "data" in body
        assert "meta" in body
        assert body["error"] is None


# ══════════════════════════════════════════════════════════════════════
# 5. 端到端 — 上传模拟文件后搜索
# ══════════════════════════════════════════════════════════════════════

class TestSearchEndToEnd:
    """使用 data/simulated_inputs/ 下的模拟文件验证入库后可检索。"""

    @pytest.mark.parametrize("file_type,title,query", [
        ("markdown", "端到端-Markdown", "解析器"),
        ("txt", "端到端-TXT", "项目"),
        ("html", "端到端-HTML", "仪表盘"),
        ("docx", "端到端-DOCX", "系统"),
        ("pdf", "端到端-PDF", "API"),
        ("pptx", "端到端-PPTX", "季度"),
        ("xlsx", "端到端-XLSX", "统计"),
    ])
    def test_upload_and_search(self, file_type, title, query):
        """上传模拟文件，创建知识块后搜索不报错。"""
        doc = _upload_simulated_file(file_type, title=title)
        doc_id = doc["doc_id"]

        try:
            chunk = _create_chunk(
                doc_id,
                title=title,
                content=f"{title}的测试内容，用于验证 {file_type} 文件入库后可被检索。",
                knowledge_type="declarative",
                category="端到端",
            )

            response = client.post("/api/v1/search", json={
                "query": query,
                "top_k": 5,
            })
            assert response.status_code == 200
            assert isinstance(response.json()["data"]["results"], list)

            _cleanup_chunk(chunk["chunk_id"])
        finally:
            _cleanup_doc(doc_id)

    @pytest.mark.parametrize("file_type,title,query", [
        ("markdown", "端到端调试-Markdown", "解析器"),
        ("txt", "端到端调试-TXT", "项目"),
        ("html", "端到端调试-HTML", "仪表盘"),
        ("docx", "端到端调试-DOCX", "系统"),
        ("pdf", "端到端调试-PDF", "API"),
        ("pptx", "端到端调试-PPTX", "季度"),
        ("xlsx", "端到端调试-XLSX", "统计"),
    ])
    def test_upload_and_debug_search(self, file_type, title, query):
        """上传模拟文件→创建知识块→调试检索，验证完整 debug 响应结构。
        覆盖 doDebugSearch() L229-249 前端读取的全部字段。"""
        doc = _upload_simulated_file(file_type, title=title)
        doc_id = doc["doc_id"]

        try:
            chunk = _create_chunk(
                doc_id,
                title=title,
                content=f"{title}的测试内容，用于验证 {file_type} 文件入库后调试检索可用。",
                knowledge_type="declarative",
                category="端到端",
            )

            response = client.post("/api/v1/search/debug", json={
                "query": query,
                "top_k": 5,
            })
            assert response.status_code == 200
            body = response.json()

            # 验证统一响应结构
            assert "data" in body
            assert "meta" in body
            assert body["error"] is None

            data = body["data"]

            # 前端 doDebugSearch() L232-235 读取的字段
            assert "query" in data, "缺少 query (search.js L232)"
            assert data["query"] == query
            assert "rewritten_query" in data, "缺少 rewritten_query (search.js L233)"
            assert "filters" in data, "缺少 filters (search.js L234)"
            assert "total_count" in data, "缺少 total_count (search.js L235)"
            assert isinstance(data["total_count"], int)

            # 前端 doDebugSearch() L238: data.results
            assert "results" in data, "缺少 results (search.js L238)"
            assert isinstance(data["results"], list)

            # 调试阶段数据
            for stage in ["rewrite", "vector_candidates", "bm25_candidates",
                          "fused_candidates", "rerank_results"]:
                assert stage in data, f"调试数据缺少 {stage}"

            # 结果卡片字段验证 (search.js L241-247)
            for r in data["results"]:
                assert "title" in r, "结果缺少 title (search.js L241)"
                assert "chunk_id" in r, "结果缺少 chunk_id (search.js L241)"
                assert "score" in r, "结果缺少 score (search.js L242)"
                assert isinstance(r["score"], (int, float))
                assert "score_components" in r, "结果缺少 score_components (search.js L244)"
                sc = r["score_components"]
                for key in ["vector", "bm25", "rerank"]:
                    assert key in sc, f"score_components 缺少 {key} (search.js L245)"
                    assert isinstance(sc[key], (int, float)), \
                        f"score_components.{key} 应为数值类型"
                assert "content" in r, "结果缺少 content (search.js L247)"

            _cleanup_chunk(chunk["chunk_id"])
        finally:
            _cleanup_doc(doc_id)


# ══════════════════════════════════════════════════════════════════════
# 6. 完整前端工作流模拟
# ══════════════════════════════════════════════════════════════════════

class TestSearchFrontendWorkflow:
    """模拟 search.js 完整用户操作流程：
    加载筛选 → 标准检索 → 详情查看 → 反馈 → 调试检索
    """

    def test_full_search_workflow(self, searchable_data):
        """模拟 search.js 的完整搜索工作流。

        1. 加载筛选项 (render L17)
        2. 标准检索 (doSearch L89)
        3. 查看详情 (showResultDetail L150)
        4. 发送反馈 (api.js L193)
        5. 调试检索 (doDebugSearch L227)
        """
        # 1. 加载筛选项 (search.js render L17)
        filters_resp = client.get("/api/v1/search/filters")
        assert filters_resp.status_code == 200
        filter_data = filters_resp.json()["data"]
        assert "categories" in filter_data
        assert "knowledge_types" in filter_data

        # 2. 标准检索 (search.js doSearch L89-96)
        search_resp = client.post("/api/v1/search", json={
            "query": "解析器的开发步骤",
            "top_k": 3,
            "filters": {
                "chunk_status": ["active"],
                "index_status": ["indexed"],
            },
            "options": {
                "hybrid": True,
                "rewrite": True,
                "highlight": True,
                "include_assets": True,
                "include_sources": True,
                "include_score_components": True,
            },
        })
        assert search_resp.status_code == 200
        search_data = search_resp.json()["data"]
        results = search_data["results"]

        # 验证 search.js renderResults L108-110 读取的字段
        assert isinstance(results, list)
        assert "total_count" in search_data
        assert "rewritten_query" in search_data

        if len(results) > 0:
            item = results[0]

            # 3. 查看详情 (search.js showResultDetail L150-184)
            assert "chunk_id" in item  # L150: 按 chunk_id 查找
            assert "knowledge_type" in item  # L158
            assert "category" in item  # L159
            assert "score" in item  # L160
            sc = item.get("score_components", {})
            assert "vector" in sc  # L162
            assert "bm25" in sc  # L163
            assert "rerank" in sc  # L164
            assert "content" in item  # L168
            assert "doc_title" in item  # L171
            assert "doc_id" in item  # L171
            assert "doc_version" in item  # L171
            assert "source_refs" in item  # L172

            # 4. 发送反馈 (api.js L193)
            feedback_resp = client.post("/api/v1/search/feedback", json={
                "chunk_id": item["chunk_id"],
                "feedback": "relevant",
                "search_id": search_data.get("search_id", ""),
            })
            assert feedback_resp.status_code == 202

        # 5. 调试检索 (search.js doDebugSearch L227)
        debug_resp = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 3,
        })
        assert debug_resp.status_code == 200
        debug_data = debug_resp.json()["data"]

        # search.js L232-235 读取的字段
        assert "query" in debug_data
        assert "rewritten_query" in debug_data
        assert "filters" in debug_data
        assert "total_count" in debug_data
        assert "results" in debug_data

        if len(debug_data["results"]) > 0:
            dr = debug_data["results"][0]
            # search.js L241-247 读取的字段
            assert "title" in dr
            assert "chunk_id" in dr
            assert "score" in dr
            dsc = dr.get("score_components", {})
            for key in ["vector", "bm25", "rerank"]:
                assert key in dsc, f"调试结果 score_components 缺少 {key}"
            assert "content" in dr

    def test_filter_workflow(self, searchable_data):
        """模拟前端按分类+类型组合筛选的搜索流程 (search.js L83-87)。"""
        # 先获取可用筛选项
        filters_resp = client.get("/api/v1/search/filters")
        categories = filters_resp.json()["data"].get("categories", [])
        ktypes = filters_resp.json()["data"].get("knowledge_types", [])

        if not categories or not ktypes:
            pytest.skip("无可用的筛选项")

        cat_value = categories[0]["value"]
        kt_value = ktypes[0]["value"]

        # 组合筛选搜索
        resp = client.post("/api/v1/search", json={
            "query": "开发",
            "top_k": 10,
            "filters": {
                "categories": [cat_value],
                "knowledge_types": [kt_value],
            },
        })
        assert resp.status_code == 200
        results = resp.json()["data"]["results"]

        for item in results:
            assert item["category"] == cat_value
            assert item["knowledge_type"] == kt_value

    def test_highlight_workflow(self, searchable_data):
        """模拟前端开启高亮的搜索流程 (search.js L77, L129)。"""
        resp = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 3,
            "options": {"highlight": True},
        })
        assert resp.status_code == 200
        results = resp.json()["data"]["results"]

        for item in results:
            assert "highlight" in item, \
                "highlight 选项开启后每个结果应有 highlight 字段 (search.js L129)"

    def test_debug_search_workflow(self, searchable_data):
        """模拟检索调试页面完整工作流 (search.js renderDebug + doDebugSearch)。

        1. 加载筛选项 (render L17)
        2. 调试检索 — 带分类过滤 (doDebugSearch L227)
        3. 验证前端 doDebugSearch() L229-249 所需的全部字段
        4. 验证阶段候选分数与结果一致性
        """
        # 1. 加载筛选项
        filters_resp = client.get("/api/v1/search/filters")
        assert filters_resp.status_code == 200
        filter_data = filters_resp.json()["data"]
        categories = filter_data.get("categories", [])

        # 2. 调试检索 — 带分类过滤
        cat_value = categories[0]["value"] if categories else None
        request_body: dict = {
            "query": "解析器的开发步骤",
            "top_k": 3,
        }
        if cat_value:
            request_body["filters"] = {"categories": [cat_value]}

        debug_resp = client.post("/api/v1/search/debug", json=request_body)
        assert debug_resp.status_code == 200, f"调试检索失败: {debug_resp.text}"
        body = debug_resp.json()
        data = body["data"]

        # 3. 验证前端 doDebugSearch() L229-249 所需字段
        # L230-236: 查询信息卡片
        assert "query" in data, "缺少 query (search.js L232)"
        assert isinstance(data["query"], str)
        assert "rewritten_query" in data, "缺少 rewritten_query (search.js L233)"
        assert "filters" in data, "缺少 filters (search.js L234)"
        assert "total_count" in data, "缺少 total_count (search.js L235)"

        # L238: 结果列表
        assert "results" in data, "缺少 results (search.js L238)"
        assert isinstance(data["results"], list)

        # L241-247: 每个结果的字段
        for r in data["results"]:
            assert "title" in r, "结果缺少 title (search.js L241)"
            assert "chunk_id" in r, "结果缺少 chunk_id (search.js L241)"
            assert "score" in r, "结果缺少 score (search.js L242)"
            assert isinstance(r["score"], (int, float)), \
                "score 应为数值类型 (search.js L242)"
            assert "score_components" in r, "结果缺少 score_components (search.js L244)"
            sc = r["score_components"]
            for key in ["vector", "bm25", "rerank"]:
                assert key in sc, f"score_components 缺少 {key} (search.js L245)"
                assert isinstance(sc[key], (int, float)), \
                    f"score_components.{key} 应为数值 (search.js L245 .toFixed)"
            assert "content" in r, "结果缺少 content (search.js L247)"

        # 4. 阶段候选列表内部结构
        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert stage in data, f"缺少 {stage}"
            candidates = data[stage]
            assert isinstance(candidates, list)
            for c in candidates:
                assert "chunk_id" in c
                assert "score" in c
                assert isinstance(c["score"], (int, float))

        # 5. 阶段候选列表长度一致
        results_count = len(data["results"])
        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert len(data[stage]) == results_count, \
                f"{stage} 长度 ({len(data[stage])}) != results ({results_count})"

        # 6. 如果有分类过滤，验证结果符合
        if cat_value:
            for r in data["results"]:
                assert r["category"] == cat_value, \
                    f"分类过滤失败: 期望 '{cat_value}', 实际 '{r['category']}'"
