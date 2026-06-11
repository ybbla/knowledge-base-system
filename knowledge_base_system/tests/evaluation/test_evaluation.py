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
from tests.evaluation.metrics import mrr, recall_at_k, recall_by_keywords, safe_mean

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


def _build_markdown_report(result: dict) -> str:
    """Format evaluation results as Markdown."""
    lines: list[str] = []
    lines.append("# 知识库检索评测报告")
    lines.append("")
    lines.append(f"- **评测时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **查询总数**: {result['total_queries']}")
    lines.append(f"- **已标注 chunk_id 查询数**: {result['annotated_chunk_queries']}")
    lines.append(f"- **已标注关键词查询数**: {result['annotated_kw_queries']}")
    lines.append("")
    lines.append("| 指标 | 值 | 说明 |")
    lines.append("|------|-----|------|")
    lines.append(f"| Recall@5 | {_fmt(result['recall@5'])} | 期望 chunk 出现在 top-5 的比例 |")
    lines.append(f"| MRR | {_fmt(result['mrr'])} | 首个命中 chunk 排名倒数的均值 |")
    lines.append(f"| Keyword Recall@5 | {_fmt(result['keyword_recall@5'])} | top-5 中含全部关键词的比例 |")
    lines.append("")
    lines.append("> N/A = 该维度未标注，不计入汇总")
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


# ── pytest integration ───────────────────────────────────────────────


class TestEvaluation:
    """Pytest-compatible evaluation test class."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            self.dataset = load_dataset()
        except FileNotFoundError:
            pytest.skip("No eval dataset found")

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
        self.dataset = self.dataset or load_dataset()
        assert self.rebuilt_chunk_count > 0
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dataset = load_dataset()
    print(f"Loaded {len(dataset)} evaluation queries")
    print(f"  annotated chunk_id queries: {sum(1 for i in dataset if i.expected_chunk_ids)}")
    print(f"  annotated keyword queries: {sum(1 for i in dataset if i.expected_content_contains)}")

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.core.deps import rebuild_retrieval_indexes_from_chunks, retrieval_pipeline

    rebuilt = rebuild_retrieval_indexes_from_chunks()
    print(f"Rebuilt retrieval indexes from {rebuilt} persisted chunks")

    def search(query: str) -> list[dict]:
        result = retrieval_pipeline.search(query, top_k=5)
        return [
            {"chunk_id": r.chunk_id, "content": r.content}
            for r in result.results
        ]

    eval_result = run_evaluation(search, dataset)

    report = _build_markdown_report(eval_result)
    print(report)

    results_dir = Path(__file__).parent.parent / "results" / "evaluation"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "eval_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")
