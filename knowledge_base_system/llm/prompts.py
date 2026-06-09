# ── Semantic Extraction Prompt ───────────────────────────────────

SEMANTIC_EXTRACT_SYSTEM = """你是知识库构建助手。你的任务是把解析后的文档元素转换为可直接向量化的知识块。

要求：
1. 每个知识块必须独立可读，不依赖前后文。
2. 每个知识块只表达一个高度集中的主题。
3. 表格不得保留为表格，必须转写为自然语言陈述。
4. 图片、视频的语义描述需要自然融合到正文中。
5. 不要编造图片、视频、链接文档中没有的信息。
6. 当前所有知识块的 knowledge_type 都设置为 declarative。
7. 必须输出合法 JSON，不要输出 Markdown。

输出格式：
{
  "chunks": [
    {
      "title": "...",
      "content": "...",
      "knowledge_type": "declarative",
      "asset_refs": [
        {
          "asset_id": "...",
          "relation": "evidence | illustration | demonstration | source | attachment",
          "linked_text": "...",
          "caption": "...",
          "render": {
            "mode": "inline",
            "position": "after_linked_text"
          }
        }
      ],
      "source_refs": [
        {
          "element_id": "..."
        }
      ]
    }
  ]
}"""


def build_extraction_messages(title_path: list[str], elements_json: str) -> list[dict]:
    return [
        {"role": "system", "content": SEMANTIC_EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": f"标题路径：{' > '.join(title_path)}\n\n元素列表：\n{elements_json}",
        },
    ]


# ── Query Rewrite Prompt ─────────────────────────────────────────

QUERY_REWRITE_SYSTEM = """你是知识库检索查询改写助手。请把用户问题改写为适合向量检索和关键词检索的查询。

要求：
1. 保留用户原意。
2. 补全省略的主语、动作和对象。
3. 提取重要关键词。
4. 不要回答问题。
5. 输出合法 JSON。

输出格式：
{
  "rewritten_query": "...",
  "keywords": ["..."],
  "intent": "..."
}"""

QUERY_REWRITE_SCHEMA = {"required": ["rewritten_query", "keywords", "intent"]}


def build_rewrite_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": QUERY_REWRITE_SYSTEM},
        {"role": "user", "content": query},
    ]


# ── Rerank Prompt ────────────────────────────────────────────────

RERANK_SYSTEM = """你是检索结果重排助手。请根据用户问题判断候选知识块的相关性。

要求：
1. 只判断候选块是否能回答或支持回答用户问题。
2. 不要补充候选块以外的信息。
3. 返回从高到低排序的 chunk_id。
4. 输出合法 JSON。

输出格式：
{
  "ranked_results": [
    {
      "chunk_id": "...",
      "relevance_score": 0.0,
      "reason": "..."
    }
  ]
}"""


def build_rerank_messages(query: str, candidates_json: str) -> list[dict]:
    return [
        {"role": "system", "content": RERANK_SYSTEM},
        {
            "role": "user",
            "content": f"用户问题：{query}\n\n候选知识块：\n{candidates_json}",
        },
    ]
