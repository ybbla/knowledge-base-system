"""应用全局配置管理 — 火山引擎 LLM/Embedding、PostgreSQL、Milvus、MinIO 等外部服务参数。"""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOLCENGINE_",
        env_file=PACKAGE_ROOT / ".env",
    )

    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_model: str = "doubao-seed-2-0-pro-260215"
    embedding_model: str = "doubao-embedding-vision-251215"
    request_timeout_seconds: float = Field(default=60.0, validation_alias="VOLCENGINE_TIMEOUT_SECONDS")

    # 检索默认参数。通过原始环境变量读取，便于评测脚本动态覆盖。
    vector_top_k: int = Field(default=30, validation_alias="VECTOR_TOP_K")
    bm25_top_k: int = Field(default=30, validation_alias="BM25_TOP_K")
    fusion_top_k: int = Field(default=15, validation_alias="FUSION_TOP_K")
    final_top_k: int = Field(default=5, validation_alias="FINAL_TOP_K")
    rrf_k: int = Field(default=60, validation_alias="RRF_K")

    # 入库处理限制
    max_recursion_depth: int = 3
    max_elements_per_doc: int = 1000
    max_window_tokens: int = 3000
    embedding_batch_size: int = Field(default=32, validation_alias="EMBEDDING_BATCH_SIZE")
    index_upsert_batch_size: int = Field(default=100, validation_alias="INDEX_UPSERT_BATCH_SIZE")

    # LLM 重试策略
    max_json_retries: int = 3

    # 后端模式：仅支持 postgres。
    backend: str = Field(default="postgres", validation_alias="BACKEND")
    database_url: str = Field(
        default="postgresql://kbuser:kbpass@localhost:5432/knowledge_base",
        validation_alias="DATABASE_URL",
    )

    # Milvus：必须启用并可连接。
    milvus_enabled: bool = Field(default=True, validation_alias="MILVUS_ENABLED")
    milvus_host: str = Field(default="localhost", validation_alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, validation_alias="MILVUS_PORT")
    milvus_collection: str = Field(
        default="knowledge_chunks", validation_alias="MILVUS_COLLECTION"
    )
    milvus_nlist: int = Field(default=128, validation_alias="MILVUS_NLIST")
    # HNSW 索引参数
    milvus_hnsw_M: int = Field(default=16, validation_alias="MILVUS_HNSW_M")
    milvus_hnsw_ef_construction: int = Field(default=200, validation_alias="MILVUS_HNSW_EF_CONSTRUCTION")
    milvus_hnsw_ef: int = Field(default=64, validation_alias="MILVUS_HNSW_EF")
    # BM25 检索参数
    milvus_sparse_ef: int = Field(default=16, validation_alias="MILVUS_SPARSE_EF")

    # MinIO：必须启用并可连接。
    minio_enabled: bool = Field(default=True, validation_alias="MINIO_ENABLED")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(
        default="minioadmin", validation_alias="MINIO_ACCESS_KEY"
    )
    minio_secret_key: str = Field(
        default="minioadmin", validation_alias="MINIO_SECRET_KEY"
    )
    minio_bucket_input: str = Field(
        default="kb-input", validation_alias="MINIO_BUCKET_INPUT"
    )
    minio_bucket_assets: str = Field(
        default="kb-assets", validation_alias="MINIO_BUCKET_ASSETS"
    )
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    minio_presigned_expiry: int = Field(
        default=3600, validation_alias="MINIO_PRESIGNED_EXPIRY"
    )

    # 多模态视觉理解
    image_vision_enabled: bool = Field(default=True, validation_alias="IMAGE_VISION_ENABLED")

    # 评测数据自动生成
    auto_eval_enabled: bool = Field(default=True, validation_alias="AUTO_EVAL_ENABLED")
    auto_eval_queries_per_doc: int = Field(default=4, validation_alias="AUTO_EVAL_QUERIES_PER_DOC")

    def reload_runtime_env(self) -> "Settings":
        """按需刷新运行期可调配置，支持评测和线上调参无需重启。"""
        fresh = type(self)()
        for field_name, field in type(self).model_fields.items():
            candidates = {field_name}
            if field.validation_alias:
                candidates.add(str(field.validation_alias))
            else:
                candidates.add(f"VOLCENGINE_{field_name.upper()}")
            if any(name in os.environ for name in candidates):
                setattr(self, field_name, getattr(fresh, field_name))
        return self


settings = Settings()


def get_settings(*, reload_env: bool = False) -> Settings:
    """返回全局配置；需要时刷新环境变量覆盖项。"""
    if reload_env:
        settings.reload_runtime_env()
    return settings
