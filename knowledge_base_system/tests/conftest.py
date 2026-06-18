import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that require external services (LLM API)")


def pytest_addoption(parser):
    """添加评测筛选命令行参数。"""
    group = parser.getgroup("evaluation")
    group.addoption("--eval-doc-id", help="按文档 ID 筛选评测数据")
    group.addoption("--eval-category", help="按业务分类筛选评测数据")
    group.addoption("--eval-difficulty", choices=["easy", "medium", "hard"],
                    help="按难度筛选评测数据")
    group.addoption("--eval-source", choices=["auto", "manual"],
                    help="按来源筛选评测数据")
    group.addoption("--eval-since", type=int, metavar="DAYS",
                    help="只评测最近 N 天新增的数据")
    group.addoption("--eval-query", metavar="KEYWORD",
                    help="按查询关键词模糊匹配")
    group.addoption("--eval-sample", type=int, metavar="N",
                    help="随机抽样 N 条评测")
    group.addoption("--eval-failed", action="store_true",
                    help="只评测上次失败的查询（回归验证）")
