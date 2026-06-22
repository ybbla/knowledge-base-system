import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── 辅助函数 ──────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def compute_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


# ── 枚举类型 ──────────────────────────────────────────────────────

# 文档生命周期：processing → active | failed
class DocStatus(str, Enum):
    active = "active"
    deleted = "deleted"          # 软删除状态，可通过 restore 恢复为 active
    failed = "failed"
    processing = "processing"


# 资源处理状态：ready | failed
class AssetStatus(str, Enum):
    ready = "ready"
    failed = "failed"


# 知识块状态：active / deleted
class ChunkStatus(str, Enum):
    active = "active"
    deleted = "deleted"


class KnowledgeType(str, Enum):
    """知识块的语义类型。当前阶段统一使用 declarative，后续扩展其余类型。"""
    declarative = "declarative"    # 陈述型：事实、定义、属性说明、概念解释
    relational = "relational"      # 关系型：实体关联、依赖、包含、对比
    procedural = "procedural"      # 流程型：步骤、操作顺序、条件分支、决策流程


class ElementType(str, Enum):
    title = "title"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    image = "image"
    video = "video"
    embedded_document = "embedded_document"  # 预留 — 子文档当前通过 ParsedElement.embedded_doc_id 关联，不使用独立元素类型
    code = "code"
    unknown = "unknown"


class AssetType(str, Enum):
    image = "image"
    video = "video"
    audio = "audio"
    attachment = "attachment"


class AssetRelation(str, Enum):
    """资源与知识块的关联关系。"""
    evidence = "evidence"            # 证据：资源直接支撑知识块内容
    illustration = "illustration"    # 示意：资源辅助理解知识块
    demonstration = "demonstration"  # 演示：视频等动态展示
    source = "source"                # 预留 — LLM 未实际输出，表示知识块来源于此资源
    attachment = "attachment"        # 预留 — LLM 未实际输出，表示资源作为附件关联


# ── 嵌套类型 ──────────────────────────────────────────────────────

class SourceLocation(BaseModel):
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    table_path: list[dict] = Field(default_factory=list)


class Render(BaseModel):
    mode: str = "inline"
    position: str = "after_linked_text"


class AssetRef(BaseModel):
    asset_id: str
    relation: AssetRelation
    linked_text: str | None = None
    caption: str | None = None
    render: Render = Field(default_factory=Render)


class SourceRef(BaseModel):
    doc_id: str
    doc_version: int = 1
    element_id: str
    source_location: SourceLocation = Field(default_factory=SourceLocation)


class ScoreComponents(BaseModel):
    vector: float = 0.0
    bm25: float = 0.0
    rrf: float = 0.0
    rerank: float | None = None  # None 表示 LLM Rerank 未执行或失败


# ── 顶层模型 ──────────────────────────────────────────────────────

class Document(BaseModel):
    doc_id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    source_type: str
    source_uri: str
    source_hash: str = ""
    category: str = "\u901a\u7528"
    version: int = 1
    status: DocStatus = DocStatus.processing
    parent_doc_id: str | None = None
    root_doc_id: str | None = None
    previous_doc_id: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedElement(BaseModel):
    element_id: str = Field(default_factory=lambda: new_id("el"))
    doc_id: str
    doc_version: int = 1
    parent_element_id: str | None = None
    sequence_order: int = 0
    element_type: ElementType
    text: str = ""
    structured_data: dict[str, Any] | None = None
    asset_ids: list[str] = Field(default_factory=list)
    embedded_doc_id: str | None = None
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    asset_id: str = Field(default_factory=lambda: new_id("asset"))
    doc_id: str
    source_element_id: str = ""
    asset_type: AssetType
    original_uri: str
    storage_uri: str | None = None
    mime_type: str = ""
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: AssetStatus = AssetStatus.ready
    extracted_text: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: new_id("chunk"))
    doc_id: str
    title: str = ""
    content: str
    content_hash: str = ""
    knowledge_type: KnowledgeType = KnowledgeType.declarative
    category: str = "\u901a\u7528"
    status: ChunkStatus = ChunkStatus.active
    asset_refs: list[AssetRef] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _set_content_hash(self) -> "KnowledgeChunk":
        if not self.content_hash and self.content:
            self.content_hash = compute_hash(self.content)
        return self


class SearchResultItem(BaseModel):
    chunk_id: str
    title: str = ""
    content: str
    score: float
    category: str
    knowledge_type: KnowledgeType
    score_components: ScoreComponents = Field(default_factory=ScoreComponents)
    asset_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    search_id: str = Field(default_factory=lambda: new_id("search"))
    query: str
    rewritten_query: str = ""
    total_count: int = 0
    results: list[SearchResultItem] = Field(default_factory=list)
