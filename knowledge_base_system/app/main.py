from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import documents as legacy_documents
from app.api import ingest as legacy_ingest
from app.api import search as legacy_search
from app.api import upload as legacy_upload
from app.api.v1 import mount_v1_sub_routers, register_v1_exception_handlers, router as v1_router
from app.core.deps import shutdown_resources, startup_resources

# 前端静态文件目录
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_resources()
    try:
        yield
    finally:
        shutdown_resources()


app = FastAPI(
    title="Knowledge Base System",
    version="0.1.0",
    lifespan=lifespan,
)

# ── API 路由 ──────────────────────────────────────────────────────────
register_v1_exception_handlers(app)
mount_v1_sub_routers()
app.include_router(v1_router)

# 旧版接口仅用于兼容存量调用方；新前端统一走 /api/v1。
app.include_router(legacy_upload.router)
app.include_router(legacy_ingest.router)
app.include_router(legacy_search.router)
app.include_router(legacy_documents.router)


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
