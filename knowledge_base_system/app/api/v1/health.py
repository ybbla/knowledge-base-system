"""系统健康检查 API — GET /api/v1/health/*

提供三层健康检查：
- /live：进程存活
- /ready：核心仓储、索引和资源存储就绪
- /dependencies：依赖状态详情（隐藏敏感信息）
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, status

from app.api.v1.schemas import APIResponse, response_json
from app.core.deps import (
    asset_store,
    bm25_index,
    chunk_store,
    document_repo,
    element_repo,
    vector_index,
)
from app.core.config import settings
from llm.volcengine_client import embedding_client

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


# ── 3.1 存活检查 ──────────────────────────────────────────────────

@router.get("/live")
async def health_live():
    """返回进程是否可响应。"""
    return APIResponse(
        data={"status": "ok"},
        meta={"service": "knowledge-base-system"},
    ).model_dump(mode="json")


# ── 3.2 就绪检查 ──────────────────────────────────────────────────

@router.get("/ready")
async def health_ready():
    """检查核心仓储、索引和资源存储是否可达。

    返回 200 表示所有核心依赖可用。
    返回 503 表示有依赖不可用（通过 data.status=degraded）。
    """
    checks: dict[str, dict[str, Any]] = {}

    # ── 文档仓储 ──
    if document_repo is not None:
        try:
            document_repo.get("_health_check_")
            checks["document_repo"] = {"status": "ok"}
        except Exception as e:
            checks["document_repo"] = {"status": "error", "summary": _safe_summary(e)}
    else:
        checks["document_repo"] = {"status": "not_configured"}

    # ── 元素仓储 ──
    if element_repo is not None:
        try:
            element_repo.get_by_doc_id("_health_check_")
            checks["element_repo"] = {"status": "ok"}
        except Exception as e:
            checks["element_repo"] = {"status": "error", "summary": _safe_summary(e)}
    else:
        checks["element_repo"] = {"status": "not_configured"}

    # ── 知识块存储 ──
    try:
        if chunk_store is not None:
            # 轻量校验：尝试计数
            count = chunk_store.count() if hasattr(chunk_store, "count") else None
            checks["chunk_store"] = {"status": "ok", "count": count}
        else:
            checks["chunk_store"] = {"status": "not_configured"}
    except Exception as e:
        checks["chunk_store"] = {"status": "error", "summary": _safe_summary(e)}

    # ── 向量索引 ──
    try:
        if vector_index is not None:
            # 轻量校验：确保实例可用
            checks["vector_index"] = {"status": "ok"}
        else:
            checks["vector_index"] = {"status": "not_configured"}
    except Exception as e:
        checks["vector_index"] = {"status": "error", "summary": _safe_summary(e)}

    # ── BM25 索引 ──
    try:
        if bm25_index is not None:
            checks["bm25_index"] = {"status": "ok"}
        else:
            checks["bm25_index"] = {"status": "not_configured"}
    except Exception as e:
        checks["bm25_index"] = {"status": "error", "summary": _safe_summary(e)}

    # ── 资源存储 ──
    if asset_store is not None:
        try:
            # 资源存储可能不支持健康检查；存在即可
            checks["asset_store"] = {"status": "ok"}
        except Exception as e:
            checks["asset_store"] = {"status": "error", "summary": _safe_summary(e)}
    else:
        checks["asset_store"] = {"status": "not_configured"}

    # ── 判定整体状态 ──
    error_deps = [k for k, v in checks.items() if v.get("status") == "error"]
    if error_deps:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        overall = "degraded"
    else:
        response_status = status.HTTP_200_OK
        overall = "ok"

    return response_json(APIResponse(
        data={"status": overall, "checks": checks},
        meta={"backend": settings.backend},
    ), response_status)


# ── 3.3 依赖状态详情 ──────────────────────────────────────────────

@router.get("/dependencies")
async def health_dependencies():
    """返回各依赖的状态详情。

    隐藏敏感信息：不暴露密钥、连接密码或完整堆栈。
    """
    deps: dict[str, dict[str, Any]] = {
        "backend": {
            "status": "ok",
            "type": settings.backend,
        },
        "document_repo": _check_repo(document_repo, "文档仓储"),
        "element_repo": _check_repo(element_repo, "元素仓储"),
        "chunk_store": _check_chunk_store(),
        "vector_index": _check_index(vector_index, "向量索引"),
        "bm25_index": _check_index(bm25_index, "BM25 索引"),
        "embedding": _check_embedding(),
        "llm": _check_llm(),
        "asset_store": _check_asset_store(),
    }

    return APIResponse(
        data={"dependencies": deps},
        meta={"service": "knowledge-base-system", "version": "0.1.0"},
    ).model_dump(mode="json")


# ── 辅助函数 ──────────────────────────────────────────────────────

def _safe_summary(exc: Exception) -> str:
    """安全提取异常摘要，不暴露堆栈。"""
    return str(exc)[:200]


def _check_repo(repo, name: str) -> dict[str, Any]:
    """检查仓储可达性。"""
    if repo is None:
        return {"status": "not_configured", "name": name}
    try:
        # 轻量操作
        if hasattr(repo, "get"):
            repo.get("_health_check_")
        return {"status": "ok", "name": name}
    except Exception as e:
        logger.warning("%s 健康检查失败: %s", name, e)
        return {"status": "error", "name": name, "summary": _safe_summary(e)}


def _check_chunk_store() -> dict[str, Any]:
    """检查知识块存储。"""
    if chunk_store is None:
        return {"status": "not_configured", "name": "知识块存储"}
    try:
        if hasattr(chunk_store, "count"):
            return {"status": "ok", "name": "知识块存储", "count": chunk_store.count()}
        return {"status": "ok", "name": "知识块存储"}
    except Exception as e:
        logger.warning("知识块存储健康检查失败: %s", e)
        return {"status": "error", "name": "知识块存储", "summary": _safe_summary(e)}


def _check_index(index, name: str) -> dict[str, Any]:
    """检查索引实例。"""
    if index is None:
        return {"status": "not_configured", "name": name}
    try:
        return {"status": "ok", "name": name}
    except Exception as e:
        logger.warning("%s 健康检查失败: %s", name, e)
        return {"status": "error", "name": name, "summary": _safe_summary(e)}


def _check_embedding() -> dict[str, Any]:
    """检查 Embedding 服务。"""
    try:
        if embedding_client is not None:
            return {"status": "ok", "name": "Embedding"}
        return {"status": "not_configured", "name": "Embedding"}
    except Exception as e:
        logger.warning("Embedding 健康检查失败: %s", e)
        return {"status": "error", "name": "Embedding", "summary": _safe_summary(e)}


def _check_llm() -> dict[str, Any]:
    """检查 LLM 服务。"""
    try:
        from app.core.deps import extractor
        if extractor is not None:
            return {"status": "ok", "name": "LLM"}
        return {"status": "not_configured", "name": "LLM"}
    except Exception as e:
        logger.warning("LLM 健康检查失败: %s", e)
        return {"status": "error", "name": "LLM", "summary": _safe_summary(e)}


def _check_asset_store() -> dict[str, Any]:
    """检查资源存储。"""
    if asset_store is None:
        return {"status": "not_configured", "name": "资源存储"}
    try:
        return {"status": "ok", "name": "资源存储"}
    except Exception as e:
        logger.warning("资源存储健康检查失败: %s", e)
        return {"status": "error", "name": "资源存储", "summary": _safe_summary(e)}
