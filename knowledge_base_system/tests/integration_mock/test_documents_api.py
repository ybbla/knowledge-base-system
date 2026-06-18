"""文档管理页面联调测试（Mock LLM 版）。

与 integration/test_documents_api.py 完全相同，
LLM 调用（语义提取 + 块嵌入）由 conftest.py mock。
"""

from __future__ import annotations

from tests.integration.test_documents_api import (
    client,
    _SIMULATED_FILES,
    _CONTENT_TYPES,
    _create_test_doc,
    _cleanup_doc,
    _get_simulated_file,
    _upload_simulated,
    TestDocumentsSearchFilters as _OrigSearchFilters,
    TestDocumentsList as _OrigList,
    TestDocumentsCreate as _OrigCreate,
    TestDocumentsDetail as _OrigDetail,
    TestDocumentsElements as _OrigElements,
    TestDocumentsUpdate as _OrigUpdate,
    TestDocumentsDelete as _OrigDelete,
    TestDocumentsRestore as _OrigRestore,
    TestDocumentsIngest as _OrigIngest,
    TestDocumentsFullCRUDFlow as _OrigFullCRUDFlow,
    TestLegacyUploadAPI as _OrigLegacyUpload,
    TestDocumentsResponseConsistency as _OrigResponseConsistency,
    TestDocumentsUpload as _OrigUpload,
    TestDocumentsUploadFullWorkflow as _OrigUploadFullWorkflow,
    TestDocumentsUploadEdgeCases as _OrigUploadEdgeCases,
)


class TestDocumentsSearchFilters(_OrigSearchFilters):
    pass


class TestDocumentsList(_OrigList):
    pass


class TestDocumentsCreate(_OrigCreate):
    pass


class TestDocumentsDetail(_OrigDetail):
    pass


class TestDocumentsElements(_OrigElements):
    pass


class TestDocumentsUpdate(_OrigUpdate):
    pass


class TestDocumentsDelete(_OrigDelete):
    pass


class TestDocumentsRestore(_OrigRestore):
    pass


class TestDocumentsIngest(_OrigIngest):
    pass


class TestDocumentsFullCRUDFlow(_OrigFullCRUDFlow):
    pass


class TestLegacyUploadAPI(_OrigLegacyUpload):
    pass


class TestDocumentsResponseConsistency(_OrigResponseConsistency):
    pass


class TestDocumentsUpload(_OrigUpload):
    pass


class TestDocumentsUploadFullWorkflow(_OrigUploadFullWorkflow):
    pass


class TestDocumentsUploadEdgeCases(_OrigUploadEdgeCases):
    pass
