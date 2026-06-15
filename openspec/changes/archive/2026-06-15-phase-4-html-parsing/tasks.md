## 1. 依赖与注册准备

- [x] 1.1 在 `requirements.txt` 增加 HTML 解析依赖，优先使用 `beautifulsoup4`，必要时补充 `lxml`。
- [x] 1.2 新建 `parsers/html_parser.py`，实现 `HtmlParser(DocumentParser)` 基础类结构和 `SUPPORTED_TYPES = {"html", "htm"}`。
- [x] 1.3 在 `app/core/deps.py` 注册 `HtmlParser`，确保 `source_type="html"` 和 `"htm"` 可由 ParserRegistry 分派。
- [x] 1.4 扩展 `tests/test_parser_registry.py`，验证 HtmlParser 注册、HTM/HTML 大小写不敏感分派和未注册格式错误不变。

## 2. HTML 文件读取与安全过滤

- [x] 2.1 实现 HTML 内容读取逻辑，支持 `doc.metadata["raw_content"]`、`file://` 来源和 MinIO 入库链路提供的内容。
- [x] 2.2 计算并写入 `doc.source_hash`，保持与现有解析器一致。
- [x] 2.3 使用 BeautifulSoup 解析 HTML，并对空内容或不可解析内容抛出清晰异常。
- [x] 2.4 跳过或移除 `script`、`style`、`noscript`、`template`、`meta`、`link` 等非正文节点。
- [x] 2.5 优先从 `main`、`article` 或 `body` 容器遍历正文；缺失时回退到根节点。

## 3. 文档结构元素解析

- [x] 3.1 将 `h1`-`h6` 转换为 `title` ParsedElement，维护 `section_path` 和 `metadata.heading_level`。
- [x] 3.2 将 `p`、`blockquote` 等正文节点转换为 `paragraph` ParsedElement，并规范化多余空白。
- [x] 3.3 将 `ul` / `ol` 转换为 `list` 容器和子段落元素，记录 `ordered` metadata。
- [x] 3.4 将 `pre` / `code` 代码块转换为 `code` ParsedElement，保留代码文本和可识别语言。
- [x] 3.5 按 DOM 顺序生成 `sequence_order`，避免标题、段落、表格和资源元素乱序。

## 4. HTML 表格解析

- [x] 4.1 将 `table` 节点转换为 `table` ParsedElement，输出兼容现有格式的 `structured_data.table`。
- [x] 4.2 提取 `caption`、`thead` 或首行表头作为表格标题和 headers。
- [x] 4.3 提取 `tbody`、`tr`、`th`、`td` 数据行，并为每个单元格保留 `text` 和 `asset_ids`。
- [x] 4.4 在单元格 metadata 中记录 `rowspan`、`colspan` 和来源标签信息。
- [x] 4.5 处理嵌套表格边界，避免嵌套表格文本重复污染父表格单元格。

## 5. 资源识别与关联

- [x] 5.1 识别 `img[src]`，创建 `Asset(asset_type=image, status=pending)`，保留 `alt`、标签和来源属性 metadata。
- [x] 5.2 识别 `video[src]`、`source[src]`、视频文件 URL、YouTube/Vimeo URL 和视频 iframe，创建 `Asset(asset_type=video, status=pending)`。
- [x] 5.3 识别非视频 `iframe`、`embed`、`object` 和常见下载链接，创建或保留 `Asset(asset_type=attachment)` 来源信息。
- [x] 5.4 将创建的 Asset 与所在 paragraph、table、image、video 或附件元素通过 `asset_ids` 关联。
- [x] 5.5 对重复 URL 做单文档内去重，避免同一 HTML 中重复创建相同 Asset。
- [x] 5.6 保留原始 URL，并在 metadata 中记录相对 URL、`base href` 或来源上下文；不在解析阶段发起网络请求。

## 6. 入库链路兼容性

- [x] 6.1 新增 `tests/test_ingestion_html.py`，验证入库管线根据 `source_type="html"` 分派到 HtmlParser。
- [x] 6.2 验证 HTML 解析结果能进入语义抽取前置流程，语义抽取接收到标题、段落、表格和资源元素。
- [x] 6.3 确认 HTML 解析失败只使对应入库 job 标记为 failed，不影响其他文档格式。
- [x] 6.4 确认资源数量限制仍由现有 `MAX_ASSETS_PER_DOC` 处理，超出资源按现有生命周期标记 skipped。

## 7. 测试覆盖

- [x] 7.1 新增 `tests/test_html_parser.py`，覆盖标题层级、标题路径、段落和脚本样式过滤。
- [x] 7.2 测试有序/无序列表解析，验证 list 容器、子元素归属和 ordered metadata。
- [x] 7.3 测试 HTML 表格解析，验证 caption、headers、rows、cell metadata 和跨度信息。
- [x] 7.4 测试图片、视频、iframe、embed、object 和附件链接的 Asset 创建及 `asset_ids` 关联。
- [x] 7.5 测试空 HTML、无 body HTML、格式不规范 HTML 和相对 URL 边界。
- [x] 7.6 跑现有 Markdown/TXT/DOCX/XLSX 解析器、入库和 API 合约相关测试，确认回归通过。

## 8. 文档与验收

- [x] 8.1 更新必要开发文档或示例，说明 HTML 入库使用 `source_type="html"` 或 `"htm"`。
- [x] 8.2 使用包含标题、段落、列表、表格、图片、视频 iframe 和附件链接的 HTML 样例做手工验收。
- [x] 8.3 运行 `openspec validate phase-4-html-parsing`，确认规格合法。
- [x] 8.4 确认 proposal、design、specs 和 tasks 与最终实现保持一致。
