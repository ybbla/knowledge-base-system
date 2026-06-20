"""知识块管理页面联调测试（Mock LLM 版）。

与 integration/test_chunks_api.py 完全相同，
LLM 调用（embed_text 块嵌入/重索引）由 conftest.py mock。
"""

from __future__ import annotations

from tests.integration.test_chunks_api import (
    client,
    _SIMULATED_FILES,
    _CONTENT_TYPES,
    _create_test_doc,
    _cleanup_doc,
    _create_test_chunk,
    _cleanup_chunk,
    TestChunksSearchFilters as _OrigSearchFilters,
    TestChunksCreate as _OrigCreate,
    TestChunksList as _OrigList,
    TestChunksDetail as _OrigDetail,
    TestChunksUpdate as _OrigUpdate,
    TestChunksDelete as _OrigDelete,
    TestChunksRestore as _OrigRestore,
    TestChunksBatch as _OrigBatch,
    TestChunksEndToEnd as _OrigEndToEnd,
)


class TestChunksSearchFilters(_OrigSearchFilters):
    pass


class TestChunksCreate(_OrigCreate):
    pass


class TestChunksList(_OrigList):
    pass


class TestChunksDetail(_OrigDetail):
    pass


class TestChunksUpdate(_OrigUpdate):
    pass


class TestChunksDelete(_OrigDelete):
    pass


class TestChunksRestore(_OrigRestore):
    pass


class TestChunksBatch(_OrigBatch):
    pass


class TestChunksEndToEnd(_OrigEndToEnd):
    pass
