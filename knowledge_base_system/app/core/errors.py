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
