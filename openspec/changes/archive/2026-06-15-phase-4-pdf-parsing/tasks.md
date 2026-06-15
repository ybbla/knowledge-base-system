## 1. 依赖与基础设施

- [x] 1.1 在 `requirements.txt` 中添加 `PyMuPDF>=1.24.0` 依赖
- [x] 1.2 安装 PyMuPDF 依赖并验证导入 `import fitz` 无错误

## 2. PdfParser 核心实现

- [x] 2.1 创建 `parsers/pdf_parser.py`，实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"pdf"}`
- [x] 2.2 实现 `_read_content()` — 支持从 `metadata.raw_content`（字节）和 `file://` URI 读取 PDF 内容
- [x] 2.3 实现页面文本提取与合并 — 使用 `page.get_text("blocks")` 按坐标排序提取文本块，基于垂直间距（> 1.5 倍行高分段）和字体一致性合并碎片为段落；实现页眉页脚过滤（重复文本检测 + y 坐标位置过滤 + 页码模式匹配）
- [x] 2.4 实现标题识别与路径传播 — TOC 优先（`doc.get_toc()` 条目直接作为 title），字体大小兜底（>= 14pt 短文本），粗体标记补全（12–13pt bold → `heading_level=3`）；实现 `section_path` 栈管理（按 heading_level 弹出旧标题、推入新标题，后续元素继承当前路径）
- [x] 2.5 实现表格检测 — `hasattr(page, "find_tables")` 防御检查后调用 `page.find_tables()`，解析为 `structured_data.table = {headers, rows}`；API 不可用、返回空或异常时降级为 paragraph，不中断解析
- [x] 2.6 实现内嵌图片提取 — 遍历 `page.get_images()`，调用 `doc.extract_image()` 获取字节和元数据，创建 image Asset（含 content_hash 和 `_data`）
- [x] 2.7 实现超链接识别 — 遍历 `page.get_links()`，识别视频 URL（正则匹配）和附件 URL，创建对应的 video/attachment Asset
- [x] 2.8 实现 `parse()` 主方法 — 串联所有步骤，生成 `ParseResult`，计算 `source_hash`

## 3. 解析器注册

- [x] 3.1 在 `parsers/__init__.py` 中导出 `PdfParser`
- [x] 3.2 在 `app/core/deps.py` 的 `parser_registry.register()` 调用中添加 `PdfParser()`

## 4. 单元测试

- [x] 4.1 创建 `tests/test_pdf_parser.py`，编写 `TestPdfParser` 测试类
- [x] 4.2 测试 `supports()` — 验证 `pdf` / `PDF` 返回 True，不支持的类型返回 False
- [x] 4.3 测试基础文本解析 — 创建简单 PDF（使用 fitz 或预置文件），验证标题、段落、页码和顺序
- [x] 4.4 测试 TOC 解析与路径传播 — 验证 TOC 条目映射为 title 元素且 `heading_level` 正确，验证 `section_path` 在元素间正确传播
- [x] 4.5 测试粗体标题检测 — 验证 12–13pt bold 短文本被识别为 `title`（`heading_level=3`），同字号非粗体为 `paragraph`
- [x] 4.6 测试表格检测 — 验证表格被解析为 `table` 元素且 `structured_data.table.headers/rows` 正确；验证 `find_tables` 不可用时安全降级
- [x] 4.7 测试图片提取 — 验证内嵌图片创建 image Asset，含 `content_hash`、`_data` 和正确的 `asset_type`
- [x] 4.8 测试资源去重 — 验证相同图片不会重复创建 Asset
- [x] 4.9 测试超链接识别 — 验证视频 URL 和附件 URL 分别创建正确的 Asset 类型
- [x] 4.10 测试页眉页脚过滤 — 验证多页 PDF 中重复出现的页眉（相同 y 位置 + 相同文本）和页码被过滤，正文内容不受影响
- [x] 4.11 测试块合并间距 — 验证垂直间距 > 1.5 倍行高时即使字体相同也分段
- [x] 4.12 测试错误处理 — 空内容、扫描件 PDF（无文本层）、无效文件、加密 PDF 均抛出 `ValueError`，错误信息有区分度
- [x] 4.13 测试 `file://` URI 读取 — 使用 `tmp_path` 写入 PDF 文件并验证解析

## 5. 入库集成测试

- [x] 5.1 创建 `tests/test_ingestion_pdf.py`，编写 `TestPdfIngestion` 集成测试类
- [x] 5.2 测试完整入库链路 — 从 PDF 文件到 ParsedElement 列表的端到端流程
- [x] 5.3 测试 PDF 通过 ingestion pipeline 生成知识块 — 验证 LLM 语义抽取能消费 PDF 解析结果

## 6. 验证与收尾

- [x] 6.1 运行全部已有测试，确认 PDF 解析器的添加不影响现有功能（`pytest tests/ -v` 全绿）
- [x] 6.2 运行 `openspec verify --change "phase-4-pdf-parsing"` 验证实现与规格一致
