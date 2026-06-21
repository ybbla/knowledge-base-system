"""知识库系统自定义异常类，按模块层级划分便于上层统一捕获和日志记录。"""


class KnowledgeBaseError(Exception):
    """知识库系统基础异常，所有自定义异常均继承自此类。"""


class ParseError(KnowledgeBaseError):
    """文档解析失败（格式不支持或解析器内部错误）。"""


class LLMError(KnowledgeBaseError):
    """LLM 调用失败，在多次重试后仍然不可用。"""


class IndexingError(KnowledgeBaseError):
    """索引写入操作失败（Milvus 或 BM25 索引异常）。"""


class RetrievalError(KnowledgeBaseError):
    """检索流水线执行失败（向量检索、BM25 或融合阶段异常）。"""


class DuplicateDocumentError(KnowledgeBaseError):
    """尝试创建已存在的文档时抛出。"""


class DocumentNotFoundError(KnowledgeBaseError):
    """指定的文档不存在。"""
