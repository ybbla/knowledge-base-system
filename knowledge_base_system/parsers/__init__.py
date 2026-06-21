"""文档解析器包。

提供多格式文档解析的统一入口，将各类文档（PDF、Markdown、DOCX、HTML、PPTX、XLSX）
解析为统一的 ParsedElement 和 Asset 结构，供下游索引管线消费。
"""

from parsers.pdf_parser import PdfParser

__all__ = ["PdfParser"]
