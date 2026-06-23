"""评测数据集自动生成模块。

从已入库的知识块出发，使用 LLM 自动生成查询 + chunk_id 标注 + 关键词标注。
仅提供入库流程调用的 API，不暴露 CLI 入口。用户可在入库后直接修改 LLM 生成的评测数据。

工作流程:
    1. 入库完成后，后台线程调用 generate_for_chunks()
    2. 将 chunk 列表（ID + title + content）发送给 LLM
    3. LLM 生成查询 → 标注期望 chunk_id → 提取关键词
    4. _validate_annotations() 校验 chunk_id 合法性和关键词存在性
    5. 返回有效条目列表，供 storage.save_per_doc_dataset() 写入文件
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # knowledge_base_system/
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

LLM_INPUT_CHUNK_LIMIT = 40   # 单次 LLM 调用的 chunk 数量上限

# ── LLM 提示词 ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是知识库检索评测数据构建助手。

你的任务是根据提供的知识块列表，为同一篇文档生成评测用的查询和标注。

要求：
1. 你必须精确生成 {target_count} 条查询，不多不少。将知识块视为同一篇文档的不同章节，查询应围绕文档主题从以下角度展开：
   - 直接询问：用标准表述直接提问（如"X 是什么？""X 包含哪些内容？"）
   - 口语化改写：用日常对话的方式问同一问题（如"怎么判断 X？""X 到底有啥用？"）
   - 模糊查询：用不精确或近似的表述来问（如把"并发限制"说成"同时能处理几个"）
2. 每条查询必须标注 expected_chunk_ids：填充能回答该查询的知识块 ID，通常 1-3 个
3. 每条查询必须标注 expected_content_contains：3-5 个从对应 chunk 正文中直接摘取的关键词，确保在正文中存在
4. 如果只有 1 个知识块，3 条查询都从不同角度问同一个知识块；如果有多个知识块，查询应均匀覆盖
5. 必须输出合法 JSON，禁止 Markdown 包装。每个 chunk ID 必须是知识块列表中真实存在的"""

USER_PROMPT_TEMPLATE = """请为以下文档的 {chunk_count} 个知识块生成恰好 {target_count} 条评测查询。

知识块列表：
{chunks_json}

直接输出 JSON："""

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


def _generate(chunks: list[dict], target_count: int) -> list[dict]:
    """调用 LLM 生成评测数据（内部函数）。

    Args:
        chunks: 知识块列表，每个 dict 包含 chunk_id, title, content。
        target_count: 期望生成的查询数量。

    Returns:
        LLM 返回的 items 列表。
    """
    from llm.volcengine_client import llm_client

    # 控制单次 LLM 输入大小，取前 LLM_INPUT_CHUNK_LIMIT 个
    selected = chunks[:LLM_INPUT_CHUNK_LIMIT]
    if len(chunks) > LLM_INPUT_CHUNK_LIMIT:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("知识块总数 %d，取前 %d 个送入 LLM", len(chunks), LLM_INPUT_CHUNK_LIMIT)

    chunks_json = json.dumps(selected, ensure_ascii=False, indent=2)
    user_msg = USER_PROMPT_TEMPLATE.format(
        chunk_count=len(selected),
        target_count=target_count,
        chunks_json=chunks_json,
    )

    result = llm_client.chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(target_count=target_count)},
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
    """校验 LLM 生成的评测数据，过滤无效条目。

    校验规则：
    1. expected_chunk_ids 必须存在于输入的 chunks 中（防止 LLM 编造 ID）
    2. expected_content_contains 中的关键词必须在对应 chunk 正文中存在

    Args:
        items: 待校验的评测条目列表。
        chunks: 知识块列表（用于校验 chunk_id 和关键词）。

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

        # 1. 校验 chunk_id 合法性 — 过滤 LLM 编造的无效 ID
        invalid_ids = [cid for cid in expected_chunk_ids if cid not in chunk_id_set]
        if invalid_ids:
            errors.append(f"条目 '{query[:30]}': 无效的 chunk_id {invalid_ids}")
            expected_chunk_ids = [cid for cid in expected_chunk_ids if cid in chunk_id_set]
            item["expected_chunk_ids"] = expected_chunk_ids

        # 2. 校验关键词在 chunk 正文中存在
        # 选定用于关键词校验的内容：优先用有效 chunk_id 对应内容，
        # 若所有 chunk_id 都无效则用全部 chunk 内容作为兜底
        if expected_chunk_ids:
            related_content = " ".join(
                chunk_content_map.get(cid, "") for cid in expected_chunk_ids
            )
        else:
            related_content = " ".join(chunk_content_map.values())

        if related_content:
            valid_keywords = [
                kw for kw in expected_keywords
                if kw.lower() in related_content.lower()
            ]
            if len(valid_keywords) != len(expected_keywords):
                invalid_kws = set(expected_keywords) - set(valid_keywords)
                errors.append(f"条目 '{query[:30]}': 关键词不在 chunk 中 - {invalid_kws}")
                item["expected_content_contains"] = valid_keywords

        # 至少有一个维度有标注才认为有效
        if expected_chunk_ids or item.get("expected_content_contains"):
            valid_items.append(item)
        else:
            errors.append(f"条目 '{query[:30]}': 缺少有效标注，已过滤")

    return valid_items, errors


def generate_for_chunks(
    chunks: list[dict],
    doc_id: str,
    doc_title: str,
    query_count: int = 3,
) -> tuple[list[dict], list[str]]:
    """为指定文档的知识块生成评测数据。

    入库流程调用的唯一入口。调用 LLM 生成查询和标注，校验后补充元数据字段。

    Args:
        chunks: 知识块列表，每个 dict 包含 chunk_id, title, content。
        doc_id: 文档 ID。
        doc_title: 文档标题。
        query_count: 期望生成的查询数量，默认 3。

    Returns:
        (有效条目列表, 错误信息列表)。每个有效条目包含 query、
        expected_chunk_ids、expected_content_contains、doc_id、source 五个字段。
    """
    # 调用 LLM 生成
    items = _generate(chunks, target_count=query_count)
    if not items:
        return [], ["LLM 未生成任何条目"]

    # 校验标注合法性
    valid_items, errors = _validate_annotations(items, chunks)

    # 补充元数据（仅保留 doc_id 和 source 两个字段）
    for item in valid_items:
        item["doc_id"] = doc_id
        item["source"] = "auto"

    return valid_items, errors
