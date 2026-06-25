## Context

知识库系统的 Asset 数据模型当前承担 5 种资源类型的管理，但存在以下问题：
- 嵌入资源（image/video）的 `original_uri` 使用 `docx://` 伪协议，与真实 HTTP 链接混在同一字段
- 链接资源分类依赖 URL（`_classify_link_url`），无法处理"链接文字是图片名但 URL 是短链接/重定向"的场景
- 占位符格式各解析器不统一（`[图片: xxx][image1]` vs `[image1]` vs 空占位符）
- 普通网页链接无 Asset 类型，散落在 `metadata["link_urls"]` 中

## Goals / Non-Goals

**Goals:**
- 统一 Asset 字段语义：`original_uri` 存外部链接，嵌入类型为空
- 新增 `web_link` 类型管理普通网页链接
- 新增 `display_text` 字段存储链接文字
- 链接分类改为按链接文字后缀（`.png` → `image_link`）
- 占位符统一为 `{{type:n}}` 格式
- 链接文字在段落中被占位符完全替换

**Non-Goals:**
- 不改变 `_data` 的运行时私有属性机制
- 不改变 MinIO 存储和 Embedding 流程
- 不改变前端 API 响应结构（字段语义兼容）
- 不处理已有旧数据的迁移（新入库文档自动适配）

## Decisions

### 1. `classify_link_text()` 替代 `_classify_link_url()`

**选择**: 通过链接文字的后缀名判断资源类型

```python
_LINK_TEXT_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif"}
_LINK_TEXT_VIDEO_EXT = {".mov", ".mp4", ".webm", ".m4v"}
_LINK_TEXT_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".7z", ".csv", ".txt", ".md"}

def classify_link_text(text: str) -> AssetType:
    suffix = PurePosixPath(text.split("?", 1)[0]).suffix.lower()
    if suffix in _LINK_TEXT_IMAGE_EXT: return AssetType.image_link
    if suffix in _LINK_TEXT_VIDEO_EXT: return AssetType.video_link
    if suffix in _LINK_TEXT_DOC_EXT: return AssetType.document_link
    return AssetType.web_link
```

**理由**: 链接文字是用户可见的描述，比 URL 更能反映用户意图。Word 中 `天空.png` 超链接到 `https://xxx.com/abc`，用户意图是图片链接。

**备选方案**: 继续按 URL 后缀分类 — 拒绝，因为 URL 可能无后缀或为短链接。

### 2. 占位符格式 `{{type:n}}`

**选择**: 双花括号 `{{image:1}}` `{{video:2}}` `{{doc:3}}` `{{web:4}}`

**理由**: 
- 与 Markdown 原生语法 `[text](url)` 明显区分，避免 LLM 误解析
- 花括号在中文文本中极少出现，便于正则匹配
- `{{image:1}}` 比 `[image1]` 语义更清晰（类型 + 编号分离）

### 3. 链接文字被占位符完全替换

**选择**: 段落中 `天空.png` → `{{image:1}}`，不保留原文

**理由**: 原文信息已在 `display_text` 中存储，段落文本重复存储无意义。前端渲染时通过 `asset_data` 映射恢复展示。

### 4. 嵌入类型 `original_uri = ""`

**选择**: 嵌入图片/视频的 `original_uri` 为空字符串，`storage_uri` 存储 MinIO key

**理由**: 嵌入资源没有外部来源，空字符串语义正确。`_data` 在运行时注入，不入库。

### 5. 保留 `_classify_link_url` 供字段指令使用

**选择**: `docx_parser._parse_field_instruction` 提取的 URL 仍通过文件名后缀分类

**理由**: 字段指令（WeDrive 等）的 `\tdfn` 字段本身就是文件名，直接用文件名后缀判断即可。

## Risks / Trade-offs

- **[风险] 链接文字无后缀时误分类**: 链接文字 `百度` 指向 `https://baidu.com`，归类为 `web_link` — 正确行为
- **[风险] 旧数据不兼容**: PG 中旧 Asset 记录的 `original_uri` 为 `docx://...` 伪协议 — 影响：仅查询展示，新逻辑不受影响；前端展示 URL 时需兼容旧格式
- **[风险] 占位符格式变更影响前端**: 前端如果硬编码了 `[image1]` 匹配逻辑 — 需要同步更新
- **[风险] `_extract_videos` 删除后遗漏**: docx 中非超链接的裸视频 URL 作为普通正文处理，不创建 Asset。原则：只有可点击的超链接才创建资源。已与用户确认

## Migration Plan

1. 清空开发环境数据库后部署，避免旧数据兼容问题
2. 前端占位符匹配逻辑同步更新为 `{{type:n}}` 格式
3. 回滚策略：git revert 所有改动，重启服务即可
