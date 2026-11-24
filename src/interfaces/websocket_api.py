"""FastAPI REST + WebSocket interface."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from src.config.settings import Settings
from src.core.orchestrator import Orchestrator
from src.core.health_check import HealthChecker
from src.llm.streaming import stream_text
from src.models import ChatRequest, ChatResponse, model_dump_compat


def create_api(orchestrator: Orchestrator, settings: Settings, health_checker: HealthChecker | None = None) -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount("/web", StaticFiles(directory="web"), name="web")

    @app.get("/")
    async def root():
        return RedirectResponse(url="/web/index.html")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        if health_checker:
            return await health_checker.check_health()
        return {"status": "ok", "app": settings.app_name}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        if health_checker:
            return await health_checker.check_readiness()
        return {"ready": True}

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
                
                # Send structured response
                await ws.send_json(jsonable_encoder({
                    "text": result.text,
                    "action_type": result.action_type,
                    "tool": result.tool_used,
                    "emotion": result.emotional_state,
                    "debug": result.debug,
                }))
        except WebSocketDisconnect:
            return

    @app.websocket("/ws-stream/{session_id}")
    async def websocket_stream(ws: WebSocket, session_id: str) -> None:
        """WebSocket endpoint with streaming LLM responses."""
        await ws.accept()
        try:
            while True:
                text = await ws.receive_text()
                
                # For streaming, we need to modify orchestrator to support streaming
                # For now, stream the final response in chunks
                result = await orchestrator.handle_user_input(session_id=session_id, user_text=text)
                
                # Stream response in chunks
                async for chunk in stream_text(result.text, chunk_size=settings.stream_chunk_size):
                    await ws.send_json(jsonable_encoder({
                        "type": "chunk",
                        "content": chunk,
                    }))
                
                # Send final metadata
                await ws.send_json(jsonable_encoder({
                    "type": "complete",
                    "action_type": result.action_type,
                    "tool": result.tool_used,
                    "emotion": result.emotional_state,
                }))
        except WebSocketDisconnect:
            return

    return app
