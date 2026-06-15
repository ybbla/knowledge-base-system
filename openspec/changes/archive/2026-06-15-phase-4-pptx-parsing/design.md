## Context

当前系统已经具备统一解析器接口 `DocumentParser`、解析器注册表 `ParserRegistry`、入库流水线 `IngestionPipeline`、资源生命周期处理、语义抽取和混合检索链路。Markdown/TXT、DOCX、XLSX 和 HTML 解析器都输出统一的 `ParseResult`，下游只依赖 `Document`、`ParsedElement` 和 `Asset`，因此 PPTX 支持应尽量收敛在解析层、注册层和相关测试中。

PPTX 与 DOCX/XLSX 同属 Office Open XML，但信息组织方式不同：DOCX 偏线性文档，XLSX 偏二维表格，PPTX 则是幻灯片容器中的形状集合。为了适配现有语义抽取链路，首版将“幻灯片”作为天然结构边界，将可读文本、列表、表格和资源按稳定顺序转换为 ParsedElement。

受影响模块：

- `knowledge_base_system/parsers/pptx_parser.py`：新增 PPTX 解析器。
- `knowledge_base_system/app/core/deps.py`：注册 PPTX 解析器。
- `knowledge_base_system/requirements.txt`：新增 `python-pptx`。
- `knowledge_base_system/tests/test_pptx_parser.py`：新增解析行为测试。
- `knowledge_base_system/tests/test_parser_registry.py`：补充 PPTX 注册和大小写分发测试。
- `knowledge_base_system/tests/test_ingestion_pptx.py`：验证入库管线分发和失败边界。
- `openspec/specs/pptx-parsing`、`document-ingestion`、`parser-registry`、`asset-lifecycle`：更新能力范围。

## Goals / Non-Goals

**Goals:**

- 支持 `source_type="pptx"` 的 `.pptx` 文件入库。
- 使用 `python-pptx` 读取幻灯片、形状、文本、表格、图片和基础关系信息。
- 每张幻灯片保留可追溯上下文，包括 `slide_index`、`slide_number`、形状位置和标题路径。
- 将标题、段落、列表、表格、图片、视频和附件映射为现有 ParsedElement/Asset 模型。
- 对不支持对象进行显式降级，避免静默丢失。
- 保持现有 Markdown/TXT/DOCX/XLSX/HTML 行为不变。

**Non-Goals:**

- 不支持旧版 `.ppt`。
- 不执行宏，不处理受密码保护演示文稿。
- 不还原动画、转场、叠放顺序的动态语义。
- 不做 OCR、图片理解、图表深度语义化或 SmartArt 结构还原。
- 不做像素级版面复刻；只保留形状坐标作为元数据。
- 不在解析阶段下载外部视频、附件或链接内容。
- 不改造公共 API；仍由调用方在 `/ingest` 中提供 `source_type`。

## Decisions

### 1. 使用 `python-pptx` 作为 PPTX 解析依赖

选择：新增 `python-pptx`，通过 `Presentation(io.BytesIO(raw))` 读取演示文稿，并遍历 slides 与 shapes。

理由：

- `python-pptx` 是 Python 生态中处理 `.pptx` 的成熟库，适合读取幻灯片、占位符、文本框、表格、图片和基础关系。
- 与当前 Python/FastAPI 技术栈一致，无需引入 LibreOffice、浏览器渲染服务或外部转换服务。
- 相比直接解析 OOXML zip，可减少底层关系解析和形状遍历的重复造轮子。

备选：

- 直接解析 OOXML zip：控制力更强，但实现复杂，容易和 `python-pptx` 能力重叠。
- 使用 LibreOffice 转 HTML/PDF 后解析：可能提升版面效果，但引入外部进程、部署复杂度和安全边界，不适合首版。

### 2. 幻灯片作为结构边界，标题路径使用幻灯片标题

选择：每张幻灯片内优先寻找标题占位符或首个标题类文本形状，生成 `title` 元素，并将 `section_path` 设为 `[slide_title]`；缺少标题时使用 `"幻灯片 {n}"` 作为上下文标题。

理由：

- PPTX 的自然阅读单位是幻灯片，幻灯片标题通常就是语义主题。
- 现有语义抽取依赖 `source_location.section_path` 建立上下文，幻灯片标题可以自然复用该机制。
- 对无标题页提供兜底标题，可以避免后续知识块缺少来源上下文。

### 3. 形状顺序按幻灯片顺序和视觉坐标排序

选择：`sequence_order` 按幻灯片顺序递增；同一幻灯片内形状优先按 `top`、`left`、原始索引排序。

理由：

- PPTX XML 顺序未必符合阅读顺序，视觉坐标更接近人类阅读路径。
- 坐标排序稳定、可测试，不需要复杂版面理解。
- 原始索引作为平局兜底，保证顺序确定。

### 4. 文本框和项目符号映射为 paragraph/list

选择：普通文本形状生成 `paragraph`；带项目符号或多级缩进的形状生成 `list` 容器和子 `paragraph`，子元素 metadata 记录 `level`、`shape_id`、`slide_index` 和坐标。

理由：

- 现有 ElementType 已有 `paragraph` 和 `list`，无需新增类型。
- PPTX 常见正文是 bullet list，保留列表容器有助于 LLM 识别流程、要点和层级。
- 首版不强制还原复杂编号样式，只保留有序性和层级元数据。

### 5. 表格复用 `structured_data.table`

选择：PPTX 表格形状输出为 `table` ParsedElement，结构沿用现有格式：

```json
{
  "table": {
    "caption": "",
    "headers": ["..."],
    "rows": [
      {
        "cells": [
          {
            "text": "...",
            "asset_ids": [],
            "metadata": {
              "row": 2,
              "column": 1,
              "slide_index": 1
            }
          }
        ]
      }
    ],
    "metadata": {
      "slide_index": 1,
      "shape_id": 12
    }
  }
}
```

理由：

- 下游 LLM prompt 已经能处理统一表格结构。
- 与 Markdown/DOCX/XLSX/HTML 保持兼容，降低语义抽取和检索层改动。

### 6. 图片提取创建 Asset，并保留原始字节

选择：对图片 shape 创建 `Asset(asset_type=image, status=pending)`，`original_uri` 使用 `pptx://{doc_id}/slide/{slide_number}/media/{name}` 风格；通过私有 `_data` 或等价机制把图片字节交给现有资源处理链路。

理由：

- DOCX 已采用从文件包内提取图片并交给资产生命周期处理的模式，PPTX 可保持一致。
- 图片内容理解不属于阶段 4，但保留 Asset 能为后续图片理解和引用展示打基础。

### 7. 视频、音频、附件和外部链接仅识别不下载

选择：识别文本中的视频 URL、形状超链接、媒体关系和附件关系；视频创建 `AssetType.video`，音频或无法分类文件创建 `AssetType.attachment`，阶段 4 不下载、不解析内容。

理由：

- 阶段 3/4 的资源生命周期已经将视频理解留作后续增强。
- PPTX 中链接可能指向网页、云盘、视频、附件或内部跳转，解析阶段只做可追溯识别更安全。

## Risks / Trade-offs

- [阅读顺序不完美] 坐标排序无法理解复杂版面、分栏或叠放设计。缓解：记录 shape 坐标和原始索引，后续可基于评测优化排序。
- [图表和 SmartArt 语义丢失] `python-pptx` 对复杂对象支持有限。缓解：首版生成 `unknown` 或提取可见文本，不伪造结构。
- [图片和媒体数量较大] 演示文稿可能包含大量高分辨率图片。缓解：继续复用 `MAX_ASSETS_PER_DOC`、图片大小限制和现有资源处理逻辑。
- [链接关系复杂] PPTX 可能包含内部跳转、外部文件、嵌入媒体和 OLE 对象。缓解：仅识别和记录，不下载、不执行、不递归解析。
- [依赖兼容性] `python-pptx` 对部分 Python/依赖版本可能有兼容问题。缓解：加入依赖安装和基础解析测试，必要时锁定最低版本。

## Migration Plan

1. 新增 `python-pptx` 依赖，不改变现有依赖行为。
2. 新增 `PptxParser`，先通过单元测试验证解析输出。
3. 在 `ParserRegistry` 注册 `PptxParser`，使 `source_type="pptx"` 生效。
4. 增加入库管线分发测试，确认 PPTX 能进入语义抽取前置流程。
5. 跑现有 Markdown/TXT/DOCX/XLSX/HTML 测试，确认回归链路不受影响。
6. 如需回滚，移除注册即可让 PPTX 回到“不支持格式”状态；现有格式不受影响。

## Open Questions

- 是否需要在首版解析 speaker notes？建议首版可跳过或作为 metadata 标记的 paragraph，避免把演讲提示污染正文。
- 是否需要把无标题幻灯片统一生成 `title` 元素？建议生成兜底标题，保证 section_path 稳定。
- 是否需要新增单独的 `MAX_PPTX_SLIDES_PER_DOC`？首版可先复用 `max_elements_per_doc` 和 `MAX_ASSETS_PER_DOC`，后续根据大文件评测再拆分配置。
