# DOCX 解析器全面改进计划

## Context

当前 `DocxParser` 存在以下缺失功能：
1. **段落内联图片未关联**：`w:drawing` 元素被忽略，图片通过 `_extract_images` 全量提取为独立元素，未关联到所在段落
2. **段落超链接未处理**：`w:hyperlink` 元素被忽略，只提取了其中的纯文本
3. **表格内图片/链接未处理**：表格单元格内不提取图片和超链接，`asset_ids` 始终为空
4. **标题仅支持英文样式名**：中文"标题 1"、法文"Titre 1"等无法识别
5. **使用内联重复代码**：本地有 `VIDEO_URL_RE`、MIME 映射等，应迁移到 `parsers/utils.py`

同时合并已有的 `openspec/changes/docx-parser-improvements/` 计划（非英文标题 + 基础设施迁移）。

## 涉及文件

- **主要修改**：[docx_parser.py](knowledge_base_system/parsers/docx_parser.py)（约 200 行新增/修改）
- **公共工具**：[utils.py](knowledge_base_system/parsers/utils.py)（已有，直接 import）
- **基类**：[base.py](knowledge_base_system/parsers/base.py)（`_BaseParseState` 已有，直接继承）
- **测试**：[test_docx_parser.py](knowledge_base_system/tests/test_docx_parser.py)（新增 8+ 测试用例）

## 实现步骤

### 步骤 1：重构 `_DocxParseState`（基础设施迁移）

将 `_DocxParseState` 改为 `@dataclass` 继承 `_BaseParseState`，新增资源跟踪字段：

```python
@dataclass
class _DocxParseState(_BaseParseState):
    _current_list_id: str | None = None
    _tracked_assets: list[str] = field(default_factory=list)
    _link_urls: list[str] = field(default_factory=list)
    _image_asset_map: dict[str, Asset] = field(default_factory=dict)
    assets: list[Asset] = field(default_factory=list)
```

新增方法：
- `track_asset(asset_id)` — 记录当前上下文的资源 ID
- `track_link_url(url)` — 记录链接 URL
- `consume_tracked_assets() -> list[str]` — 消费并清空资源跟踪
- `consume_link_urls() -> list[str]` — 消费并清空链接跟踪

修改 `add_paragraph`：消费 `_tracked_assets` → `el.asset_ids`，`_link_urls` → `el.metadata.link_urls`

删除：显式 `__init__`、`_seq`、`_section_path`、`_next_seq`（全部从基类继承）、`_image_counter`

### 步骤 2：导入公共工具，删除本地重复

从 `parsers/utils.py` 导入：
- `guess_mime`, `is_video_url`, `is_attachment_url`, `normalize_text`
- `VIDEO_URL_RE`, `HTTP_URL_RE`, `MIME_MAP`, `ATTACHMENT_EXTENSIONS`

删除本地的：
- `VIDEO_URL_RE` 正则（第 41-44 行）
- `_extract_images` 中的 `mimetype_map` 字典

### 步骤 3：非英文标题样式名支持

新增类属性 `HEADING_KEYWORDS`：
```python
HEADING_KEYWORDS = {
    "heading", "head",      # 英文
    "标题",                  # 中文
    "titre", "title",       # 法文/变体
    "uberschrift", "überschrift",  # 德文
    "titulo", "título",     # 西班牙文/葡萄牙文
    "intestazione",         # 意大利文
    "見出し",               # 日文
}
```

新增 `_detect_heading_level(style_name, docx) -> int | None` 方法：
1. 样式名小写后检查是否包含任一关键词
2. 去掉关键词后提取尾部数字作为 level
3. 无数字时通过 `docx.styles` 二次确认

修改 `_process_paragraph`：用 `_detect_heading_level()` 替换原来的两阶段检测逻辑。
增加保护：`is_list` 为 True 时强制 `heading_match = None`（防止 List 样式误判为标题）。

### 步骤 4：段落中内联图片（`w:drawing`）处理

新增 `_extract_drawing_rIds(p_el) -> list[str]`：
遍历 `w:drawing` → `a:blip` → 提取 `r:embed` 属性。

新增 `_resolve_image_asset(rId, docx, state) -> Asset | None`：
通过 `docx.part.rels[rId]` 查找 relationship，匹配 `target_ref` 到 `state._image_asset_map`。

修改 `_process_paragraph` 的文本提取逻辑：
- 从 `p_el.iter()` 全量遍历改为按 `w:p` 的直接子元素顺序遍历（`w:r` 和 `w:hyperlink`）
- 对 `w:r`：先检查 `w:drawing`（提取 rId → 解析 Asset → track），再提取 `w:t` 文本
- 对 `w:hyperlink`：提取显示文字和目标 URL，按类型处理（见步骤 5）
- 图片在文本中用 `[图片: filename]` 占位

修改空段落跳过逻辑：有 drawing 或 hyperlink 但没有文本的段落仍创建元素。

### 步骤 5：段落中超链接（`w:hyperlink`）处理

DOCX 中超链接的结构：
```
w:p
  w:r         → 普通文本
  w:hyperlink → 包含 w:r → w:t（链接显示文字）
  w:r         → 普通文本
```

遍历 `w:p` 的直接子元素（`p_el.findall("*")` 或迭代 `p_el`），遇到 `w:hyperlink` 时：

1. 提取显示文字：遍历其内部所有 `w:t` 节点，拼接文本
2. 提取目标 URL：通过 `r:id` 属性在 `docx.part.rels` 中查找 → `rel.target_ref`
3. 分类 URL（`_classify_link_url`）：
   - **文件/附件链接**（`AssetType.attachment`）：创建 Asset，文本只保留显示文字（链接的 asset_id 通过 `track_asset` 关联到段落）
   - **视频链接**（`AssetType.video`）：创建 Asset，文本只保留显示文字
   - **图片链接**（`AssetType.image`）：创建 Asset，文本只保留显示文字
   - **普通网页链接**：URL 写入段落 `metadata.link_urls`，文本保留显示文字（不追加 URL）

新增 `_classify_link_url(url) -> AssetType | None`（与 MarkdownParser 相同逻辑）：
视频 URL → `AssetType.video`，图片后缀 → `AssetType.image`，附件后缀 → `AssetType.attachment`，其他 → None。

新增 `_IMAGE_EXTENSIONS` 常量（与 MarkdownParser 保持一致）。

### 步骤 6：图片预提取重构

将 `_extract_images` 改为 `_build_image_asset_map(doc, state)`：
- 从 zip 提取 `word/media/*` → 创建 Asset → 存入 `state._image_asset_map` 和 `state.assets`
- 不再创建独立的 image 类型 ParsedElement（图片关联到其所在段落/表格）
- 使用 `guess_mime` 代替本地 MIME 字典

### 步骤 7：表格单元格图片和超链接处理

修改 `_process_table` 的单元格提取逻辑：
- 按 `w:tc` 的直接子元素遍历（`w:r` 和 `w:hyperlink`，与段落相同模式）
- 提取 `w:drawing` → 解析 Asset → 收集到 `cell_asset_ids`
- 提取 `w:hyperlink` → 提取显示文字 + URL → 分类：
  - 附件链接 → 创建 Asset，文本保留 `显示文字(url)`
  - 视频/图片链接 → 创建 Asset，文本用 `[视频: url]` / `[图片: url]`
  - 普通网页 → URL 记录到 cell metadata
- 单元格存储从 `str` 改为 `(text: str, asset_ids: list[str])` 元组

更新 `vertical_merges` 字典：值类型从 `str` 改为 `tuple[str, list[str]]`。

更新 `structured_data` 构建：
- 每个 cell 的 `asset_ids` 从实际提取填充
- 表格级 `asset_ids` 汇总所有单元格的资源 ID（去重）

### 步骤 8：视频提取更新

修改 `_extract_videos`：
- 使用 `utils.VIDEO_URL_RE` 和 `utils.guess_mime`
- 不再创建独立的 video 类型 ParsedElement（视频关联到所在元素）
- Asset 存入 `state.assets`

### 步骤 9：整合 `parse()` 入口

新的 `parse()` 流程：
1. 打开 docx → 创建 state
2. `_build_image_asset_map(doc, state)` — 预提取所有图片到 asset map
3. 遍历 body 元素（段落 + 表格）
4. `state.flush_elements()` → elements
5. `_extract_videos(doc, elements, state)` — 提取视频链接
6. `_link_assets_to_elements(elements, state.assets)` — 回填 Asset.source_element_id
7. `doc.source_hash = compute_hash(content)`
8. 返回 `ParseResult(doc=doc, elements=elements, assets=state.assets)`

新增 `_link_assets_to_elements(elements, assets)`（与 MarkdownParser 相同模式）。

### 步骤 10：清理旧代码

删除：
- `_extract_images` 方法（替换为 `_build_image_asset_map`）
- 本地 `VIDEO_URL_RE`
- 本地 MIME 字典

## 页眉页脚说明

DOCX 的 `python-docx` 库的 `docx.element.body` 只包含正文元素（`w:p` 和 `w:tbl`），页眉页脚存储在 `docx.sections[].header` 和 `docx.sections[].footer` 中。当前代码已只遍历 body，天然满足"只处理正文"的要求。

## 验证方案

### 单元测试（test_docx_parser.py 新增）

| 测试 | 验证内容 |
|------|---------|
| `test_heading_chinese` | 中文"标题 1"样式正确识别 |
| `test_heading_french` | 法文"Titre 1"样式正确识别 |
| `test_paragraph_with_image` | 段落中内联图片关联到 `asset_ids`，文本含 `[图片: xxx]` |
| `test_paragraph_with_hyperlink` | 段落中普通网页超链接 URL 写入 `metadata.link_urls`，文本保留显示文字 |
| `test_paragraph_with_attachment_link` | 文件/附件链接创建 Asset，段落文本只保留显示文字，asset_id 关联到段落 |
| `test_paragraph_with_video_link` | 视频链接创建 Asset 并关联到段落 |
| `test_table_cell_with_image` | 表格单元格图片关联到 `structured_data` 的 cell `asset_ids` |
| `test_table_cell_with_hyperlink` | 表格单元格超链接正确处理 |
| `test_merged_cell_with_asset` | gridSpan/vMerge 合并单元格正确传递 asset_ids |
| `test_image_only_paragraph` | 纯图片段落（无文本）仍创建元素 |
| `test_asset_source_element_backfill` | `_link_assets_to_elements` 正确回填 |

### 回归测试

运行 `pytest tests/test_docx_parser.py -v` 确认所有已有测试通过（`test_extract_embedded_image_from_raw_content` 需要适配：图片不再创建独立元素，改为关联到段落）。

### 集成验证

```bash
cd knowledge_base_system
pytest tests/ -v  # 全量测试
```

## 风险与注意事项

1. **`docx.part.rels` 访问**：`python-docx` 的 `Document` 对象通过 `part.rels` 访问 relationships，需确认 `DocxDocument(io.BytesIO(content))` 创建的对象有此属性
2. **图片元素语义变更**：图片不再创建独立 `ElementType.image` 元素，而是关联到段落/表格的 `asset_ids`。下游如果有依赖独立 image 元素的逻辑需要适配
3. **`_BaseParseState` dataclass 继承**：子类使用 `@dataclass` 继承父 dataclass，字段默认值需使用 `field(default_factory=...)`
4. **`_cleanup_raw_content` 不存在**：经确认 `DocumentParser` 基类目前没有 `_cleanup_raw_content` 方法，此步骤从计划中移除
