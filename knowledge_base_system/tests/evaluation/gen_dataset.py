"""评测数据集自动生成脚本。

从已入库的知识块出发，使用 LLM 自动生成查询 + chunk 标注 + 关键词，
产出可直接使用的 eval_dataset.json。

使用方式::

    # 查看帮助
    python tests/evaluation/gen_dataset.py --help

    # 从指定分类的知识块生成，追加到现有数据集
    python tests/evaluation/gen_dataset.py --category 技术文档

    # 指定查询数量，输出到新文件
    python tests/evaluation/gen_dataset.py --count 30 --output eval_new.json

    # 预览模式：生成但不写入文件，仅打印预览
    python tests/evaluation/gen_dataset.py --dry-run

工作流程:
    1. 从 chunk_store 读取已入库的知识块（可按 category 过滤）
    2. 将 chunk 列表（ID + title + content）发送给 LLM
    3. LLM 生成多样化查询 → 标注期望 chunk_id → 提取关键词
    4. 合并到已有 eval_dataset.json（去重避免覆盖人工修正的条目）
    5. 输出合并后的数据集
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # knowledge_base_system/
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "eval_dataset.json"
QUERIES_PER_CHUNK = 3       # 每个 chunk 生成几条查询
MAX_AUTO_COUNT = 50          # 自动模式最大查询数
LLM_INPUT_CHUNK_LIMIT = 40   # 单次 LLM 调用的 chunk 上限

# ── LLM Prompt ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是知识库检索评测数据构建助手。

你的任务是根据已有知识块列表，生成评测用的查询（query）和标注（annotation）。

要求：
1. 为每个知识块生成 2-4 条不同角度、不同措辞的查询。查询应覆盖：
   - 直接询问（"X 是什么？"）
   - 口语化询问（"怎么判断 X？"）
   - 模糊询问（用户用不精确的表述来问同一个问题）
2. 每条查询标注 `expected_chunk_ids`：哪些知识块能回答该查询（通常 1-2 个）
3. 每条查询标注 `expected_content_contains`：答案应包含的关键词（3-5 个）
4. 关键词应从对应 chunk 正文中提取，确保精确匹配
5. 查询总数不少于指定数量，均匀覆盖所有知识块
6. 必须输出合法 JSON，不要输出 Markdown"""

USER_PROMPT_TEMPLATE = """请为以下 {chunk_count} 个知识块生成至少 {target_count} 条评测查询。

知识块列表：
{chunks_json}

输出格式：
{{
  "items": [
    {{
      "query": "用户可能输入的自然语言查询",
      "expected_chunk_ids": ["chunk_xxx"],
      "expected_content_contains": ["关键词1", "关键词2", "关键词3"]
    }}
  ]
}}"""

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["query", "expected_chunk_ids", "expected_content_contains"],
                "properties": {
                    "query": {"type": "string"},
                    "expected_chunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "expected_content_contains": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


def _load_existing(path: Path) -> list[dict[str, Any]]:
    """加载已有数据集，文件不存在时返回空列表。"""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_chunks(category: str | None = None) -> list[dict[str, Any]]:
    """从 chunk_store 读取已入库的知识块，返回精简列表。"""
    from app.core.deps import chunk_store

    if hasattr(chunk_store, "list_all"):
        chunks = chunk_store.list_all(category=category)
    else:
        all_chunks = list(getattr(chunk_store, "_chunks", {}).values())
        chunks = (
            [c for c in all_chunks if c.category == category]
            if category
            else all_chunks
        )

    if not chunks:
        cat_msg = f"分类 '{category}' 下无" if category else "无"
        raise SystemExit(f"{cat_msg}已入库的知识块。请先入库文档后再生成评测数据。")

    return [
        {
            "chunk_id": c.chunk_id,
            "title": c.title,
            "content": c.content,
        }
        for c in chunks
    ]


def _auto_count(chunk_count: int) -> int:
    """根据 chunk 数量自动计算合理的查询数。"""
    return min(chunk_count * QUERIES_PER_CHUNK, MAX_AUTO_COUNT)


def _generate(chunks: list[dict], target_count: int, dry_run: bool = False) -> list[dict]:
    """调用 LLM 生成评测数据。"""
    from llm.volcengine_client import llm_client

    # 控制单次 LLM 输入大小
    selected = chunks[:LLM_INPUT_CHUNK_LIMIT]
    if len(chunks) > LLM_INPUT_CHUNK_LIMIT:
        print(f"知识块总数 {len(chunks)}，取前 {LLM_INPUT_CHUNK_LIMIT} 个送入 LLM")

    if target_count <= 0:
        target_count = _auto_count(len(selected))

    chunks_json = json.dumps(selected, ensure_ascii=False, indent=2)
    user_msg = USER_PROMPT_TEMPLATE.format(
        chunk_count=len(selected),
        target_count=target_count,
        chunks_json=chunks_json,
    )

    print(f"发送 {len(selected)} 个知识块到 LLM，请求生成 {target_count} 条查询...")

    if dry_run:
        print("[dry-run] 跳过 LLM 调用")
        print()
        print("── LLM 输入预览（前 500 字符）──")
        print(user_msg[:500])
        print("──")
        return []

    result = llm_client.chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        schema=OUTPUT_SCHEMA,
        temperature=0.7,
    )
    return result.get("items", [])


def _merge(
    existing: list[dict],
    new_items: list[dict],
) -> list[dict]:
    """合并新旧数据集：按 query 去重，已有条目保持不变（保护人工修正）。"""
    existing_queries = {item["query"] for item in existing}
    merged = list(existing)
    added = 0

    for item in new_items:
        q = item.get("query", "")
        if q and q not in existing_queries:
            merged.append({
                "query": q,
                "expected_chunk_ids": item.get("expected_chunk_ids", []),
                "expected_content_contains": item.get("expected_content_contains", []),
            })
            existing_queries.add(q)
            added += 1

    if added > 0:
        print(f"新增 {added} 条（跳过 {len(new_items) - added} 条重复）")
    else:
        print("无新增条目，所有 LLM 生成的 query 已存在于现有数据集中。")
    return merged


def _validate(items: list[dict]) -> list[str]:
    """校验数据集条目，返回错误信息列表。"""
    errors: list[str] = []
    for i, item in enumerate(items):
        if not item.get("query"):
            errors.append(f"条目 {i}: 缺少 query")
        if not item.get("expected_chunk_ids") and not item.get("expected_content_contains"):
            errors.append(f"条目 {i} ('{item.get('query', '')}'): 缺少标注")
    return errors


# ── 主入口 ──────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="从已入库知识块自动生成评测数据集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--category",
        default=None,
        help="按业务分类过滤知识块（不指定则使用全部）",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="目标查询数量（0=自动：每 chunk %d 条，上限 %d）" % (QUERIES_PER_CHUNK, MAX_AUTO_COUNT),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认追加到 eval_dataset.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：仅打印 LLM 输入，不调用 API、不写文件",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="完全替换现有数据集（默认：与现有数据合并，保护人工修正的条目）",
    )
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else DEFAULT_DATASET

    # 1. 加载数据
    existing = [] if args.replace else _load_existing(output_path)
    if existing:
        print(f"已加载 {len(existing)} 条现有评测数据")

    chunks = _load_chunks(category=args.category)
    print(f"从 chunk_store 读取 {len(chunks)} 个知识块")

    # 2. LLM 生成
    new_items = _generate(chunks, args.count, dry_run=args.dry_run)
    if args.dry_run:
        return 0

    if not new_items:
        print("LLM 未生成任何条目，请检查 API 配置。")
        return 1

    # 3. 校验
    errors = _validate(new_items)
    if errors:
        print(f"\n⚠ 校验发现 {len(errors)} 个问题：")
        for e in errors:
            print(f"  - {e}")
        print()
        resp = input("存在校验问题，是否继续合并？[y/N] ")
        if resp.lower() != "y":
            print("已取消。")
            return 1

    # 4. 合并 & 保存
    merged = _merge(existing, new_items)
    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n已保存 {len(merged)} 条评测数据到: {output_path}")
    print()
    print("评测数据已生成。运行评测：")
    print(f"  python -m pytest {EVAL_DIR}/test_evaluation.py -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
