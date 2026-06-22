## Context

当前 `PptxParser` 已能从形状级 `click_action.hyperlink` 和文本运行级 `run.hyperlink` 中提取 URL 并创建 Asset。但存在以下问题：

1. **链接文字丢失**：运行级超链接的显示文字虽然已包含在 `paragraph.text` 中，但没有显式记录"哪段文字对应哪个 URL"的映射关系
2. **资源分类逻辑分散**：`_asset_type_for_url`、`_is_video_url`、`_is_audio_url` 在 `PptxParser` 内部实现，而 `parsers/utils.py` 已有 `is_video_url`、`is_attachment_url`、`VIDEO_URL_RE`、`HTTP_URL_RE` 等公共工具，存在重复
3. **MIME 推断重复**：`_guess_mime` 内部维护了一套 MIME 映射表，与 `parsers/utils.py` 的 `guess_mime` + `MIME_MAP` 高度重复（`xlsx_parser` 已使用公共版本）
4. **图片超链接未记录**：图片形状如果同时带有超链接（如点击图片跳转到文档），链接信息未被写入 `ParsedElement`
5. **缺少 `classify_link` 公共函数**：其他解析器（如 HtmlParser）也有类似的 URL→AssetType 分类需求，但没有统一的分类函数

## Goals / Non-Goals

**Goals:**
- 在 `ParsedElement.structured_data.links` 中记录每个超链接的 `{text, url, link_type}` 三元组
- 在 `parsers/utils.py` 中添加 `classify_link` 公共函数，统一按 URL 后缀/域名分类为 `image`/`video`/`audio`/`document`/`url`
- PPTX 解析器改用 `classify_link` 替代内部 `_asset_type_for_url`
- PPTX 解析器改用 `parsers.utils.guess_mime` 替代内部 `_guess_mime`
- 图片形状的超链接也写入 `structured_data.links`
- 删除 PptxParser 中不再需要的内部重复代码

**Non-Goals:**
- 不下载或递归解析超链接指向的外部资源
- 不修改 Asset 的创建和去重逻辑（`_asset_for_url`、`_asset_ids_for_urls` 不变）
- 不修改下游 pipeline、语义抽取器的行为（它们可选择性使用 `links` 字段）
- 不修改前端展示逻辑
- 不修改其他解析器（HtmlParser 等）使用 `classify_link`

## Decisions

### Decision 1: Link 数据结构

选择在 `ParsedElement.structured_data` 中新增 `links` 数组：

```json
{
  "links": [
    {"text": "点击查看文档", "url": "https://example.com/doc.pdf", "link_type": "document"},
    {"text": "演示视频", "url": "https://example.com/demo.mp4", "link_type": "video"}
  ]
}
```

- **理由**：`structured_data` 是 `dict | None`，已有表格等结构使用此字段。新增 `links` 不影响现有消费方。
- **备选方案**：在 `metadata` 中存储 — 但 metadata 是扁平 dict，不适合存列表结构。

### Decision 2: 新增 `_collect_shape_links` 方法（而非修改 `_paragraphs`）

选择新增独立方法而非修改 `_paragraphs`：

```python
def _collect_shape_links(self, record, slide_index, state, doc) -> list[dict]:
    """收集形状中所有超链接的 {text, url, link_type} 信息。"""
    links = []
    # 形状级超链接（click_action.hyperlink）
    try:
        addr = record.shape.click_action.hyperlink.address
        if addr:
            links.append({
                "text": self._shape_text(record.shape),
                "url": addr,
                "link_type": classify_link(addr),
            })
    except Exception:
        pass
    # 运行级超链接（run.hyperlink）
    if self._shape_has_text(record.shape):
        for para in record.shape.text_frame.paragraphs:
            for run in para.runs:
                try:
                    addr = run.hyperlink.address
                except Exception:
                    addr = None
                if addr:
                    links.append({
                        "text": self._normalize_text(run.text),
                        "url": addr,
                        "link_type": classify_link(addr),
                    })
    return links
```

- **理由**：
  - 单一职责：`_paragraphs` 只做文本提取，`_collect_shape_links` 只做链接收集
  - 不破坏现有 `_paragraphs` 的调用方（`_is_list_shape` 依赖其返回结构）
  - 已有先例：`_asset_ids_for_shape_hyperlinks` 也是独立方法做超链接收集
- **备选方案**：修改 `_paragraphs` 返回值结构 → 需要改 `_is_list_shape` 等依赖方，风险更大

### Decision 3: `classify_link` 分类规则

在 `parsers/utils.py` 中实现，按优先级分类：

1. URL 路径后缀匹配图片扩展名（`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, `.svg`, `.ico`, `.tiff`, `.tif`）→ `image`
2. URL 路径后缀匹配视频扩展名（`.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.mkv`, `.webm`）→ `video`
3. URL 域名匹配视频平台（`youtube.com`, `youtu.be`, `bilibili.com`, `vimeo.com`）→ `video`
4. URL 路径后缀匹配音频扩展名（`.mp3`, `.wav`, `.m4a`, `.aac`, `.ogg`, `.flac`）→ `audio`
5. URL 路径后缀匹配文档扩展名（`.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`, `.txt`, `.md`, `.csv`）→ `document`
6. 其他 → `url`

**理由**：必须保留 `audio` 类型，否则 `.mp3` 等音频 URL 会从 `AssetType.audio` 降级为 `AssetType.attachment`，破坏现有行为。

### Decision 4: `classify_link` → `AssetType` 映射

`_asset_type_for_url` 改为：

```python
def _asset_type_for_url(self, url: str) -> AssetType:
    kind = classify_link(url)
    return {
        "image": AssetType.image,
        "video": AssetType.video,
        "audio": AssetType.audio,
    }.get(kind, AssetType.attachment)
```

### Decision 5: `_guess_mime` → `parsers.utils.guess_mime`

- **理由**：`xlsx_parser` 已使用公共 `guess_mime`（`from parsers.utils import guess_mime`）。PPTX 内部 `_guess_mime` 的 MIME 映射表与 `MIME_MAP` 重复 90%。
- **影响**：行为不变 — 两者的映射表一致（都按后缀匹配，回退到 asset_type 通配 MIME）。

### Decision 6: 删除内部重复代码

确认以下代码删除后无其他引用：
- `_is_video_url` — 仅 `_asset_type_for_url` 引用 → 可安全删除
- `_is_audio_url` — 仅 `_asset_type_for_url` 引用 → 可安全删除
- `_guess_mime` — 被 `_add_image` 和 `_asset_for_url` 引用，替换为 `guess_mime` 后 → 可安全删除
- `VIDEO_URL_RE` — 仅 `_is_video_url` 引用 → 可安全删除
- `AUDIO_URL_RE` — 仅 `_is_audio_url` 引用 → 可安全删除
- `HTTP_URL_RE` — 仍被 `_asset_ids_for_text` 使用 → **必须保留**

## Risks / Trade-offs

- **Risk**：`classify_link` 分类依赖 URL 后缀，对于无后缀的资源 URL（如 CDN 链接）会归类为 `url` → **Mitigation**：`url` 类型也会创建 `AssetType.attachment` 的 Asset，不影响入库流程；后续可在 `classify_link` 中扩展域名规则
- **Risk**：`structured_data.links` 增加了解析输出的体积 → **Mitigation**：链接数量通常很少（每页几个），影响可忽略
- **Risk**：`_guess_mime` 替换为 `guess_mime` 后 MIME 推断行为变化 → **Mitigation**：两者的后缀→MIME 映射表一致，且 `xlsx_parser` 已使用公共版本验证了兼容性

## Migration Plan

1. 在 `parsers/utils.py` 中添加 `classify_link` 函数，更新 `__all__`
2. 修改 `PptxParser`：
   - 新增 `_collect_shape_links` 方法
   - 导入 `classify_link` 和 `guess_mime`
   - `_add_text_shape`（普通段落 + 列表两个分支）调用 `_collect_shape_links` 写入 `structured_data.links`
   - `_add_image` 调用 `_collect_shape_links` 写入 `structured_data.links`
   - `_asset_type_for_url` 改为调用 `classify_link`
   - `_guess_mime` 调用替换为 `guess_mime`
   - 删除 `_is_video_url`、`_is_audio_url`、`_guess_mime`、`VIDEO_URL_RE`、`AUDIO_URL_RE`
3. 更新测试用例
4. 运行全量测试验证：`pytest tests/test_pptx_parser.py tests/test_parser_utils.py -v`

**回滚**：改动集中在 `pptx_parser.py` 和 `utils.py`，不影响 API 契约。回滚只需 `git revert` 即可。
