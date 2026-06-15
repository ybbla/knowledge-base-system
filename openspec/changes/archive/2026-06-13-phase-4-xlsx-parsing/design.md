## Context

当前系统已经具备统一解析器接口 `DocumentParser`、解析器注册表 `ParserRegistry`、入库流水线 `IngestionPipeline`、LLM 语义抽取、资源生命周期处理以及混合检索链路。Markdown/TXT 与 DOCX 解析器都输出统一的 `ParseResult`，下游只依赖 `ParsedElement`、`Asset` 和 `Document`，因此 XLSX 支持应尽量收敛在解析层和注册层。

XLSX 的核心差异在于它天然是工作簿/工作表/单元格网格，而不是线性文档。为了适配现有语义抽取链路，本设计将 XLSX 中的连续非空区域转为 `table` 元素，将工作表名转为 `title` 元素，并把单元格范围、公式、超链接、合并单元格等信息放入 `structured_data` 或 `metadata` 中。

受影响模块：

- `knowledge_base_system/parsers/xlsx_parser.py`：新增 XLSX 解析器。
- `knowledge_base_system/app/core/deps.py`：注册 XLSX 解析器。
- `knowledge_base_system/requirements.txt`：新增 `openpyxl`。
- `knowledge_base_system/tests/test_xlsx_parser.py`：新增解析行为测试。
- `knowledge_base_system/tests/test_parser_registry.py`：补充 XLSX 注册与大小写分派测试。
- `openspec/specs/document-ingestion`、`openspec/specs/parser-registry`：更新能力范围。

## Goals / Non-Goals

**Goals:**

- 支持 `source_type="xlsx"` 的 `.xlsx` 文件入库。
- 使用 `openpyxl` 读取工作簿内容，输出统一 `ParseResult`。
- 每个可见工作表生成一个 `title` 元素，保留工作表名称和顺序。
- 将连续非空单元格区域转换为 `table` 元素，沿用现有 `structured_data.table` 结构。
- 展开合并单元格，减少表格语义丢失。
- 识别公式值、超链接、视频 URL 和附件链接，保留可追溯元数据。
- 保持 Markdown/TXT/DOCX 现有行为不变。

**Non-Goals:**

- 不支持旧版 `.xls`。
- 不执行宏，不解析 VBA。
- 不支持受密码保护工作簿。
- 不做 OCR、图表语义理解、复杂透视表语义还原。
- 不在本阶段改造递归加载器为跨格式注册表分派。
- 不新增公共 API；仍由调用方在 `/ingest` 中提供 `source_type`。

## Decisions

### 1. 使用 `openpyxl` 作为 XLSX 解析依赖

选择：新增 `openpyxl`，以 `load_workbook(..., data_only=True)` 优先读取公式缓存值，并在必要时第二次读取公式文本。

理由：

- `openpyxl` 是 Python 生态中处理 `.xlsx` 的成熟库，适合读取工作表、单元格值、合并单元格、超链接和图片锚点。
- 与当前 Python/FastAPI 技术栈一致，无需引入外部服务。

备选：

- `pandas`：适合数据分析，但会丢失较多工作簿结构信息，例如合并单元格、超链接、图片锚点。
- 直接解析 OOXML zip：控制力强，但实现复杂且容易重复造轮子。

### 2. 工作表作为标题元素，连续区域作为表格元素

选择：每个可见工作表生成一个 `title` 元素；工作表内连续非空区域生成一个或多个 `table` 元素。

理由：

- 现有语义抽取按标题路径进行窗口化，工作表名作为标题可以自然进入 `source_location.section_path`。
- XLSX 常见业务文档会在同一工作表中放多个独立表格，整张 sheet 粗暴解析为一个表会污染语义边界。

区域识别首版采用保守规则：

- 非空单元格、含公式单元格、含超链接单元格均视为有效单元格。
- 空行或空列作为区域边界。
- 区域第一行默认作为 headers，其余行作为 rows。
- 单个孤立文本区域可降级为 `paragraph`，避免制造只有一个单元格的弱表格。

备选：

- 使用 Excel Table 对象：结构准确但覆盖不全，很多业务表没有定义为正式 Table。
- 整个 used range 作为单表：简单但容易把多个业务表混在一起。

### 3. 复用现有 `structured_data.table` 结构

选择：XLSX 表格输出与 Markdown/DOCX 保持兼容：

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
              "cell": "A2",
              "hyperlink": "https://example.com"
            }
          }
        ]
      }
    ],
    "metadata": {
      "sheet_name": "Sheet1",
      "range": "A1:D20"
    }
  }
}
```

理由：

- 下游 LLM prompt 已经明确要求表格转写为自然语言。
- 保持字段兼容可以减少语义抽取、索引和检索层变更。

### 4. 合并单元格采用展开策略

选择：对合并单元格，将左上角单元格值复制到合并范围内，并在单元格 metadata 中记录 `merged_from`。

理由：

- DOCX 表格已采用合并单元格展开策略，XLSX 保持一致。
- LLM 接收完整行列矩阵时更容易保留“某列/某行属于某个分组”的语义。

### 5. 公式读取采用缓存值优先、公式文本兜底

选择：默认读取公式缓存值；当缓存值为空但单元格包含公式时，保留公式文本，并在 metadata 中标记 `formula` 和 `formula_value_missing`。

理由：

- openpyxl 不计算公式，强行计算需要 Excel、LibreOffice 或专用计算引擎，超出当前阶段。
- 保留公式文本比丢弃信息更安全，同时明确告知下游它不是计算结果。

### 6. 超链接与资源识别保持轻量

选择：视频 URL 创建 `Asset(asset_type=video)`，普通超链接创建 `Asset(asset_type=attachment)` 或记录在单元格 metadata；首版不递归解析附件内容。

理由：

- 阶段 3 已有视频链接资源化链路。
- XLSX 中超链接可能指向网页、文件、邮件或内部 sheet 位置，首版只做识别和追溯，避免把递归解析边界扩大。

## Risks / Trade-offs

- [区域识别误分组] 同一工作表中复杂排版可能被拆成过多或过少表格。→ 采用保守规则并在 metadata 记录范围，后续可根据评测调整区域识别算法。
- [公式值不准确] `openpyxl` 不计算公式，缓存值可能缺失或过期。→ 标记公式元数据，缓存缺失时保留公式文本，不伪造计算结果。
- [大工作簿性能压力] 大量单元格会放大解析时间和 LLM 输入窗口。→ 使用 `settings.max_elements_per_doc` 控制总元素量，首版按区域生成表格而非逐单元格生成元素。
- [安全风险] XLSX 可能含宏、外部链接或恶意内容。→ 仅使用 `openpyxl` 读取 `.xlsx` 数据，不执行宏；不自动访问外部超链接。
- [图片锚点复杂] openpyxl 图片锚点和表格区域的关系不总是明确。→ 图片解析可先生成独立 image 元素，并在 metadata 记录锚点单元格，后续再优化关联。

## Migration Plan

1. 新增依赖 `openpyxl`，不改变现有依赖行为。
2. 新增 `XlsxParser`，先通过单元测试验证解析输出。
3. 在 `ParserRegistry` 注册 `XlsxParser`，使 `source_type="xlsx"` 生效。
4. 跑现有 Markdown/TXT/DOCX 测试，确认回归链路不受影响。
5. 若需要回滚，移除注册即可让 XLSX 入库回到“不支持格式”状态；现有格式不受影响。

## Open Questions

- 是否需要在 `/upload` 响应中根据扩展名建议 `source_type`？当前提案保持 API 不变，仍由调用方传入。
- 图片提取是否放入首个实现批次，还是先完成文本/表格/超链接后再补？建议首批至少保留图片锚点，完整图片资源化可作为后续任务。
- 是否需要对超大工作簿增加单独的 `MAX_XLSX_CELLS_PER_DOC` 配置？首版可复用现有 `max_elements_per_doc`，但它对单个巨大表格的保护不够精细。
