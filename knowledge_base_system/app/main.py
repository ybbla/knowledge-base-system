from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1 import mount_v1_sub_routers, register_v1_exception_handlers, router as v1_router
from app.core.deps import recover_stale_processing_docs, recover_stale_processing_jobs, shutdown_resources
from app.utils.thread_pool import (
    startup_health_pool, shutdown_health_pool,
    startup_search_pool, shutdown_search_pool,
    startup_upload_pool, shutdown_upload_pool,
    startup_sub_ingest_pool, shutdown_sub_ingest_pool,
    startup_asset_worker_pool, shutdown_asset_worker_pool,
    startup_eval_gen_pool, shutdown_eval_gen_pool,
)

# 前端静态文件目录
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_health_pool()
    startup_search_pool()
    startup_upload_pool()
    startup_sub_ingest_pool()
    startup_asset_worker_pool()
    startup_eval_gen_pool()
    recover_stale_processing_docs()
    recover_stale_processing_jobs()
    try:
        yield
    finally:
        shutdown_resources()
        shutdown_health_pool()
        shutdown_search_pool()
        shutdown_asset_worker_pool()
        shutdown_sub_ingest_pool()
        shutdown_upload_pool()
        shutdown_eval_gen_pool()


app = FastAPI(
    title="Knowledge Base System",
    version="0.1.0",
    lifespan=lifespan,
)

# ── API 路由 ──────────────────────────────────────────────────────────
register_v1_exception_handlers(app)
mount_v1_sub_routers()
app.include_router(v1_router)



# ── 前端静态文件 ─────────────────────────────────────────────────────
# 注意: 静态挂载和 SPA 回退必须在所有 API 路由之后注册，
# 以确保 API 路径优先匹配。
if _FRONTEND_DIR.is_dir():
    from fastapi.responses import FileResponse

    app.mount("/css", StaticFiles(directory=str(_FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(_FRONTEND_DIR / "js")), name="js")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        """SPA 回退 — 所有非 API/静态文件路径返回 index.html。"""
        file_path = _FRONTEND_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        index_path = _FRONTEND_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return {"detail": "Frontend not found"}, 404
