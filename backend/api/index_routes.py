from core.indexer import indexer
from fastapi import APIRouter, HTTPException
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
