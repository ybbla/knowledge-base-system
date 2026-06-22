## Why

MarkdownParser 存在三个功能缺陷：`blockquote` 引用块语义完全丢失（`blockquote_open/close` 均为 pass）、Markdown 链接 `[text](url)` 的 URL 被丢弃（仅保留链接文本）、表格单元格内的图片和链接资源未关联到 `asset_ids`。本次变更修复这三个问题，并将剩余的重复代码迁移到公共基础设施。

## What Changes

- **blockquote 语义保留**：引用块内段落标记 `metadata.blockquote=true`
- **段落内链接 URL 提取**：`[text](url)` 中的 URL 按类型识别——视频/图片/附件创建 Asset 并关联到 `asset_ids`，普通网页写入 `metadata.link_urls`
- **表格单元格资源关联**：表格单元格内的图片和链接 Asset 写入 `cells[].asset_ids`，汇总到表格级 `asset_ids`
- **迁移到公共基础设施**：使用 `utils.VIDEO_URL_RE`、`utils.guess_mime()`、`_ParseState` 继承 `_BaseParseState`
- **删除重复代码**：本地 `VIDEO_URL_RE`、`_guess_mime()`、`_ParseState` 重复字段

## Capabilities

### New Capabilities
- `markdown-parsing`: Markdown 文档解析能力规范，定义 blockquote 语义保留、链接 URL 提取、表格单元格资源关联、公共基础设施迁移后的行为契约

## Impact

- **修改文件**：`parsers/markdown_parser.py`
- **测试**：更新 `tests/test_markdown_ingest.py`，补充 blockquote、链接 URL、表格资源关联的测试用例
- **API 兼容**：`ParseResult` 输出结构不变，blockquote 通过 metadata 标记（不修改 ElementType 枚举）
