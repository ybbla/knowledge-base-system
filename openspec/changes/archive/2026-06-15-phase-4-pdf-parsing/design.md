## Context

当前知识库系统已完成阶段 4 中 HTML、XLSX、PPTX 三种格式的解析器，均遵循统一的 `DocumentParser` 接口和 `ParseResult` 输出契约。PDF 是该阶段最后一个待实现格式。

现有解析器已形成成熟模式：
- 内容读取：`doc.metadata["raw_content"]`（字节）或 `file://` URI
- 元素生成：按文档顺序生成 `ParsedElement`（title/paragraph/table/image/video/code/unknown）
- 资源提取：图片/视频/附件 URL → `Asset`（去重、MIME 推断）
- 层级追踪：`source_location.section_path`（标题路径）
- 结构保留：表格 → `structured_data.table = {caption, headers, rows}`
- Hash 计算：`compute_hash(raw)` → `doc.source_hash`

PDF 格式的特殊性在于：它没有原生的"标题""段落""列表"语义，只有文字块的位置、字体和大小。PyMuPDF 是 Python 生态中处理 PDF 最成熟的库，既能提取文本块和图片，也提供 TOC 解析和基础表格检测。

## Goals / Non-Goals

**Goals:**
- 将 PDF 文本内容按页面和阅读顺序提取为 `paragraph` 和 `title` 元素
- 利用 TOC（目录大纲）和字体大小启发式识别标题层级
- 检测并提取 PDF 内嵌表格，保留行列表头结构
- 提取内嵌图片 → 创建 image `Asset`（含 content_hash 和原始字节）
- 识别超链接中的视频 URL 和附件 URL → 创建对应 `Asset`
- 每个元素关联页码（`source_location.page`）
- 与现有五种解析器的下游契约完全兼容

**Non-Goals:**
- 版面识别/OCR（复杂多栏、扫描件）— 超出阶段 4 范围
- PDF 表单字段提取 — 不做
- 视频/附件下载或递归解析 — 仅标记为 Asset，阶段 4 不处理
- PDF 注释/批注提取 — 不做
- 加密 PDF 解密 — 不做，加密文件直接报错

## Decisions

### 决策 1：使用 PyMuPDF (fitz) 而非 pdfplumber 或 pypdf

**选择**: PyMuPDF >= 1.24.0

**理由**:
- PyMuPDF 是 C 库 MuPDF 的 Python 绑定，提取文本和图片的速度显著快于纯 Python 方案
- 内置 TOC 提取（`get_toc()`）、链接提取（`get_links()`）、图片提取（`get_images()` + `extract_image()`）
- 新版 PyMuPDF（>= 1.23.0）内置表格检测（`find_tables()`），无需额外依赖
- 对比 pdfplumber：后者表格检测更强但对中文 PDF 的文本提取稳定性不如 PyMuPDF
- 对比 pypdf：后者无表格检测、图片提取 API 较弱

**备选方案**: pdfplumber + pypdf 组合 — 被拒绝，因为会增加两个依赖且整合复杂。

### 决策 2：标题识别与层级传播策略 — TOC 优先 + 字体/粗体兜底

**选择**: 三信号标题检测 + 显式 section_path 栈管理

**标题检测（三个信号，按优先级）**:

1. **TOC 优先**: 读取 `doc.get_toc()` 获取 `(level, title, page_number)` 列表。TOC 条目直接作为 title 元素，按 `page_number` 插入对应页面的元素流开头。不需要与页面文本做模糊匹配——TOC 条目文本即标题文本。
2. **字体大小**: 无 TOC 覆盖时，字体 >= 14pt 的短文本块（≤ 80 字符）识别为标题，`heading_level` 按字号递减推断（如 18pt→1, 16pt→2, 14pt→3）。
3. **粗体标记**: 12–13pt 且 `font_flags` 含 bold 的短文本块识别为低级标题（`heading_level=3`），捕获常见的"粗体同字号子标题"模式。

**section_path 传播机制**:

参照 HtmlParser 的栈管理模式，维护一个 `section_path: list[str]` 栈。每当识别到标题：
- 按 `heading_level` 弹出栈中 >= 当前层级的旧标题（`while len(path) >= level: path.pop()`）
- 将新标题 push 入栈
- 后续所有元素继承当前 `section_path`

```text
示例: TOC = [(1, "第一章", 1), (2, "1.1 背景", 1), (2, "1.2 目标", 3)]

第 1 页:
  title "第一章"    → section_path = ["第一章"]
  paragraph "..."   → section_path = ["第一章"]
  title "1.1 背景"  → section_path = ["第一章", "1.1 背景"]
  paragraph "..."   → section_path = ["第一章", "1.1 背景"]

第 3 页:
  title "1.2 目标"  → section_path = ["第一章", "1.2 目标"]  (1.1 被弹出)
  paragraph "..."   → section_path = ["第一章", "1.2 目标"]
```

**理由**:
- TOC 是最可靠的标题来源（由 PDF 作者显式定义），直接使用避免模糊匹配的不可靠性
- 粗体检测补全了纯字号方案的盲区——大量企业 PDF 使用 bold 12pt 做子标题
- 显式栈管理与 HtmlParser 模式对齐，已有代码可以参考
- 避免过度识别：字号阈值 + 字符数上限（≤ 80 字符）+ 粗体仅在 12–13pt 生效

### 决策 3：文本块排序与合并 — 页面内自上而下、自左而右 + 间距分段

**选择**: 使用 `page.get_text("blocks")` 获取文本块，按 `(y0, x0)` 排序后，基于垂直间距和字体一致性合并/分段

**合并规则**:
1. 相邻文本块，字体大小相同且 `font_flags` 一致 → 合并为同一段落
2. 垂直间距 > 1.5 倍行高（以当前字体大小为基准）→ 即使字体一致也视为新段落
3. 垂直间距 ≤ 1.5 倍行高 → 跨行续排，文本以空格连接

**排序规则**:
- PyMuPDF 的 blocks 已按阅读顺序排序（默认启用 `sort=True`）
- 同一 y 坐标范围内的块从左到右排列

**理由**:
- 仅凭"字体一致"合并会导致段落边界模糊——PDF 中相邻段落常使用相同字体
- 1.5 倍行高阈值是排版惯例（段落间距通常 ≥ 1 个空行）
- 兼容主流单栏 PDF 文档，多栏留待后续

### 决策 4：表格提取策略

**选择**: 优先使用 `page.find_tables()`，失败时降级为普通文本块；同时对 API 可用性做防御

**降级链路**:
1. `hasattr(page, "find_tables")` → False → 整个页面表格检测跳过，所有内容按文本处理
2. `page.find_tables()` → 返回空列表 → 无表格，正常跳过
3. `page.find_tables()` → 抛出异常 → catch 后降级为文本块，记录 warning 日志
4. `page.find_tables()` → 成功 → 提取 `table.extract()` 行列数据

**理由**:
- PyMuPDF >= 1.23.0 的 `find_tables()` 能处理大多数有边框的表格
- `hasattr` 检查防止旧版 PyMuPDF 因缺少 API 导致 `AttributeError` 崩溃
- 表格检测失败时不应阻塞整个解析流程 — 降级为文本块保留信息
- 表格数据结构与现有 `structured_data.table = {headers, rows}` 对齐

### 决策 5：图片提取与资源模型

**选择**: 内嵌图片提取为 `Asset`，通过 `asset_ids` 关联到 `image` 类型 `ParsedElement`

**理由**:
- 与 PPTX 解析器的内嵌图片处理模式对齐
- 计算 `content_hash` 实现文档内/跨文档去重
- 图片原始字节暂存于 Asset 私有属性 `_data`（参考 PPTX 做法），供后续 MinIO 上传链路消费
- 阶段 4 不调用多模态模型进行图片理解

### 决策 6：元素类型映射

| PDF 来源 | ElementType | 说明 |
|----------|-------------|------|
| TOC 条目 或 字体 >= 14pt 的短文本 | `title` | 标题，metadata 含 `heading_level` 和 `page` |
| 普通文本块 | `paragraph` | 段落 |
| `find_tables()` 检测结果 | `table` | 含 `structured_data.table` |
| 内嵌图片 | `image` | text 为 `[图片: page N]` |
| 超链接指向视频 URL | `video` Asset | 不生成独立元素，Asset 挂在所在段落/图片上 |
| 超链接指向附件 URL | `attachment` Asset | 同上 |

### 决策 7：页眉页脚过滤

**选择**: 基于重复文本检测 + y 坐标位置的双重过滤策略

**过滤规则**:
1. **重复文本检测**: 遍历所有页面提取的文本块，如果同一文本（trim 后完全相同）在 ≥ 3 个页面的相同 y 坐标区间（容忍 ±5pt）出现，标记为候选页眉/页脚并移除
2. **y 坐标位置过滤**: 位于页面顶部 15%（y0 < page_height * 0.15）或底部 15%（y0 > page_height * 0.85）的短文本块（≤ 100 字符），如果字体 ≤ 10pt，直接移除
3. **页码模式匹配**: 匹配纯数字、罗马数字、"数字/总页数"等页码模式，结合底部位置过滤

**理由**:
- PDF 的页眉页脚与正文不同——它们每页重复出现，没有语义价值
- 不处理会导致 LLM 语义抽取时看到 N 次重复的"产品手册 v2.0"和页码，严重污染知识块质量
- 两阶段检测（先全局重复分析，再局部位置过滤）比单纯位置过滤更可靠——某些 PDF 的页眉可能不在标准位置
- 3 页阈值避免误杀短文档（2 页文档没有"重复"页眉的概念）
- HTML/XLSX/PPTX 解析器无此问题，因为它们的格式天然不含页眉页脚，这是 PDF 特有设计

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 页眉页脚过滤误杀正文 | 短文档的章节标题若恰好在页面顶部 15% 区域且 ≤ 10pt，可能被错误移除 | 三页阈值确保短文档不受影响；过滤规则仅移除字体 ≤ 10pt 的顶部文本，正文章节标题通常 > 12pt |
| `find_tables()` 对无边框表格检测弱 | 表格被当作普通文本，丢失行列结构 | 降级为文本而非丢弃；后续可集成更强的表格检测库 |
| `find_tables()` API 不可用（PyMuPDF < 1.23.0） | 所有表格均无法检测 | `hasattr` 防御检查 + 降级为文本提取，不崩溃 |
| 多栏 PDF 文本顺序错乱 | 段落内容跨栏混合 | 阶段 4 先简单排序覆盖单栏主流场景，多栏留待后续 |
| 加密 PDF 无法解析 | 用户文件无法入库 | 显式抛出 `ValueError("PDF 解析失败：文档已加密")` |
| 扫描件 PDF（仅图片无文本层） | 解析返回空文本，用户困惑 | 区分"空文件"和"图片型 PDF"的错误消息；后续阶段 5 可加 OCR |
| PyMuPDF 大文件内存占用 | 大型 PDF（>100MB）可能 OOM | 依赖入库管线的文件大小限制（后续阶段配置） |
| 无 TOC 且无粗体/大字号的 PDF 标题检测弱 | 标题路径缺失，语义抽取质量下降 | 三信号检测（TOC + 字号 + 粗体）覆盖多数企业文档；LLM 可根据内容推断主题 |

## Open Questions

- 是否需要在阶段 4 就支持多栏 PDF 的栏检测和排序？（当前评估：主流企业 PDF 以单栏为主，暂不实现）
- 字体大小启发式的阈值（14pt）是否需要可配置？（建议先硬编码，按实际反馈调整）
