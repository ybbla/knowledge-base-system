from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.models import Asset, Document, ParsedElement


@dataclass
class ParseResult:
    doc: Document
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    embedded_docs: list[Document] = field(default_factory=list)


class DocumentParser(ABC):
    """Abstract parser interface."""

    @abstractmethod
    def supports(self, source_type: str) -> bool: ...

    @abstractmethod
    def parse(self, doc: Document) -> ParseResult: ...
