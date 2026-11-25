"""Data export: complete, readable, and never carrying a secret. All data here is invented."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.agent import export as data_export
from src.agent import graph
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore

SECRETS = {"telegram_token": "999999:" + "T" * 30, "vapid_private_key": "VAPID-" + "K" * 40, "telegram_pair": "PAIR-" + "P" * 12, "vision:2026-11-25": "424242"}


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


async def fill(store):
    now = "2026-11-25T00:00:00+00:00"
    await store.execute("INSERT INTO memories (content, category, created_at) VALUES ('likes tea', 'preference', ?)", (now,))
    await store.execute("INSERT INTO notes (title, body, tags, created_at, updated_at, space, kind) VALUES ('t', 'a lesson', '', ?, ?, 'growth', 'lesson')", (now, now))
    await store.execute("INSERT INTO episodes (session_id, timestamp, user_text, assistant_text, emotional_state) VALUES ('s', ?, 'hello', 'hi', 'neutral')", (now,))
    await graph.link(store, "Zorya", "works at", "Quillon Labs")
    for key, value in SECRETS.items():
        await store.execute("INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?)", (key, value, now))
    await store.execute("INSERT INTO app_settings (id, value, updated_at) VALUES ('ex_budget', '3000000', ?)", (now,))
    await store.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES ('https://push.example/abc', 'P256KEY', 'AUTHKEY', ?)", (now,))


async def test_export_contains_the_users_data_with_counts(store):
    await fill(store)
    out = await data_export.build(store, Settings(llm_provider="mock", sqlite_path=":memory:", currency="INR"))
    assert out["app"] == "TAPAN_AI" and out["format"] == 1 and out["currency"] == "INR"
    t = out["tables"]
    assert t["memories"][0]["content"] == "likes tea" and t["notes"][0]["body"] == "a lesson" and t["episodes"][0]["user_text"] == "hello"
    assert {n["name"] for n in t["kg_nodes"]} == {"Zorya", "Quillon Labs"} and len(t["kg_edges"]) == 1
    assert out["counts"]["memories"] == 1 and out["counts"]["kg_edges"] == 1
    assert [s["id"] for s in t["settings"]] == ["ex_budget"]
    json.dumps(out)                                                                   # must be serialisable as is


async def test_no_secret_ever_reaches_the_export(store):
    await fill(store)
    text = json.dumps(await data_export.build(store, Settings(llm_provider="mock", sqlite_path=":memory:")))
    for value in list(SECRETS.values()) + ["P256KEY", "AUTHKEY", "https://push.example/abc"]:
        assert value not in text
    assert "push_subscriptions" not in text and "telegram" not in text


async def test_only_listed_tables_are_exported(store):
    out = await data_export.build(store, Settings(llm_provider="mock", sqlite_path=":memory:"))
    assert set(out["tables"]) == set(data_export.TABLES) | {"settings"}
    assert not any(name.startswith("bak_") or "subscription" in name for name in out["tables"] if name != "ex_subs")


TOKEN = "test-token-123"


@pytest.fixture
def client():
    import asyncio

    from src.interfaces.websocket_api import create_api
    from src.main import build_runtime

    cfg = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC", api_token=TOKEN)
    runtime = asyncio.run(build_runtime(cfg))
    with TestClient(create_api(runtime.orchestrator, cfg, runtime.health_checker, runtime=runtime)) as c:
        yield c


def test_the_export_route_needs_the_access_token(client):
    assert client.get("/api/export").status_code == 401
    assert client.get("/api/export", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.get("/api/export", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200 and ok.json()["format"] == 1 and "tables" in ok.json()
