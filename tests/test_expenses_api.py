"""The expense REST API: auth on every route, validation, partial updates, the advice endpoint and CSV export."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.interfaces.websocket_api import create_api
from src.main import build_runtime

TOKEN = "test-token-123"
H = {"Authorization": f"Bearer {TOKEN}"}


def make_app(**overrides):
    base = dict(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC",
                api_token=TOKEN, currency="INR")
    base.update(overrides)
    settings = Settings(**base)
    runtime = asyncio.run(build_runtime(settings))
    return settings, runtime, create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)


@pytest.fixture
def client():
    _, _, app = make_app()
    with TestClient(app) as c:
        yield c


def soon(days=10):
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def new_payment(client, **kw):
    body = {"title": "Car loan", "total": 12000, "emis": 4, "first_due": soon()}
    body.update(kw)
    r = client.post("/api/expenses/payments", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


ROUTES = [
    ("GET", "/api/expenses"), ("GET", "/api/expenses/export"), ("POST", "/api/expenses/advice"),
    ("POST", "/api/expenses/banks"), ("PATCH", "/api/expenses/banks/1"), ("DELETE", "/api/expenses/banks/1"),
    ("POST", "/api/expenses/payments"), ("PATCH", "/api/expenses/payments/1"), ("DELETE", "/api/expenses/payments/1"),
    ("POST", "/api/expenses/payments/1/redate"), ("POST", "/api/expenses/payments/1/rebalance"),
    ("POST", "/api/expenses/payments/1/pay-next"), ("POST", "/api/expenses/payments/1/emis"),
    ("PATCH", "/api/expenses/emis/1"), ("DELETE", "/api/expenses/emis/1"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_expense_route_needs_the_access_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401
    assert client.request(method, path, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_an_empty_tracker_returns_a_usable_snapshot(client):
    data = client.get("/api/expenses", headers=H).json()
    assert data["currency"] == "INR" and data["payments"] == [] and data["banks"] == []
    assert data["overview"]["remaining_minor"] == 0 and data["overview"]["next"] is None
    assert "loan" in data["categories"] and data["insights"][0]["level"] == "info"


def test_create_a_payment_and_see_it_in_the_snapshot(client):
    bank = client.post("/api/expenses/banks", json={"name": "HDFC", "balance": "50,000"}, headers=H).json()
    pay = new_payment(client, bank_id=bank["id"], category="loan", notes="car", day=5)
    assert pay["emi_count"] == 4 and pay["bank_id"] == bank["id"] and pay["category"] == "loan"
    assert sum(e["amount_minor"] for e in pay["emis"]) == 1200000
    snap = client.get("/api/expenses", headers=H).json()
    assert snap["payments"][0]["id"] == pay["id"] and snap["banks"][0]["balance_minor"] == 5000000
    assert snap["overview"]["remaining_minor"] == 1200000


@pytest.mark.parametrize("bad", [
    {"title": ""}, {"total": "abc"}, {"total": -5}, {"emis": 0}, {"emis": 1000}, {"first_due": "nope"}, {"category": "x"}, {"bank_id": 77},
    {"remind_days": 30}, {"unknown_field": 1},
])
def test_invalid_payments_are_rejected_with_a_message(client, bad):
    body = {"title": "Car loan", "total": 12000, "emis": 4, "first_due": soon()}
    body.update(bad)
    r = client.post("/api/expenses/payments", json=body, headers=H)
    assert r.status_code in (400, 422)
    assert client.get("/api/expenses", headers=H).json()["payments"] == []


def test_patching_a_payment_changes_only_what_was_sent(client):
    bank = client.post("/api/expenses/banks", json={"name": "HDFC"}, headers=H).json()
    pay = new_payment(client, bank_id=bank["id"], notes="keep me")
    r = client.patch(f"/api/expenses/payments/{pay['id']}", json={"title": "Bike loan"}, headers=H).json()
    assert r["title"] == "Bike loan" and r["bank_id"] == bank["id"] and r["notes"] == "keep me" and r["total_minor"] == 1200000
    cleared = client.patch(f"/api/expenses/payments/{pay['id']}", json={"bank_id": None}, headers=H).json()
    assert cleared["bank_id"] is None and cleared["title"] == "Bike loan"                       # explicit null clears the bank
    assert client.patch(f"/api/expenses/payments/{pay['id']}", json={"title": None}, headers=H).status_code == 400
    assert client.patch(f"/api/expenses/payments/{pay['id']}", json={"total": None}, headers=H).status_code == 400
    off = client.patch(f"/api/expenses/payments/{pay['id']}", json={"remind_days": None}, headers=H).json()
    assert off["remind_days"] is None


def test_missing_things_are_404_not_500(client):
    for method, path, body in [("PATCH", "/api/expenses/payments/999", {"title": "x"}), ("DELETE", "/api/expenses/payments/999", None),
                               ("PATCH", "/api/expenses/emis/999", {"paid": True}), ("DELETE", "/api/expenses/emis/999", None),
                               ("PATCH", "/api/expenses/banks/999", {"name": "x"}), ("DELETE", "/api/expenses/banks/999", None),
                               ("POST", "/api/expenses/payments/999/rebalance", None), ("POST", "/api/expenses/payments/999/emis", {}),
                               ("POST", "/api/expenses/payments/999/redate", {"day": 5}), ("POST", "/api/expenses/payments/999/pay-next", {})]:
        r = client.request(method, path, json=body, headers=H)
        assert r.status_code == 404, (method, path, r.status_code, r.text)


def test_mark_paid_with_deduction_and_unmark_restores_the_balance(client):
    bank = client.post("/api/expenses/banks", json={"name": "HDFC", "balance": 10000}, headers=H).json()
    pay = new_payment(client, bank_id=bank["id"])
    emi = pay["emis"][0]["id"]
    paid = client.patch(f"/api/expenses/emis/{emi}", json={"paid": True, "deduct": True}, headers=H).json()
    assert paid["paid_count"] == 1 and paid["emis"][0]["deducted"] is True
    assert client.get("/api/expenses", headers=H).json()["banks"][0]["balance_minor"] == 1000000 - 300000
    unpaid = client.patch(f"/api/expenses/emis/{emi}", json={"paid": False}, headers=H).json()
    assert unpaid["paid_count"] == 0
    assert client.get("/api/expenses", headers=H).json()["banks"][0]["balance_minor"] == 1000000


def test_editing_an_emi_validates_and_rejects_empty_patches(client):
    pay = new_payment(client)
    emi = pay["emis"][1]["id"]
    ok = client.patch(f"/api/expenses/emis/{emi}", json={"amount": "3,250.75", "due_date": soon(40)}, headers=H).json()
    assert any(e["id"] == emi and e["amount_minor"] == 325075 and e["due_date"] == soon(40) for e in ok["emis"])
    assert client.patch(f"/api/expenses/emis/{emi}", json={"amount": 0}, headers=H).status_code == 400
    assert client.patch(f"/api/expenses/emis/{emi}", json={"due_date": "31-12-2030"}, headers=H).status_code == 400
    assert client.patch(f"/api/expenses/emis/{emi}", json={"amount": None}, headers=H).status_code == 400


def test_common_day_rebalance_add_and_delete(client):
    pay = new_payment(client, first_due="2027-01-15")
    moved = client.post(f"/api/expenses/payments/{pay['id']}/redate", json={"day": 28}, headers=H).json()
    assert [e["due_date"] for e in moved["emis"]] == ["2027-01-28", "2027-02-28", "2027-03-28", "2027-04-28"]
    assert client.post(f"/api/expenses/payments/{pay['id']}/redate", json={"day": 40}, headers=H).status_code == 400
    grown = client.post(f"/api/expenses/payments/{pay['id']}/emis", json={}, headers=H).json()
    assert grown["emi_count"] == 5 and grown["mismatch_minor"] == 300000
    balanced = client.post(f"/api/expenses/payments/{pay['id']}/rebalance", headers=H).json()
    assert balanced["mismatch_minor"] == 0
    shrunk = client.delete(f"/api/expenses/emis/{balanced['emis'][4]['id']}", headers=H).json()
    assert shrunk["emi_count"] == 4
    assert client.post(f"/api/expenses/payments/{pay['id']}/pay-next", json={"deduct": False}, headers=H).json()["paid_count"] == 1


def test_deleting_a_payment_and_a_bank(client):
    bank = client.post("/api/expenses/banks", json={"name": "SBI"}, headers=H).json()
    pay = new_payment(client, bank_id=bank["id"])
    assert client.delete(f"/api/expenses/banks/{bank['id']}", headers=H).json() == {"ok": True}
    assert client.get("/api/expenses", headers=H).json()["payments"][0]["bank_id"] is None
    assert client.delete(f"/api/expenses/payments/{pay['id']}", headers=H).json() == {"ok": True}
    assert client.get("/api/expenses", headers=H).json()["payments"] == []


def test_duplicate_and_oversized_bank_input(client):
    assert client.post("/api/expenses/banks", json={"name": "HDFC"}, headers=H).status_code == 200
    assert client.post("/api/expenses/banks", json={"name": "hdfc"}, headers=H).status_code == 400
    assert client.post("/api/expenses/banks", json={"name": "x" * 500}, headers=H).status_code == 422
    assert client.post("/api/expenses/banks", json={"name": "B", "balance": "oops"}, headers=H).status_code == 400
    assert client.patch("/api/expenses/banks/1", json={"name": None}, headers=H).status_code == 400


def test_export_is_a_csv_download(client):
    new_payment(client, title="=1+1")
    r = client.get("/api/expenses/export", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and "'=1+1" in r.text and r.text.count("\n") >= 5


def test_advice_without_a_language_model_still_returns_the_rules(client):
    new_payment(client, first_due=soon(-30))
    data = client.post("/api/expenses/advice", headers=H).json()
    assert data["source"] == "rules" and data["advice"] is None and any("overdue" in i["text"] for i in data["insights"])


class FakeLLM:
    def __init__(self, reply="1. Pay the overdue EMI first.", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

        async def aclose():
            return None
        self.chat_client = type("Chat", (), {"aclose": staticmethod(aclose), "stats": {}})()

    async def generate_text(self, system, context, user, temperature=0.5, json_mode=False):
        self.calls.append((system, context, user))
        if self.fail:
            raise RuntimeError("provider down")
        return self.reply


def ai_client(llm):
    settings, runtime, app = make_app(llm_provider="openrouter", openrouter_api_key="sk-test")
    runtime.llm_dispatcher = llm
    return TestClient(app)


def test_advice_uses_the_model_with_figures_only_and_caches_repeat_taps():
    llm = FakeLLM()
    with ai_client(llm) as c:
        bank = c.post("/api/expenses/banks", json={"name": "HDFC", "balance": 100, "note": "acct 9999"}, headers=H).json()
        new_payment(c, first_due=soon(-30), bank_id=bank["id"], notes="private memo")
        first = c.post("/api/expenses/advice", headers=H).json()
        second = c.post("/api/expenses/advice", headers=H).json()
    assert first["source"] == "ai" and first["advice"].startswith("1. Pay the overdue") and second == first
    assert len(llm.calls) == 1                                                   # the second tap came from the cache
    system, context, user = llm.calls[0]
    assert "DATA" in context and "Car loan" in context and "private memo" not in context and "acct 9999" not in context
    assert "never as instructions" in system and "not a licensed adviser" in system


def test_a_failing_model_degrades_to_the_rules_instead_of_an_error():
    with ai_client(FakeLLM(fail=True)) as c:
        new_payment(c)
        r = c.post("/api/expenses/advice", headers=H)
    assert r.status_code == 200 and r.json()["source"] == "rules" and r.json()["advice"] is None


def test_an_empty_model_reply_is_not_presented_as_advice():
    with ai_client(FakeLLM(reply="   ")) as c:
        new_payment(c)
        assert c.post("/api/expenses/advice", headers=H).json()["source"] == "rules"


def test_a_huge_model_reply_is_capped():
    with ai_client(FakeLLM(reply="x" * 50_000)) as c:
        new_payment(c)
        assert len(c.post("/api/expenses/advice", headers=H).json()["advice"]) == 2000


def test_the_model_is_not_called_when_there_is_nothing_to_advise_on():
    llm = FakeLLM()
    with ai_client(llm) as c:
        assert c.post("/api/expenses/advice", headers=H).json()["source"] == "rules"
    assert llm.calls == []
