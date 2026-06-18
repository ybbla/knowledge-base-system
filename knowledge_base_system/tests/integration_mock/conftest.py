"""集成测试 Mock 配置 — 用模拟函数替换所有 LLM/Embedding 调用。

只 mock 火山引擎的外部 API 调用（chat_json + embed_text），
存储、索引（Faiss/BM25）、API 路由、pipeline 逻辑均保持真实运行，
确保前后端联调合约验证的有效性。

使用方式：
    cd knowledge_base_system
    pytest tests/integration_mock/ -v
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest


# ── 伪向量生成 ────────────────────────────────────────────────────────

def _fake_vector(text: str) -> list[float]:
    """基于文本内容的 MD5 哈希生成确定性 1024 维伪向量。

    向量值范围 [-1, 1]，同一文本始终生成相同向量，
    保证向量检索结果可复现，同时充分模拟真实 embedding 的维度。
    """
    import hashlib
    h = hashlib.md5(text.encode("utf-8")).digest()
    return [(h[i % 16] / 255.0) * 2.0 - 1.0 for i in range(1024)]


# ── Mock LLM chat_json ─────────────────────────────────────────────────

def _mock_chat_json(messages, schema=None, temperature=0.3):
    """模拟 llm_client.chat_json — 根据 system prompt 内容自动区分调用类型。

    支持的调用类型：
    - 查询改写（system prompt 含 "查询改写"）→ 返回 rewritten_query / keywords / intent
    - 候选重排（system prompt 含 "重排"）→ 返回 ranked_results 含 relevance_score
    - 语义提取（其他）→ 返回 chunks
    """
    system_content = ""
    user_content = ""
    for m in messages:
        role = m.get("role", "")
        if role == "system":
            system_content = m.get("content", "")
        elif role == "user":
            user_content = m.get("content", "")

    if "查询改写" in system_content:
        # ── QueryRewriter.rewrite() ──
        # user_content 即为原始查询文本
        query = user_content.strip()
        return {
            "rewritten_query": query,
            "keywords": [query],
            "intent": "factual",
        }

    elif "重排" in system_content:
        # ── Reranker.rerank() ──
        # user_content 格式: "用户问题：xxx\n\n候选知识块：\n[{...}]"
        match = re.search(r"候选知识块：\s*\n?(\[.*\])", user_content, re.DOTALL)
        candidates: list[dict] = []
        if match:
            try:
                candidates = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        ranked = []
        for i, c in enumerate(candidates):
            ranked.append({
                "index": c.get("index", i),
                "chunk_id": c.get("chunk_id", ""),
                "relevance_score": max(0.95 - i * 0.05, 0.1),
                "reason": f"候选 {i + 1} 与查询相关",
            })
        return {"ranked_results": ranked}

    else:
        # ── 语义提取 或 其他调用 ──
        # 注意：PDF/DOCX 解析器提取的原始文本可能含非 UTF-8 字节，
        # 真实 LLM 会做文本归一化处理。mock 必须用安全文本占位，
        # 否则 JSON 序列化时会触发 UnicodeDecodeError。
        safe_content = ""
        if user_content:
            try:
                # 只取 JSON 中元素列表的纯文本部分
                elements = json.loads(user_content) if user_content.strip().startswith("[") else None
                if isinstance(elements, list) and elements:
                    safe_content = str(elements[0].get("text", "") or elements[0])[:200]
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        if not safe_content:
            safe_content = "mock 语义提取内容"
        return {
            "chunks": [
                {
                    "title": "自动提取",
                    "content": safe_content,
                    "knowledge_type": "declarative",
                    "asset_refs": [],
                    "source_refs": [],
                }
            ]
        }


# ── autouse fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="module")
def _mock_llm_and_flush():
    """模块级 autouse fixture：mock LLM 调用 + Milvus flush()。

    仅 mock 以下三类外部依赖：
    1. llm_client.chat_json   — 查询改写 + 候选重排（火山 LLM）
    2. embedding_client.embed_text — 文本向量化（火山 Embedding）
    3. pymilvus.Collection.flush    — 强制刷盘（每块 4 次调用，累积数十秒）

    Milvus 的 upsert/delete/search 等核心操作保持真实，只跳过同步
    刷盘的阻塞等待（Milvus 自身有后台自动刷盘，不影响数据可见性）。

    scope="module" 确保整个测试模块内 mock 持续生效，
    覆盖 searchable_data fixture 的初始化阶段（知识块索引）。
    """
    with patch(
        "llm.volcengine_client.llm_client.chat_json",
        side_effect=_mock_chat_json,
    ), patch(
        "llm.volcengine_client.embedding_client.embed_text",
        side_effect=lambda texts: [_fake_vector(t) for t in texts],
    ), patch(
        "pymilvus.Collection.flush",
        side_effect=lambda *a, **kw: None,  # no-op：跳过同步刷盘
    ):
        yield
