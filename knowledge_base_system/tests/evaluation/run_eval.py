"""评测触发脚本（无参数）。

加载全局评测数据集，重建检索索引，逐条查询并计算标准 Recall@5
和 MRR，最后将结果追加写入 results/history.jsonl。

使用方式：
    cd knowledge_base_system
    python tests/evaluation/run_eval.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# 确保 knowledge_base_system 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.evaluation.dataset import load_dataset
from tests.evaluation.metrics import mrr, recall_at_k, safe_mean
from tests.evaluation.storage import append_eval_result
from tests.evaluation.dataset import EvalItem


def _run() -> int:
    """执行评测主流程。"""
    # ── 1. 加载全局评测数据集 ──
    try:
        dataset = load_dataset()
    except FileNotFoundError:
        print("❌ 全局评测数据集 eval_dataset.json 不存在。")
        print("   请先入库文档（自动生成评测数据），然后用 merge_to_global.py 合并到全局。")
        return 1

    if not dataset:
        print("⚠️  评测数据集为空，请先添加评测数据。")
        return 1

    # ── 2. 过滤过期标注（预期 chunk 已不存在的条目） ──
    from app.core.deps import chunk_store

    all_expected_ids = set()
    for item in dataset:
        all_expected_ids.update(item.expected_chunk_ids)

    existing_ids: set[str] = set()
    if all_expected_ids and hasattr(chunk_store, "get_batch"):
        existing_chunks = chunk_store.get_batch(list(all_expected_ids))
        existing_ids = {c.chunk_id for c in existing_chunks}

    stale_count = 0
    active_dataset: list[EvalItem] = []
    for item in dataset:
        if item.expected_chunk_ids and not any(
            cid in existing_ids for cid in item.expected_chunk_ids
        ):
            stale_count += 1
            continue
        active_dataset.append(item)

    if stale_count:
        print(f"🗑️  过滤 {stale_count} 条过期标注（chunk 已被删除）")

    if not active_dataset:
        print("⚠️  过滤后无有效评测条目，请先入库文档生成新的评测数据。")
        return 1

    # ── 3. 初始化检索索引 ──
    from app.core.deps import rebuild_retrieval_indexes_from_chunks, retrieval_pipeline

    rebuilt = rebuild_retrieval_indexes_from_chunks()
    if rebuilt == 0:
        print("⚠️  没有可评测的持久化知识块，请先完成文档入库。")
        return 1

    # ── 4. 逐条查询并计算指标 ──
    recall_scores: list[float | None] = []
    mrr_scores: list[float | None] = []

    print(f"\n🔍 检索索引已重建: {rebuilt} 个 chunks")
    print(f"📊 评测中，共 {len(active_dataset)} 条查询（已过滤 {stale_count} 条过期）...\n")

    start_time = time.time()

    for i, item in enumerate(active_dataset, 1):
        try:
            result = retrieval_pipeline.search(query=item.query, top_k=5)
            chunk_ids = [r.chunk_id for r in result.results]
        except Exception as exc:
            print(f"  [{i}/{len(active_dataset)}] 检索异常: {item.query[:40]}... ({exc})")
            recall_scores.append(None)
            mrr_scores.append(None)
            continue

        r5 = recall_at_k(chunk_ids, item.expected_chunk_ids, k=5)
        m = mrr(chunk_ids, item.expected_chunk_ids)
        recall_scores.append(r5)
        mrr_scores.append(m)

        # 每 10 条输出一次进度
        if i % 10 == 0 or i == len(active_dataset):
            print(f"  [{i}/{len(active_dataset)}] 已完成...")

    elapsed = time.time() - start_time

    # ── 4. 汇总指标 ──
    avg_recall = safe_mean(recall_scores)
    avg_mrr = safe_mean(mrr_scores)
    annotated_count = sum(1 for v in recall_scores if v is not None)

    # ── 5. 控制台输出 ──
    print()
    print("=" * 50)
    print("📊 评测完成")
    print("=" * 50)
    print(f"  查询总数:       {len(active_dataset)}（已过滤 {stale_count} 条过期）")
    print(f"  已标注查询数:    {annotated_count}")
    print(f"  耗时:           {elapsed:.1f}s")
    print(f"  Recall@5:       {avg_recall:.4f}" if avg_recall is not None else "  Recall@5:       N/A")
    print(f"  MRR:            {avg_mrr:.4f}" if avg_mrr is not None else "  MRR:            N/A")
    print()

    # ── 6. 追加评测历史 ──
    from app.core.config import get_settings
    cfg = get_settings(reload_env=True)

    search_params = {
        "rewrite": True,           # 当前管线始终启用查询改写
        "vector_top_k": cfg.vector_top_k,
        "bm25_top_k": cfg.bm25_top_k,
        "rrf_k": cfg.fusion_top_k,
        "rerank": True,            # 当前管线始终启用重排序
        "top_k": 5,
    }

    metrics = {
        "recall_at_5": avg_recall,
        "mrr": avg_mrr,
    }

    history_path = append_eval_result(
        search_params=search_params,
        metrics=metrics,
        query_count=len(active_dataset),
    )
    print(f"📄 结果已追加: {history_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
