## Why

XlsxParser 存在两个层面的问题：

**性能与代码质量**：
- `load_workbook` 被调用两次（`data_only=True` + `data_only=False`）导致大文件内存翻倍
- `_find_regions` 用笛卡尔积生成候选区域，稀疏工作表产生大量空区域遍历
- 存在内联重复代码（本地 `VIDEO_URL_RE`、`HTTP_URL_RE`、`_guess_mime()` 等）

**功能缺失**：
- 嵌入图片（Excel 中直接插入的图片）完全未被提取，用户粘贴的截图、logo 等直接丢失
- 链接 URL 类型分类粗糙：仅分 `video` vs `attachment`，图片链接（`.png`/`.jpg`）被错归为 `attachment`，导致下游 `process_image()` 视觉理解无法触发

## What Changes

- **单次加载**：仅 `load_workbook(data_only=True, read_only=False)`，公式文本从 zip 原始 XML 按需提取（`read_only=False` 保留以支持 `ws._images` 图片提取）
- **区域检测优化**：构建 `occupied_rows: dict[int, set[int]]` 用于快速跳过空区域，避免笛卡尔积产生的无效遍历
- **嵌入图片提取**：遍历 `ws._images`，提取嵌入图片为 `AssetType.image` 的 Asset，与 `docx_parser` 保持一致的 `_data` 存储模式
- **链接类型细分**：新增 `_classify_link_asset_type()`，按视频 > 图片 > 附件优先级分类，图片链接正确归为 `AssetType.image`
- **迁移到公共基础设施**：使用 `utils` 模块的公共实现，`_XlsxParseState` 继承 `_BaseParseState`
- **删除重复代码**：本地 `VIDEO_URL_RE`、`HTTP_URL_RE`、`_guess_mime()`、`_is_video_url()` 等

## Capabilities

### Modified Capabilities
- `xlsx-parsing`: 工作簿单次加载优化、稀疏区域检测性能修复、公共基础设施迁移、嵌入图片提取、链接 URL 类型细分

## Impact

- **修改文件**：`parsers/xlsx_parser.py`
- **测试**：更新 `tests/test_xlsx_parser.py` 补充嵌入图片提取、链接类型细分、超链接文字保留测试
- **内存**：大文件内存占用减半（删除 formula_wb 二次加载）
- **功能增强**：嵌入图片不再丢失，图片链接正确触发视觉理解
- **API 兼容**：无 **BREAKING** 变更
