## Why

阶段 4 已通过 XLSX 纵切验证了多格式解析接入 ParserRegistry、入库管线和语义抽取链路的方式。HTML 是知识库中常见的在线文档、产品手册、帮助中心和导出资料格式，优先支持 HTML 可以用较小边界继续扩大入库覆盖面，并自然复用现有标题、段落、表格、图片和视频资源化模型。

本变更聚焦 `.html` / `.htm` 文档解析，不扩大到 PDF、PPTX 或浏览器渲染级页面理解，避免阶段 4 后续纵切一次跨入复杂版面还原和动态脚本执行。

## What Changes

- 新增 HTML 解析能力，将 HTML 文档解析为统一 `ParseResult`。
- 使用 HTML 结构提取标题、段落、列表、表格、代码块、图片、视频链接和 iframe/embed/object 附件引用。
- 将 `h1`-`h6` 映射为 `title` 元素，并维护 `source_location.section_path`。
- 将 `p`、`blockquote` 等文本节点映射为 `paragraph` 元素，过滤脚本、样式、导航和空白内容。
- 将 `ul` / `ol` 映射为 `list` 容器和子段落，保留有序/无序元数据。
- 将 HTML 表格映射为兼容现有 Markdown/DOCX/XLSX 的 `structured_data.table`。
- 识别 `img` 创建 `Asset(asset_type=image)`，识别视频 URL、`video`、`iframe` 等创建或关联 `Asset(asset_type=video)`。
- 对非视频的外部链接、iframe、embed、object 等保留为附件类资源候选，不下载或递归解析附件内容。
- 注册 `HtmlParser`，使 `/ingest` 可通过 `source_type="html"` / `"htm"` 自动选择解析器。
- 新增 HTML 解析和入库分派测试，覆盖标题路径、表格、图片、视频、iframe、过滤脚本样式和无效 HTML 边界。

## Capabilities

### New Capabilities

- `html-parsing`：定义 HTML 文档解析为统一 ParsedElement/Asset 输出的行为，包括标题、段落、列表、表格、代码、图片、视频、iframe/附件引用和安全边界。

### Modified Capabilities

- `document-ingestion`：将当前支持格式从 Markdown/TXT/DOCX/XLSX 扩展为包含 HTML/HTM，并要求入库管线通过 ParserRegistry 分派到 HtmlParser。
- `parser-registry`：增加 HTML 解析器注册和 `source_type="html"` / `"htm"` 的分派要求。
- `asset-lifecycle`：明确 HTML 解析阶段识别图片、视频、iframe/embed/object 等资源时的 Asset 类型、状态和不下载边界。

## Impact

受影响代码模块：

- `knowledge_base_system/parsers/`：新增 HTML 解析器。
- `knowledge_base_system/app/core/deps.py`：注册 `HtmlParser`。
- `knowledge_base_system/requirements.txt`：新增 HTML 解析依赖，优先使用 `beautifulsoup4`，如需要可配合 `lxml`。
- `knowledge_base_system/tests/`：新增 HTML 解析器、注册表和入库分派相关测试。
- `openspec/specs/html-parsing`：新增 HTML 解析能力规格。
- `openspec/specs/document-ingestion`、`openspec/specs/parser-registry`、`openspec/specs/asset-lifecycle`：更新支持格式和资源识别要求。

公共 API 保持向后兼容：`/upload` 与 `/ingest` 请求结构不变，调用方仅需在入库时传入 `source_type="html"` 或 `"htm"`。

对现有功能的影响：

- Markdown/TXT/DOCX/XLSX 解析、语义抽取、资源处理、索引和检索链路不应改变。
- HTML 解析失败只影响对应入库任务，不应影响其他文档格式。
- 首版不执行 JavaScript，不发起网络请求，不进行 CSS 布局还原，不处理浏览器渲染后的动态 DOM，不递归下载 iframe 或附件内容。

回滚计划：

- 从 ParserRegistry 中移除 `HtmlParser` 注册即可停止新 HTML 入库。
- 移除 HTML 解析依赖和新增解析器文件，不影响现有 Markdown/TXT/DOCX/XLSX 链路。
- 已入库的 HTML 知识块可按 `doc_id`、`source_type="html"` / `"htm"` 或入库任务进行删除和重建，索引可通过现有删除和重建流程恢复。
