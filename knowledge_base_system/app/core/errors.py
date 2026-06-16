class KnowledgeBaseError(Exception):
    """Base error for the knowledge base system."""


class ParseError(KnowledgeBaseError):
    """Document parsing failed."""


class LLMError(KnowledgeBaseError):
    """LLM call failed after retries."""


class IndexingError(KnowledgeBaseError):
    """Index operation failed."""


class RetrievalError(KnowledgeBaseError):
    """Retrieval pipeline failed."""


class DuplicateDocumentError(KnowledgeBaseError):
    """尝试创建已存在的文档时抛出。"""


class VersionConflictError(KnowledgeBaseError):
    """文档乐观锁版本冲突——并发更新导致 version 不匹配。"""


class DocumentNotFoundError(KnowledgeBaseError):
    """指定的文档不存在。"""
