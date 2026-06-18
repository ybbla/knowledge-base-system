"""知识库检索质量评测脚本。

启动方式：
    1. 安装依赖：pip install -r requirements.txt
    2. 准备评测数据：确认 tests/evaluation/eval_dataset.json 已标注
       expected_chunk_ids 或 expected_content_contains。
    3. 先完成待评测文档入库，让当前进程内的检索索引有数据。
    4. pytest 模式：
       python -m pytest knowledge_base_system/tests/evaluation/test_evaluation.py -v
    5. 独立脚本模式（会生成 Markdown 报告）：
       python knowledge_base_system/tests/evaluation/test_evaluation.py

执行流程：
    1. 加载 eval_dataset.json 并校验字段完整性。
    2. 对每条 query 调用 RetrievalPipeline.search(top_k=5)。
    3. 计算 Recall@5、MRR 和 Keyword Recall@5。
    4. pytest 模式只断言指标合法且不低于环境变量设置的 baseline；
       独立脚本模式会把逐条查询明细写入报告。

结果保存：
    - pytest 模式：结果输出到终端，不额外写文件。
    - 独立脚本模式：knowledge_base_system/tests/results/evaluation/eval_report.md。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.evaluation.dataset import EvalItem, load_dataset
from tests.evaluation.filter import apply_filters
from tests.evaluation.metrics import mrr, recall_at_k, recall_by_keywords, safe_mean
from tests.evaluation.storage import load_all_datasets, load_latest_eval_result, save_eval_result

logger = logging.getLogger(__name__)
BASELINE_RECALL_AT_5 = float(os.getenv("EVAL_BASELINE_RECALL_AT_5", "0.0"))
BASELINE_MRR = float(os.getenv("EVAL_BASELINE_MRR", "0.0"))


def _fmt(v: float | None) -> str:
    """Format a metric value for display."""
    if v is None:
        return "N/A"
    return f"{v:.4f}"


def _fmt_i(v: float | None) -> str:
    """Format a metric value as integer 0/1 or N/A."""
    if v is None:
        return "N/A"
    return f"{v:.0f}"


def run_evaluation(
    search_fn: Callable[[str], list[dict]],
    dataset: list[EvalItem],
) -> dict:
    """Run evaluation over the dataset."""
    details: list[dict] = []
    recall_scores: list[float | None] = []
    mrr_scores: list[float | None] = []
    kw_scores: list[float | None] = []

    for item in dataset:
        t0 = time.time()
        try:
            results = search_fn(item.query)
        except Exception as exc:
            details.append({
                "query": item.query,
                "expected_chunk_ids": item.expected_chunk_ids,
                "expected_keywords": item.expected_content_contains,
                "difficulty": item.difficulty,
                "category": item.category,
                "error": str(exc),
                "recall@5": None, "mrr": None, "kw_recall@5": None,
                "time": time.time() - t0,
            })
            continue

        chunk_ids = [r["chunk_id"] for r in results]
        contents = [r.get("content", "") for r in results]

        r5 = recall_at_k(chunk_ids, item.expected_chunk_ids, k=5)
        m = mrr(chunk_ids, item.expected_chunk_ids)
        kw = recall_by_keywords(contents, item.expected_content_contains, k=5)

        recall_scores.append(r5)
        mrr_scores.append(m)
        kw_scores.append(kw)

        details.append({
            "query": item.query,
            "expected_chunk_ids": item.expected_chunk_ids,
            "expected_keywords": item.expected_content_contains,
            "difficulty": item.difficulty,
            "category": item.category,
            "returned_ids": chunk_ids[:3],
            "recall@5": r5,
            "mrr": m,
            "kw_recall@5": kw,
            "time": time.time() - t0,
        })

    return {
        "total_queries": len(dataset),
        "annotated_chunk_queries": sum(1 for v in recall_scores if v is not None),
        "annotated_kw_queries": sum(1 for v in kw_scores if v is not None),
        "recall@5": safe_mean(recall_scores),
        "mrr": safe_mean(mrr_scores),
        "keyword_recall@5": safe_mean(kw_scores),
        "details": details,
    }


def _build_markdown_report(result: dict, filter_summary: str = "") -> str:
    """Format evaluation results as Markdown with per-dimension statistics."""
    lines: list[str] = []
    lines.append("# 知识库检索评测报告")
    lines.append("")
    if filter_summary:
        lines.append(f"- **筛选条件**: {filter_summary}")
    lines.append(f"- **评测时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **查询总数**: {result['total_queries']}")
    lines.append(f"- **已标注 chunk_id 查询数**: {result['annotated_chunk_queries']}")
    lines.append(f"- **已标注关键词查询数**: {result['annotated_kw_queries']}")
    lines.append("")
    lines.append("## 核心指标")
    lines.append("")
    lines.append("| 指标 | 值 | 说明 |")
    lines.append("|------|-----|------|")
    lines.append(f"| Recall@5 | {_fmt(result['recall@5'])} | 期望 chunk 出现在 top-5 的比例 |")
    lines.append(f"| MRR | {_fmt(result['mrr'])} | 首个命中 chunk 排名倒数的均值 |")
    lines.append(f"| Keyword Recall@5 | {_fmt(result['keyword_recall@5'])} | top-5 中含全部关键词的比例 |")
    lines.append("")
    lines.append("> N/A = 该维度未标注，不计入汇总")
    lines.append("")

    # 分难度统计
    details = result["details"]
    by_difficulty: dict[str, dict] = {}
    by_category: dict[str, dict] = {}

    for d in details:
        diff = d.get("difficulty") or "medium"
        cat = d.get("category") or "未分类"

        for stats_dict, key in [(by_difficulty, diff), (by_category, cat)]:
            if key not in stats_dict:
                stats_dict[key] = {"total": 0, "recall_hit": 0, "mrr_sum": 0.0}
            stats_dict[key]["total"] += 1
            if d.get("recall@5") == 1:
                stats_dict[key]["recall_hit"] += 1
            if d.get("mrr") is not None:
                stats_dict[key]["mrr_sum"] += d["mrr"]

    if len(by_difficulty) > 1:
        lines.append("## 按难度统计")
        lines.append("")
        lines.append("| 难度 | 总数 | Recall@5 | 平均 MRR |")
        lines.append("|------|------|----------|----------|")
        for diff, stats in sorted(by_difficulty.items()):
            recall = stats["recall_hit"] / stats["total"] if stats["total"] > 0 else 0.0
            avg_mrr = stats["mrr_sum"] / stats["total"] if stats["total"] > 0 else 0.0
            lines.append(f"| {diff} | {stats['total']} | {recall:.2%} | {avg_mrr:.4f} |")
        lines.append("")

    if len(by_category) > 1:
        lines.append("## 按分类统计")
        lines.append("")
        lines.append("| 分类 | 总数 | Recall@5 | 平均 MRR |")
        lines.append("|------|------|----------|----------|")
        for cat, stats in sorted(by_category.items()):
            recall = stats["recall_hit"] / stats["total"] if stats["total"] > 0 else 0.0
            avg_mrr = stats["mrr_sum"] / stats["total"] if stats["total"] > 0 else 0.0
            lines.append(f"| {cat} | {stats['total']} | {recall:.2%} | {avg_mrr:.4f} |")
        lines.append("")

    lines.append("## 查询详情")
    lines.append("")
    lines.append("| # | Query | Expected IDs | Keywords | Top-3 | R@5 | MRR | KW | Time |")
    lines.append("|---|-------|-------------|----------|-------|-----|-----|-----|------|")

    for i, d in enumerate(result["details"], 1):
        eids = str(d.get("expected_chunk_ids", []))[:30]
        ekw = str(d.get("expected_keywords", []))[:30]
        if "error" in d:
            lines.append(f"| {i} | {d['query'][:20]} | {eids} | {ekw} | ERROR | - | - | - | {d['time']:.0f}s |")
        else:
            rids = str(d.get("returned_ids", []))[:30]
            lines.append(
                f"| {i} | {d['query'][:20]} | {eids} | {ekw} | {rids} | "
                f"{_fmt_i(d['recall@5'])} | {_fmt(d['mrr'])} | {_fmt_i(d['kw_recall@5'])} | {d['time']:.0f}s |"
            )

    return "\n".join(lines)


def _build_comparison_report(current_metrics: dict) -> str:
    """生成与上次评测结果的对比报告。"""
    latest = load_latest_eval_result()
    if not latest:
        return ""

    prev_metrics = latest.get("metrics", {})
    lines = [""]
    lines.append("## 与上次评测对比")
    lines.append("")
    lines.append("| 指标 | 上次 | 本次 | 变化 |")
    lines.append("|------|------|------|------|")

    for key in ["recall@5", "mrr", "keyword_recall@5"]:
        prev = prev_metrics.get(key, 0) or 0
        curr = current_metrics.get(key, 0) or 0
        diff = curr - prev
        sign = "↑" if diff > 0 else ("↓" if diff < 0 else "=")
        lines.append(f"| {key} | {_fmt(prev)} | {_fmt(curr)} | {sign} {abs(diff)*100:.1f}% |")

    return "\n".join(lines)


# ── pytest integration ───────────────────────────────────────────────


class TestEvaluation:
    """Pytest-compatible evaluation test class."""

    @pytest.fixture(autouse=True)
    def _setup(self, request):
        try:
            self.dataset = load_all_datasets()
        except FileNotFoundError:
            pytest.skip("No eval dataset found")

        # 从 pytest 命令行参数读取筛选条件
        doc_id = request.config.getoption("--eval-doc-id")
        category = request.config.getoption("--eval-category")
        difficulty = request.config.getoption("--eval-difficulty")
        source = request.config.getoption("--eval-source")
        since_days = request.config.getoption("--eval-since")
        query_keyword = request.config.getoption("--eval-query")
        sample_count = request.config.getoption("--eval-sample")
        only_failed = request.config.getoption("--eval-failed")

        # 应用筛选
        self.dataset, self.filter_summary = apply_filters(
            self.dataset,
            doc_id=doc_id,
            category=category,
            difficulty=difficulty,
            source=source,
            since_days=since_days,
            query_keyword=query_keyword,
            sample_count=sample_count,
            only_failed=only_failed,
        )

        if not self.dataset:
            pytest.skip("筛选后无评测数据，请调整筛选条件")

        has_chunk_ids = any(item.expected_chunk_ids for item in self.dataset)
        has_keywords = any(item.expected_content_contains for item in self.dataset)
        if not has_chunk_ids and not has_keywords:
            pytest.skip("Dataset has no annotations (no expected_chunk_ids or keywords)")

        from app.core.deps import rebuild_retrieval_indexes_from_chunks

        self.rebuilt_chunk_count = rebuild_retrieval_indexes_from_chunks()
        if self.rebuilt_chunk_count == 0:
            pytest.skip("No persisted chunks available for retrieval evaluation")

    def _local_search(self, query: str) -> list[dict]:
        from app.core.deps import retrieval_pipeline

        result = retrieval_pipeline.search(query, top_k=5)
        return [
            {"chunk_id": r.chunk_id, "content": r.content}
            for r in result.results
        ]

    def test_evaluation_metrics(self):
        assert self.rebuilt_chunk_count > 0
        logger.info("评测筛选条件: %s", self.filter_summary)

        result = run_evaluation(self._local_search, self.dataset)

        assert result["total_queries"] > 0
        r5 = result["recall@5"]
        mr = result["mrr"]
        if r5 is not None:
            assert 0.0 <= r5 <= 1.0
            assert r5 >= BASELINE_RECALL_AT_5
        if mr is not None:
            assert 0.0 <= mr <= 1.0
            assert mr >= BASELINE_MRR

        logger.info("Recall@5: %s, MRR: %s", _fmt(r5), _fmt(mr))


# ── standalone entry point ────────────────────────────────────────────


def _build_arg_parser():
    """构建命令行参数解析器。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="运行知识库检索评测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 全量评测
  python test_evaluation.py

  # 只评测某个文档的数据
  python test_evaluation.py --doc-id doc_abc123

  # 评测最近 7 天新增的困难用例
  python test_evaluation.py --since 7 --difficulty hard

  # 随机抽 20 条快速验证
  python test_evaluation.py --sample 20

  # 只跑上次失败的查询（回归验证）
  python test_evaluation.py --failed

  # 组合筛选：分类为"检索"的中等难度、包含"并发"的查询
  python test_evaluation.py --category 检索 --difficulty medium --query 并发
        """,
    )

    # 筛选参数
    filter_group = parser.add_argument_group("筛选参数")
    filter_group.add_argument("--doc-id", help="按文档 ID 筛选")
    filter_group.add_argument("--category", help="按业务分类筛选")
    filter_group.add_argument("--difficulty", choices=["easy", "medium", "hard"],
                              help="按难度筛选")
    filter_group.add_argument("--source", choices=["auto", "manual"],
                              help="按来源筛选: auto=自动生成, manual=人工标注")
    filter_group.add_argument("--since", type=int, metavar="DAYS", dest="since_days",
                              help="只评测最近 N 天新增的数据")
    filter_group.add_argument("--query", metavar="KEYWORD", dest="query_keyword",
                              help="按查询关键词模糊匹配")
    filter_group.add_argument("--sample", type=int, metavar="N", dest="sample_count",
                              help="随机抽样 N 条评测")
    filter_group.add_argument("--failed", action="store_true",
                              help="只评测上次失败的查询（回归验证）")

    # 输出参数
    output_group = parser.add_argument_group("输出参数")
    output_group.add_argument("--dataset", help="指定评测集文件路径")
    output_group.add_argument("--output", help="结果输出路径")
    output_group.add_argument("--no-save", action="store_true", help="不保存结果")
    output_group.add_argument("--no-compare", action="store_true", help="不与上次结果对比")
    output_group.add_argument("--verbose", "-v", action="store_true", help="显示每条详情")

    return parser


def main() -> int:
    """评测脚本主入口。"""
    parser = _build_arg_parser()
    args = parser.parse_args()

    # 1. 加载数据集
    if args.dataset:
        dataset = load_dataset(args.dataset)
    else:
        # 加载所有数据集（全局 + 分文档）
        dataset = load_all_datasets()

    if not dataset:
        print("⚠️  无评测数据，请先生成评测数据集。")
        return 1

    # 2. 应用筛选
    dataset, filter_summary = apply_filters(
        dataset,
        doc_id=args.doc_id,
        category=args.category,
        difficulty=args.difficulty,
        source=args.source,
        since_days=args.since_days,
        query_keyword=args.query_keyword,
        sample_count=args.sample_count,
        only_failed=args.failed,
    )

    if not dataset:
        print("⚠️  筛选后无评测数据，请调整筛选条件。")
        return 1

    # 3. 初始化检索
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.core.deps import rebuild_retrieval_indexes_from_chunks, retrieval_pipeline

    rebuilt = rebuild_retrieval_indexes_from_chunks()
    if rebuilt == 0:
        print("⚠️  没有可评测的持久化 chunk，请先完成文档入库。")
        return 1

    def search(query: str) -> list[dict]:
        result = retrieval_pipeline.search(query, top_k=5)
        return [
            {"chunk_id": r.chunk_id, "content": r.content}
            for r in result.results
        ]

    # 4. 运行评测
    print("=" * 60)
    print("📊 知识库检索评测")
    print("=" * 60)
    print(filter_summary)
    print(f"🔍 检索索引已重建: {rebuilt} 个 chunks")
    print()

    start_time = time.time()
    eval_result = run_evaluation(search, dataset)
    duration = time.time() - start_time
    eval_result["duration"] = duration

    # 5. 输出报告
    report = _build_markdown_report(eval_result, filter_summary)

    # 添加对比报告
    if not args.no_compare:
        comparison = _build_comparison_report(eval_result)
        if comparison:
            report += comparison

    print(report)

    # 6. 保存结果
    if not args.no_save:
        metrics = {
            "recall@5": eval_result.get("recall@5"),
            "mrr": eval_result.get("mrr"),
            "keyword_recall@5": eval_result.get("keyword_recall@5"),
            "total_queries": eval_result.get("total_queries"),
            "annotated_chunk_queries": eval_result.get("annotated_chunk_queries"),
            "annotated_kw_queries": eval_result.get("annotated_kw_queries"),
            "duration": duration,
        }
        result_path = save_eval_result(
            metrics=metrics,
            details=eval_result.get("details", []),
            trigger="manual-cli",
        )
        print(f"\n✅ 结果已保存: {result_path}")

        # 同时保存 Markdown 报告
        results_dir = Path(__file__).parent.parent / "results" / "evaluation"
        results_dir.mkdir(parents=True, exist_ok=True)
        report_path = results_dir / "eval_report.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"📄 Markdown 报告: {report_path}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
