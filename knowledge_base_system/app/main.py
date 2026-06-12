from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import ingest, search, upload
from app.core.deps import shutdown_resources, startup_resources


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

app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(upload.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
