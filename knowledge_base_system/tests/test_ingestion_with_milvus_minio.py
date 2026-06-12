import os
import time

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_E2E_MILVUS_MINIO_TESTS") != "1",
    reason="需要完整 Docker 环境和外部 LLM；设置 RUN_E2E_MILVUS_MINIO_TESTS=1 后运行",
)
def test_ingestion_with_milvus_minio_end_to_end():
    from app.core.deps import ingestion_pipeline
    from app.core.models import Document

    doc = Document(
        title="阶段三端到端",
        source_type="markdown",
        source_uri="memory://inline",
        metadata={"raw_content": "# 标题\n\n![img](https://example.com/a.png)\n"},
    )
    job = ingestion_pipeline.submit(doc)
    assert job.job_id

    deadline = time.time() + 60
    while job.status in {"pending", "processing"} and time.time() < deadline:
        time.sleep(0.5)

    assert job.status == "completed"
    assert job.chunk_count > 0
