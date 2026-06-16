from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import documents, ingest, search, upload
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
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(upload.router)
app.include_router(documents.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


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
