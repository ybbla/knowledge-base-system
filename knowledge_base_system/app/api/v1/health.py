"""系统健康检查 API — GET /api/v1/health/*

提供两级健康检查：
- /live：进程存活
- /    ：整体状态 + 外部依赖详情（PostgreSQL、Milvus、MinIO、LLM）
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.api.v1.schemas import APIResponse

router = APIRouter(prefix="/health", tags=["health"])

logger = logging.getLogger(__name__)


# ── 存活检查 ────────────────────────────────────────────────────────


@router.get("/live")
async def health_live():
    """返回进程是否可响应。"""
    return APIResponse(
        data={"status": "ok"},
        meta={"service": "knowledge-base-system", "version": "0.3.0"},
    ).model_dump(mode="json")


# ── 整体状态 + 外部依赖 ──────────────────────────────────────────────


@router.get("")
async def health():
    """返回系统整体状态和外部依赖详情。

    仅显示外部服务：PostgreSQL、Milvus、MinIO、LLM。
    隐藏敏感信息：不暴露密钥、连接密码或完整堆栈。
    任一依赖 error 时 data.status 为 degraded，HTTP 仍返回 200。
    """
    deps: dict[str, dict[str, Any]] = {
        "postgresql": _check_postgresql(),
        "milvus": _check_milvus(),
        "minio": _check_minio(),
        "llm": _check_llm(),
    }

    error_deps = [k for k, v in deps.items() if v.get("status") == "error"]
    overall = "degraded" if error_deps else "ok"

    return APIResponse(
        data={
            "status": overall,
            "dependencies": deps,
        },
        meta={"service": "knowledge-base-system", "version": "0.3.0"},
    ).model_dump(mode="json")


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _safe_summary(exc: Exception) -> str:
    """安全提取异常摘要，不暴露堆栈。"""
    return str(exc)[:200]


def _check_postgresql() -> dict[str, Any]:
    """检查 PostgreSQL 数据库连接。"""
    try:
        from sqlalchemy import text
        from app.db.engine import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "name": "PostgreSQL"}
    except Exception as e:
        logger.warning("PostgreSQL 健康检查失败: %s", e)
        return {"status": "error", "name": "PostgreSQL", "summary": _safe_summary(e)}


def _check_milvus() -> dict[str, Any]:
    """检查 Milvus 向量数据库连接。"""
    try:
        from app.core.deps import milvus_manager

        if milvus_manager is not None:
            milvus_manager.ensure_collection()
            return {"status": "ok", "name": "Milvus"}
        return {"status": "not_configured", "name": "Milvus"}
    except Exception as e:
        logger.warning("Milvus 健康检查失败: %s", e)
        return {"status": "error", "name": "Milvus", "summary": _safe_summary(e)}


def _check_minio() -> dict[str, Any]:
    """检查 MinIO 对象存储连接。"""
    try:
        from app.core.deps import minio_asset_store

        if minio_asset_store is not None:
            minio_asset_store.client.list_buckets()
            return {"status": "ok", "name": "MinIO"}
        return {"status": "not_configured", "name": "MinIO"}
    except Exception as e:
        logger.warning("MinIO 健康检查失败: %s", e)
        return {"status": "error", "name": "MinIO", "summary": _safe_summary(e)}


def _check_llm() -> dict[str, Any]:
    """检查 LLM 服务。"""
    try:
        from app.core.deps import extractor
        if extractor is not None:
            return {"status": "ok", "name": "LLM"}
        return {"status": "not_configured", "name": "LLM"}
    except Exception as e:
        logger.warning("LLM 服务健康检查失败: %s", e)
        return {"status": "error", "name": "LLM", "summary": _safe_summary(e)}
