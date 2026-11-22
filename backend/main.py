import os

import uvicorn
from api.chat_routes import router as chat_router
from api.fs_routes import router as fs_router
from api.git_routes import router as git_router
from api.index_routes import router as index_router
from api.model_routes import router as model_router
from api.workspace_routes import router as workspace_router
from core.logging_config import configure_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

configure_logging()

app = FastAPI(title="PrivateCopilot API")

_allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
allowed_origins = [o.strip() for o in _allowed.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace_router, prefix="/workspace", tags=["Workspace"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(index_router, prefix="/index", tags=["Index"])
app.include_router(model_router, prefix="/model", tags=["Model"])
app.include_router(fs_router, prefix="/fs", tags=["FileSystem"])
app.include_router(git_router, prefix="/git", tags=["Git"])

@app.get("/")
def read_root():
    return {"message": "PrivateCopilot API is running"}


@app.get("/health")
def health():
    import requests

    ollama_ok = False
    try:
        res = requests.get(f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/tags", timeout=2)
        ollama_ok = res.status_code == 200
    except Exception:  # noqa: BLE001
        ollama_ok = False

    deps = {}
    for mod in ("chromadb", "sentence_transformers", "fastapi", "uvicorn"):
        try:
            __import__(mod)
            deps[mod] = True
        except Exception:  # noqa: BLE001
            deps[mod] = False

    return {
        "status": "ok",
        "ollama": ollama_ok,
        "dependencies": deps,
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
