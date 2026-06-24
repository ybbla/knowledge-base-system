## 1. 基础设施迁移

- [x] 1.1 删除本地 `VIDEO_URL_RE`、`HTTP_URL_RE` 和 `_guess_mime()`、`_is_video_url()`，导入 `parsers.utils` 模块的公共实现
- [x] 1.2 `_XlsxParseState` 继承 `_BaseParseState`，移除重复的 `doc_id`、`doc_version`、`elements`、`_seq`、`_next_seq()` 字段
- [x] 1.3 `parse()` 末尾调用 `self._cleanup_raw_content(doc)`

## 2. 单次加载 + 公式预提取

- [x] 2.1 改为仅 `load_workbook(raw, data_only=True, read_only=False)`（保留 `read_only=False` 以支持 `ws._images` 图片提取），删除 `formula_wb` 二次加载
- [x] 2.2 实现 `_extract_all_formulas_from_zip(raw, sheet_index)` 方法，每 sheet 一次 `finditer` 全量解析 zip XML，返回 `{cell_ref: formula_text}` 映射
- [x] 2.3 `_collect_cells()` 中：始终从 `formulas_map` 查询公式（无论缓存值是否存在），设置 `metadata.formula` 和 `metadata.formula_value_missing`

## 3. 区域检测优化

- [x] 3.1 `_find_regions()` 预构建 `occupied_rows: dict[int, set[int]]` 映射
- [x] 3.2 笛卡尔积遍历时用 `occupied_rows` 做快速空区域跳过

## 4. 链接 URL 类型细分（新增）

- [x] 4.1 新增 `_classify_link_asset_type(url)` 静态方法，按视频 > 图片 > 附件优先级分类
- [x] 4.2 修改 `_assets_from_cell()` 中 asset_type 判断逻辑，调用 `_classify_link_asset_type()` 替代原有二分逻辑
- [x] 4.3 复用 `parsers.utils` 的 `is_video_url()`、`is_attachment_url()`、`MIME_MAP`

## 5. 嵌入图片提取（新增）

- [x] 5.1 新增 `_extract_sheet_images(ws, doc, sheet_name, sheet_index, assets)` 方法，遍历 `ws._images` 提取嵌入图片，返回 `dict[(row,col), list[asset_id]]` 映射
- [x] 5.2 通过 `img.anchor._from` 获取图片锚定单元格位置（0-based → 1-based 转换）
- [x] 5.3 通过 `img._data()` 读取图片二进制数据，`object.__setattr__(asset, '_data', data)` 存储
- [x] 5.4 在 `_collect_cells()` 中合并 `image_cell_map` 的图片 asset_id 到对应单元格的 `_CellInfo.asset_ids`
- [x] 5.5 图片 Asset 通过 `_CellInfo.asset_ids` → `ParsedElement.asset_ids` → `Asset.source_element_id` 完整链路关联到单元格/元素
- [x] 5.6 在 `parse()` 的 sheet 遍历循环中，`_collect_cells()` 之前调用 `_extract_sheet_images()`
- [x] 5.7 异常处理：`_images` 不存在或 `_data()` 失败时静默跳过

## 6. 测试更新

- [x] 6.1 新增测试：嵌入图片被提取为 `AssetType.image` 的 Asset
- [x] 6.2 新增测试：图片链接（`.png`/`.jpg`）被识别为 `AssetType.image`
- [x] 6.3 新增测试：视频链接（`.mp4`）被识别为 `AssetType.video`
- [x] 6.4 新增测试：文档链接（`.pdf`/`.docx`）被识别为 `AssetType.attachment`
- [x] 6.5 新增测试：超链接文字保留（`cell.value` 为链接文字时不被 URL 覆盖）
- [x] 6.6 新增测试：合并单元格 + 超链接组合场景
- [x] 6.7 新增测试：多 Sheet + 图片 + 链接组合场景
- [x] 6.8 运行全部现有测试确认无回归
