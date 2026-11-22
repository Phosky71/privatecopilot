from core.indexer import indexer
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class IndexWorkspaceRequest(BaseModel):
    workspace_id: str


@router.post("/")
def index_workspace(request: IndexWorkspaceRequest):
    try:
        result = indexer.index_workspace(request.workspace_id)
        return result
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start", status_code=202)
def start_index(request: IndexWorkspaceRequest):
    try:
        snapshot = indexer.start_indexing_job(request.workspace_id)
        return snapshot
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def index_status(workspace_id: str = Query(...)):
    try:
        return indexer.get_progress(workspace_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
def index_stream(workspace_id: str = Query(...)):
    def generator():
        for snapshot in indexer.iter_progress(workspace_id):
            import json

            yield f"data: {json.dumps(snapshot)}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")
