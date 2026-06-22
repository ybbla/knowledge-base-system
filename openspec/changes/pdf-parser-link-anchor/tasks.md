## 1. 数据模型变更

- [x] 1.1 `app/core/models.py` — `ParsedElement` 新增 `link_anchors: list[dict[str, Any]]` 字段（`Field(default_factory=list)`），中文注释说明每个 dict 的键（url, text, asset_id, page, bbox）。**向后兼容**：`Field(default_factory=list)` 确保旧数据反序列化不报错
- [x] 1.2 `parsers/pdf_parser.py` — `_TextBlock` 新增 `span_bboxes: list[tuple[str, tuple[float,float,float,float]]]` 字段，记录每个 span 的文本和 bbox 四元组

## 2. PDF 解析器核心改动

- [x] 2.1 `parsers/pdf_parser.py` — 新增 `IMAGE_EXTENSIONS` 常量（`.png`/`.jpg`/`.jpeg`/`.gif`/`.webp`/`.bmp`/`.svg`）
- [x] 2.2 `parsers/pdf_parser.py` — 新增 `_is_image_url(url: str) -> bool` 静态方法，按后缀判断
- [x] 2.3 `parsers/pdf_parser.py` — `_asset_type_for_url()` 修正：三分类（视频→video、图片→image、其余→attachment）
- [x] 2.4 `parsers/pdf_parser.py` — `_extract_blocks()` 增强：在 span 遍历中收集每个 span 的 `(text, bbox)` 到 `_TextBlock.span_bboxes`
- [x] 2.5 `parsers/pdf_parser.py` — `_merge_adjacent_blocks()` 增强：合并两个块时也合并 `span_bboxes` 列表
- [x] 2.6 `parsers/pdf_parser.py` — `_process_page()` 增强：步骤 3（文本块）之后新增步骤 3.5，遍历 `page.get_links()`，对每个 link 用 `from` 矩形与当前页所有块的 `span_bboxes` 做交叉匹配（阈值 ≥ 0.1），找到锚文本后创建 Asset 并写入对应元素的 `link_anchors` 和 `asset_ids`；未匹配到的孤立 link 回退到原有 `_asset_ids_for_page_links()` 兜底逻辑
- [x] 2.7 `parsers/pdf_parser.py` — `_process_page()` 增强：步骤 4（图片）检查图片 bbox Y 是否在页眉页脚区域（`y0 < page_height * 0.15` 或 `y1 > page_height * 0.85`），是则跳过；步骤 5（链接兜底）同样检查
- [x] 2.8 `parsers/pdf_parser.py` — 所有新增/修改的方法添加中文注释

## 3. 测试

- [x] 3.1 `tests/test_pdf_parser.py` — `test_link_anchor_by_bbox_match`：创建带 link rect 的 PDF，验证 link rect 与 span bbox 交叉匹配正确、锚文本保留在 text 中、`link_anchors` 字段正确填充
- [x] 3.2 `tests/test_pdf_parser.py` — `test_multiple_links_in_page`：同一页多个 link rect 均正确匹配到对应文本块，互不干扰
- [x] 3.3 `tests/test_pdf_parser.py` — `test_remote_image_url_as_image_asset`：`.png`/`.jpg` URL → `AssetType.image`
- [x] 3.4 `tests/test_pdf_parser.py` — `test_asset_type_classification`：`.pdf`→attachment，YouTube→video，`.png`→image，三者不混淆
- [x] 3.5 `tests/test_pdf_parser.py` — `test_link_fallback_when_no_span_match`：link rect 无法匹配任何 span 时回退到原有 `_asset_ids_for_page_links()` 逻辑
- [x] 3.6 `tests/test_pdf_parser.py` — `test_header_footer_images_filtered`：页眉页脚区域图片被过滤
- [x] 3.7 `tests/test_pdf_parser.py` — `test_header_footer_links_filtered`：页眉页脚区域链接被过滤
- [x] 3.8 `tests/test_pdf_parser.py` — `test_link_anchor_page_number`：link_anchors 中 page 字段正确
- [x] 3.9 运行全量测试 `pytest tests/ -v` 确保无回归（121/122 通过，1 个失败是已有 TestScoreComponents 问题）
