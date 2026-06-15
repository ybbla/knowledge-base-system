## Context

当前系统已经具备统一解析器接口 `DocumentParser`、解析器注册表 `ParserRegistry`、入库流水线 `IngestionPipeline`、资源生命周期处理、LLM 语义抽取以及混合检索链路。Markdown/TXT、DOCX 和 XLSX 解析器都输出统一的 `ParseResult`，下游只依赖 `Document`、`ParsedElement` 和 `Asset`。

HTML 与现有格式的主要差异是它同时承载文档结构、链接结构和网页噪声：同一文件中可能包含正文、导航、脚本、样式、iframe、图片、视频和附件链接。为了保持阶段 4 的可控边界，本设计只解析静态 HTML 源码，不执行 JavaScript，不发起网络请求，不做 CSS 布局和浏览器渲染后的 DOM 还原。

受影响模块：

- `knowledge_base_system/parsers/html_parser.py`：新增 HTML 解析器。
- `knowledge_base_system/app/core/deps.py`：注册 HTML 解析器。
- `knowledge_base_system/requirements.txt`：新增 `beautifulsoup4` 依赖，必要时新增 `lxml`。
- `knowledge_base_system/tests/test_html_parser.py`：新增解析行为测试。
- `knowledge_base_system/tests/test_ingestion_html.py`：新增入库分派测试。
- `knowledge_base_system/tests/test_parser_registry.py`：补充 HTML/HTM 注册与大小写分派测试。
- `openspec/specs/html-parsing`：新增能力规格。
- `openspec/specs/document-ingestion`、`openspec/specs/parser-registry`、`openspec/specs/asset-lifecycle`：更新支持格式和资源识别要求。

## Goals / Non-Goals

**Goals:**

- 支持 `source_type="html"` 和 `source_type="htm"` 的静态 HTML 文件入库。
- 使用成熟 HTML 解析库读取结构，输出统一 `ParseResult`。
- 将 `h1`-`h6` 解析为 `title` 元素，并维护标题路径。
- 将正文段落、引用块和可读文本块解析为 `paragraph` 元素。
- 将 `ul` / `ol` 解析为 `list` 容器和子段落，保留有序/无序信息。
- 将 HTML 表格转换为兼容现有 `structured_data.table` 的 `table` 元素。
- 识别图片、视频 URL、`video`、`iframe`、`embed`、`object` 和普通附件链接，创建或关联可追溯 Asset。
- 保持 Markdown/TXT/DOCX/XLSX 现有行为不变。

**Non-Goals:**

- 不执行 JavaScript，不解析运行后生成的动态 DOM。
- 不发起网络请求，不下载 HTML 中的外部链接、iframe 或附件内容。
- 不做 CSS 布局还原、可视区域判断、响应式页面重排或浏览器截图。
- 不做网页正文抽取算法的复杂打分，例如 Readability 全量规则。
- 不递归解析 HTML 内的附件或 iframe 指向的文档。
- 不新增公共 API；仍由调用方在 `/ingest` 中提供 `source_type`。

## Decisions

### 1. 使用 BeautifulSoup 解析静态 HTML

选择：新增 `beautifulsoup4`，优先使用 Python 标准 `html.parser` 或可选 `lxml` 解析器，将 HTML 源码转为可遍历树。

理由：

- BeautifulSoup 对不规范 HTML 容错较好，适合知识库中来自网页导出、帮助中心和手工维护页面的混合来源。
- 当前目标是结构化提取而非浏览器级渲染，不需要引入 Playwright、Selenium 或 headless browser。
- 依赖轻量，与 FastAPI/Python 技术栈一致。

备选：

- `lxml.html`：性能好，但 API 更偏底层，容错和易用性不如 BeautifulSoup。
- 浏览器渲染后解析 DOM：能处理动态页面，但会引入网络、脚本执行和安全边界，超出本阶段。
- `html2text`：能快速转 Markdown，但会丢失表格、资源和精确来源元数据。

### 2. 以文档流顺序遍历可见内容节点

选择：在解析前移除或跳过 `script`、`style`、`noscript`、`template`、`svg`、`meta`、`link` 等非正文节点；对 `main` / `article` / `body` 采取优先容器策略，按 DOM 顺序生成元素。

理由：

- 现有语义抽取依赖 `sequence_order` 和 `section_path`，保留文档流顺序比按标签类型批量抽取更可靠。
- HTML 页面常带导航、页脚和脚本噪声，首版做保守过滤即可显著降低无效知识块。

备选：

- 全文 `get_text()`：实现简单但会丢失标题层级、表格结构和资源关联。
- 完整 Readability 抽取：正文质量更好，但规则复杂，可能误删产品文档中的表格和列表。

### 3. 标题路径沿用现有 section_path 机制

选择：`h1`-`h6` 生成 `title` 元素，`metadata.heading_level` 记录等级；遇到新标题时按等级修剪并追加 `_section_path`。

理由：

- Markdown 和 DOCX 已使用标题路径，HTML 保持一致可以复用语义窗口化、来源引用和检索结果展示。
- 网页帮助文档通常具有清晰标题层级，直接映射收益高。

### 4. 表格复用 `structured_data.table`

选择：`table` 节点生成 `ElementType.table`，提取 `caption`、`thead` / 首行表头、`tbody` 数据行、单元格文本和单元格内资源引用。

理由：

- 下游 LLM prompt 已经要求表格转写为自然语言。
- Markdown/DOCX/XLSX 均已使用 `structured_data.table`，HTML 表格保持兼容能减少下游变更。

边界：

- 首版只做 `rowspan` / `colspan` 的轻量展开或元数据记录，不追求复杂嵌套表格完美还原。
- 嵌套表格可作为独立 table 元素处理，避免污染父表格。

### 5. 资源识别只创建 Asset，不主动访问外部资源

选择：`img[src]` 创建 `Asset(asset_type=image)`；视频文件 URL、YouTube/Vimeo URL、`video[src]`、`source[src]`、视频 iframe 创建 `Asset(asset_type=video)`；其他 `iframe`、`embed`、`object` 和可下载链接创建或保留 `Asset(asset_type=attachment)`。

理由：

- 阶段 3 已有图片处理和视频链接资源化链路，HTML 解析器只负责识别和关联。
- 不主动访问外部资源可以避免 SSRF、慢请求、鉴权泄漏和不可控下载。

### 6. URL 规范化保持轻量

选择：保留原始 URL，同时在 `metadata` 中记录标签、属性、可选的 `base_url` 或来源上下文。相对 URL 首版可按文档 `source_uri` 或 `<base href>` 尝试解析；无法解析时保留原值。

理由：

- 知识库来源可能是本地上传 HTML、MinIO 文件或外部导出包。强行要求 URL 都可解析会降低可用性。
- 保留原始 URL 便于追溯和后续离线资源包支持。

## Risks / Trade-offs

- [正文噪声过多] HTML 页面可能包含导航、页脚、侧边栏和脚本残留。→ 首版跳过常见非正文标签和空文本，并在测试中覆盖脚本样式过滤；后续可增加正文抽取策略。
- [动态页面内容缺失] JavaScript 渲染出的正文不会出现在静态 HTML 源码中。→ 明确 Non-Goal；需要动态页面时另开浏览器渲染纵切。
- [表格还原不完整] 复杂 `rowspan` / `colspan` / 嵌套表格可能无法完全还原。→ 保留 cell metadata 和原始跨度信息，优先保证下游可读和可追溯。
- [外部链接安全风险] HTML 可包含恶意 URL 或大量附件链接。→ 解析阶段只识别不访问，资源生命周期继续受 `MAX_ASSETS_PER_DOC` 和后续处理限制保护。
- [资源关联不精确] 图片或视频可能与最近段落/表格的语义关系不清晰。→ 解析器将资源关联到其所在元素或生成独立元素，下游 LLM 根据上下文决定是否引用。
- [大 HTML 性能压力] 超长页面或巨大表格可能放大解析时间和 LLM 输入窗口。→ 复用 `settings.max_elements_per_doc` 和资源数量限制，任务中加入大文档边界测试。

## Migration Plan

1. 新增 HTML 解析依赖，不改变现有依赖行为。
2. 新增 `HtmlParser`，先通过单元测试验证结构化输出。
3. 在 `ParserRegistry` 注册 `HtmlParser`，使 `source_type="html"` / `"htm"` 生效。
4. 补充入库分派测试，确认 HTML 解析结果进入语义抽取和索引前置流程。
5. 跑现有 Markdown/TXT/DOCX/XLSX 解析和 API 合约相关测试，确认回归链路不受影响。
6. 若需要回滚，移除注册即可让 HTML 入库回到“不支持格式”状态；现有格式不受影响。

## Open Questions

- 是否需要在 `/upload` 响应中根据扩展名建议 `source_type`？当前方案保持 API 不变，仍由调用方传入。
- 相对 URL 是否必须基于 `<base href>` 或 `source_uri` 转为绝对 URL？建议首版保留原值并记录解析依据，避免本地上传 HTML 场景误判。
- 普通 `<a href>` 是否全部创建 attachment Asset，还是仅对文件扩展名明显的链接创建？建议首版对常见文件扩展名创建附件，其余仅保留 metadata，避免资源数量膨胀。
