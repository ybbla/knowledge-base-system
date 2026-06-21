"""文档解析器抽象基类和通用数据结构。

定义所有解析器必须遵循的统一契约：ParseResult 数据类和 DocumentParser 抽象类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.models import Asset, Document, ParsedElement


@dataclass
class ParseResult:
    """解析结果，包含文档、结构化元素、资源资产和嵌入子文档。

    由各格式解析器的 parse() 方法返回，下游索引管线据此构建检索索引。
    """
    doc: Document
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    embedded_docs: list[Document] = field(default_factory=list)


class DocumentParser(ABC):
    """文档解析器抽象基类。

    所有格式解析器需实现 supports() 和 parse() 两个方法。
    通过 ParserRegistry 按 source_type 注册和分发。
    """

    @abstractmethod
    def supports(self, source_type: str) -> bool:
        """判断当前解析器是否支持指定的 source_type。"""
        ...

    @abstractmethod
    def parse(self, doc: Document) -> ParseResult:
        """将原始文档解析为 ParseResult。

        Args:
            doc: 待解析的文档对象，需包含 source_uri 或 metadata.raw_content。

        Returns:
            包含文档、元素列表和资源资产列表的 ParseResult。
        """
        ...
