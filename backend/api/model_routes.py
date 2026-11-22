
from core.llm import llm_client
from core.providers import provider_store
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.schemas import ProviderCreateRequest, ProviderUpdateRequest, SetModelRequest

router = APIRouter()


class ProviderTestRequest(BaseModel):
    id: str | None = None
    name: str | None = None
    provider_type: str
    base_url: str
    api_key: str | None = None
    models: list[str] = []


@router.get("/")
def get_models():
    return llm_client.get_models_config()


@router.get("/current")
def get_current_model(workspace_id: str | None = None):
    model_name, source = llm_client.resolve_model_details(workspace_id)
    return {
        "workspace_id": workspace_id,
        "selected_model": model_name,
        "source": source,
    }


@router.post("/set")
def set_model(request: SetModelRequest):
    model_id = request.model_id
    workspace_id = request.workspace_id
    try:
        from services.workspace_service import workspace_service

        if workspace_id:
            workspace_service.update_model(workspace_id, model_id)
            active_model_str = model_id
        else:
            active_model_str = llm_client.set_active_model(model_id)
            workspace_service.set_active_model_id(model_id)

        return {
            "status": "ok",
            "active_model": active_model_str,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


# Provider management endpoints
@router.get("/providers")
def list_providers():
    return {"providers": provider_store.list_sanitized(), "local_status": llm_client.get_models_config().get("providers_status", [])}


@router.post("/providers")
def create_provider(req: ProviderCreateRequest):
    item = provider_store.create(req.model_dump())
    return {"provider": provider_store.list_sanitized() and next((p for p in provider_store.list_sanitized() if p["id"] == item["id"]), None)}


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, req: ProviderUpdateRequest):
    updated = provider_store.update(provider_id, req.model_dump(exclude_unset=True), clear_api_key=req.clear_api_key)
    if not updated:
        raise HTTPException(status_code=404, detail="Provider not found")
    sanitized = next((p for p in provider_store.list_sanitized() if p["id"] == provider_id), None)
    return {"provider": sanitized}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str):
    ok = provider_store.delete(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"status": "success"}


@router.post("/providers/test")
def test_provider(req: ProviderTestRequest):
    data = req.model_dump()
    return provider_store.test_connection(data)
