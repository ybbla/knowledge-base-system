"""手动合并脚本 — 将指定文档的评测数据合并到全局数据集中。

使用方式：
    cd knowledge_base_system
    python tests/evaluation/merge_to_global.py <doc_id>

行为：
    - 在 datasets/ 目录下查找文件名前缀匹配 doc_id 的 JSON 文件
    - 读取其中的 items 数组，按 query 文本去重
    - 追加到 eval_dataset.json，已存在（source 为 "manual"）的条目不被覆盖
    - 输出合并结果摘要
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 knowledge_base_system 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.evaluation.dataset import load_dataset, save_dataset
from tests.evaluation.storage import DATASETS_DIR, init_storage


def merge_doc_to_global(doc_id: str) -> int:
    """将指定文档的评测数据合并到全局数据集。

    Args:
        doc_id: 文档 ID（完整或前缀均可，用于匹配文件名）。

    Returns:
        实际新增的条目数量。
    """
    init_storage()

    # ── 1. 查找匹配的分文档数据集 ──
    matching_files = sorted(DATASETS_DIR.glob(f"doc_{doc_id[:12]}*.json"))
    if not matching_files:
        print(f"❌ 未找到文档 {doc_id} 的评测数据文件")
        print(f"   在 {DATASETS_DIR} 中搜索 doc_{doc_id[:12]}*.json")
        return 0

    print(f"📂 找到 {len(matching_files)} 个匹配文件:")
    for f in matching_files:
        print(f"   - {f.name}")

    # ── 2. 收集所有待合并的条目 ──
    new_items: list[dict] = []
    for file_path in matching_files:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        new_items.extend(items)
        print(f"   读取 {file_path.name}: {len(items)} 条")

    if not new_items:
        print("⚠️  没有可合并的条目。")
        return 0

    # ── 3. 加载全局数据集，构建已存在 query 的集合 ──
    global_path = Path(__file__).parent / "eval_dataset.json"
    existing_items: list[dict] = []
    if global_path.exists():
        with open(global_path, encoding="utf-8") as f:
            existing_items = json.load(f)

    # 构建已有 query → index 的映射
    existing_queries: dict[str, int] = {}
    for idx, item in enumerate(existing_items):
        q = item.get("query", "")
        if q:
            existing_queries[q] = idx

    # ── 4. 按 query 去重合并 ──
    added = 0
    skipped = 0
    for item in new_items:
        q = item.get("query", "")
        if not q:
            continue

        if q in existing_queries:
            # 已存在 → 检查是否人工标注
            existing_idx = existing_queries[q]
            if existing_items[existing_idx].get("source") == "manual":
                # 人工标注条目不覆盖
                skipped += 1
                continue
            # 自动生成条目可覆盖
            skipped += 1
            continue

        # 新条目 → 添加到全局数据集
        existing_items.append({
            "query": q,
            "expected_chunk_ids": item.get("expected_chunk_ids", []),
            "expected_content_contains": item.get("expected_content_contains", []),
            "doc_id": item.get("doc_id"),
            "source": item.get("source", "auto"),
        })
        existing_queries[q] = len(existing_items) - 1
        added += 1

    # ── 5. 写回全局数据集 ──
    global_path.write_text(
        json.dumps(existing_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\n📊 合并完成:")
    print(f"   新增: {added} 条")
    print(f"   跳过: {skipped} 条（已存在）")
    print(f"   全局数据集总计: {len(existing_items)} 条")
    print(f"   📄 {global_path}")

    return added


def main() -> int:
    """CLI 入口。"""
    if len(sys.argv) < 2:
        print("用法: python merge_to_global.py <doc_id>")
        print()
        print("示例:")
        print("  python merge_to_global.py doc_abc123456789")
        return 1

    doc_id = sys.argv[1]
    added = merge_doc_to_global(doc_id)
    return 0 if added >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
