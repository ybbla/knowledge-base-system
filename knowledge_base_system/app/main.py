from fastapi import FastAPI

from app.api import ingest, search, upload

app = FastAPI(title="Knowledge Base System", version="0.1.0")

app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(upload.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
