import logging
from typing import Any

from parsers.base import DocumentParser

logger = logging.getLogger(__name__)


class UnsupportedFormatError(ValueError):
    """Raised when no parser is registered for a given source_type."""

    def __init__(self, source_type: str, supported_types: list[str]) -> None:
        self.source_type = source_type
        self.supported_types = supported_types
        super().__init__(
            f"Unsupported source_type: {source_type}. "
            f"Supported types: {', '.join(sorted(supported_types))}"
        )


class ParserRegistry:
    """Registry for DocumentParser implementations, keyed by source_type."""

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    @property
    def supported_types(self) -> list[str]:
        return sorted(self._parsers.keys())

    def register(self, *parsers: DocumentParser) -> None:
        """Register one or more parsers.

        Each parser's SUPPORTED_TYPES are used as keys (case-insensitive).
        Duplicate registrations overwrite the previous parser with a warning.
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
        """Return the parser for the given source_type.

        Raises UnsupportedFormatError if no parser is registered.
        """
        key = source_type.lower()
        if key not in self._parsers:
            raise UnsupportedFormatError(source_type, self.supported_types)
        return self._parsers[key]
