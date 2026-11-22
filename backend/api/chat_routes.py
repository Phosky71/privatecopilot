
from core.llm import llm_client
from core.logging_config import logger
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.workspace_service import workspace_service

from api.schemas import ChatHistoryMessage

router = APIRouter()


class ChatRequest(BaseModel):
    workspace_id: str
    query: str
    history: list[ChatHistoryMessage] | None = None


@router.post("/")
def chat(request: ChatRequest):
    try:
        history = [m.model_dump() for m in request.history] if request.history else None
        if history is None:
            history = workspace_service.get_chat_history(request.workspace_id)
        response = llm_client.generate(request.workspace_id, request.query, history=history)
        if response:
            workspace_service.append_chat_turn(request.workspace_id, request.query, response)
        return {"response": response}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
def chat_stream(request: ChatRequest):
    history = [m.model_dump() for m in request.history] if request.history else None
    if history is None:
        history = workspace_service.get_chat_history(request.workspace_id)

    def generator():
        assistant_parts: list[str] = []
        errored = False
        for chunk in llm_client.generate_stream(request.workspace_id, request.query, history=history):
            yield chunk
            # Collect assistant text for persistence.
            try:
                import json

                payload = chunk
                payload = payload.removeprefix("data: ")
                data = json.loads(payload)
                if "error" in data:
                    errored = True
                elif data.get("response"):
                    assistant_parts.append(data["response"])
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to persist chat turn: %s", e)

        assistant_message = "".join(assistant_parts)
        if assistant_message and not errored:
            try:
                workspace_service.append_chat_turn(request.workspace_id, request.query, assistant_message)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to persist chat turn: %s", e)

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/history")
def get_history(workspace_id: str = Query(...)):
    try:
        messages = workspace_service.get_chat_history(workspace_id)
        return {"messages": messages}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/history")
def clear_history(workspace_id: str = Query(...)):
    try:
        workspace_service.clear_chat_history(workspace_id)
        return {"status": "success"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
