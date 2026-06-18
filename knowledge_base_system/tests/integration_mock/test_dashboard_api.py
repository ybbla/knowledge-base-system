"""仪表板页面联调测试（Mock LLM 版）。

与 integration/test_dashboard_api.py 完全相同，LLM/Embedding 调用由 conftest.py mock。
仪表板接口（health/ready、dependencies、documents/chunks 列表）本身不直接调用 LLM，
但 conftest 的 mock 确保 app 初始化阶段不因外部 API 超时而阻塞。
"""

from __future__ import annotations

from tests.integration.test_dashboard_api import (
    client,
    TestDashboardHealthLive as _OrigHealthLive,
    TestDashboardHealthReady as _OrigHealthReady,
    TestDashboardHealthDependencies as _OrigHealthDependencies,
    TestDashboardDocumentList as _OrigDocumentList,
    TestDashboardChunkList as _OrigChunkList,
    TestDashboardFullFlow as _OrigFullFlow,
    TestDashboardFrontendAlignment as _OrigFrontendAlignment,
    TestDashboardConcurrency as _OrigConcurrency,
)


class TestDashboardHealthLive(_OrigHealthLive):
    pass


class TestDashboardHealthReady(_OrigHealthReady):
    pass


class TestDashboardHealthDependencies(_OrigHealthDependencies):
    pass


class TestDashboardDocumentList(_OrigDocumentList):
    pass


class TestDashboardChunkList(_OrigChunkList):
    pass


class TestDashboardFullFlow(_OrigFullFlow):
    pass


class TestDashboardFrontendAlignment(_OrigFrontendAlignment):
    pass


class TestDashboardConcurrency(_OrigConcurrency):
    pass
