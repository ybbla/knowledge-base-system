# -*- coding: utf-8 -*-
"""分析 sample_comprehensive.docx 的输入结构和解析输出对照。"""
import io, re, zipfile, sys
from parsers.docx_parser import DocxParser
from app.core.models import Document, ElementType, AssetType

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8")

parser = DocxParser()
with open("tests/fixtures/sample_comprehensive.docx", "rb") as f:
    content = f.read()
doc = Document(
    title="综合示例", source_type="docx", source_uri="memory://demo",
    metadata={"raw_content": content},
)
result = parser.parse(doc, content)

# ═══════════════════════════════════════════════════════════════════
# 1. 关系映射表
# ═══════════════════════════════════════════════════════════════════
zf = zipfile.ZipFile(io.BytesIO(content))
rels_raw = zf.read("word/_rels/document.xml.rels").decode("utf-8")
print("--- 输入: word/_rels/document.xml.rels (rId -> 资源映射) ---")
for line in rels_raw.split("\n"):
    rid = re.search(r'Id="(rId\d+)"', line)
    ttype = re.search(r'Type=".*/(\w+)"', line)
    target = re.search(r'Target="([^"]+)"', line)
    if rid and target:
        rtype = ttype.group(1) if ttype else "?"
        print(f"  {rid.group(1)}  ->  [{rtype:11s}]  {target.group(1)}")
print()

# ═══════════════════════════════════════════════════════════════════
# 2. 提取 body XML 中的关键结构
# ═══════════════════════════════════════════════════════════════════
doc_raw = zf.read("word/document.xml").decode("utf-8")
body_start = doc_raw.find("<w:body")
body_end = doc_raw.find("</w:body>") + len("</w:body>")
body_xml = doc_raw[body_start:body_end]

# 分割每个 w:p 和 w:tbl
pattern = re.compile(
    r'(<w:p(?:\s[^>]*)?>.*?</w:p>)|(<w:tbl(?:\s[^>]*)?>.*?</w:tbl>)',
    re.DOTALL,
)
sections = [m.group(0) for m in pattern.finditer(body_xml)]

print("=" * 70)
print("  逐元素对照: 输入 (document.xml)  ->  输出 (ParseResult)")
print("=" * 70)

for i, section in enumerate(sections):
    style_match = re.search(r'w:val="([^"]+)"', section)
    style = style_match.group(1) if style_match else ""
    has_hyperlink = "w:hyperlink" in section
    has_drawing = "r:embed=" in section
    hyperlink_rids = re.findall(r'r:id="(rId\d+)"', section)
    drawing_rids = re.findall(r'r:embed="(rId\d+)"', section)
    is_table = section.startswith("<w:tbl")
    texts = re.findall(r"<w:t[^>]*>([^<]+)</w:t>", section)
    xml_text = "".join(texts)

    print(f"\n--- 元素 {i+1} ----------------------------------------------")
    print(f"  [输入] 类型: {'w:tbl (表格)' if is_table else 'w:p (段落)'}")
    if style:
        print(f"  [输入] 样式: w:pStyle w:val=\"{style}\"")
    if has_drawing:
        print(f"  [输入] 图片: r:embed=\"{', '.join(drawing_rids)}\"")
    if has_hyperlink:
        print(f"  [输入] 链接: r:id=\"{', '.join(hyperlink_rids)}\"")
    print(f"  [输入] 文本: {xml_text[:80]!r}")

    if i < len(result.elements):
        el = result.elements[i]
        etype = el.element_type.value
        meta_parts = []
        if el.metadata.get("heading_level"):
            meta_parts.append(f"H{el.metadata['heading_level']}")
        if el.asset_ids:
            meta_parts.append(f"assets:{len(el.asset_ids)}")
        if el.metadata.get("link_urls"):
            meta_parts.append(f"links:{len(el.metadata['link_urls'])}")
        meta_str = " [" + ", ".join(meta_parts) + "]" if meta_parts else ""

        print(f"  [输出] 类型: {etype}{meta_str}")
        print(f"  [输出] text: {el.text[:80]!r}")
        if el.asset_ids:
            print(f"  [输出] asset_ids: {el.asset_ids}")
        if el.metadata.get("link_urls"):
            print(f"  [输出] link_urls: {el.metadata['link_urls']}")

        if el.element_type == ElementType.table:
            sd = el.structured_data["table"]
            print(f"  [输出] 表格结构化:")
            print(f"         表头: {[(h['text'][:15], h['asset_ids']) for h in sd['headers']]}")
            for ri, row in enumerate(sd["rows"]):
                print(f"         行{ri}: {[(c['text'][:15], c['asset_ids']) for c in row['cells']]}")
            print(f"         表格级 asset_ids: {el.asset_ids}")

# ═══════════════════════════════════════════════════════════════════
# 3. 资源汇总
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'=' * 70}")
print("  资源汇总 (state.assets)")
print(f"{'=' * 70}")
for a in result.assets:
    print(f"  [{a.asset_type.value:11s}] uri={a.original_uri[:55]!r}  -> el={a.source_element_id[:25]}")

# ═══════════════════════════════════════════════════════════════════
# 4. 回填验证
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'=' * 70}")
print("  source_element_id 回填验证")
print(f"{'=' * 70}")
el_ids = {el.element_id for el in result.elements}
for a in result.assets:
    ok = "OK" if a.source_element_id in el_ids else "MISSING!"
    print(f"  [{ok}]  {a.asset_id[:25]}  ->  {a.source_element_id[:25]}")
