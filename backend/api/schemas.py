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
    repo_path: str | None = None

class GitConfigRequest(BaseModel):
    git_init_policy: Literal["ask", "auto", "never"]

class GitInitRequest(BaseModel):
    workspace_id: str
    repo_path: str | None = None

class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ProviderCreateRequest(BaseModel):
    name: str
    provider_type: Literal["ollama", "openai_compatible", "anthropic"]
    base_url: str
    api_key: str | None = None
    models: list[str] = []
    enabled: bool = True

class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    provider_type: Literal["ollama", "openai_compatible", "anthropic"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    enabled: bool | None = None
    clear_api_key: bool = False
