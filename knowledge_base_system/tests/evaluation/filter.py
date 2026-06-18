"""评测数据集筛选器。

支持多维度筛选评测数据：
- 按文档 ID 筛选（doc_id）
- 按业务分类筛选（category）
- 按难度筛选（difficulty: easy/medium/hard）
- 按来源筛选（source: auto/manual）
- 按时间范围筛选（since: 最近 N 天）
- 按查询关键词筛选（query 模糊匹配）
- 随机抽样（sample）
- 只跑上次失败的用例（failed）
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from tests.evaluation.dataset import EvalItem

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class FilterCriteria:
    """筛选条件配置。"""

    doc_id: str | None = None
    category: str | None = None
    difficulty: str | None = None
    source: str | None = None
    since_days: int | None = None
    query_keyword: str | None = None
    sample_count: int | None = None
    only_failed: bool = False


class DatasetFilter:
    """评测数据集筛选器。

    应用多个筛选条件的组合，返回符合所有条件的评测条目。
    """

    def __init__(self, criteria: FilterCriteria | None = None) -> None:
        self.criteria = criteria or FilterCriteria()
        self._filters: list[Callable[[EvalItem], bool]] = []
        self._build_filters()

    def _build_filters(self) -> None:
        """构建筛选函数链。"""
        c = self.criteria

        if c.doc_id:
            self._filters.append(lambda item: item.source_doc_id == c.doc_id)

        if c.category:
            self._filters.append(lambda item: item.category == c.category)

        if c.difficulty:
            self._filters.append(lambda item: item.difficulty == c.difficulty)

        if c.source:
            self._filters.append(lambda item: item.source == c.source)

        if c.since_days:
            cutoff = datetime.now() - timedelta(days=c.since_days)

            def _by_date(item: EvalItem) -> bool:
                if not item.generated_at:
                    return False
                try:
                    gen_time = datetime.fromisoformat(item.generated_at)
                    return gen_time >= cutoff
                except (ValueError, TypeError):
                    return False

            self._filters.append(_by_date)

        if c.query_keyword:
            kw = c.query_keyword.lower()
            self._filters.append(lambda item: kw in item.query.lower())

        if c.only_failed:
            self._filters.append(lambda item: item._last_passed is False)

    def apply(self, dataset: list[EvalItem]) -> list[EvalItem]:
        """应用所有筛选条件。

        Args:
            dataset: 原始评测数据集

        Returns:
            筛选后的评测数据集
        """
        result = dataset

        # 应用基础筛选
        for f in self._filters:
            result = [item for item in result if f(item)]

        # 随机抽样（如果配置了）
        if self.criteria.sample_count and self.criteria.sample_count < len(result):
            result = random.sample(result, self.criteria.sample_count)

        return result

    @staticmethod
    def load_last_failed(dataset: list[EvalItem]) -> None:
        """加载上次评测失败的条目，标记到 item._last_passed。

        Args:
            dataset: 评测数据集（会被原地修改）
        """
        latest = RESULTS_DIR / "latest.json"
        if not latest.exists():
            return

        try:
            with open(latest, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, KeyError, TypeError):
            return

        # 构建失败查询集合
        failed_queries = set()
        for detail in data.get("details", []):
            recall = detail.get("recall@5")
            mrr = detail.get("mrr")
            kw_recall = detail.get("kw_recall@5")
            # 只要有一个维度失败就算失败
            if (recall is not None and recall == 0) or \
               (mrr is not None and mrr == 0) or \
               (kw_recall is not None and kw_recall == 0):
                failed_queries.add(detail["query"])

        # 标记到条目
        for item in dataset:
            if item.query in failed_queries:
                item._last_passed = False
            else:
                item._last_passed = True

    def get_summary(self, original_count: int, filtered_count: int) -> str:
        """生成筛选摘要文本。

        Args:
            original_count: 原始数据条目数
            filtered_count: 筛选后的数据条目数

        Returns:
            摘要字符串
        """
        c = self.criteria
        conditions = []

        if c.doc_id:
            conditions.append(f"文档={c.doc_id}")
        if c.category:
            conditions.append(f"分类={c.category}")
        if c.difficulty:
            conditions.append(f"难度={c.difficulty}")
        if c.source:
            conditions.append(f"来源={c.source}")
        if c.since_days:
            conditions.append(f"最近{c.since_days}天")
        if c.query_keyword:
            conditions.append(f"关键词='{c.query_keyword}'")
        if c.sample_count:
            conditions.append(f"抽样={c.sample_count}")
        if c.only_failed:
            conditions.append("仅上次失败")

        if not conditions:
            return f"全量评测: {filtered_count} 条"

        return f"筛选后: {filtered_count}/{original_count} 条 ({', '.join(conditions)})"


def apply_filters(
    dataset: list[EvalItem],
    doc_id: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    source: str | None = None,
    since_days: int | None = None,
    query_keyword: str | None = None,
    sample_count: int | None = None,
    only_failed: bool = False,
) -> tuple[list[EvalItem], str]:
    """便捷函数：创建筛选器并应用。

    参数与 FilterCriteria 一一对应。

    Returns:
        (筛选后的数据集, 筛选摘要文本)
    """
    if only_failed:
        DatasetFilter.load_last_failed(dataset)

    criteria = FilterCriteria(
        doc_id=doc_id,
        category=category,
        difficulty=difficulty,
        source=source,
        since_days=since_days,
        query_keyword=query_keyword,
        sample_count=sample_count,
        only_failed=only_failed,
    )

    ds_filter = DatasetFilter(criteria)
    original_count = len(dataset)
    filtered = ds_filter.apply(dataset)
    summary = ds_filter.get_summary(original_count, len(filtered))

    return filtered, summary
