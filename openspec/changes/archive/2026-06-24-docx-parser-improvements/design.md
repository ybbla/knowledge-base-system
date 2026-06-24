## Context

DocxParser 当前存在多项功能缺失：标题仅支持英文样式名、段落内联图片和超链接被忽略、表格单元格不提取资源、图片/视频提取使用内联重复代码。

依赖：`parser-common-infra` change 中 `_BaseParseState` 和 `parsers/utils.py` 已完成。

## Goals / Non-Goals

**Goals:**
- 迁移到公共基础设施（`_BaseParseState` 继承 + `utils` 模块导入）
- 支持中文、法文、德文、西班牙文、葡萄牙文、意大利文、日文等非英文标题样式名
- 段落中内联图片（`w:drawing`）关联到所在段落的 `asset_ids`
- 段落中超链接（`w:hyperlink`）按类型分类处理（视频/图片/附件/普通网页）
- 表格单元格内的图片和超链接正确提取并关联
- 图片预提取改为 asset map 模式，不再创建独立 image 元素
- 视频提取使用公共工具，不再创建独立 video 元素

**Non-Goals:**
- 不新增 `ElementType`
- 不修改 `ParseResult` 结构

## Decisions

### 1. `_DocxParseState` 继承 `_BaseParseState`

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

修改 `add_paragraph`：消费 `_tracked_assets` → `el.asset_ids`，`_link_urls` → `el.metadata.link_urls`。

删除：显式 `__init__`、`_seq`、`_section_path`、`_next_seq`（全部从基类继承）、`_image_counter`。

**理由**：与 MarkdownParser 的 `_ParseState` 保持一致的资源跟踪模式，消除代码重复。

### 2. 样式名匹配扩展

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

**理由**：单一方法替代分散的两阶段检测逻辑，增加可测试性；关键词集合覆盖主流 Office 语言版本。

### 3. 段落子元素遍历策略

修改 `_process_paragraph` 的文本提取逻辑：从 `p_el.iter()` 全量遍历改为按 `w:p` 的直接子元素顺序遍历（`w:r` 和 `w:hyperlink`）。

遍历 `p_el` 的每个直接子元素（通过 `p_el.findall("*")` 或迭代 `p_el`）：

**对 `w:r`（文本运行）：**
1. 先检查是否包含 `w:drawing`（内联图片）
2. 有 drawing → 提取 `a:blip` → `r:embed` rId → 解析 Asset → `track_asset()`
3. 再提取 `w:t` 文本（如果有）
4. 图片在文本中用 `[图片: filename]` 占位

**对 `w:hyperlink`（超链接）：**
1. 提取显示文字：遍历其内部所有 `w:t` 节点，拼接文本
2. 提取目标 URL：通过 `r:id` 属性在 `docx.part.rels` 中查找 → `rel.target_ref`
3. 分类 URL（`_classify_link_url`）：
   - 文件/附件链接 → 创建 Asset，文本只保留显示文字（asset_id 通过 `track_asset` 关联）
   - 视频链接 → 创建 Asset，文本只保留显示文字
   - 图片链接 → 创建 Asset，文本只保留显示文字
   - 普通网页链接 → URL 写入段落 `metadata.link_urls`，文本保留显示文字

修改空段落跳过逻辑：有 drawing 或 hyperlink 但没有文本的段落仍创建元素。

**理由**：DOCX 中 `w:p` 的子元素是顺序混合的（文本运行和超链接交错出现），按直接子元素顺序遍历才能保持原文顺序。`w:hyperlink` 内的 `w:r` 子元素不应与段落级的 `w:r` 混淆。

### 4. `_classify_link_url` 与 MarkdownParser 保持一致

新增 `_classify_link_url(url) -> AssetType | None`（静态方法，与 MarkdownParser 相同逻辑）：
视频 URL → `AssetType.video`，图片后缀 → `AssetType.image`，附件后缀 → `AssetType.attachment`，其他 → None。

新增 `_IMAGE_EXTENSIONS` 常量（与 MarkdownParser 保持一致）：
```python
_IMAGE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif",
}
```

**理由**：链接分类逻辑在 DOCX 和 Markdown 解析器中完全一致，避免行为不一致。

### 5. 图片预提取改为 asset map 模式

将 `_extract_images` 改为 `_build_image_asset_map(doc, state)`：
- 从 zip 提取 `word/media/*` → 创建 Asset
- 存入 `state._image_asset_map`，使用**双 key**：
  - `word/media/image1.png`（zip 内完整路径）
  - `media/image1.png`（与 `rel.target_ref` 匹配的短路径）
- 同时存入 `state.assets`
- 不再创建独立的 image 类型 ParsedElement（图片关联到其所在段落/表格）
- 使用 `utils.guess_mime` 代替本地 MIME 字典

新增 `_resolve_image_asset(rId, docx, state) -> Asset | None`：
通过 `docx.part.rels[rId]` 查找 relationship → `rel.target_ref`（格式为 `media/image1.png`）→
在 `state._image_asset_map` 中查找（双 key 保证命中）。

新增 `_extract_drawing_rIds(p_el) -> list[str]`：
遍历 `w:drawing` → `a:blip` → 提取 `r:embed` 属性（`qn("r:embed")` 命名空间已验证正确）。

**验证结果**：
- `docx.part.rels[rId].target_ref` 对图片返回 `media/image1.png`（无 `word/` 前缀）
- zip 内路径为 `word/media/image1.png`（有 `word/` 前缀）
- 因此需要双 key 存储以同时支持 rId 解析和后续 zip 操作

**理由**：图片不再独立成元素，而是作为段落/表格的附属资源，语义更准确。asset map 双 key 模式解决了 rels 路径与 zip 路径不一致的问题。

### 6. 表格单元格资源处理

**重要发现**：`w:tc`（表格单元格）的直接子元素是 `w:tcPr` 和 `w:p`（段落），而不是 `w:r` 和 `w:hyperlink`。
图片和超链接嵌套在 `w:tc` → `w:p` → `w:r`/`w:hyperlink` 中。

因此修改 `_process_table` 的单元格提取逻辑：
- 遍历 `w:tc` 中的每个 `w:p`（段落）子元素
- 对每个 `w:p`，复用段落处理模式：按 `w:p` 的直接子元素遍历（`w:r` 和 `w:hyperlink`）
- 提取 `w:drawing` → 调用 `_resolve_image_asset()` → 收集到 `cell_asset_ids`
- 提取 `w:hyperlink` → 提取显示文字 + URL → 分类：
  - 附件链接 → 创建 Asset，文本保留显示文字，asset_id 收集到 `cell_asset_ids`
  - 视频/图片链接 → 创建 Asset，文本保留显示文字，asset_id 收集到 `cell_asset_ids`
  - 普通网页 → URL 记录到 cell metadata
- 提取 `w:t` 文本 → 拼接 cell 文本
- 多个 `w:p` 之间用换行符分隔

单元格存储从 `str` 改为 `(text: str, asset_ids: list[str])` 元组。

更新 `vertical_merges` 字典：值类型从 `str` 改为 `tuple[str, list[str]]`。

更新 `structured_data` 构建：
- 每个 cell 的 `asset_ids` 从实际提取填充
- 表格级 `asset_ids` 汇总所有单元格的资源 ID（去重）

**验证结果**：
- `w:tc` 的直接子元素：`tcPr`、`w:p`（不是 `w:r`/`w:hyperlink`）
- `w:p` 内的 `w:drawing` 通过 `r:embed`（`qn("r:embed")`）引用图片 rId
- `w:p` 内的 `w:hyperlink` 通过 `r:id` 引用超链接 rId

**理由**：与 MarkdownParser 表格处理模式一致（`_current_row` 每格存 `(text, asset_ids)` 元组），下游 LLM 语义抽取可获取完整的表格资源信息。

### 7. 视频提取更新

修改 `_extract_videos`：
- 使用 `utils.VIDEO_URL_RE` 和 `utils.guess_mime`
- 不再创建独立的 video 类型 ParsedElement（视频关联到所在元素）
- Asset 存入 `state.assets`

**理由**：视频与图片一致，不应作为独立元素，而是关联到包含它的段落/表格。

### 8. `parse()` 入口整合

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

**理由**：流程与 MarkdownParser 保持一致，`flush_elements` 后 elements 的 element_id 已确定，此时回填 Asset.source_element_id 保证关联正确。

### 9. 页眉页脚说明

DOCX 的 `python-docx` 库的 `docx.element.body` 只包含正文元素（`w:p` 和 `w:tbl`），页眉页脚存储在 `docx.sections[].header` 和 `docx.sections[].footer` 中。当前代码已只遍历 body，天然满足"只处理正文"的要求，无需额外处理。

## Risks / Trade-offs

1. **`docx.part.rels` 访问**：已验证 `DocxDocument(io.BytesIO(content)).part.rels` 可正常访问，返回 `Relationships` 对象，`rId` 键 → `rel.target_ref` / `rel.reltype` 均可获取。图片 reltype 以 `relationships/image` 结尾，超链接 reltype 以 `relationships/hyperlink` 结尾。
2. **图片 rels 路径与 zip 路径不一致**：`rel.target_ref` 返回 `media/image1.png`（无 `word/` 前缀），而 zip 内路径为 `word/media/image1.png`。需要在 `_image_asset_map` 中使用双 key 存储。
3. **图片元素语义变更（BREAKING）**：图片不再创建独立 `ElementType.image` 元素，而是关联到段落/表格的 `asset_ids`。下游如果有依赖独立 image 元素的逻辑需要适配。
4. **视频元素语义变更（BREAKING）**：视频不再创建独立 `ElementType.video` 元素。下游如有依赖独立 video 元素的逻辑需要适配。
5. **`_BaseParseState` dataclass 继承**：子类使用 `@dataclass` 继承父 dataclass，字段默认值需使用 `field(default_factory=...)`。
6. **表格单元格类型变更**：单元格从 `str` 变为 `(text, asset_ids)` 元组，影响 `vertical_merges` 和 `structured_data` 构建逻辑。
7. **表格单元格结构层级**：`w:tc` 的直接子元素是 `w:p`（不是 `w:r`/`w:hyperlink`），图片/超链接嵌套在 `w:tc` → `w:p` → `w:r`/`w:hyperlink` 中。设计已据此修正。
8. **`r:embed` 命名空间**：`qn("r:embed")` 已验证正确返回 `{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed`。
9. **`w:p` 的直接子元素**：已验证 `w:p` 中混合出现 `w:r` 和 `w:hyperlink`，按直接子元素顺序遍历可正确保持原文顺序。
