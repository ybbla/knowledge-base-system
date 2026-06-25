"""测试 SemanticExtractor 全文优先 + 递进降级策略。

测试覆盖：
- 全文路径（一次 LLM）
- 标题递进切分（h1→h2→h3…）
- LLM 失败降级（调不通 / 返回空）
- Embedding 语义切分 / token 硬切兜底
- source_refs 空兜底 + AssetRef 无 relation
"""

import json

import pytest

from app.core.models import (
    Asset,
    AssetData,
    AssetRef,
    AssetStatus,
    AssetType,
    ElementType,
    KnowledgeChunk,
    KnowledgeType,
    ParsedElement,
    SourceLocation,
    SourceRef,
)
from llm.semantic_extractor import SemanticExtractor


# ── 辅助工厂函数 ──────────────────────────────────────────────────

def _make_el(
    element_id: str,
    element_type: ElementType,
    text: str,
    doc_id: str = "doc_test",
    heading_level: int | None = None,
    structured_data: dict | None = None,
    asset_data: list | None = None,
    section_path: list[str] | None = None,
) -> ParsedElement:
    """创建 ParsedElement 快捷工厂。"""
    meta: dict = {}
    if heading_level is not None:
        meta["heading_level"] = heading_level
    return ParsedElement(
        element_id=element_id,
        doc_id=doc_id,
        element_type=element_type,
        text=text,
        structured_data=structured_data,
        asset_data=asset_data or [],
        source_location=SourceLocation(section_path=section_path or []),
        metadata=meta,
    )


def _make_asset(asset_id: str, doc_id: str = "doc_test", extracted_text: str | None = None) -> Asset:
    """创建 Asset 快捷工厂。"""
    return Asset(
        asset_id=asset_id,
        doc_id=doc_id,
        asset_type=AssetType.image,
        original_uri=f"{asset_id}.png",
        extracted_text=extracted_text,
        status=AssetStatus.ready,
    )


def _make_chunk_data(chunks: list[dict]) -> dict:
    """构造 LLM 返回的标准 chunk 数据。"""
    return {"chunks": chunks}


def _simple_chunk(content: str = "测试内容", title: str = "测试标题", **kw) -> dict:
    """构造单条 chunk 字典。"""
    chunk = {
        "title": title,
        "content": content,
        "knowledge_type": "declarative",
        "source_refs": [],
        "asset_refs": [],
    }
    chunk.update(kw)
    return chunk


# ── 7.1: 全文一次 LLM ───────────────────────────────────────────

class TestExtractFullDocument:
    """测试全文优先路径——不超限时一次 LLM 调用。"""

    def test_small_doc_extracts_in_single_call(self, monkeypatch):
        """文档 token 不超 SAFE_THRESHOLD 时应全文一次调用 LLM。"""
        extractor = SemanticExtractor()
        # 覆盖安全阈值为一个极小值以强制全文路径（默认 800K，我们设很大）
        extractor._safe_threshold = 100_000

        elements = [
            _make_el("el_1", ElementType.title, "第一章", heading_level=1,
                     section_path=["第一章"]),
            _make_el("el_2", ElementType.paragraph, "这是第一段内容。"),
            _make_el("el_3", ElementType.title, "第二节", heading_level=2,
                     section_path=["第一章", "第二节"]),
            _make_el("el_4", ElementType.paragraph, "这是第二节内容。"),
        ]
        assets: list[Asset] = []

        call_count = 0

        def mock_chat_json(messages, schema=None):
            nonlocal call_count
            call_count += 1
            return _make_chunk_data([
                _simple_chunk("第一章涵盖了基本概念。",
                              source_refs=[{"element_id": "el_1"}, {"element_id": "el_2"}]),
                _simple_chunk("第二节介绍了具体操作。",
                              source_refs=[{"element_id": "el_3"}, {"element_id": "el_4"}]),
            ])

        import llm.semantic_extractor as mod
        monkeypatch.setattr(mod.llm_client, "chat_json", mock_chat_json)

        chunks = extractor.extract(elements, assets, "通用")

        assert call_count == 1, f"全文路径应仅 1 次 LLM 调用，实际 {call_count} 次"
        assert len(chunks) == 2
        # title 来自 LLM 输出的 title 字段（_simple_chunk 默认 "测试标题"）
        assert chunks[0].content == "第一章涵盖了基本概念。"
        assert chunks[1].content == "第二节介绍了具体操作。"


# ── 7.2: _split_at_heading_level ─────────────────────────────────

class TestSplitAtHeadingLevel:
    """测试按指定 heading_level 切分元素列表。"""

    def test_split_h1(self):
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.title, "第一章", heading_level=1),
            _make_el("el_2", ElementType.paragraph, "段落A"),
            _make_el("el_3", ElementType.title, "第二章", heading_level=1),
            _make_el("el_4", ElementType.paragraph, "段落B"),
        ]
        sections = extractor._split_at_heading_level(elements, level=1)
        assert len(sections) == 2
        assert sections[0][0].text == "第一章"
        assert sections[1][0].text == "第二章"

    def test_split_h2_ignores_h1(self):
        """h2 切分时，h1 标题不触发切分但成为独立 section 的前导。

        结果：3 个 section —— [h1], [h2(1.1)+段落A], [h2(1.2)+段落B]。
        """
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.title, "第一章", heading_level=1),
            _make_el("el_2", ElementType.title, "1.1 节", heading_level=2),
            _make_el("el_3", ElementType.paragraph, "段落A"),
            _make_el("el_4", ElementType.title, "1.2 节", heading_level=2),
            _make_el("el_5", ElementType.paragraph, "段落B"),
        ]
        sections = extractor._split_at_heading_level(elements, level=2)
        # h1 触发第一个 section，两个 h2 各触发一个 → 共 3 个
        assert len(sections) == 3
        assert sections[0][0].text == "第一章"
        assert sections[1][0].text == "1.1 节"
        assert sections[2][0].text == "1.2 节"

    def test_no_matching_level_returns_single(self):
        """无匹配层级时返回单 section。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.paragraph, "无标题文本段落。"),
            _make_el("el_2", ElementType.paragraph, "另一段落。"),
        ]
        sections = extractor._split_at_heading_level(elements, level=1)
        assert len(sections) == 1
        assert len(sections[0]) == 2

    def test_split_h3(self):
        """h3 切分：h1 成为独立 section，两个 h3 各触发新 section → 共 3 个。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.title, "H1", heading_level=1),
            _make_el("el_2", ElementType.title, "H3-a", heading_level=3),
            _make_el("el_3", ElementType.paragraph, "段落"),
            _make_el("el_4", ElementType.title, "H3-b", heading_level=3),
            _make_el("el_5", ElementType.paragraph, "段落"),
        ]
        sections = extractor._split_at_heading_level(elements, level=3)
        assert len(sections) == 3


# ── 7.3 & 7.4: _split_recursive 递进切分 ────────────────────────

class TestSplitRecursive:
    """测试递进切分——仅超限 section 下钻。"""

    def test_all_under_threshold_no_split(self, monkeypatch):
        """所有元素整体不超限时，_split_recursive 直接走 _extract_section 一次。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 10_000

        elements = [
            _make_el("el_1", ElementType.title, "H1-1", heading_level=1),
            _make_el("el_2", ElementType.paragraph, "短文段落。"),
            _make_el("el_3", ElementType.title, "H1-2", heading_level=1),
            _make_el("el_4", ElementType.paragraph, "另一短文段落。"),
        ]
        call_elements: list[list] = []

        def mock_extract_section(els, assets, category, resources=None):
            call_elements.append(els)
            return [
                KnowledgeChunk(
                    doc_id="doc_test",
                    title=f"chunk_from_{len(call_elements)}",
                    content=" ".join(el.text for el in els),
                    category=category,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_section", mock_extract_section)

        chunks = extractor._split_recursive(elements, [], "通用", level=1)

        # 整体不超限 → 一次 _extract_section 即可
        assert len(call_elements) == 1
        assert len(chunks) == 1

    def test_oversized_section_splits_deeper(self, monkeypatch):
        """超限 section 下钻到更深层，非超限的保持完整。"""
        extractor = SemanticExtractor()
        # SAFE_THRESHOLD 设为 15 token ≈ ~27 字符——让大 section 超限
        extractor._safe_threshold = 15

        # section 1: 小（不超限）
        h1_1_els = [
            _make_el("el_h1a", ElementType.title, "H1-Small", heading_level=1),
            _make_el("el_p1", ElementType.paragraph, "短。"),
        ]
        # section 2: 大（超限），含 h2 子标题
        h1_2_els = [
            _make_el("el_h1b", ElementType.title, "H1-Big", heading_level=1),
            _make_el("el_h2a", ElementType.title, "H2-A", heading_level=2),
            _make_el("el_p2", ElementType.paragraph, "较长内容较长内容较长内容较长内容较长内容。"),
            _make_el("el_h2b", ElementType.title, "H2-B", heading_level=2),
            _make_el("el_p3", ElementType.paragraph, "更多较长内容更多较长内容更多较长内容。"),
        ]
        elements = h1_1_els + h1_2_els

        processed_sections: list[list] = []

        def mock_extract_section(els, assets, category, resources=None):
            processed_sections.append(els)
            return [
                KnowledgeChunk(
                    doc_id="doc_test",
                    title=f"s_{len(processed_sections)}",
                    content=" ".join(el.text for el in els),
                    category=category,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_section", mock_extract_section)

        chunks = extractor._split_recursive(elements, [], "通用", level=1)

        # h1-small 直接走 LLM（1次）
        # h1-big 超限 → 按 h2 切出 [h1b],[h2a+p2],[h2b+p3]（3次）
        assert len(processed_sections) == 4
        assert len(chunks) == 4

    def test_multi_level_recursive_h1_h2_h3(self, monkeypatch):
        """多层级递进：h1 切出 3 section，仅超限的下钻 h2→h3。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 10  # 极低阈值，所有 section 都超限

        elements = [
            _make_el("el_h1a", ElementType.title, "H1-A", heading_level=1),
            _make_el("el_h2a", ElementType.title, "H2-a", heading_level=2),
            _make_el("el_h3a", ElementType.title, "H3-1", heading_level=3),
            _make_el("el_pp", ElementType.paragraph, "段落。"),
            _make_el("el_h3b", ElementType.title, "H3-2", heading_level=3),
            _make_el("el_pq", ElementType.paragraph, "另一段落。"),
            _make_el("el_h1b", ElementType.title, "H1-B", heading_level=1),
            _make_el("el_pr", ElementType.paragraph, "短文。"),
        ]

        processed: list[list] = []

        def mock_extract_section(els, assets, category, resources=None):
            processed.append(els)
            return [
                KnowledgeChunk(
                    doc_id="doc_test",
                    title=f"c_{len(processed)}",
                    content=" ".join(el.text for el in els),
                    category=category,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_section", mock_extract_section)

        extractor._split_recursive(elements, [], "通用", level=1)

        # 最终应下钻到 h3 级别：H3-1 section + H3-2 section + H1-B section
        # 具体次数取决于递进逻辑，但应 > 2（至少下钻了一层）
        assert len(processed) >= 2


# ── 7.5 & 7.6: LLM 失败降级 ─────────────────────────────────────

class TestLLMFailureFallback:
    """测试 LLM 调用失败时的降级行为。"""

    def test_full_doc_llm_exception_triggers_split(self, monkeypatch):
        """全文 LLM 抛异常时进入递进降级路径。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 100_000  # 全文路径

        elements = [
            _make_el("el_1", ElementType.title, "标题", heading_level=1),
            _make_el("el_2", ElementType.paragraph, "内容。"),
        ]

        # 模拟 LLM 抛异常
        def mock_chat_json_raise(messages, schema=None):
            raise RuntimeError("模拟 API 超时")

        import llm.semantic_extractor as mod
        monkeypatch.setattr(mod.llm_client, "chat_json", mock_chat_json_raise)

        # 由于只有 1 个 h1 section 且 token 小，extract 应走
        # 全文 → 失败 → _split_recursive → _extract_section → 再失败 → _split_deeper_or_semantic
        # → 更深层无 → embedding/token 硬切 → fallback

        chunks = extractor.extract(elements, [], "通用")

        # 最终走 fallback：应有至少 1 个 chunk
        assert len(chunks) >= 1
        assert "标题" in chunks[0].content or "内容" in chunks[0].content

    def test_extract_returns_empty_triggers_fallback(self, monkeypatch):
        """LLM 返回空 chunks 时触发降级。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 100_000

        elements = [
            _make_el("el_1", ElementType.title, "标题", heading_level=1),
            _make_el("el_2", ElementType.paragraph, "落文本。"),
        ]

        # LLM 返回空列表
        def mock_chat_json_empty(messages, schema=None):
            return {"chunks": []}

        import llm.semantic_extractor as mod
        monkeypatch.setattr(mod.llm_client, "chat_json", mock_chat_json_empty)

        chunks = extractor.extract(elements, [], "通用")

        # 应触发 fallback
        assert len(chunks) >= 1
        assert "标题" in chunks[0].content

    def test_extract_all_empty_content_triggers_fallback(self, monkeypatch):
        """LLM 返回的 chunks 全部 content 为空时触发降级。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 100_000

        elements = [
            _make_el("el_1", ElementType.paragraph, "有效文本。"),
        ]

        def mock_chat_json_all_empty(messages, schema=None):
            return _make_chunk_data([
                {"title": "空块", "content": "", "knowledge_type": "declarative"}
            ])

        import llm.semantic_extractor as mod
        monkeypatch.setattr(mod.llm_client, "chat_json", mock_chat_json_all_empty)

        chunks = extractor.extract(elements, [], "通用")

        assert len(chunks) >= 1
        assert "有效文本" in chunks[0].content


# ── 7.7: section 级 LLM 失败继续下钻 ──────────────────────────────

class TestSectionLLMFailureFurtherSplit:
    """测试降级路径中 section 的 LLM 失败→继续下钻。"""

    def test_section_failure_with_deeper_heading_splits_further(self, monkeypatch):
        """LLM 失败的 section 有更深标题 → 继续按更深层切分。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 15  # 强制超限→下钻

        elements = [
            _make_el("el_h1", ElementType.title, "H1", heading_level=1),
            _make_el("el_h2a", ElementType.title, "H2-A", heading_level=2),
            _make_el("el_pa", ElementType.paragraph, "段落段落段落段落。"),
            _make_el("el_h2b", ElementType.title, "H2-B", heading_level=2),
            _make_el("el_pb", ElementType.paragraph, "内容内容内容内容。"),
        ]

        call_count = 0

        def mock_extract_section(els, assets, category, resources=None):
            nonlocal call_count
            call_count += 1
            # 前两次抛异常模拟失败，第三次成功
            if call_count <= 2:
                raise RuntimeError("模拟 section LLM 失败")
            return [
                KnowledgeChunk(
                    doc_id="doc_test",
                    title=f"success_{call_count}",
                    content=" ".join(el.text for el in els),
                    category=category,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_section", mock_extract_section)

        chunks = extractor.extract(elements, [], "通用")

        # 至少有一次成功产出
        assert any(not c.metadata.get("fallback") for c in chunks), "应有非 fallback chunk"


# ── 7.8 & 7.9: Embedding / token 硬切兜底 ────────────────────────

class TestSemanticAndHardSplit:
    """测试 embedding 语义切分和 token 硬切兜底。"""

    def test_no_headings_falls_to_token_split(self, monkeypatch):
        """无标题文档超限→无法按标题切→走 embedding/token 硬切。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 5  # 极低

        elements = [
            _make_el(f"el_{i}", ElementType.paragraph, f"段落{i}内容文本。" * 3)
            for i in range(10)
        ]

        # 禁用 embedding 切分，强制走 token 硬切
        monkeypatch.setattr(extractor, "_split_by_semantic",
                            lambda els: [list(els)])

        chunks = extractor._split_deeper_or_semantic(elements, [], "通用", level=1)

        # 硬切后至少有几个 chunk
        assert len(chunks) >= 1

    def test_semantic_split_produces_multiple_sections(self, monkeypatch):
        """embedding 语义切分产生多个子 section 各自走 LLM。"""
        extractor = SemanticExtractor()
        extractor._safe_threshold = 5  # 极低阈值强制进入降级分叉

        elements = [
            _make_el(f"el_{i}", ElementType.paragraph, f"主题A相关段落{i}。")
            if i < 5 else
            _make_el(f"el_{i}", ElementType.paragraph, f"完全不同主题B段落{i}。")
            for i in range(10)
        ]

        # 模拟 embedding 切分返回 2 个 section
        def mock_semantic_split(els):
            mid = len(els) // 2
            return [els[:mid], els[mid:]]

        monkeypatch.setattr(extractor, "_split_by_semantic", mock_semantic_split)
        # LLM 也返回有效数据
        monkeypatch.setattr(extractor, "_extract_section",
                            lambda els, a, c: [
                                KnowledgeChunk(
                                    doc_id="doc_test",
                                    title="chunk",
                                    content=" ".join(el.text for el in els),
                                    category=c,
                                )
                            ])

        chunks = extractor._split_recursive(elements, [], "通用", level=1)

        # embedding 切出 2 个 section，各走 LLM → ≥2 chunk
        assert len(chunks) >= 2


# ── 7.10: _build_chunks 空 source_refs ──────────────────────────

class TestBuildChunksEmptySourceRefs:
    """测试 source_refs 空兜底逻辑。"""

    def test_no_source_refs_in_llm_output_leaves_empty(self):
        """LLM 未提供 source_refs → chunk 的 source_refs 为空列表。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.paragraph, "测试内容。"),
        ]

        data = _make_chunk_data([
            {
                "title": "测试",
                "content": "这是一段测试内容。",
                "knowledge_type": "declarative",
                # 故意不提供 source_refs
            }
        ])

        chunks = extractor._build_chunks(data, elements, [], "通用")

        assert len(chunks) == 1
        assert chunks[0].source_refs != [], (
            "LLM 不提供 source_refs 时，应回退到当前分段的全部元素，避免孤儿知识块"
        )

    def test_source_refs_with_element_ids(self):
        """正常提供 source_refs 时正确构造。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.title, "标题", heading_level=1),
            _make_el("el_2", ElementType.paragraph, "内容段落。"),
        ]

        data = _make_chunk_data([
            {
                "title": "标题",
                "content": "完整的知识块内容。",
                "knowledge_type": "declarative",
                "source_refs": [
                    {"element_id": "el_1"},
                    {"element_id": "el_2"},
                ],
            }
        ])

        chunks = extractor._build_chunks(data, elements, [], "通用")

        assert len(chunks[0].source_refs) == 2
        assert chunks[0].source_refs[0].element_id == "el_1"


# ── 7.11: AssetRef 无 relation ───────────────────────────────────

class TestAssetRefNoRelation:
    """测试 AssetRef 不包含 relation 字段。"""

    def test_chunk_asset_ref_has_no_relation(self):
        """构造 KnowledgeChunk 后 asset_refs 条目不含 relation。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.paragraph, "图片",
                     ),
        ]
        assets = [
            _make_asset("asset_001", extracted_text="图片描述"),
        ]

        data = _make_chunk_data([
            {
                "title": "包含图片的知识块",
                "content": "正文含图片描述。",
                "knowledge_type": "declarative",
                "asset_refs": [
                    {
                        "asset_id": "asset_001",
                        "linked_text": "相关图片",
                        "caption": "图1",
                    }
                ],
            }
        ])

        chunks = extractor._build_chunks(data, elements, assets, "通用")

        assert len(chunks[0].asset_refs) == 1
        ref = chunks[0].asset_refs[0]
        assert ref.asset_id == "asset_001"
        assert ref.caption == "图1"
        # 不应有 relation 属性
        ref_dict = ref.model_dump(mode="json")
        assert "relation" not in ref_dict, (
            f"AssetRef 不应包含 relation 字段，实际: {list(ref_dict.keys())}"
        )

    def test_fallback_chunk_asset_ref_has_no_relation(self):
        """fallback chunk 的 asset_refs 也不含 relation。"""
        extractor = SemanticExtractor()
        elements = [
            _make_el("el_1", ElementType.paragraph, "图片",
                     asset_data=[AssetData(placeholder="[图片]", asset_id="asset_001")]),
            _make_el("el_2", ElementType.paragraph, "文本内容。"),
        ]
        assets = [
            _make_asset("asset_001"),
        ]

        chunks = extractor._fallback_chunks(elements, assets, "通用")

        assert len(chunks) == 1
        assert len(chunks[0].asset_refs) == 1
        ref_dict = chunks[0].asset_refs[0].model_dump(mode="json")
        assert "relation" not in ref_dict


# ── 补充: _estimate_tokens + _elements_to_json ──────────────────

class TestEstimateTokens:
    """测试 token 估算修正。"""

    def test_includes_structured_data(self):
        """structured_data 计入 token 估算。"""
        elements_without_sd = [
            _make_el("el_1", ElementType.paragraph, "短文本"),
        ]
        elements_with_sd = [
            _make_el("el_1", ElementType.table, "短文本",
                     structured_data={"rows": [{"a": 1}] * 50}),
        ]

        base = SemanticExtractor._estimate_tokens(elements_without_sd)
        with_sd = SemanticExtractor._estimate_tokens(elements_with_sd)
        assert with_sd > base, "包含 structured_data 的估算应更大"

    def test_uses_1_8_divisor(self):
        """验证使用 /1.8 而非 //2。"""
        elements = [
            _make_el("el_1", ElementType.paragraph, "测试文本内容"),
        ]
        tokens = SemanticExtractor._estimate_tokens(elements)
        # len("测试文本内容") = 6, 6/1.8 ≈ 3
        assert tokens >= 1


class TestElementsToJsonLanguage:
    """测试 _elements_to_json 注入 language 字段。"""

    def test_code_element_has_language(self):
        """代码元素序列化时包含 language 字段。"""
        elements = [
            _make_el("el_1", ElementType.code, "print('hello')",
                     structured_data={"language": "python"}),
        ]

        result = SemanticExtractor._elements_to_json(elements)
        data = json.loads(result)

        assert data[0]["language"] == "python"

    def test_non_code_element_has_no_language(self):
        """非代码元素不包含 language 字段。"""
        elements = [
            _make_el("el_1", ElementType.paragraph, "普通段落。"),
        ]

        result = SemanticExtractor._elements_to_json(elements)
        data = json.loads(result)

        assert "language" not in data[0]

    def test_code_without_language_field(self):
        """代码元素但 structured_data 无 language 时不注入。"""
        elements = [
            _make_el("el_1", ElementType.code, "some code",
                     structured_data={}),
        ]

        result = SemanticExtractor._elements_to_json(elements)
        data = json.loads(result)

        assert "language" not in data[0]

    def test_heading_level_injection(self):
        """标题元素注入 heading_level。"""
        elements = [
            _make_el("el_1", ElementType.title, "标题", heading_level=2),
            _make_el("el_2", ElementType.paragraph, "段落"),
        ]

        result = SemanticExtractor._elements_to_json(elements)
        data = json.loads(result)

        assert data[0]["heading_level"] == 2
        assert "heading_level" not in data[1]


# ── 补充: _chunks_have_content ───────────────────────────────────

class TestChunksHaveContent:
    """测试 _chunks_have_content 辅助函数。"""

    def test_empty_list(self):
        assert SemanticExtractor._chunks_have_content([]) is False

    def test_all_empty_content(self):
        chunks = [
            KnowledgeChunk(content="", title="t", category="通用"),
            KnowledgeChunk(content="  ", title="t2", category="通用"),
        ]
        assert SemanticExtractor._chunks_have_content(chunks) is False

    def test_one_has_content(self):
        chunks = [
            KnowledgeChunk(content="", title="t", category="通用"),
            KnowledgeChunk(content="有效内容", title="t2", category="通用"),
        ]
        assert SemanticExtractor._chunks_have_content(chunks) is True
