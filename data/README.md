# 数据目录说明

- `source_documents/`：人工放入的原始业务资料，用于批量入库或构建知识库。
- `uploads/`：服务运行时由 `/upload` 端点写入的上传文件。
- `runtime/`：预留给后续索引快照、缓存或本地运行状态。

测试样例不放在这里，统一放在 `knowledge_base_system/tests/fixtures/`。

## XLSX 入库说明

阶段 4 起支持 `.xlsx` 工作簿入库。通过 `/upload` 上传文件后，调用 `/ingest` 时将文档的 `source_type` 设置为 `"xlsx"`；系统会按工作表和连续单元格区域解析为标题、段落和表格元素。

## HTML 入库说明

阶段 4 继续支持 `.html` / `.htm` 静态 HTML 文档入库。通过 `/upload` 上传文件后，调用 `/ingest` 时将文档的 `source_type` 设置为 `"html"` 或 `"htm"`；系统会解析标题、段落、列表、表格、代码块、图片、视频 iframe 和附件链接，不执行 JavaScript，也不在解析阶段下载外部 iframe 或附件内容。

## PPTX 入库说明

阶段 4 继续支持 `.pptx` 演示文稿入库。通过 `/upload` 上传文件后，调用 `/ingest` 时将文档的 `source_type` 设置为 `"pptx"`；系统会按幻灯片解析标题、段落、列表、表格、内嵌图片、视频链接和附件链接，不执行宏、动画或复杂版面还原，也不在解析阶段下载外部视频或附件内容。
