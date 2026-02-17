"""FastAPI REST + WebSocket interface."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from tapan_ai.config.settings import Settings
from tapan_ai.core.orchestrator import Orchestrator
from tapan_ai.models import ChatRequest, ChatResponse, model_dump_compat


def create_api(orchestrator: Orchestrator, settings: Settings) -> FastAPI:
    app = FastAPI(title=settings.app_name)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        result = await orchestrator.handle_user_input(session_id=req.session_id, user_text=req.message)
        return ChatResponse(
            session_id=result.session_id,
            response=result.text,
            action_type=result.action_type,
            tool_used=result.tool_used,
            emotional_state=result.emotional_state,
        )

    @app.websocket("/ws/{session_id}")
    async def websocket_chat(ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        try:
            while True:
                text = await ws.receive_text()
                result = await orchestrator.handle_user_input(session_id=session_id, user_text=text)
                payload = model_dump_compat(result)
                await ws.send_json(payload)
        except WebSocketDisconnect:
            return

    return app

