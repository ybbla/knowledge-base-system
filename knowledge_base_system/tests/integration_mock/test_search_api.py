"""知识搜索页面前后端联调测试（Mock LLM 版）。

与 integration/test_search_api.py 完全相同的测试用例，
但所有火山引擎 LLM/Embedding API 调用由 conftest.py 中的 mock 替代。

运行速度：~5-15 秒（原版 ~5-10 分钟），适用于：
 - 快速回归验证 API 响应结构
 - CI 流水线中的前后端合约测试
 - 开发过程中的高频验证

使用方式：
    cd knowledge_base_system
    pytest tests/integration_mock/test_search_api.py -v

    # 只跑特定测试类
    pytest tests/integration_mock/test_search_api.py::TestStandardSearch -v
"""

from __future__ import annotations

import pytest

# ── 从原始集成测试导入共享组件 ──────────────────────────────────────
# 导入时原始模块会创建 TestClient(app)，但在 mock conftest 的作用下
# 所有 LLM 调用已被 patch，不影响初始化。
from tests.integration.test_search_api import (  # noqa: F401 — re-export for pytest
    # 模块级对象
    client,
    _SIMULATED_FILES,
    _CONTENT_TYPES,
    # 辅助函数（被测试方法通过模块引用调用）
    _create_doc,
    _cleanup_doc,
    _create_chunk,
    _cleanup_chunk,
    _upload_simulated_file,
    # 模块级 fixture
    searchable_data,
    # 原始测试类（以 _Orig 后缀导入，子类化后由 pytest 重新发现）
    TestSearchFilters as _OrigTestSearchFilters,
    TestStandardSearch as _OrigTestStandardSearch,
    TestSearchDebug as _OrigTestSearchDebug,
    TestSearchEndToEnd as _OrigTestSearchEndToEnd,
    TestSearchFrontendWorkflow as _OrigTestSearchFrontendWorkflow,
)


# ══════════════════════════════════════════════════════════════════════
# Mock 版测试类 — 继承原始测试的全部用例，在 mock LLM 环境下运行
# ══════════════════════════════════════════════════════════════════════

class TestSearchFilters(_OrigTestSearchFilters):
    """Mock 版：筛选项接口测试 — GET /api/v1/search/filters。"""
    pass


class TestStandardSearch(_OrigTestStandardSearch):
    """Mock 版：标准检索测试 — POST /api/v1/search。"""

    def test_highlight_content_has_mark_tag(self, searchable_data):
        """Mock 版：只验证 highlight 字段存在，不要求含 <mark>。

        伪向量 + Milvus 混合检索下结果排序不同于真实 embedding，
        可能导致含关键字的块不在 Top-K 中，高亮自然无法命中。
        """
        response = client.post("/api/v1/search", json={
            "query": "解析器",
            "top_k": 5,
            "options": {"highlight": True},
        })
        results = response.json()["data"]["results"]

        if len(results) == 0:
            pytest.skip("无检索结果")

        # 只验证 highlight 字段存在且为字符串
        for item in results:
            assert "highlight" in item, \
                f"highlight 选项开启后结果缺少 highlight 字段: {item.get('chunk_id')}"
            assert isinstance(item["highlight"], str)


class TestSearchDebug(_OrigTestSearchDebug):
    """Mock 版：调试检索测试 — POST /api/v1/search/debug。"""

    def test_stage_candidates_count_consistency(self, searchable_data):
        """Mock 版：放宽 BM25 候选数量检查。

        伪向量 + mock Reranker 不保证各阶段候选数量与最终结果的精确对应，
        只验证结构字段存在。
        """
        response = client.post("/api/v1/search/debug", json={
            "query": "解析器",
            "top_k": 5,
        })
        data = response.json()["data"]

        # 只验证字段存在，不验证数量关系（mock 数据不满足精确一致性）
        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert stage in data, f"调试数据缺少 {stage}"
            assert isinstance(data[stage], list)
            for c in data[stage]:
                assert "chunk_id" in c, f"{stage} 条目缺少 chunk_id"
                assert "score" in c, f"{stage} 条目缺少 score"

    def test_stage_candidate_scores_match_results(self, searchable_data):
        """Mock 版：跳过跨阶段评分一致性校验。

        原因：mock Reranker 返回固定递减分值 (0.95, 0.90, ...)，
        与向量/BM25/RRF 阶段基于伪向量的评分无实际关联，
        因此无法做交叉验证。结构验证由其他测试覆盖。
        """
        pytest.skip("Mock Reranker 分值不与向量/BM25/RRF 阶段关联，跳过交叉校验")


class TestSearchEndToEnd(_OrigTestSearchEndToEnd):
    """Mock 版：端到端测试 — 上传模拟文件后搜索。

    覆盖说明：
    - test_upload_and_search / test_upload_and_debug_search 不再依赖 ingest job。
      上传后直接创建知识块并验证搜索/调试检索，无需轮询或检查 ingest job 状态。
    - _create_chunk 不再传递 index_after_create 参数（v1 API 已移除）。
    """
    pass


class TestSearchFrontendWorkflow(_OrigTestSearchFrontendWorkflow):
    """Mock 版：完整前端工作流模拟测试。"""

    def test_debug_search_workflow(self, searchable_data):
        """Mock 版：放宽阶段候选数量一致性检查。

        伪向量下各阶段候选数量不保证相等，改为 >= 校验。
        """
        import json as json_mod

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
        assert debug_resp.status_code == 200
        body = debug_resp.json()
        data = body["data"]

        # 3. 验证前端 doDebugSearch() L229-249 所需字段
        assert "query" in data
        assert isinstance(data["query"], str)
        assert "rewritten_query" in data
        assert "filters" in data
        assert "total_count" in data

        assert "results" in data
        assert isinstance(data["results"], list)

        for r in data["results"]:
            assert "title" in r
            assert "chunk_id" in r
            assert "score" in r
            assert isinstance(r["score"], (int, float))
            assert "score_components" in r
            sc = r["score_components"]
            for key in ["vector", "bm25", "rerank"]:
                assert key in sc
                assert isinstance(sc[key], (int, float))
            assert "content" in r

        # 4. 阶段候选列表内部结构
        for stage in ["vector_candidates", "bm25_candidates", "fused_candidates", "rerank_results"]:
            assert stage in data
            candidates = data[stage]
            assert isinstance(candidates, list)
            for c in candidates:
                assert "chunk_id" in c
                assert "score" in c
                assert isinstance(c["score"], (int, float))

        # 5. 阶段候选列表长度 — mock 版用 >= 代替 ==
        #    伪向量可能导致各阶段召回数量不同
        results_count = len(data["results"])
        for stage in ["rerank_results"]:
            assert len(data[stage]) >= results_count, \
                f"{stage} 长度 ({len(data[stage])}) 应 >= results ({results_count})"

        # 6. 如果有分类过滤，验证结果符合
        if cat_value:
            for r in data["results"]:
                assert r["category"] == cat_value

        # 验证 filters 可 JSON 序列化
        serialized = json_mod.dumps(data["filters"])
        assert serialized
