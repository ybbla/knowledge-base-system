import os

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_E2E_MILVUS_MINIO_TESTS") != "1",
    reason="需要完整 Docker 环境和外部 LLM；设置 RUN_E2E_MILVUS_MINIO_TESTS=1 后运行",
)
def test_search_with_milvus_returns_presigned_asset_urls():
    from app.core.deps import rebuild_retrieval_indexes_from_chunks, retrieval_pipeline

    assert rebuild_retrieval_indexes_from_chunks() > 0

    result = retrieval_pipeline.search("上传", top_k=5)
    assert result.results
    for item in result.results:
        for asset in item.asset_refs:
            uri = asset.get("storage_uri")
            assert uri is None or uri.startswith(("http://", "https://"))
