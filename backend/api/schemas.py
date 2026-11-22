from typing import Literal

from pydantic import BaseModel


class OpenWorkspaceRequest(BaseModel):
    folder_path: str
    name: str | None = None

class CreateWorkspaceRequest(BaseModel):
    name: str

class AddFolderRequest(BaseModel):
    workspace_id: str
    folder_path: str
    
class SwitchWorkspaceRequest(BaseModel):
    workspace_id: str

class UpdateWorkspaceRequest(BaseModel):
    workspace_id: str
    name: str

class FileRequest(BaseModel):
    workspace_id: str
    file_path: str

class RemoveFolderRequest(BaseModel):
    workspace_id: str
    folder_path: str



class SetModelRequest(BaseModel):
    model_id: str
    workspace_id: str | None = None

class GitApplyRequest(BaseModel):
    workspace_id: str
    file_path: str
    original: str
    replacement: str
    confirm_git_init: bool = False

class GitConfigRequest(BaseModel):
    git_init_policy: Literal["ask", "auto", "never"]

class GitInitRequest(BaseModel):
    workspace_id: str
