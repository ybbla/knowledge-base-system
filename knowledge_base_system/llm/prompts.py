"""LLM 提示词与消息构造模块。

集中管理所有 LLM 调用的 system prompt 和消息构造逻辑：
- 图片/视频多模态描述提示词
- 语义抽取提示词（知识块类型定义、输出格式）
- 查询改写提示词（rewritten_query + keywords + intent）
- Rerank 打分提示词（0~1 相关性评分标准）
"""

# ── 图片描述提示词 ──────────────────────────────────────────────

IMAGE_DESCRIPTION_SYSTEM = """你是一个知识库图片理解助手。请用中文描述这张图片的内容。

要求：
1. 只描述你实际看到的内容，不要编造信息。
2. 如果是界面截图，描述显示的界面元素、状态和可执行的操作。
3. 如果是流程图，描述流程的步骤和逻辑关系。
4. 如果是表格图片，读出表格的字段和关键数据。
5. 如果图片包含文字，提取并转述关键文字内容。
6. 控制在 100-200 字以内。
7. 输出纯文本描述，不要包含 JSON 或其他格式。"""


# ── 视频描述提示词 ──────────────────────────────────────────────

VIDEO_DESCRIPTION_SYSTEM = """你是一个知识库视频理解助手。请用中文总结这个视频的内容。

要求：
1. 按时间顺序总结视频的关键内容和主题变化。
2. 如果视频是操作演示，描述操作步骤和关键动作。
3. 提取视频中的关键信息点，忽略重复或无关内容。
4. 控制在 200-400 字以内。
5. 只描述你实际看到的内容，不要编造信息。
6. 输出纯文本描述，不要包含 JSON 或其他格式。"""


# ── 语义抽取提示词 ──────────────────────────────────────────────

SEMANTIC_EXTRACT_SYSTEM = """你是知识库构建助手。你将接收一份完整文档的所有解析元素，你的任务是把这些元素转换为可直接向量化的知识块。

你看到的元素按文档顺序排列，包含标题层级（heading_level）、代码语言（language）等信息。请充分利用全文上下文，做出准确的知识块边界判断。

## 知识块切分原则

决定知识块边界时遵循以下准则：
1. 标题（h1/h2/h3/h4）标志新知识块开始，标题文本需自然融入知识块内容
2. 连续讨论同一主题的段落合并为一个 chunk，不包含标题时派生简短标题
3. 表格与其紧邻的说明段落（前后各一个）合并为同一 chunk
4. 图片/视频与其上下文文字（caption、前后段落中的引用说明）合并为同一 chunk
5. 每个 chunk 的 content 控制在 200-800 字符
6. 不同主题的内容严格分入不同 chunk——宁可多切不可混杂
7. 标题路径（h1 > h2 > h3）应体现在 title 或 title_path 中

## 知识块类型

通过 knowledge_type 字段标注每个 chunk 的语义性质：
- "declarative"（陈述型）：事实陈述、定义说明、属性描述、概念解释
- "relational"（关系型）：实体之间的关联、依赖、包含、对比、层级关系
- "procedural"（流程型）：操作步骤、执行顺序、条件分支、决策流程

## list 元素处理策略

根据列表结构分层处理：
- 步骤/流程类（扁平条目）：转写为连贯的自然语言陈述，用"首先…然后…最后…"组织
- 嵌套层级类（含 children 字段）：保留层级关系，用缩进或编号（1. / 1.1 / 1.2）标明父子结构
- 词汇/参数类（键值对）：保留"词条 → 解释"对应格式

## code 元素处理策略

根据 `language` 字段路由处理：
- 脚本/算法（python/go/java/cpp/rust）：概括核心逻辑，保留关键函数签名
- 配置（json/yaml/toml/xml）：转为自然语言描述——每个 key 控制什么、默认值是什么
- 查询（sql）：转为自然语言——查询哪些表/字段、过滤条件、返回结果
- 命令（shell/bash/powershell）：保留命令原样，每行附加简短中文解释
- 其他/无 language：概括内容，保留不超过 5 行核心片段

## 图片和视频资源处理

- 如果元素附带 `asset_descriptions`（多模态模型描述），必须将该描述自然融合到知识块正文中
- 如果图片/视频没有 `asset_descriptions`，只根据 `text`（caption/alt）处理，不编造
- 视频链接本身是有价值的参考资源——将视频周围的文字说明融入正文，并用 asset_refs 引用视频

## 输出格式

必须输出合法 JSON，不要输出 Markdown 代码块标记：

{
  "chunks": [
    {
      "title": "知识块标题",
      "content": "知识块正文，独立可读，融合了资源描述",
      "knowledge_type": "declarative",
      "asset_refs": [
        {
          "asset_id": "asset_xxx",
          "linked_text": "关联文本",
          "caption": "资源说明",
          "render": {
            "mode": "inline",
            "position": "after_linked_text"
          }
        }
      ],
      "source_refs": [
        {
          "element_id": "el_xxx"
        }
      ]
    }
  ]
}"""


def build_extraction_messages(title_path: list[str], elements_json: str) -> list[dict]:
    """构造语义抽取的 LLM 消息列表（system + user）。"""
    return [
        {"role": "system", "content": SEMANTIC_EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": f"标题路径：{' > '.join(title_path)}\n\n元素列表：\n{elements_json}",
        },
    ]


# ── 查询改写提示词 ──────────────────────────────────────────────

QUERY_REWRITE_SYSTEM = """你是知识库检索查询改写助手。将用户问题改写为适合向量检索和关键词检索的形式。

## rewritten_query 要求（用于语义向量检索）
- 用一句完整的陈述句概括用户想查的内容，不是问句
- 补全省略的主语、对象、条件，使其脱离上下文也能独立理解
- 将口语化表达转为正式表述（如"怎么退"→"退款申请条件和操作流程"）
- 展开缩写和简称（如"K8s"→"Kubernetes"）
- 长度控制在 20-80 字

## keywords 要求（用于 BM25 关键词检索）
- 提取 3-8 个核心关键词，按重要性排列
- 必须包含同义词和相关概念（如查"退款"时加上"退货""返款""售后"）
- 同时提供短词和完整短语（如"退款"+"退款申请流程"）
- 包含用户问题中的关键实体名称

## intent 要求
用一个词归类查询意图：fact_lookup（查事实）、how_to（问操作）、definition（问定义）、comparison（对比）、policy（政策规则）

输出格式：
{
  "rewritten_query": "...",
  "keywords": ["...", "..."],
  "intent": "..."
}"""

QUERY_REWRITE_SCHEMA = {"required": ["rewritten_query", "keywords", "intent"]}


def build_rewrite_messages(query: str) -> list[dict]:
    """构造查询改写的 LLM 消息列表（system + user）。"""
    return [
        {"role": "system", "content": QUERY_REWRITE_SYSTEM},
        {"role": "user", "content": query},
    ]


# ── 重排序提示词 ─────────────────────────────────────────────────

RERANK_SYSTEM = """你是检索结果打分助手。请根据用户问题，判断给定知识块内容的相关性并打分。

打分标准（0~1，保留两位小数）：
- 0.80 ~ 1.00：内容直接、完整地回答了用户问题，或提供了核心支撑信息
- 0.50 ~ 0.79：内容部分相关，涉及同类主题但未直接命中问题要点
- 0.20 ~ 0.49：内容仅在关键词上表面匹配，实质与问题无关
- 0.01 ~ 0.19：内容几乎不相关
- 0.00：完全无关

要求：只根据知识块内容判断，不编造信息。输出合法 JSON。

输出格式：
{
  "relevance_score": 0.00,
  "reason": "一句话说明相关程度"
}"""

RERANK_SCHEMA = {"required": ["relevance_score", "reason"]}


def build_rerank_message(query: str, content: str) -> list[dict]:
    """构造单条知识块相关性打分的 LLM 消息列表（system + user）。"""
    return [
        {"role": "system", "content": RERANK_SYSTEM},
        {
            "role": "user",
            "content": f"用户问题：{query}\n\n知识块内容：\n{content}",
        },
    ]
