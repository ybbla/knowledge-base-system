## 1. 公共工具层 — classify_link 函数

- [x] 1.1 在 [parsers/utils.py](knowledge_base_system/parsers/utils.py) 中添加 `classify_link(url: str) -> str` 函数，按 URL 后缀和域名特征分类为 `image`/`video`/`audio`/`document`/`url`，需导入 `urllib.parse.urlparse`
- [x] 1.2 更新 `__all__` 导出列表，加入 `classify_link`（utils.py 无 __all__，模块级函数自动导出）

## 2. PPTX 解析器 — 链接信息收集

- [x] 2.1 在 [pptx_parser.py](knowledge_base_system/parsers/pptx_parser.py) 中新增 `_collect_shape_links` 方法：遍历形状级 `click_action.hyperlink` 和运行级 `run.hyperlink`，收集 `{text, url, link_type}` 三元组。图片形状的 `_shape_text()` 返回空字符串，需用 `filename` 作为链接文字 fallback
- [x] 2.2 修改 `_add_text_shape` 方法（普通段落分支）：调用 `_collect_shape_links`，将结果写入 `ParsedElement.structured_data` 的 `links` 字段
- [x] 2.3 修改 `_add_text_shape` 方法（列表分支）：修复已有缺陷——补充 `_asset_ids_for_shape_hyperlinks` 调用（此前列表项中的运行级/形状级超链接不会创建 Asset）；同时调用 `_collect_shape_links` 将链接信息写入各子元素的 `structured_data.links`
- [x] 2.4 修改 `_add_image` 方法：当图片形状带有超链接时，调用 `_collect_shape_links` 写入 `structured_data.links`

## 3. PPTX 解析器 — 统一资源分类与 MIME 推断

- [x] 3.1 导入 `parsers.utils.classify_link` 和 `parsers.utils.guess_mime`
- [x] 3.2 修改 `_asset_type_for_url` 方法：使用 `classify_link` 替代内部 `_is_video_url`/`_is_audio_url`，映射 `image`→`AssetType.image`、`video`→`AssetType.video`、`audio`→`AssetType.audio`、`document`/`url`→`AssetType.attachment`
- [x] 3.3 将 `_guess_mime` 调用替换为 `parsers.utils.guess_mime`（`_add_image` line 388 和 `_asset_for_url` line 545 两个调用点）
- [x] 3.4 删除不再需要的 `_is_video_url`、`_is_audio_url`、`_guess_mime` 方法，以及 `VIDEO_URL_RE`、`AUDIO_URL_RE` 类属性（`HTTP_URL_RE` 必须保留——仍被 `_asset_ids_for_text` 使用）

## 4. 测试更新

- [x] 4.1 在 [test_pptx_parser.py](knowledge_base_system/tests/test_pptx_parser.py) 中新增测试用例：验证文本运行中超链接的文字保留和 `structured_data.links` 输出
- [x] 4.2 新增测试用例：验证形状级超链接（`click_action.hyperlink`）的文字和链接记录
- [x] 4.3 新增测试用例：验证图片形状带超链接时 `structured_data.links` 正确输出（含 filename 作为链接文字 fallback）
- [x] 4.4 新增测试用例：验证多超链接混合文本（部分 run 有超链接、部分无）的正确处理
- [x] 4.5 新增测试用例：验证列表项中的超链接同时创建 Asset 和写入 `structured_data.links`
- [x] 4.6 新增测试用例：验证 `classify_link` 对各类 URL（图片、视频、音频、文档、普通链接）的分类正确性
- [x] 4.7 新增测试用例：验证 `guess_mime` 替换 `_guess_mime` 后行为不变
- [x] 4.8 运行全量 PPTX 解析器测试，确保已有测试不退化：`pytest tests/test_pptx_parser.py tests/test_parser_utils.py -v`
