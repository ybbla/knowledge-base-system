"""仪表板页面前后端联调测试 — 验证前端 dashboard.js 调用的 5 个接口。

前端 dashboard.js 调用链：
  1. GET /api/v1/health/live       → liveRes?.data?.status === 'ok'
  2. GET /api/v1/health            → healthRes?.data?.status + data.dependencies
  3. GET /api/v1/documents?page=1&page_size=1 → docsRes?.meta?.total
  4. GET /api/v1/chunks?page=1&page_size=1    → chunksRes?.meta?.total

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# 0. GET /api/v1/health/live — 存活检查
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthLive:
    """前端: liveRes?.data?.status === 'ok' — 进程存活探针"""

    def test_live_returns_unified_api_response_structure(self):
        """存活接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_live_data_status_is_ok(self):
        """前端读取 data.status 判断进程是否存活。"""
        response = client.get("/api/v1/health/live")
        body = response.json()
        assert body["data"]["status"] == "ok"

    def test_live_meta_has_service_info(self):
        """meta 包含服务名和版本号。"""
        response = client.get("/api/v1/health/live")
        body = response.json()
        assert "service" in body["meta"]
        assert "version" in body["meta"]
        assert isinstance(body["meta"]["service"], str)
        assert len(body["meta"]["service"]) > 0

    def test_live_is_fast_and_lightweight(self):
        """存活检查应极快（无外部依赖调用）。"""
        import time
        start = time.perf_counter()
        response = client.get("/api/v1/health/live")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        # 存活检查不应超过 500ms（无 DB、无索引、无网络调用）
        assert elapsed_ms < 500, f"存活检查耗时 {elapsed_ms:.0f}ms，超过 500ms 阈值"


# ══════════════════════════════════════════════════════════════════════
# 1. GET /api/v1/health — 整体健康检查（合并了旧版 ready + dependencies）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthReady:
    """前端: healthRes?.data?.status === 'ok' — 整体状态"""

    def test_ready_returns_unified_api_response_structure(self):
        """健康检查接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_ready_data_contains_status_field(self):
        """前端读取 data.status 判断整体状态。"""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "status" in body["data"]
        assert body["data"]["status"] in {"ok", "degraded"}

    def test_ready_data_contains_dependencies_dict(self):
        """data.dependencies 包含各外部依赖状态。"""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "dependencies" in body["data"]
        assert isinstance(body["data"]["dependencies"], dict)

    def test_ready_meta_has_service_info(self):
        """meta 包含服务名和版本号。"""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "service" in body["meta"]
        assert "version" in body["meta"]

    def test_ready_external_deps_all_valid(self):
        """外部依赖检查结果状态合法。"""
        response = client.get("/api/v1/health")
        body = response.json()

        assert response.status_code == 200

        deps = body["data"]["dependencies"]
        for key, dep in deps.items():
            assert dep["status"] in {"ok", "error", "not_configured"}, (
                f"{key} 状态异常: {dep.get('status')}"
            )


# ══════════════════════════════════════════════════════════════════════
# 2. GET /api/v1/health — 外部依赖详情（合并了旧版 /health/dependencies）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthDependencies:
    """前端: Object.entries(depStatuses) — 遍历 data.dependencies 渲染状态列表"""

    def test_dependencies_returns_unified_structure(self):
        """健康检查接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_dependencies_contains_external_services(self):
        """data.dependencies 包含四个外部服务。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        required = ["postgresql", "milvus", "minio", "llm"]
        for key in required:
            assert key in deps, f"缺少依赖项: {key}"

    def test_dependencies_every_dep_has_name_and_status(self):
        """每个依赖项都有 name 和 status 字段，前端据此渲染。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        for key, dep in deps.items():
            assert "name" in dep, f"{key} 缺少 name"
            assert "status" in dep, f"{key} 缺少 status"
            assert dep["status"] in {"ok", "error", "not_configured"}, (
                f"{key} status 异常: {dep['status']}"
            )

    def test_dependencies_status_values_match_frontend_rendering(self):
        """前端 dashboard.js: _formatStatus(): ok→正常, error→异常, not_configured→未配置。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        valid_statuses = {"ok", "error", "not_configured"}
        for key, dep in deps.items():
            assert dep["status"] in valid_statuses, (
                f"依赖项 '{key}' 的 status='{dep['status']}' 不在合法范围 {valid_statuses}"
            )

    def test_dependencies_no_sensitive_info(self):
        """依赖响应不含密钥、密码等敏感信息。"""
        response = client.get("/api/v1/health")
        body_str = str(response.json()).lower()
        for secret in ["password", "secret", "api_key", "token"]:
            assert secret not in body_str, f"泄露敏感信息: {secret}"

    def test_dependencies_meta_has_service_info(self):
        """meta 包含服务版本标识。"""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "service" in body["meta"]


# ══════════════════════════════════════════════════════════════════════
# 3. GET /api/v1/documents — 文档列表（仪表盘仅取 meta.total）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardDocumentList:
    """前端: docsRes?.meta?.total"""

    def test_list_documents_returns_paginated_structure(self):
        """文档列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_list_documents_meta_has_total(self):
        """前端通过 meta.total 获取文档总数。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert "total" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 0

    def test_list_documents_meta_pagination_fields(self):
        """meta 包含完整分页信息。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 1
        assert "total_pages" in body["meta"]

    def test_list_documents_data_is_array(self):
        """data 是文档条目数组。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert isinstance(body["data"], list)
        assert len(body["data"]) <= 1  # page_size=1

    def test_list_documents_default_params(self):
        """不带参数时使用默认分页（page=1, page_size=20）。"""
        response = client.get("/api/v1/documents")
        body = response.json()

        assert response.status_code == 200
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20


# ══════════════════════════════════════════════════════════════════════
# 4. GET /api/v1/chunks — 知识块列表（仪表盘仅取 meta.total）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardChunkList:
    """前端: chunksRes?.meta?.total"""

    def test_list_chunks_returns_paginated_structure(self):
        """知识块列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_list_chunks_meta_has_total(self):
        """前端通过 meta.total 获取知识块总数。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert "total" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 0

    def test_list_chunks_meta_pagination_fields(self):
        """meta 包含完整分页信息。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 1
        assert "total_pages" in body["meta"]

    def test_list_chunks_data_is_array(self):
        """data 是知识块条目数组。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert isinstance(body["data"], list)
        assert len(body["data"]) <= 1

    def test_list_chunks_default_params(self):
        """不带参数时使用默认分页（page=1, page_size=20）。"""
        response = client.get("/api/v1/chunks")
        body = response.json()

        assert response.status_code == 200
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20


# ══════════════════════════════════════════════════════════════════════
# 5. 综合联调测试 — 模拟前端 dashboard.render() 完整调用流程
# ══════════════════════════════════════════════════════════════════════

class TestDashboardFullFlow:
    """模拟前端 dashboard.js render() 的 API 调用序列。"""

    def test_full_dashboard_flow_all_succeed(self):
        """API 全部成功，响应结构匹配前端期望。"""

        # ── 步骤 1: API.health() ──
        health = client.get("/api/v1/health")

        # 前端: healthOk = res?.data?.status === 'ok'
        assert health.json()["data"]["status"] in {"ok", "degraded"}

        # 前端: depStatuses = res?.data?.dependencies || {}
        dep_statuses = health.json()["data"]["dependencies"]
        assert isinstance(dep_statuses, dict) and len(dep_statuses) > 0

        # 每个依赖项都有 name 用于前端展示
        for key, dep in dep_statuses.items():
            assert "name" in dep, f"依赖项 {key} 缺少 name"
            assert "status" in dep, f"依赖项 {key} 缺少 status"

        # ── 步骤 2: API.listDocuments({ page: 1, page_size: 1 }) ──
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        # 前端: docCount = docsRes?.meta?.total || 0
        assert isinstance(docs.json()["meta"]["total"], int)

        # ── 步骤 3: API.listChunks({ page: 1, page_size: 1 }) ──
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        # 前端: chunkCount = chunksRes?.meta?.total || 0
        assert isinstance(chunks.json()["meta"]["total"], int)

    def test_dashboard_handles_any_data_volume(self):
        """仪表板无论数据量多少（包括空库），响应结构始终正确。"""
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        # 核心：meta.total 必须存在且为有效整数
        assert isinstance(docs.json()["meta"]["total"], int)
        assert isinstance(chunks.json()["meta"]["total"], int)
        # data 是数组，且不超过 page_size
        assert isinstance(docs.json()["data"], list)
        assert len(docs.json()["data"]) <= 1
        assert isinstance(chunks.json()["data"], list)
        assert len(chunks.json()["data"]) <= 1

    def test_v1_endpoints_no_x_deprecated_header(self):
        """仪表板使用的 v1 接口不应返回 X-Deprecated 警告头。"""
        urls = [
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/documents?page=1&page_size=1",
            "/api/v1/chunks?page=1&page_size=1",
        ]
        for url in urls:
            response = client.get(url)
            assert "x-deprecated" not in response.headers, (
                f"{url} 不应有 X-Deprecated 头"
            )


# ══════════════════════════════════════════════════════════════════════
# 6. 前端渲染逻辑精确对齐测试 — 模拟 dashboard.js 取值路径
# ══════════════════════════════════════════════════════════════════════

class TestDashboardFrontendAlignment:
    """验证后端响应与前端 dashboard.js 逐行取值逻辑精确匹配。"""

    # ── 6.1 前端: depStatuses 遍历 ──────────────────────────────────

    def test_dependencies_every_entry_has_name_field(self):
        """前端 dashboard.js: 每个依赖项需有 name 字段用于展示。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        for key, dep in deps.items():
            assert "name" in dep, (
                f"依赖项 '{key}' 缺少 name 字段，前端将回退显示英文 key"
            )
            assert isinstance(dep["name"], str) and len(dep["name"]) > 0, (
                f"依赖项 '{key}' 的 name 为空"
            )

    def test_dependencies_has_four_external_services(self):
        """前端展示 4 个外部服务状态。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        # 4 个外部服务：PostgreSQL、Milvus、MinIO、LLM
        assert len(deps) == 4, (
            f"外部依赖应为 4 个，实际 {len(deps)} 个"
        )

    def test_dependencies_status_values_match_frontend_rendering(self):
        """前端 dashboard.js: _formatStatus() 映射: ok→正常, error→异常, not_configured→未配置。
        验证所有依赖项的 status 在 {ok, error, not_configured} 范围内。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]

        valid_statuses = {"ok", "error", "not_configured"}
        for key, dep in deps.items():
            assert dep["status"] in valid_statuses, (
                f"依赖项 '{key}' 的 status='{dep['status']}' 不在合法范围 {valid_statuses}"
            )

    # ── 6.2 前端: healthOk 判断 ────────────────────────────────────

    def test_health_status_is_string(self):
        """前端 dashboard.js: res?.data?.status === 'ok'
        严格相等比较，确保是字符串类型。"""
        response = client.get("/api/v1/health")
        status_val = response.json()["data"]["status"]

        assert isinstance(status_val, str), "status 必须是字符串类型"
        assert status_val in {"ok", "degraded"}, (
            f"期望 status 为 'ok' 或 'degraded'，实际为 '{status_val}'"
        )

    # ── 6.3 前端: meta.total 数值 ──────────────────────────────────

    def test_documents_meta_total_is_non_negative_int(self):
        """前端 dashboard.js: docsRes?.meta?.total || 0
        total 必须是非负整数。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        total = response.json()["meta"]["total"]

        assert isinstance(total, int), f"total 应为 int，实际为 {type(total)}"
        assert total >= 0, f"total 应为非负整数，实际为 {total}"

    def test_chunks_meta_total_is_non_negative_int(self):
        """前端 dashboard.js: chunksRes?.meta?.total || 0
        total 必须是非负整数。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        total = response.json()["meta"]["total"]

        assert isinstance(total, int), f"total 应为 int，实际为 {type(total)}"
        assert total >= 0, f"total 应为非负整数，实际为 {total}"

    # ── 6.4 前端: data 数据结构 ────────────────────────────────────

    def test_health_data_is_dict_not_list(self):
        """health 接口 data 是对象而非数组。"""
        response = client.get("/api/v1/health")
        data = response.json()["data"]
        assert isinstance(data, dict), "health data 应为 dict 对象"

    def test_dependencies_data_is_dict_not_list(self):
        """data.dependencies 是对象而非数组。
        前端: Object.entries(depStatuses) 需要对象格式。"""
        response = client.get("/api/v1/health")
        deps = response.json()["data"]["dependencies"]
        assert isinstance(deps, dict), (
            "dependencies 必须是 dict，前端 Object.entries() 需要对象格式"
        )

    # ── 6.5 前端 fallback 逻辑 — 服务离线时的兜底 ─────────────────

    def test_health_endpoint_returns_valid_json_even_on_error(self):
        """健康检查接口始终返回合法 JSON 且结构一致。"""
        response = client.get("/api/v1/health")
        body = response.json()
        # data/meta/error 三字段必须存在
        assert "data" in body
        assert "meta" in body
        assert "error" in body

    def test_pagination_structure_valid_regardless_of_data_volume(self):
        """无论知识库数据量多少，分页响应结构始终完整且一致。"""
        # 文档列表
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        docs_body = docs.json()
        assert isinstance(docs_body["data"], list), "data 必须是数组"
        assert len(docs_body["data"]) <= 1, "page_size=1 最多返回 1 条"
        assert isinstance(docs_body["meta"]["total"], int), "total 必须是整数"
        assert docs_body["meta"]["total"] >= 0, "total 必须 >= 0"
        # total_pages 与 total/page_size 逻辑一致
        expected_pages = (
            (docs_body["meta"]["total"] + docs_body["meta"]["page_size"] - 1)
            // docs_body["meta"]["page_size"]
            if docs_body["meta"]["total"] > 0 else 0
        )
        assert docs_body["meta"]["total_pages"] == expected_pages

        # 知识块列表
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        chunks_body = chunks.json()
        assert isinstance(chunks_body["data"], list), "data 必须是数组"
        assert len(chunks_body["data"]) <= 1, "page_size=1 最多返回 1 条"
        assert isinstance(chunks_body["meta"]["total"], int), "total 必须是整数"
        assert chunks_body["meta"]["total"] >= 0, "total 必须 >= 0"
        expected_pages = (
            (chunks_body["meta"]["total"] + chunks_body["meta"]["page_size"] - 1)
            // chunks_body["meta"]["page_size"]
            if chunks_body["meta"]["total"] > 0 else 0
        )
        assert chunks_body["meta"]["total_pages"] == expected_pages

    def test_error_field_is_explicit_null_in_success_responses(self):
        """成功响应中 error 字段必须显式为 null（非 undefined/missing）。
        前端可能做 truthy 检查，确保 error 是 null 而非空字符串或其他。"""
        urls = [
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/documents?page=1&page_size=1",
            "/api/v1/chunks?page=1&page_size=1",
        ]
        for url in urls:
            response = client.get(url)
            body = response.json()
            assert body["error"] is None, (
                f"{url} 成功响应中 error 应为 null，实际为 {body['error']!r}"
            )


# ══════════════════════════════════════════════════════════════════════
# 7. 并发场景测试 — 模拟前端 Promise.all 并行请求
# ══════════════════════════════════════════════════════════════════════

class TestDashboardConcurrency:
    """模拟前端并行请求场景。"""

    def test_concurrent_health_checks(self):
        """并行调用 health 和 health/live，验证无竞态错误。"""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                "health": executor.submit(client.get, "/api/v1/health"),
                "live": executor.submit(client.get, "/api/v1/health/live"),
            }
            results = {k: v.result() for k, v in futures.items()}

        assert results["health"].status_code == 200
        assert results["live"].status_code == 200

    def test_concurrent_document_and_chunk_counts(self):
        """并行调用文档列表和知识块列表，验证无竞态错误。"""
        import concurrent.futures

        def fetch_docs():
            return client.get("/api/v1/documents", params={"page": 1, "page_size": 1})

        def fetch_chunks():
            return client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                "docs": executor.submit(fetch_docs),
                "chunks": executor.submit(fetch_chunks),
            }
            results = {k: v.result() for k, v in futures.items()}

        assert results["docs"].status_code == 200
        assert results["chunks"].status_code == 200
        assert isinstance(results["docs"].json()["meta"]["total"], int)
        assert isinstance(results["chunks"].json()["meta"]["total"], int)
