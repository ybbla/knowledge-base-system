## 1. 依赖与注册准备

- [x] 1.1 在 `requirements.txt` 增加 `python-pptx` 依赖，并确认不影响现有依赖安装。
- [x] 1.2 新建 `parsers/pptx_parser.py`，实现 `PptxParser(DocumentParser)` 基础类结构和 `SUPPORTED_TYPES = {"pptx"}`。
- [x] 1.3 在 `app/core/deps.py` 注册 `PptxParser`，确保 `source_type="pptx"` 可由 ParserRegistry 分发。
- [x] 1.4 扩展 `tests/test_parser_registry.py`，验证 PptxParser 注册、大小写不敏感分发和未注册格式错误不变。

## 2. PPTX 文件读取与幻灯片遍历

- [x] 2.1 实现 PPTX 字节读取逻辑，支持 `doc.metadata["raw_content"]` 和 `file://` 来源。
- [x] 2.2 使用 `python-pptx` 加载演示文稿，对空内容、无效 zip 或非 PPTX 文件抛出清晰异常。
- [x] 2.3 遍历幻灯片，记录 `slide_index`、`slide_number` 和基础幻灯片元数据。
- [x] 2.4 为每张幻灯片确定标题：优先标题占位符，其次首个标题类文本形状，最后使用兜底标题。
- [x] 2.5 计算并写入 `doc.source_hash`。

## 3. 文本、标题与列表解析

- [x] 3.1 将幻灯片标题转换为 `title` ParsedElement，并维护 `source_location.section_path`。
- [x] 3.2 将普通文本框、正文占位符和形状文本转换为 `paragraph` ParsedElement。
- [x] 3.3 识别项目符号和缩进层级，将列表内容转换为 `list` 容器和子 `paragraph` 元素。
- [x] 3.4 按幻灯片顺序、形状 `top`、`left` 和原始索引生成稳定 `sequence_order`。
- [x] 3.5 在元素 metadata 中记录 `slide_index`、`slide_number`、`shape_id`、`shape_name`、坐标和占位符类型。

## 4. 表格解析

- [x] 4.1 识别 PPTX 表格形状并转换为 `table` ParsedElement。
- [x] 4.2 提取首行作为 `structured_data.table.headers`，后续行作为 `rows`。
- [x] 4.3 为每个单元格保留 `text`、`asset_ids` 和行列位置 metadata。
- [x] 4.4 在 table metadata 中记录 `slide_index`、`shape_id`、行数、列数和形状坐标。
- [x] 4.5 确保输出结构与 Markdown/DOCX/XLSX/HTML 表格兼容。

## 5. 图片、媒体与链接资源

- [x] 5.1 识别图片 shape，创建 `Asset(asset_type=image, status=pending)` 并生成 `image` ParsedElement。
- [x] 5.2 提取图片字节、MIME 类型和内容 hash，复用现有资源生命周期处理链路。
- [x] 5.3 识别文本和超链接中的视频 URL，创建 `Asset(asset_type=video, status=pending)`。
- [x] 5.4 识别音频、附件、外部文件链接或 OLE 对象候选，创建或保留 `Asset(asset_type=attachment)` 来源信息。
- [x] 5.5 将创建的 Asset 与对应 ParsedElement 通过 `asset_ids` 和 `source_element_id` 关联。
- [x] 5.6 对同一文档内重复 URL 或重复媒体资源做去重，避免重复创建相同 Asset。

## 6. 降级与边界处理

- [x] 6.1 对 SmartArt、图表、组合形状、OLE 对象等暂不支持内容生成 `unknown` 或降级文本元素。
- [x] 6.2 对受密码保护、损坏或空演示文稿抛出清晰错误，使入库 job 标记为 failed。
- [x] 6.3 确保旧版 `.ppt` 不被 `PptxParser.supports()` 接受。
- [x] 6.4 确认资源数量限制仍由现有 `MAX_ASSETS_PER_DOC` 处理，超出资源按现有生命周期标记 skipped。
- [x] 6.5 检查大演示文稿解析时的元素数量边界，避免为无意义空形状生成过量 ParsedElement。

## 7. 入库链路测试

- [x] 7.1 新增 `tests/test_pptx_parser.py`，覆盖标题、段落、列表、幻灯片上下文和 ParseResult 返回。
- [x] 7.2 测试 PPTX 表格解析，验证 headers、rows、cell metadata 和 source_location。
- [x] 7.3 测试图片提取、Asset 创建、`asset_ids` 关联和 source_element_id 回填。
- [x] 7.4 测试视频 URL、普通附件链接和重复资源去重。
- [x] 7.5 测试无效 PPTX、空演示文稿、无标题幻灯片和不支持对象降级。
- [x] 7.6 新增 `tests/test_ingestion_pptx.py`，验证入库管线根据 `source_type="pptx"` 分发到 PptxParser。
- [x] 7.7 跑现有 Markdown/TXT/DOCX/XLSX/HTML 解析器、入库和 API 合约相关测试，确认回归通过。

## 8. 文档与验收

- [x] 8.1 更新必要开发文档或示例，说明 PPTX 入库使用 `source_type="pptx"`。
- [x] 8.2 使用包含多幻灯片、标题、列表、表格、图片和链接的 PPTX 样例做手工验收。
- [x] 8.3 运行 OpenSpec 校验或等价状态检查，确认 proposal、design 和 tasks 与实现计划一致。
- [x] 8.4 确认本变更未引入 PDF、OCR、动画语义或复杂版面还原等超出范围内容。
