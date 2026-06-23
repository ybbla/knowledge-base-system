## Context

当前 `SemanticExtractor` 将文档元素按 h2 边界一刀切分为多个窗口，超限的窗口再按 token 硬切。设计前提是 LLM 上下文窗口有限，但这是粗粒度的过度切分：文档中大部分 section 并不超限，却因为一刀切策略被拆散。

更合理的策略是：只在需要的地方切，层级越深越好。先用最粗的标题层级（h1），仅对其中超限的 section 用更细的层级再切，以此类推。结构信息被最大程度保留，切分只在必要处发生。

同时借这个机会清理数据模型中长期积累的冗余：幽灵参数、无用的枚举值、错误的兜底逻辑、缺失的状态。

## Goals / Non-Goals

**Goals:**
- 全文路径为主：不超限的文档一次 LLM，LLM 看到完整文档自行决定知识块边界
- 溢出时按标题层级递进切分：h1 → h2 → h3 → …，仅切超限的 section，未超限的不切
- 标题耗尽后 embedding 相似度找断点；embedding 切后仍超限 → token 硬切兜底
- 增强 prompt：注入 `heading_level`、新增 `list` 和 `code` 分层处理策略、新增切分原则
- 删除 AssetRelation 枚举（三个值在下游无行为差异）
- 删除 `_attach_unreferenced_video_assets`（错误的兜底）
- 清理幽灵参数 `ingest_job_id` / `doc_version`
- `document_link` 子文档入库改为后台异步

**Non-Goals:**
- 不改动解析器代码
- 不改动 Milvus schema、索引写入、检索链路
- 不改变 chunk 存储格式
- 不引入新依赖

## Decisions

### 1. 全文优先 + 递进降级

**选择**：

```
全文 elements（token 估算）
  │
  ├─ < SAFE_THRESHOLD → _extract_section(全文) → LLM
  │   │
  │   └─ LLM 失败 → 进入降级路径
  │
  └─ ≥ SAFE_THRESHOLD / LLM 失败
      │
      ├─ 有标题 → _split_recursive(elements, level=1)
      │   │
      │   │  按 heading_level=N 切分 → 仅对超限的 section 下钻
      │   │    ├─ ≤ SAFE_THRESHOLD → _extract_section(完整)
      │   │    │   └─ LLM 失败 → 降级到下一层
      │   │    └─ > SAFE_THRESHOLD → _split_recursive(section, level=N+1)
      │   │
      │   └─ 标题耗尽仍超限 →
      │       ├─ embedding 可用 → 相邻元素相似度断点切分
      │       │   └─ 切后仍超限 → token 硬切 + 20% 重叠
      │       └─ embedding 不可用 → token 硬切 + 20% 重叠
      │
      └─ 无标题 → embedding 断点 / token 硬切
```

**LLM 失败定义**（两种，触发相同降级路径）：
1. **调不通**：API 超时、服务端错误、JSON 解析重试 3 次仍失败 → 抛 Exception
2. **返回空**：正常返回但 `chunks` 为空或每个 chunk 的 `content` 均为空字符串

只有最底层——section 标题耗尽且 LLM 仍失败——才走 `_fallback_chunks`（纯文本拼接，不调 LLM）。

### 2. 标题切分只在超限的 section 上递归

不全局递归。仅超限的 section 向下一层切，兄弟 section 保持完整。

**示例**：一份 PDF 有 12 个 h1 章。10 个章不超限，各自完整走 LLM。第 11 章超限 → 仅此章按 h2 再切。h2 切出的 5 个小节中 4 个不超限，1 个仍超限 → 继续按 h3 切。

### 3. Prompt 增强

**3a. heading_level 注入**（已实现）：
标题元素序列化时携带 `heading_level`，`source_location` 只传 `section_path`。LLM 能区分 h1/h2/h3 而非仅靠路径深度猜测。

**3b. 切分原则**：
- 标题（h1/h2/h3）标志新知识块开始
- 连续同主题段落合并为一个 chunk
- 表格与其紧邻说明段落合并
- 图片/视频与其上下文文字合并
- 每个 chunk 控制在 200-800 字符
- 不同主题内容分入不同 chunk

**3c. list 分层处理策略**：
- 步骤/流程类 → 转写为连贯的自然语言陈述
- 嵌套层级类 → 保留层级关系，用缩进或编号标明父子结构
- 词汇/参数类 → 保留"词条 → 解释"对应格式

**3d. code 按 language 路由处理策略**：
- 脚本/算法（python/go/java）→ 概括逻辑，保留函数签名
- 配置（json/yaml/toml）→ 转为自然语言描述（key 控制什么，默认值是什么）
- 查询（sql）→ 转为自然语言（查询哪些表，过滤条件，返回字段）
- 命令（sh/bash）→ 保留命令原样，每行附加解释
- 其他 → 概括内容，保留不超过 5 行核心片段

**3e. `_elements_to_json` 注入 `language`**：
代码元素序列化时从 `structured_data.language` 提取并注入到 JSON，使 LLM 能区分代码种类。

### 4. 安全阈值

`SAFE_THRESHOLD = context_window × 0.8`，配置化。20% buffer 给 prompt 模板和 LLM 输出。

### 5. source_refs 兜底改为空

LLM 不输出 `source_refs` 时留空。全量关联等于没有溯源。

### 6. 删除 AssetRelation 枚举

**选择**：完全删除。`AssetRef` 移除 `relation` 字段。

**理由**：三个值（`evidence`/`illustration`/`demonstration`）在下游无任何行为差异——不路由、不过滤、不调整渲染。删掉后 prompt 更短，AssetRef 更干净。

**存量数据**：旧 JSON 中的 `relation` 键自然保留在 Milvus/PG 中，Pydantic 反序列化时丢弃。不影响系统运行。

### 7. 删除 `_attach_unreferenced_video_assets`

**理由**：将未被 LLM 引用的视频挂到第一个 chunk 上产生错误关联。原因只有两种——多模态描述失败（修 prompt/预处理层）或 LLM 调用失败（走 fallback）——都不应该用错误的兜底掩盖。

### 8. document_link 异步化

`_process_document_link` 中 `self.ingest(child_doc)` → daemon thread。子文档已在 PG 创建且文件已上传 MinIO，即使后台失败也会更新 status。

### 9. 清理幽灵参数

移除 `SemanticExtractor` 全链路 `ingest_job_id` 和 `KnowledgeChunk` 构造中的 `doc_version`。模型已无这些字段。

### 10. 模型枚举调整

| 枚举 | 改动 | 理由 |
|------|------|------|
| AssetRelation | 删除整个枚举 | 下游无行为差异，纯标签 |
| AssetRef | 移除 `relation` 字段 | 关联枚举删除 |
| ElementType | 不变 | 枚举合理；`blockquote`/`math` 等应由解析器跟进 |

## Risks / Trade-offs

| 风险 | 概率 | 缓解 |
|------|------|------|
| 全文 LLM 失败整篇进入降级 | 低 | 降级逐层重试，大部分内容正常产出 |
| 超大 section 递归到最深层仍超限 | 低 | token 硬切 + 20% 重叠兜底 |
| embedding 切后仍超限 | 中 | embedding 只选切分点，不保证不超限；仍需 token 硬切兜底 |
| LLM 切分质量不如预期 | 中 | prompt 分层策略 + heading_level 注入提供明确指引 |
| 删除 AssetRelation 后存量数据反序列化 | 极低 | Pydantic 默认忽略多余字段；`relation` 字段本就未使用 |
| 删除 `_attach_unreferenced_video_assets` 后视频丢失 | 极低 | prompt 明确要求引用；LLM 失败走 fallback 仍会关联 |
