## Context

当前 PDF 解析器（`parsers/pdf_parser.py`）使用 PyMuPDF (fitz) 解析 PDF 文档。文本提取通过 `page.get_text("dict")` 获取 block/line/span 三层结构，超链接提取通过 `page.get_links()` 获取页面级注释列表。现有实现的问题是：

1. **链接信息脱节**：`_asset_ids_for_page_links()` 拿到页面级链接后，仅将 asset_id 追加到当前页"最后一个非 image 元素"的 `asset_ids` 中，完全丢失了链接在文本中的精确位置和锚文本
2. **链接锚文本未提取**：PyMuPDF 的 `page.get_links()` 返回链接的 `from` 矩形（链接在页面上的位置），通过将该矩形与 span 的 bbox 做交叉匹配，可以确定哪个 span 的文本是链接的锚文本，但当前代码未做此匹配
3. **图片 URL 类型错误**：`_asset_type_for_url()` 中非视频 URL 一律返回 `AssetType.attachment`，导致 `https://...screenshot.png` 被归类为附件而非图片
4. **页眉页脚过滤不完整**：`_detect_header_footer_blocks()` 只过滤文本块，`_process_page()` 中图片和链接提取在过滤之后仍然处理页眉页脚区域的内容

**验证结论**：经实际代码验证，PyMuPDF 1.27.2 的 span 字典中**不存在 `uri` 字段**（`insert_textbox` 和 `insert_htmlbox` 均不会在 span 上设置链接信息）。可行方案是：`page.get_links()` 获取链接矩形 + span bbox 交叉匹配来确定锚文本。

下游影响：Pipeline 的 `_prepare_assets()` 按 asset_type 分发处理，`process_image()` 可处理远程图片 URL（`read_uri_bytes` 支持 `http(s)://`），因此修正 `AssetType` 后远程图片可被正确下载和理解。

## Goals / Non-Goals

**Goals:**
- 通过 `page.get_links()` + span bbox 交叉匹配提取内联超链接锚文本（链接上覆盖的文字），保留到 element.text
- 将链接信息（URL、锚文本、asset_id、位置）记录到 `ParsedElement.link_anchors` 字段
- 识别远程图片 URL（`.png`/`.jpg`/`.jpeg`/`.gif`/`.webp`/`.bmp`/`.svg` 后缀），归类为 `AssetType.image`
- 页眉页脚区域的图片和链接也进行过滤
- 页面级超链接按其 link rect 与 span bbox 的交叉匹配精确定位到所属文本块元素

**Non-Goals:**
- 不新增 ElementType（如 `link` 类型）
- 不修改 SemanticExtractor 来消费 `link_anchors`（后续单独任务）
- 不下载远程图片（`process_image` 已有此能力）
- 不修改 PDF 外其他解析器的链接处理

## Decisions

### 决策 1: 使用 page.get_links() + span bbox 交叉匹配确定锚文本（非 span 级 uri 字段）

**选择**：`_extract_blocks()` 在遍历 span 时同时收集 `span_bboxes: list[tuple[str, tuple[float,...]]]`（span 文本 + bbox）；`_process_page()` 在步骤 3（文本块生成元素）之后新增步骤 3.5，遍历 `page.get_links()`，对每个 link 用 `from` 矩形与当前页所有块的 `span_bboxes` 做交叉匹配

**验证结果**：
- PyMuPDF span 字典中没有 `uri` 字段（实测确认）
- `page.get_links()` 返回的 link 包含 `from` 矩形，可与 span bbox 做交集判断
- 实测：link rect 与对应 span bbox 交叉比率为 0.55~0.88，足以精确匹配
- 多个 `insert_textbox` 生成的多个 span 均保留独立 bbox
- `block_to_element` 映射方案已验证：在 `_process_page` 的 for 循环中记录 `block_index → element_index`，匹配后原地修改 `elements[ei].link_anchors` 和 `elements[ei].asset_ids`

**理由**：
- 这是 PyMuPDF 唯一可用的链接锚文本提取方式
- span bbox 信息已在 `get_text("dict")` 中可用，无需额外 API 调用
- 在 `_process_page` 中内联匹配（而非在 `_add_text_block` 中）保持了方法职责单一
- 未匹配到的孤立 link 回退到原有 `_asset_ids_for_page_links()` 兜底逻辑

### 决策 2: 在 _TextBlock 上新增 `span_bboxes` 字段

**选择**：`_TextBlock` 新增 `span_bboxes: list[tuple[str, tuple[float, float, float, float]]]` 字段（span 文本 + bbox 四元组）

**理由**：
- 块合并后仍需保留每个原始 span 的 bbox，用于链接精确匹配
- 合并时合并两个块的 span_bboxes 列表
- 不改变 `block.text` 的现有逻辑

### 决策 3: link_anchors 使用 dict 列表

**选择**：`ParsedElement.link_anchors: list[dict[str, Any]] = Field(default_factory=list)`

每个 dict 包含：`url`、`text`（锚文本）、`asset_id`、`page`、`bbox`

**理由**：与 `ParsedElement` 已有的 `metadata`、`structured_data` 字段风格一致

### 决策 4: 使用后缀判断图片 URL 类型

**选择**：在 `pdf_parser.py` 新增 `IMAGE_EXTENSIONS` 常量，`_asset_type_for_url()` 改为三分类（video → image → attachment）

### 决策 5: 页眉页脚区域过滤复用现有常量

**选择**：在 `_process_page()` 的步骤 4 和 5 中检查图片/链接的 Y 坐标，复用 `HEADER_FOOTER_Y_MARGIN = 0.15`

## Risks / Trade-offs

- **[风险] link rect 可能覆盖多个 span**：某些 PDF 中一个链接可能跨越多个 span。→ 缓解：取交叉比率最大的 span 作为锚文本；如果有多个 span 交叉比率相近，合并它们的文本
- **[风险] link rect 可能不精确**：某些 PDF 生成器产生的 link rect 可能与实际文字位置有偏移。→ 缓解：使用较低的交叉阈值（≥0.1），并在找不到匹配时回退到"最后一个非 image 元素"
- **[风险] 图片 URL 后缀判断可能不准确**：某些 CDN 链接不含图片扩展名。→ 缓解：后缀判断是合理的启发式方法，未来可引入 Content-Type 头检测
