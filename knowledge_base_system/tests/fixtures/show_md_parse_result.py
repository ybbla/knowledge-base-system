"""运行 Markdown 解析器，输出等效测试的解析结果概览。"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.models import Document
from parsers.markdown_parser import MarkdownParser

MD_CONTENT = """\
# 知识库系统设计文档

## 架构概述

本文档描述了知识库系统的整体架构设计，包括解析层、索引层和检索层。

- 解析器支持多种格式
- 索引使用 Milvus + BM25 双路
- 检索采用 RRF 融合 + LLM Rerank

| 模块 | 技术栈 | 说明 |
|---|---|---|
| 解析层 | python-docx/PyMuPDF | 多格式文档解析 |
| 索引层 | Milvus 2.5 | 向量 + BM25 双路 |
| 合并示例 | | 跨两列合并 |

系统架构图（内嵌）：![架构图](https://example.com/architecture.png)

演示视频：[系统演示](https://www.youtube.com/watch?v=dQw4w9WgXcQ)

详细设计文档：[design-spec.pdf](https://example.com/design-spec.pdf)

也可通过链接观看：https://www.bilibili.com/video/BV1xx411c7mD/

普通网页参考：[官方文档](https://example.com/docs)

以下为嵌入对象：[不支持的对象](unknown://obj)
"""

parser = MarkdownParser()
doc = Document(
    title="MD Coverage Test",
    source_type="markdown",
    source_uri="memory://md-coverage",
    metadata={"raw_content": MD_CONTENT},
)
result = parser.parse(doc, MD_CONTENT)

print("=" * 72)
print("  ElementType 统计")
print("=" * 72)
from collections import Counter
type_counts = Counter(e.element_type.value for e in result.elements)
for et in ["title", "paragraph", "list", "table", "code", "unknown"]:
    count = type_counts.get(et, 0)
    status = "OK" if count > 0 else "MISSING"
    print(f"  {et:15s} : {count:3d}  {status}")

print()
print("=" * 72)
print("  AssetType 统计")
print("=" * 72)
at_counts = Counter(a.asset_type.value for a in result.assets)
for at in ["image", "image_link", "video_link", "document_link"]:
    count = at_counts.get(at, 0)
    status = "OK" if count > 0 else "MISSING"
    print(f"  {at:16s} : {count:3d}  {status}")

print()
print("=" * 72)
print("  逐元素详情")
print("=" * 72)
for i, el in enumerate(result.elements):
    text_preview = (el.text or "")[:100].replace("\n", "\\n")
    type_tag = el.element_type.value

    ad_summary = ""
    if el.asset_data:
        types = [f"{ad.type}" for ad in el.asset_data]
        ad_summary = f" | assets: {types}"

    meta_summary = ""
    if el.metadata:
        keys = list(el.metadata.keys())
        meta_summary = f" | meta: {keys}"

    sd_summary = ""
    if el.structured_data:
        sd_keys = list(el.structured_data.keys())
        sd_summary = f" | structured: {sd_keys}"

    heading_info = ""
    if el.element_type.value == "title":
        heading_info = f" L{el.metadata.get('heading_level', '?')}"

    parent_info = ""
    if el.parent_element_id:
        parent_info = f" parent={el.parent_element_id}"

    print(
        f"  [{i:02d}] {type_tag:12s}{heading_info} "
        f"\"{text_preview}\"{ad_summary}{meta_summary}{sd_summary}{parent_info}"
    )

print()
print("=" * 72)
print("  Asset 详情")
print("=" * 72)
for i, a in enumerate(result.assets):
    source_info = ""
    if a.element_id:
        source_info = f" -> element: {a.element_id}"
    print(
        f"  [{i:02d}] {a.asset_type.value:16s} "
        f"mime={a.mime_type or '?':24s} "
        f"uri={a.original_uri}{source_info}"
    )

print()
print("=" * 72)
print("  关键观察")
print("=" * 72)
print("  注意列表项如何处理、链接如何占位、裸URL如何处理")
print()
