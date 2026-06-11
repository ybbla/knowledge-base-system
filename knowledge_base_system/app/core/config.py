from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "VOLCENGINE_", "env_file": ".env"}

    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_model: str = "doubao-seed-2-0-pro-260215"
    embedding_model: str = "doubao-embedding-vision-251215"

    # Retrieval defaults
    vector_top_k: int = 50
    bm25_top_k: int = 50
    fusion_top_k: int = 20
    final_top_k: int = 5
    rrf_k: int = 60

    # Ingestion limits
    max_recursion_depth: int = 3
    max_elements_per_doc: int = 1000
    max_window_tokens: int = 3000

    # LLM retry
    max_json_retries: int = 3

    # Backend mode (no prefix — read from raw env vars)
    backend: str = Field(default="memory", validation_alias="BACKEND")
    database_url: str = Field(
        default="postgresql://kbuser:kbpass@localhost:5432/knowledge_base",
        validation_alias="DATABASE_URL",
    )


settings = Settings()
