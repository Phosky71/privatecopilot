from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from services.git_service import (
    GitInitDisabledError,
    GitInitRequiredError,
    git_service,
)
from services.workspace_service import workspace_service

from api.schemas import GitApplyRequest, GitConfigRequest, GitInitRequest

router = APIRouter()


@router.get("/status")
def get_git_status(workspace_id: str):
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    return git_service.get_status(workspace_id)


@router.get("/config")
def get_git_config():
    return {"git_init_policy": workspace_service.get_git_init_policy()}


@router.post("/config")
def set_git_config(request: GitConfigRequest):
    try:
        policy = workspace_service.set_git_init_policy(request.git_init_policy)
        return {"git_init_policy": policy}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/init")
def init_git(request: GitInitRequest):
    policy = workspace_service.get_git_init_policy()
    if policy == "never":
        raise HTTPException(status_code=400, detail="Git initialization is disabled by policy.")
    try:
        repo_path = git_service._get_repo_path(request.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    git_service.init_repo_if_needed(repo_path)
    return git_service.get_status(request.workspace_id)


@router.post("/apply")
def apply_git_edit(request: GitApplyRequest):
    try:
        branch = git_service.apply_edit_and_commit(
            request.workspace_id,
            request.file_path,
            request.original,
            request.replacement,
            confirm_git_init=request.confirm_git_init,
        )
        return {"status": "success", "branch": branch}
    except GitInitRequiredError as e:
        return JSONResponse(
            status_code=409,
            content={"detail": str(e), "code": "GIT_INIT_REQUIRED"},
        )
    except GitInitDisabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        msg = str(e)
        if "outside the repository" in msg:
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
