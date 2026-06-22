import logging

import pytest

from app.core.models import Document
from parsers.base import DocumentParser, ParseResult, _BaseParseState
from parsers.docx_parser import DocxParser
from parsers.markdown_parser import MarkdownParser
from parsers.pptx_parser import PptxParser
from parsers.registry import ParserRegistry, UnsupportedFormatError
from parsers.xlsx_parser import XlsxParser


class _FakeParserA(DocumentParser):
    SUPPORTED_TYPES = {"alpha", "beta"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc, content):
        return ParseResult(doc=doc)


class _FakeParserB(DocumentParser):
    SUPPORTED_TYPES = {"gamma"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc, content):
        return ParseResult(doc=doc)


class TestParserRegistry:
    def test_register_and_get(self):
        registry = ParserRegistry()
        registry.register(_FakeParserA(), _FakeParserB())
        assert isinstance(registry.get("alpha"), _FakeParserA)
        assert isinstance(registry.get("beta"), _FakeParserA)
        assert isinstance(registry.get("gamma"), _FakeParserB)

    def test_case_insensitive(self):
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        assert isinstance(registry.get("ALPHA"), _FakeParserA)
        assert isinstance(registry.get("AlPhA"), _FakeParserA)

    def test_unsupported_type_raises_with_list(self):
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        with pytest.raises(UnsupportedFormatError) as exc_info:
            registry.get("unknown")
        assert "unknown" in str(exc_info.value)
        assert "alpha" in str(exc_info.value)
        assert "beta" in str(exc_info.value)

    def test_duplicate_registration_warns(self, caplog):
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        with caplog.at_level(logging.WARNING):
            registry.register(_FakeParserB())  # gamma is new, no warning
        # Register another parser with same type to trigger warning
        class _FakeParserC(DocumentParser):
            SUPPORTED_TYPES = {"beta"}
            def supports(self, s): return s in self.SUPPORTED_TYPES
            def parse(self, doc, content): return ParseResult(doc=doc)

        with caplog.at_level(logging.WARNING):
            registry.register(_FakeParserC())
        assert any("覆盖" in record.message for record in caplog.records)
        assert isinstance(registry.get("beta"), _FakeParserC)

    def test_supported_types_property(self):
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        assert "alpha" in registry.supported_types
        assert "beta" in registry.supported_types

    def test_register_real_document_parsers(self):
        registry = ParserRegistry()
        registry.register(MarkdownParser(), DocxParser(), XlsxParser(), PptxParser())

        assert isinstance(registry.get("markdown"), MarkdownParser)
        assert isinstance(registry.get("docx"), DocxParser)
        assert isinstance(registry.get("xlsx"), XlsxParser)
        assert isinstance(registry.get("XLSX"), XlsxParser)
        assert isinstance(registry.get("pptx"), PptxParser)
        assert isinstance(registry.get("PPTX"), PptxParser)

    # ── 新增：注销测试 ────────────────────────────────────────

    def test_unregister_removes_type(self):
        """注销后 get 抛出 UnsupportedFormatError。"""
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        registry.unregister("alpha")
        with pytest.raises(UnsupportedFormatError):
            registry.get("alpha")
        # 同解析器的其他类型仍可用
        assert isinstance(registry.get("beta"), _FakeParserA)

    def test_unregister_nonexistent_is_idempotent(self):
        """注销未注册的类型不报错。"""
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        registry.unregister("unknown")  # 不抛异常

    # ── 新增：优先级测试 ──────────────────────────────────────

    def test_higher_priority_overrides(self, caplog):
        """高优先级覆盖低优先级。"""
        class _LowPrio(DocumentParser):
            SUPPORTED_TYPES = {"custom"}
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)

        class _HighPrio(DocumentParser):
            SUPPORTED_TYPES = {"custom"}
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)

        registry = ParserRegistry()
        registry.register(_LowPrio(), priority=0)
        with caplog.at_level(logging.WARNING):
            registry.register(_HighPrio(), priority=10)
        assert isinstance(registry.get("custom"), _HighPrio)

    def test_lower_priority_not_override(self, caplog):
        """低优先级不覆盖高优先级。"""
        class _HighPrio(DocumentParser):
            SUPPORTED_TYPES = {"custom"}
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)

        class _LowPrio(DocumentParser):
            SUPPORTED_TYPES = {"custom"}
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)

        registry = ParserRegistry()
        registry.register(_HighPrio(), priority=10)
        with caplog.at_level(logging.WARNING):
            registry.register(_LowPrio(), priority=0)
        assert isinstance(registry.get("custom"), _HighPrio)
        assert any("跳过注册" in record.message for record in caplog.records)

    # ── 新增：get_all 测试 ─────────────────────────────────────

    def test_get_all_returns_all_registered(self):
        """get_all 返回完整的 {source_type: parser} 映射。"""
        registry = ParserRegistry()
        registry.register(_FakeParserA(), _FakeParserB())
        all_parsers = registry.get_all()
        assert isinstance(all_parsers, dict)
        assert isinstance(all_parsers["alpha"], _FakeParserA)
        assert isinstance(all_parsers["beta"], _FakeParserA)
        assert isinstance(all_parsers["gamma"], _FakeParserB)

    def test_get_all_after_unregister(self):
        """get_all 不包含已注销的类型。"""
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        registry.unregister("alpha")
        all_parsers = registry.get_all()
        assert "alpha" not in all_parsers
        assert "beta" in all_parsers


class TestDocumentParserBase:
    """DocumentParser 基类新增属性和方法测试。"""

    def test_content_is_text_default(self):
        """默认 CONTENT_IS_TEXT 为 False。"""
        class _DefaultFormat(DocumentParser):
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)
        assert _DefaultFormat.CONTENT_IS_TEXT is False

    def test_content_is_text_override(self):
        """子类可覆写 CONTENT_IS_TEXT。"""
        class _TextFormat(DocumentParser):
            CONTENT_IS_TEXT = True
            def supports(self, s): return True
            def parse(self, doc, content): return ParseResult(doc=doc)
        assert _TextFormat.CONTENT_IS_TEXT is True


class TestBaseParseState:
    """_BaseParseState 基类测试。"""

    def test_basic_fields(self):
        """基础字段正确初始化。"""
        state = _BaseParseState(doc_id="d1", doc_version=1)
        assert state.doc_id == "d1"
        assert state.doc_version == 1
        assert state.elements == []
        assert state._seq == 0
        assert state._section_path == []

    def test_next_seq(self):
        """_next_seq 返回递增序号。"""
        state = _BaseParseState(doc_id="d1", doc_version=1)
        assert state._next_seq() == 1
        assert state._next_seq() == 2
        assert state._next_seq() == 3

    def test_subclass_extension(self):
        """子类可扩展自有字段。"""
        from dataclasses import dataclass, field

        @dataclass
        class _CustomState(_BaseParseState):
            custom_field: str = "default"
            custom_list: list[str] = field(default_factory=list)

        state = _CustomState(doc_id="d1", doc_version=1, custom_field="hello")
        assert state.doc_id == "d1"
        assert state.custom_field == "hello"
        assert state._next_seq() == 1
