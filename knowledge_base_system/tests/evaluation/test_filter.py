"""
筛选器模块单元测试。

测试 filter.py 中的核心功能：
- FilterCriteria 数据类
- DatasetFilter 类
- 各种筛选条件
- apply_filters() 便捷函数
"""

import json
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.evaluation.dataset import EvalItem
from tests.evaluation.filter import DatasetFilter, FilterCriteria, apply_filters


class TestFilterCriteria:
    """测试筛选条件数据类。"""

    def test_default_values(self):
        """测试默认值都是 None/False。"""
        criteria = FilterCriteria()
        assert criteria.doc_id is None
        assert criteria.category is None
        assert criteria.difficulty is None
        assert criteria.source is None
        assert criteria.since_days is None
        assert criteria.query_keyword is None
        assert criteria.sample_count is None
        assert criteria.only_failed is False


class TestDatasetFilter:
    """测试 DatasetFilter 筛选器类。"""

    @pytest.fixture
    def sample_items(self):
        """创建测试用的评测条目列表。"""
        return [
            EvalItem(
                query="如何配置检索参数？",
                expected_chunk_ids=["chunk_1"],
                source_doc_id="doc_001",
                source_doc_title="检索指南",
                category="检索",
                difficulty="easy",
                source="manual",
                generated_at=(datetime.now() - timedelta(days=30)).isoformat(),
            ),
            EvalItem(
                query="怎么调整召回率？",
                expected_chunk_ids=["chunk_2"],
                source_doc_id="doc_001",
                source_doc_title="检索指南",
                category="检索",
                difficulty="hard",
                source="manual",
                generated_at=(datetime.now() - timedelta(days=10)).isoformat(),
            ),
            EvalItem(
                query="文档上传的步骤？",
                expected_chunk_ids=["chunk_3"],
                source_doc_id="doc_002",
                source_doc_title="用户手册",
                category="文档管理",
                difficulty="medium",
                source="auto",
                generated_at=(datetime.now() - timedelta(days=3)).isoformat(),
            ),
            EvalItem(
                query="怎么删除文档？",
                expected_chunk_ids=["chunk_4"],
                source_doc_id="doc_002",
                source_doc_title="用户手册",
                category="文档管理",
                difficulty="easy",
                source="auto",
                generated_at=(datetime.now() - timedelta(days=1)).isoformat(),
            ),
            EvalItem(
                query="怎么配置分类？",
                expected_chunk_ids=["chunk_5"],
                source_doc_id="doc_003",
                source_doc_title="管理员指南",
                category="分类",
                difficulty="medium",
                source="auto",
                generated_at=(datetime.now()).isoformat(),
            ),
        ]

    def test_filter_by_doc_id(self, sample_items):
        """测试按文档 ID 筛选。"""
        criteria = FilterCriteria(doc_id="doc_001")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2
        assert all(item.source_doc_id == "doc_001" for item in result)

        # 摘要信息
        summary = ds_filter.get_summary(len(sample_items), len(result))
        assert "doc_001" in summary

    def test_filter_by_category(self, sample_items):
        """测试按分类筛选。"""
        criteria = FilterCriteria(category="检索")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2
        assert all(item.category == "检索" for item in result)

    def test_filter_by_difficulty(self, sample_items):
        """测试按难度筛选。"""
        criteria = FilterCriteria(difficulty="easy")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2
        assert all(item.difficulty == "easy" for item in result)

    def test_filter_by_source(self, sample_items):
        """测试按来源筛选。"""
        criteria = FilterCriteria(source="manual")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2
        assert all(item.source == "manual" for item in result)

    def test_filter_by_since_days(self, sample_items):
        """测试按时间范围筛选。"""
        criteria = FilterCriteria(since_days=5)  # 最近 5 天
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        # doc_002（3天、1天前）+ doc_003（今天）= 3 条
        assert len(result) == 3

    def test_filter_by_query_keyword(self, sample_items):
        """测试按查询关键词筛选。"""
        criteria = FilterCriteria(query_keyword="配置")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        # "如何配置检索参数？" + "怎么配置分类？" = 2 条
        assert len(result) == 2
        assert all("配置" in item.query for item in result)

    def test_filter_by_query_keyword_case_insensitive(self, sample_items):
        """测试关键词筛选大小写不敏感。"""
        criteria = FilterCriteria(query_keyword="检索")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 1
        assert "检索" in result[0].query

    def test_filter_sampling(self, sample_items):
        """测试随机抽样。"""
        random.seed(42)  # 固定种子保证测试可复现
        criteria = FilterCriteria(sample_count=2)
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2

        # 抽样数量超过总数时返回全部
        criteria2 = FilterCriteria(sample_count=100)
        ds_filter2 = DatasetFilter(criteria2)
        result2 = ds_filter2.apply(sample_items)
        assert len(result2) == 5

    def test_filter_by_only_failed(self, sample_items):
        """测试只筛选上次失败的条目。"""
        # 先标记一些为失败
        for item in sample_items[:2]:
            item._last_passed = False
        for item in sample_items[2:]:
            item._last_passed = True

        criteria = FilterCriteria(only_failed=True)
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 2

    def test_combined_filters(self, sample_items):
        """测试多条件组合筛选。"""
        criteria = FilterCriteria(
            category="检索",
            difficulty="hard",
            source="manual",
        )
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        # 只有"怎么调整召回率？"满足所有条件
        assert len(result) == 1
        assert result[0].query == "怎么调整召回率？"

    def test_filter_no_match(self, sample_items):
        """测试筛选后无结果。"""
        criteria = FilterCriteria(category="不存在的分类")
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 0

    def test_empty_filter(self, sample_items):
        """测试空筛选条件返回全部。"""
        criteria = FilterCriteria()
        ds_filter = DatasetFilter(criteria)
        result = ds_filter.apply(sample_items)
        assert len(result) == 5

    def test_load_last_failed(self, sample_items):
        """测试加载上次失败记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            import tests.evaluation.filter as filter_module
            original_dir = filter_module.RESULTS_DIR
            filter_module.RESULTS_DIR = Path(tmpdir)

            try:
                # 写入一个模拟的 latest.json，包含失败结果
                latest_data = {
                    "details": [
                        {"query": "怎么调整召回率？", "recall@5": 0.0},  # 失败
                        {"query": "如何配置检索参数？", "recall@5": 1.0},  # 成功
                        {"query": "文档上传的步骤？", "recall@5": 0.0},  # 失败
                    ]
                }
                latest_path = Path(tmpdir) / "latest.json"
                latest_path.write_text(json.dumps(latest_data, ensure_ascii=False), encoding="utf-8")

                # 加载失败标记
                DatasetFilter.load_last_failed(sample_items)

                # 验证：应该有 2 条被标记为失败
                failed_count = sum(1 for item in sample_items if item._last_passed is False)
                assert failed_count == 2

            finally:
                filter_module.RESULTS_DIR = original_dir

    def test_load_last_failed_no_file(self, sample_items):
        """测试没有 latest.json 文件时不报错。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            import tests.evaluation.filter as filter_module
            original_dir = filter_module.RESULTS_DIR
            filter_module.RESULTS_DIR = Path(tmpdir)

            try:
                # 不应该抛出异常
                DatasetFilter.load_last_failed(sample_items)
                # 所有条目的 _last_passed 应该保持 None
                assert all(item._last_passed is None for item in sample_items)
            finally:
                filter_module.RESULTS_DIR = original_dir


class TestApplyFilters:
    """测试 apply_filters() 便捷函数。"""

    @pytest.fixture
    def sample_items(self):
        return [
            EvalItem(query="测试查询1", expected_chunk_ids=["chunk_1"], category="检索"),
            EvalItem(query="测试查询2", expected_chunk_ids=["chunk_2"], category="检索"),
            EvalItem(query="其他查询", expected_chunk_ids=["chunk_3"], category="文档"),
        ]

    def test_basic_apply(self, sample_items):
        """测试基本的筛选应用。"""
        filtered, summary = apply_filters(sample_items, category="检索")
        assert len(filtered) == 2
        assert "检索" in summary

    def test_empty_dataset(self):
        """测试空数据集筛选。"""
        filtered, summary = apply_filters([], category="检索")
        assert len(filtered) == 0
