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
QUERIES_PER_CHUNK = 3       # 每个 chunk 生成几条查询
MAX_AUTO_COUNT = 50          # 自动模式最大查询数
LLM_INPUT_CHUNK_LIMIT = 40   # 单次 LLM 调用的 chunk 上限

from tests.evaluation.storage import init_storage

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


def _validate_annotations(
    items: list[dict],
    chunks: list[dict],
) -> tuple[list[dict], list[str]]:
    """校验生成的评测数据，过滤无效条目。

    校验内容：
    1. expected_chunk_ids 必须存在于输入的 chunks 中（防止 LLM 编造 ID）
    2. expected_content_contains 中的关键词必须在对应的 chunk 中存在

    Args:
        items: 待校验的评测条目列表
        chunks: 知识块列表（用于校验 chunk_id 和关键词）

    Returns:
        (有效条目列表, 错误信息列表)
    """
    chunk_id_set = {c["chunk_id"] for c in chunks}
    chunk_content_map = {c["chunk_id"]: c.get("content", "") for c in chunks}

    valid_items = []
    errors = []

    for i, item in enumerate(items):
        query = item.get("query", "")
        if not query:
            errors.append(f"条目 {i}: 缺少 query")
            continue

        expected_chunk_ids = item.get("expected_chunk_ids", [])
        expected_keywords = item.get("expected_content_contains", [])

        # 1. 校验 chunk_id 合法性
        invalid_ids = [cid for cid in expected_chunk_ids if cid not in chunk_id_set]
        if invalid_ids:
            errors.append(f"条目 '{query}': 无效的 chunk_id {invalid_ids}")
            # 过滤掉无效的 chunk_id
            expected_chunk_ids = [cid for cid in expected_chunk_ids if cid in chunk_id_set]
            item["expected_chunk_ids"] = expected_chunk_ids

        # 2. 校验关键词在 chunk 中存在
        if expected_chunk_ids:
            # 收集所有关联 chunk 的内容
            related_content = " ".join(
                chunk_content_map.get(cid, "") for cid in expected_chunk_ids
            )
            # 过滤掉不在任何 chunk 中的关键词
            valid_keywords = [
                kw for kw in expected_keywords
                if kw.lower() in related_content.lower()
            ]
            if len(valid_keywords) != len(expected_keywords):
                invalid_kws = set(expected_keywords) - set(valid_keywords)
                errors.append(f"条目 '{query}': 关键词不在 chunk 中 - {invalid_kws}")
                item["expected_content_contains"] = valid_keywords

        # 只要有一个维度有标注，条目就是有效的
        if expected_chunk_ids or item.get("expected_content_contains"):
            valid_items.append(item)
        else:
            errors.append(f"条目 '{query}': 缺少有效标注，已过滤")

    return valid_items, errors


def generate_for_chunks(
    chunks: list[dict],
    doc_id: str,
    doc_title: str,
    query_count: int = 4,
) -> tuple[list[dict], list[str]]:
    """为指定文档的知识块生成评测数据。

    这是供入库流程调用的 API，不依赖命令行参数。

    Args:
        chunks: 知识块列表，每个 dict 包含 chunk_id, title, content
        doc_id: 文档 ID
        doc_title: 文档标题
        query_count: 期望生成的查询数量（默认 4）

    Returns:
        (生成的条目列表, 错误信息列表)
    """
    from datetime import datetime

    # 调用 LLM 生成
    items = _generate(chunks, target_count=query_count, dry_run=False)
    if not items:
        return [], ["LLM 未生成任何条目"]

    # 校验标注合法性
    valid_items, errors = _validate_annotations(items, chunks)

    # 补充元数据
    for item in valid_items:
        item["source_doc_id"] = doc_id
        item["source_doc_title"] = doc_title
        item["generated_at"] = datetime.now().isoformat()
        item["source"] = "auto"
        # 默认难度为 medium，后续可以根据查询复杂度调整
        item["difficulty"] = "medium"

    return valid_items, errors


# ── 主入口 ──────────────────────────────────────────────────────────

def main() -> int:
    from datetime import datetime

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
        help="输出文件路径（默认写入 datasets/manual_gen_{timestamp}.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：仅打印 LLM 输入，不调用 API、不写文件",
    )
    args = parser.parse_args()

    # 确定输出路径：默认写入 datasets/ 目录，与人工标注的 eval_dataset.json 隔离
    if args.output:
        output_path = Path(args.output)
    else:
        init_storage()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = EVAL_DIR / "datasets" / f"manual_gen_{timestamp}.json"

    # 1. 加载 chunk
    chunks = _load_chunks(category=args.category)
    print(f"从 chunk_store 读取 {len(chunks)} 个知识块")

    # 2. LLM 生成
    new_items = _generate(chunks, args.count, dry_run=args.dry_run)
    if args.dry_run:
        return 0

    if not new_items:
        print("LLM 未生成任何条目，请检查 API 配置。")
        return 1

    # 3. 校验（含 chunk_id 和关键词合法性）
    valid_items, errors = _validate_annotations(new_items, chunks)
    if errors:
        print(f"\n⚠ 校验发现 {len(errors)} 个问题：")
        for e in errors[:10]:
            print(f"  - {e}")
        if len(errors) > 10:
            print(f"  ... 还有 {len(errors) - 10} 条未显示")
        print()

    if not valid_items:
        print("所有条目校验失败，没有可保存的有效数据。")
        return 1

    # 4. 写入文件（不合并到全局，保持自动生成与人工标注隔离）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 如果文件已存在，追加模式（按 query 去重）
    existing = _load_existing(output_path)
    existing_queries = {item["query"] for item in existing}
    added = 0
    for item in valid_items:
        q = item.get("query", "")
        if q and q not in existing_queries:
            existing.append(item)
            existing_queries.add(q)
            added += 1

    output_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if added > 0:
        print(f"✅ 新增 {added} 条评测数据（跳过 {len(valid_items) - added} 条重复）")
    else:
        print("ℹ️  没有新增数据（所有 query 已存在）")
    print(f"📄 输出文件: {output_path}")

    print()
    print("评测数据已生成。运行评测：")
    print(f"  python -m pytest {EVAL_DIR}/test_evaluation.py -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
