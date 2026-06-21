"""解析器注册表。

按 source_type 管理和分发 DocumentParser 实现，支持大小写不敏感的注册与查找。
"""

import logging

from parsers.base import DocumentParser

logger = logging.getLogger(__name__)


class UnsupportedFormatError(ValueError):
    """当没有解析器能处理给定的 source_type 时抛出。"""

    def __init__(self, source_type: str, supported_types: list[str]) -> None:
        self.source_type = source_type
        self.supported_types = supported_types
        super().__init__(
            f"Unsupported source_type: {source_type}. "
            f"Supported types: {', '.join(sorted(supported_types))}"
        )


class ParserRegistry:
    """按 source_type 注册和查找 DocumentParser 实现的注册表。

    使用方式：
        registry = ParserRegistry()
        registry.register(MarkdownParser(), PdfParser())
        parser = registry.get("pdf")
        result = parser.parse(doc)
    """

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    @property
    def supported_types(self) -> list[str]:
        """返回所有已注册的 source_type（按字母排序）。"""
        return sorted(self._parsers.keys())

    def register(self, *parsers: DocumentParser) -> None:
        """注册一个或多个解析器。

        每个解析器的 SUPPORTED_TYPES 类属性作为注册键（大小写不敏感）。
        重复注册会覆盖旧解析器并输出警告日志。
        """
        for parser in parsers:
            supported = getattr(parser, "SUPPORTED_TYPES", set())
            for source_type in supported:
                key = source_type.lower()
                if key in self._parsers and self._parsers[key] is not parser:
                    logger.warning(
                        "Parser for '%s' already registered (%s), overwriting with %s",
                        key,
                        type(self._parsers[key]).__name__,
                        type(parser).__name__,
                    )
                self._parsers[key] = parser

    def get(self, source_type: str) -> DocumentParser:
        """获取指定 source_type 对应的解析器。

        Args:
            source_type: 文档类型标识（如 "pdf"、"markdown"、"docx" 等）。

        Returns:
            匹配的 DocumentParser 实例。

        Raises:
            UnsupportedFormatError: 当没有注册该类型的解析器时。
        """
        key = source_type.lower()
        if key not in self._parsers:
            raise UnsupportedFormatError(source_type, self.supported_types)
        return self._parsers[key]
