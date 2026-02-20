"""UI to core integration tests (REST + WebSocket paths)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.interfaces.websocket_api import create_api
from src.main import build_runtime


def _build_test_app():
    settings = Settings.from_env()
    settings.llm_provider = "mock"
    settings.sqlite_path = ":memory:"
    runtime = asyncio.run(build_runtime(settings=settings))
    return create_api(runtime.orchestrator, settings, runtime.health_checker)


def test_chat_endpoint_to_core_tools():
    app = _build_test_app()
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"session_id": "ui-chat-session", "message": "create account savings with 1000"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "ui-chat-session"
        assert body["action_type"] in {"tool", "respond", "clarify"}
        assert isinstance(body["response"], str) and len(body["response"]) > 0


def test_websocket_endpoint_to_core_tools():
    app = _build_test_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui-ws-session") as ws:
            ws.send_text("show accounts")
            payload = ws.receive_json()
            assert "text" in payload
            assert "action_type" in payload
            assert "tool" in payload
            assert isinstance(payload["text"], str)


def test_websocket_stream_endpoint():
    app = _build_test_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws-stream/ui-stream-session") as ws:
            ws.send_text("hello")
            seen_complete = False
            for _ in range(50):
                msg = ws.receive_json()
                if msg.get("type") == "complete":
                    seen_complete = True
                    break
            assert seen_complete
