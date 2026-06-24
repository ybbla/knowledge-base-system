## Why

当前 PDF 解析器在处理带超链接的 PDF 时存在严重缺陷：页面级超链接被粗暴地追加到最后一个非图片元素上，丢失了链接在文本中的精确位置和锚文本（覆盖在链接上的文字）；远程图片链接（如 `https://...png`）未被识别为图片资源而是被归类为附件；页眉页脚区域的图片和链接未被过滤。这导致含链接、图片链接的 PDF 文档入库后资源关联错乱、内容不完整。

## What Changes

- **新增 link rect 与 span bbox 交叉匹配**：通过 `page.get_links()` 获取链接的 `from` 矩形，与 `get_text("dict")` 中 span 的 bbox 做交集匹配来确定锚文本，锚文本保留在 element.text 中
- **新增 `link_anchors` 字段**：在 `ParsedElement` 上新增可选字段，记录每个内联超链接的 URL、锚文本、asset_id、位置信息
- **新增远程图片 URL 识别**：将 `https?://...png/.jpg/.gif/.webp/.bmp/.svg` 等图片后缀 URL 归类为 `AssetType.image`
- **增强页眉页脚过滤**：对落在页眉页脚区域的图片和链接也进行过滤，不再仅过滤文本块
- **修正链接元素关联**：页面超链接按其 link rect 与 span bbox 的交叉匹配精确定位到所属文本块，不再简单追加到最后元素
- **修正 `_asset_type_for_url`**：从二分类（video/attachment）改为三分类（video/image/attachment）

> 技术验证：PyMuPDF 1.27.2 的 span 字典中不存在 `uri` 字段，因此锚文本提取采用 link rect 与 span bbox 交叉匹配方案（实测交叉比率 0.65~0.80，可精确匹配）。

## Capabilities

### New Capabilities

- `pdf-link-anchor`: 通过 `page.get_links()` + span bbox 交叉匹配提取超链接锚点，保留锚文本和精确位置，通过 `ParsedElement.link_anchors` 字段传递给下游
- `pdf-image-link`: 识别 PDF 中指向远程图片 URL 的超链接，将其归类为 `AssetType.image` 而非附件

### Modified Capabilities

- `pdf-parsing`: 新增链接锚点提取需求、远程图片 URL 识别需求、页眉页脚区域图片/链接过滤需求；修正 `_asset_type_for_url` 分类逻辑

## Impact

- **`parsers/pdf_parser.py`**：核心改动文件，涉及 `_TextBlock`、`_extract_blocks`、`_merge_adjacent_blocks`、`_asset_ids_for_page_links`、`_asset_type_for_url`、`_process_page` 等
- **`app/core/models.py`**：`ParsedElement` 新增 `link_anchors: list[dict]` 字段
- **`tests/test_pdf_parser.py`**：新增链接锚点、远程图片、页眉页脚过滤增强等测试用例
- 不涉及 API 变更、数据库 schema 变更、前端变更
