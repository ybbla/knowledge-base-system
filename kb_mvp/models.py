from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawDocument:
    """原始文档输入模型。

    该模型表示尚未被解析的文档内容。MVP 阶段主要承载 Markdown/TXT
    字符串内容，同时保留来源 URI、父文档、递归深度和扩展元数据，便于后续
    接入真实文件系统、对象存储或远程 URL。
    """

    doc_id: str
    title: str
    source_type: str
    content: str
    source_uri: str | None = None
    parent_doc_id: str | None = None
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceLocation:
    """文档内来源定位信息。

    用于把知识块追溯回原始文档中的位置。MVP 阶段主要使用标题路径和表格
    行列信息；后续解析 PDF、DOCX、PPTX 时可以补充分页、坐标、页内区域等
    更精细的位置数据。
    """

    section_path: list[str] = field(default_factory=list)
    page: int | None = None
    table_id: str | None = None
    row: int | None = None
    column: int | None = None


@dataclass
class Asset:
    """多媒体或外部资源模型。

    图片、视频、附件等资源统一使用该模型表达。MVP 阶段不真实上传 MinIO，
    而是使用 `memory://` URI 模拟存储位置，同时保留原始 URI 和资源语义
    描述，方便知识块引用和前端渲染。
    """

    asset_id: str
    asset_type: str
    original_uri: str
    storage_uri: str
    mime_type: str | None = None
    extracted_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedElement:
    """解析后的文档结构元素。

    解析器把原始文档转换成一组标准元素，例如标题、段落、表格、表格行、
    图片引用或视频引用。语义抽取阶段基于这些元素生成知识块，而不是直接
    对原始文档字符串做切片。
    """

    element_id: str
    doc_id: str
    element_type: str
    text: str = ""
    children: list["ParsedElement"] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    source_location: SourceLocation = field(default_factory=SourceLocation)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """标准化后的文档解析结果。

    一个 `ParsedDocument` 包含顶层结构元素、提取到的资源对象，以及递归
    发现的嵌入文档。入库流水线会继续处理 `embedded_documents`，从而完成
    有边界的递归解析。
    """

    doc_id: str
    title: str
    root_elements: list[ParsedElement]
    assets: list[Asset]
    embedded_documents: list[RawDocument] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssetRef:
    """知识块中的资源引用。

    该模型只保存知识块渲染和解释所需的轻量资源信息，不直接保存资源字节。
    正式版本中 `storage_uri` 会指向 MinIO；MVP 阶段则指向内存资源 URI。
    """

    asset_id: str
    asset_type: str
    storage_uri: str
    caption: str = ""
    relation: str = "evidence"


@dataclass
class SourceRef:
    """知识块到解析元素的来源引用。

    一个知识块可能来自多个段落、表格行或多媒体资源。该引用用于保留可追溯
    性，让检索结果能够说明它来自哪个文档、哪个元素和哪个位置。
    """

    doc_id: str
    element_id: str
    source_location: SourceLocation


@dataclass
class KnowledgeChunk:
    """可向量化和检索的最小知识单元。

    知识块是入库流水线的最终产物。`content` 应当是独立可读、语义集中的
    自然语言文本；`assets` 关联图片/视频等可渲染资源；`metadata` 预留
    知识类型、标题路径和模型信息等扩展字段。
    """

    chunk_id: str
    doc_id: str
    content: str
    knowledge_type: str = "declarative"
    assets: list[AssetRef] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


@dataclass
class SearchHit:
    """检索命中结果。

    包装被召回的知识块、综合分数和分数明细。向量检索、BM25、RRF 融合和
    LLM 重排都可以把自己的分数写入 `score_detail`，方便调试检索质量。
    """

    chunk: KnowledgeChunk
    score: float
    score_detail: dict[str, float] = field(default_factory=dict)
