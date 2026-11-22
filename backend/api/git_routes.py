from fastapi import APIRouter, HTTPException
from services.git_service import git_service

from api.schemas import GitApplyRequest

router = APIRouter()

@router.get("/status")
def get_git_status(workspace_id: str):
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    return git_service.get_status(workspace_id)

@router.post("/apply")
def apply_git_edit(request: GitApplyRequest):
    try:
        branch = git_service.apply_edit_and_commit(
            request.workspace_id,
            request.file_path,
            request.original,
            request.replacement
        )
        return {"status": "success", "branch": branch}
    except ValueError as e:
        msg = str(e)
        if "outside the repository" in msg:
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
