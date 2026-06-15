import logging

import pytest

from parsers.base import DocumentParser, ParseResult
from parsers.docx_parser import DocxParser
from parsers.html_parser import HtmlParser
from parsers.markdown_parser import MarkdownParser
from parsers.pptx_parser import PptxParser
from parsers.registry import ParserRegistry, UnsupportedFormatError
from parsers.xlsx_parser import XlsxParser


class _FakeParserA(DocumentParser):
    SUPPORTED_TYPES = {"alpha", "beta"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc):
        return ParseResult(doc=doc)


class _FakeParserB(DocumentParser):
    SUPPORTED_TYPES = {"gamma"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc):
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
            def parse(self, doc): return ParseResult(doc=doc)

        with caplog.at_level(logging.WARNING):
            registry.register(_FakeParserC())
        assert any("overwriting" in record.message.lower() for record in caplog.records)
        assert isinstance(registry.get("beta"), _FakeParserC)

    def test_supported_types_property(self):
        registry = ParserRegistry()
        registry.register(_FakeParserA())
        assert "alpha" in registry.supported_types
        assert "beta" in registry.supported_types

    def test_register_real_document_parsers(self):
        registry = ParserRegistry()
        registry.register(MarkdownParser(), DocxParser(), XlsxParser(), HtmlParser(), PptxParser())

        assert isinstance(registry.get("markdown"), MarkdownParser)
        assert isinstance(registry.get("docx"), DocxParser)
        assert isinstance(registry.get("xlsx"), XlsxParser)
        assert isinstance(registry.get("XLSX"), XlsxParser)
        assert isinstance(registry.get("html"), HtmlParser)
        assert isinstance(registry.get("htm"), HtmlParser)
        assert isinstance(registry.get("HTML"), HtmlParser)
        assert isinstance(registry.get("pptx"), PptxParser)
        assert isinstance(registry.get("PPTX"), PptxParser)
