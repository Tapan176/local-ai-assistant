"""REST routes added with spending, subscriptions, payment kinds, groups, bulk paid and fixed EMI amounts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_expenses_api import FakeLLM, H, ai_client, make_app, new_payment, soon


@pytest.fixture
def client():
    _, _, app = make_app()
    with TestClient(app) as c:
        yield c


NEW_ROUTES = [
    ("GET", "/api/expenses/spending"), ("POST", "/api/expenses/spending"), ("PATCH", "/api/expenses/spending/1"), ("DELETE", "/api/expenses/spending/1"),
    ("PUT", "/api/expenses/budget"), ("GET", "/api/expenses/spending-export"),
    ("GET", "/api/expenses/subscriptions"), ("POST", "/api/expenses/subscriptions"), ("PATCH", "/api/expenses/subscriptions/1"),
    ("DELETE", "/api/expenses/subscriptions/1"), ("POST", "/api/expenses/subscriptions/1/renew"), ("POST", "/api/expenses/emis/bulk"),
]


@pytest.mark.parametrize("method,path", NEW_ROUTES)
def test_every_new_route_needs_the_access_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401
    assert client.request(method, path, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401


# ── payments: kinds, auto-total, groups, fixed amounts ───────────────────
def test_create_with_an_emi_amount_computes_the_total(client):
    r = client.post("/api/expenses/payments", json={"title": "Phone", "emi_amount": "1234.50", "emis": 4, "first_due": soon()}, headers=H)
    assert r.status_code == 200 and r.json()["total_minor"] == 123450 * 4
    bad = client.post("/api/expenses/payments", json={"title": "Phone", "total": 5000, "emi_amount": 1000, "emis": 4, "first_due": soon()}, headers=H)
    assert bad.status_code == 400 and "don't match" in bad.json()["detail"]
    none = client.post("/api/expenses/payments", json={"title": "Phone", "emis": 4, "first_due": soon()}, headers=H)
    assert none.status_code == 400 and "total amount" in none.json()["detail"]


def test_due_and_open_payments_over_the_api_and_the_snapshot_shows_them(client):
    due = client.post("/api/expenses/payments", json={"title": "Card min due", "kind": "due", "emi_amount": 800, "total": 9000, "first_due": soon(4), "grp": "Cards"}, headers=H).json()
    owe = client.post("/api/expenses/payments", json={"title": "Owe Rahul", "kind": "open", "total": 2500, "grp": "Personal"}, headers=H).json()
    assert due["kind"] == "due" and due["emi_count"] == 1 and owe["kind"] == "open" and owe["emis"] == []
    snap = client.get("/api/expenses", headers=H).json()
    assert snap["overview"]["open"] == {"count": 1, "amount_minor": 250000} and snap["overview"]["due_30"]["amount_minor"] == 80000
    assert {g["label"] for g in snap["groups"]} == {"Cards", "Personal"}
    part = client.patch(f"/api/expenses/payments/{owe['id']}", json={"open_paid": 1000}, headers=H).json()
    assert part["remaining_minor"] == 150000
    done = client.patch(f"/api/expenses/payments/{owe['id']}", json={"settled": True}, headers=H).json()
    assert done["finished"] is True
    nope = client.patch(f"/api/expenses/payments/{due['id']}", json={"settled": True}, headers=H)
    assert nope.status_code == 400
    assert client.patch(f"/api/expenses/payments/{owe['id']}", json={"settled": None}, headers=H).status_code == 400     # an explicit null is not a value


def test_the_group_filter_is_a_query_parameter(client):
    new_payment(client, title="Home loan", total=60000, emis=12, grp="Home loan")
    new_payment(client, title="Phone", total=12000, emis=6)
    full = client.get("/api/expenses", headers=H).json()
    cut = client.get("/api/expenses", params={"exclude": "Home loan"}, headers=H).json()
    assert cut["overview"]["remaining_minor"] == full["overview"]["remaining_minor"] - 6000000
    assert cut["hidden"]["payments"] == 1 and cut["excluded"] == ["home loan"]
    assert client.get("/api/expenses", params={"exclude": "x" * 5000}, headers=H).status_code == 200      # absurd input is truncated, not an error


def test_spreading_over_the_api_keeps_a_fixed_emi_and_reset_replaces_it(client):
    pay = new_payment(client, total=10000, emis=4)
    last = pay["emis"][-1]["id"]
    edited = client.patch(f"/api/expenses/emis/{last}", json={"amount": 1000}, headers=H).json()
    assert edited["emis"][-1]["custom"] is True
    spread = client.post(f"/api/expenses/payments/{pay['id']}/rebalance", headers=H).json()             # no body: still valid
    assert spread["emis"][-1]["amount_minor"] == 100000 and spread["mismatch_minor"] == 0
    unlocked = client.patch(f"/api/expenses/emis/{last}", json={"custom": False}, headers=H).json()
    assert unlocked["emis"][-1]["custom"] is False and unlocked["emis"][-1]["amount_minor"] == 100000
    client.patch(f"/api/expenses/emis/{last}", json={"custom": True}, headers=H)
    reset = client.post(f"/api/expenses/payments/{pay['id']}/rebalance", json={"reset": True}, headers=H).json()
    assert [e["amount_minor"] for e in reset["emis"]] == [250000] * 4
    assert client.post(f"/api/expenses/payments/{pay['id']}/rebalance", json={"reset": "maybe"}, headers=H).status_code == 422
    assert client.post(f"/api/expenses/payments/{pay['id']}/rebalance", json={"extra": 1}, headers=H).status_code == 422


def test_bulk_mark_paid_and_unpaid(client):
    bank = client.post("/api/expenses/banks", json={"name": "SBI", "balance": 10000}, headers=H).json()
    pay = new_payment(client, total=4000, emis=4, bank_id=bank["id"])
    ids = [e["id"] for e in pay["emis"][:3]]
    r = client.post("/api/expenses/emis/bulk", json={"ids": ids, "paid": True, "deduct": True}, headers=H)
    assert r.status_code == 200 and r.json() == {"changed": 3, "skipped": 0}
    snap = client.get("/api/expenses", headers=H).json()
    assert snap["payments"][0]["paid_count"] == 3 and snap["banks"][0]["balance_minor"] == 1000000 - 300000
    client.post("/api/expenses/emis/bulk", json={"ids": ids, "paid": False}, headers=H)
    assert client.get("/api/expenses", headers=H).json()["banks"][0]["balance_minor"] == 1000000          # restored exactly
    assert client.post("/api/expenses/emis/bulk", json={"ids": []}, headers=H).status_code == 400
    assert client.post("/api/expenses/emis/bulk", json={"ids": [999999]}, headers=H).status_code == 404
    assert client.post("/api/expenses/emis/bulk", json={"ids": list(range(500))}, headers=H).status_code == 422
    assert client.post("/api/expenses/emis/bulk", json={"ids": ["x"]}, headers=H).status_code == 422


# ── spending ───────────────────────────────────────────────────────────
def test_spending_over_the_api(client):
    a = client.post("/api/expenses/spending", json={"amount": "250.5", "category": "food", "note": "lunch"}, headers=H)
    assert a.status_code == 200 and a.json()["amount_minor"] == 25050
    client.post("/api/expenses/spending", json={"amount": 100, "category": "travel"}, headers=H)
    data = client.get("/api/expenses/spending", headers=H).json()
    assert len(data["items"]) == 2 and data["summary"]["total_minor"] == 35050 and "food" in data["categories"]
    assert len(client.get("/api/expenses/spending", params={"category": "food"}, headers=H).json()["items"]) == 1
    assert client.get("/api/expenses/spending", params={"month": "nope"}, headers=H).status_code == 400
    edited = client.patch(f"/api/expenses/spending/{a.json()['id']}", json={"amount": 300}, headers=H)
    assert edited.json()["amount_minor"] == 30000
    assert client.patch(f"/api/expenses/spending/{a.json()['id']}", json={"amount": None}, headers=H).status_code == 400
    assert client.delete(f"/api/expenses/spending/{a.json()['id']}", headers=H).json() == {"ok": True}
    assert client.delete(f"/api/expenses/spending/{a.json()['id']}", headers=H).status_code == 404
    assert client.post("/api/expenses/spending", json={"amount": 0}, headers=H).status_code == 400
    assert client.post("/api/expenses/spending", json={"amount": 5, "bogus": 1}, headers=H).status_code == 422
    csv = client.get("/api/expenses/spending-export", headers=H)
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0] == "date,amount,category,note"


def test_budget_and_the_overview_card(client):
    assert client.put("/api/expenses/budget", json={"amount": 5000}, headers=H).json() == {"budget_minor": 500000}
    client.post("/api/expenses/spending", json={"amount": 6000}, headers=H)
    snap = client.get("/api/expenses", headers=H).json()
    assert snap["spending"]["spent_minor"] == 600000 and snap["spending"]["budget_left_minor"] == -100000
    assert any("over your" in i["text"] for i in snap["insights"])
    assert client.put("/api/expenses/budget", json={"amount": None}, headers=H).json() == {"budget_minor": None}
    assert client.put("/api/expenses/budget", json={"amount": "lots"}, headers=H).status_code == 400


# ── subscriptions ──────────────────────────────────────────────────────
def test_subscriptions_over_the_api(client):
    r = client.post("/api/expenses/subscriptions", json={"name": "Netflix", "amount": 649, "next_date": soon(3), "category": "entertainment"}, headers=H)
    assert r.status_code == 200
    sub = r.json()
    listing = client.get("/api/expenses/subscriptions", headers=H).json()
    assert listing["summary"]["monthly_minor"] == 64900 and listing["subs"][0]["status"] == "soon"
    renewed = client.post(f"/api/expenses/subscriptions/{sub['id']}/renew", headers=H).json()      # no body: record the charge
    assert renewed["next_date"] > sub["next_date"]
    assert client.get("/api/expenses/spending", headers=H).json()["summary"]["total_minor"] in (64900, 0)   # booked in the month of the charge
    paused = client.patch(f"/api/expenses/subscriptions/{sub['id']}", json={"active": False}, headers=H).json()
    assert paused["status"] == "paused"
    assert client.post(f"/api/expenses/subscriptions/{sub['id']}/renew", headers=H).status_code == 400
    assert client.patch(f"/api/expenses/subscriptions/{sub['id']}", json={"name": None}, headers=H).status_code == 400
    assert client.patch(f"/api/expenses/subscriptions/{sub['id']}", json={"remind_days": None}, headers=H).status_code == 200     # null is meaningful here: no reminder
    assert client.delete(f"/api/expenses/subscriptions/{sub['id']}", headers=H).json() == {"ok": True}
    assert client.delete(f"/api/expenses/subscriptions/{sub['id']}", headers=H).status_code == 404
    bad = client.post("/api/expenses/subscriptions", json={"name": "X", "amount": 5, "cycle": "daily"}, headers=H)
    assert bad.status_code == 400 and "billing cycle" in bad.json()["detail"]


def test_a_subscription_cannot_name_someone_elses_bank(client):
    r = client.post("/api/expenses/subscriptions", json={"name": "X", "amount": 5, "bank_id": 4242}, headers=H)
    assert r.status_code == 400 and "bank" in r.json()["detail"].lower()


# ── advice sees spending and subscription figures, never notes ───────────
def test_advice_includes_spending_and_subscription_figures_but_not_notes():
    llm = FakeLLM()
    with ai_client(llm) as c:
        c.post("/api/expenses/spending", json={"amount": 750, "category": "food", "note": "dinner with my secret client"}, headers=H)
        c.post("/api/expenses/subscriptions", json={"name": "Netflix", "amount": 649, "next_date": soon(9), "notes": "shared password hint"}, headers=H)
        data = c.post("/api/expenses/advice", headers=H).json()
    assert data["source"] == "ai" and len(llm.calls) == 1
    context = llm.calls[0][1]
    assert "spending_this_month" in context and '"food"' in context and "Netflix" in context and "649" in context
    assert "secret client" not in context and "password hint" not in context
    assert any("subscription" in i["text"] for i in data["insights"])


def test_advice_is_rules_only_with_no_data_at_all():
    llm = FakeLLM()
    with ai_client(llm) as c:
        data = c.post("/api/expenses/advice", headers=H).json()
    assert data["source"] == "rules" and llm.calls == []
