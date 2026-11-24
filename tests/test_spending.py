"""Day-to-day spending and subscriptions: the ledger, month summaries, budget, renewals without date drift, reminders."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.agent import expenses, spending, timeutil
from src.agent.expenses import ExpenseError, NotFound
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone="Asia/Kolkata", currency="INR")


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


def today(settings) -> date:
    return timeutil.now(settings).date()


def day(settings, n: int) -> str:
    return (today(settings) + timedelta(days=n)).isoformat()


# ── ledger ─────────────────────────────────────────────────────────────
async def test_add_edit_delete_a_spend(store, settings):
    row = await spending.add_spend(store, settings, amount="250.50", category="food", note="  lunch   with team ")
    assert row["amount_minor"] == 25050 and row["spent_on"] == day(settings, 0) and row["note"] == "lunch with team"
    row = await spending.update_spend(store, settings, row["id"], amount=300, category="groceries")
    assert row["amount_minor"] == 30000 and row["category"] == "groceries"
    await spending.delete_spend(store, row["id"])
    with pytest.raises(NotFound):
        await spending.update_spend(store, settings, row["id"], amount=1)


@pytest.mark.parametrize("kwargs,message", [
    ({"amount": 0}, "more than zero"), ({"amount": "abc"}, "must be a number"), ({"amount": -5}, "cannot be negative"),
    ({"amount": 10, "category": "yachts"}, "category must be one of"), ({"amount": 10, "spent_on": "2999-01-01"}, "in the future"),
    ({"amount": 10, "spent_on": "1999-01-01"}, "too far in the past"), ({"amount": 10, "spent_on": "yesterday"}, "real date"),
    ({"amount": 10, "note": "x" * 201}, "too long"),
])
async def test_bad_spends_are_refused_with_a_reason(store, settings, kwargs, message):
    with pytest.raises(ExpenseError, match=message):
        await spending.add_spend(store, settings, **kwargs)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_spend"))["n"] == 0


async def test_month_summary_totals_categories_comparison_and_projection(store, settings):
    t = today(settings)
    first = t.replace(day=1)
    prev_month_day = (first - timedelta(days=1)).replace(day=1)
    await spending.add_spend(store, settings, amount=1000, spent_on=first.isoformat(), category="food")
    await spending.add_spend(store, settings, amount=500, spent_on=first.isoformat(), category="food")
    await spending.add_spend(store, settings, amount=1500, spent_on=first.isoformat(), category="transport")
    await spending.add_spend(store, settings, amount=2000, spent_on=prev_month_day.isoformat(), category="food")
    s = await spending.month_summary(store, settings)
    assert s["month"] == t.strftime("%Y-%m") and s["current"] is True
    assert s["total_minor"] == 300000 and s["count"] == 3 and s["previous_total_minor"] == 200000 and s["change_pct"] == 50
    assert [(c["category"], c["amount_minor"], c["share"]) for c in s["categories"]] == [("food", 150000, 50), ("transport", 150000, 50)] or \
           [(c["category"], c["amount_minor"], c["share"]) for c in s["categories"]] == [("transport", 150000, 50), ("food", 150000, 50)]
    assert s["by_day"] == [{"date": first.isoformat(), "amount_minor": 300000}]
    assert s["average_per_day_minor"] == 300000 // t.day
    assert s["projected_minor"] == 300000 * s["days_in_month"] // t.day
    assert s["top"][0]["amount_minor"] == 150000
    past = await spending.month_summary(store, settings, prev_month_day.strftime("%Y-%m"))
    assert past["total_minor"] == 200000 and past["current"] is False and past["projected_minor"] is None


async def test_an_empty_month_has_zeroes_not_errors(store, settings):
    s = await spending.month_summary(store, settings, "2020-02")
    assert s["total_minor"] == 0 and s["categories"] == [] and s["change_pct"] is None and s["average_per_day_minor"] >= 0
    assert s["days_in_month"] == 29                                                     # a leap February


@pytest.mark.parametrize("bad", ["2026-13", "26-11", "2026/11", "nov", "2026-00", "../etc"])
async def test_month_must_look_like_a_month(store, settings, bad):
    with pytest.raises(ExpenseError, match="must look like"):
        await spending.month_summary(store, settings, bad)


async def test_the_list_filters_by_category_and_is_capped(store, settings):
    for i in range(5):
        await spending.add_spend(store, settings, amount=10 + i, category="food" if i % 2 else "travel")
    data = await spending.list_spend(store, settings, category="food")
    assert [i["category"] for i in data["items"]] == ["food", "food"]
    with pytest.raises(ExpenseError, match="category must be one of"):
        await spending.list_spend(store, settings, category="nope")
    assert len((await spending.list_spend(store, settings, limit=2))["items"]) == 2


async def test_budget_set_clear_and_reflected_in_the_summary(store, settings):
    await spending.add_spend(store, settings, amount=400)
    assert await spending.set_budget(store, 1000) == 100000
    s = await spending.month_summary(store, settings)
    assert s["budget_minor"] == 100000 and s["budget_left_minor"] == 60000
    c = await spending.card(store, settings)
    assert c["budget_left_minor"] == 60000 and c["spent_minor"] == 40000
    await spending.add_spend(store, settings, amount=700)
    over = spending.card_insights(await spending.card(store, settings), "INR")
    assert over[0]["level"] == "warn" and "over your ₹1,000 budget" in over[0]["text"]
    assert await spending.set_budget(store, None) is None and (await spending.month_summary(store, settings))["budget_minor"] is None
    with pytest.raises(ExpenseError):
        await spending.set_budget(store, "lots")


async def test_spending_csv_neutralises_formulas(store, settings):
    await spending.add_spend(store, settings, amount=5, note='=HYPERLINK("http://evil")')
    out = await spending.export_spend_csv(store)
    assert out.splitlines()[0] == "date,amount,category,note" and "'=HYPERLINK" in out and "\n=" not in "\n" + out


# ── subscriptions ──────────────────────────────────────────────────────
def test_monthly_equivalents_are_integer_and_rounded_half_up():
    assert spending.monthly_equivalent(64900, "monthly") == 64900
    assert spending.monthly_equivalent(120000, "yearly") == 10000
    assert spending.monthly_equivalent(30000, "quarterly") == 10000
    assert spending.monthly_equivalent(10000, "weekly") == 43333                        # 100.00 x 52 / 12 = 433.33
    assert spending.monthly_equivalent(1, "yearly") == 0 and spending.monthly_equivalent(7, "yearly") == 1   # half-up at 0.58


def test_renewal_dates_return_to_the_original_day_and_never_drift():
    d = date(2027, 1, 31)
    seen = []
    for _ in range(4):
        d = spending.add_cycle(d, "monthly", 31)
        seen.append(d.isoformat())
    assert seen == ["2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31"]            # clamped, then back to the 31st
    assert spending.add_cycle(date(2028, 2, 29), "yearly", 29) == date(2029, 2, 28)
    assert spending.add_cycle(date(2027, 11, 30), "quarterly", 30) == date(2028, 2, 29)
    assert spending.add_cycle(date(2027, 12, 28), "weekly", 28) == date(2028, 1, 4)


async def test_create_list_and_summarise_subscriptions(store, settings):
    await spending.create_sub(store, settings, name="Netflix", amount=649, cycle="monthly", next_date=day(settings, 3), category="entertainment")
    await spending.create_sub(store, settings, name="Domain", amount=1200, cycle="yearly", next_date=day(settings, 200), category="software")
    data = await spending.list_subs(store, settings)
    assert [s["name"] for s in data["subs"]] == ["Netflix", "Domain"]                   # soonest renewal first
    assert data["summary"]["active"] == 2 and data["summary"]["monthly_minor"] == 64900 + 10000
    assert data["summary"]["yearly_minor"] == (64900 + 10000) * 12
    assert data["summary"]["due_7"] == {"count": 1, "amount_minor": 64900}
    assert data["subs"][0]["status"] == "soon" and data["subs"][1]["status"] == "ok"
    with pytest.raises(ExpenseError, match="billing cycle"):
        await spending.create_sub(store, settings, name="X", amount=1, cycle="daily")
    with pytest.raises(ExpenseError, match="next renewal date"):
        await spending.create_sub(store, settings, name="X", amount=1, next_date="soon")


async def test_renewing_logs_spending_advances_the_date_and_moves_the_reminder(store, settings):
    sub = await spending.create_sub(store, settings, name="Netflix", amount=649, next_date=day(settings, 3), category="entertainment")
    first_reminder = await store.fetchone("SELECT id, title, due_at FROM reminders WHERE session_id = 'expenses' AND status = 'pending'")
    assert first_reminder["title"] == "Subscription · Netflix · ₹649 renews tomorrow"
    renewed = await spending.renew_sub(store, settings, sub["id"])
    due = date.fromisoformat(day(settings, 3))
    assert renewed["next_date"] == spending.add_cycle(due, "monthly", due.day).isoformat()
    month = await spending.list_spend(store, settings, month=today(settings).strftime("%Y-%m"))
    rows = [i for i in month["items"] if i["sub_id"] == sub["id"]]
    assert len(rows) <= 1                                                               # recorded in the month of the charge (today at the latest)
    all_spend = await store.fetchall("SELECT * FROM ex_spend WHERE sub_id = ?", (sub["id"],))
    assert len(all_spend) == 1 and all_spend[0]["amount_minor"] == 64900 and all_spend[0]["category"] == "entertainment"
    assert all_spend[0]["spent_on"] <= day(settings, 0)                                 # an upcoming renewal is never logged in the future
    pending = await store.fetchall("SELECT id FROM reminders WHERE session_id = 'expenses' AND status = 'pending'")
    old = await store.fetchone("SELECT status FROM reminders WHERE id = ?", (first_reminder["id"],))
    assert len(pending) == 1 and old["status"] == "cancelled"                          # exactly one live reminder, pointing at the new date


async def test_renew_without_logging_and_with_a_bank_deduction(store, settings):
    bank = await expenses.create_bank(store, "HDFC", 1000)
    sub = await spending.create_sub(store, settings, name="Gym", amount=500, bank_id=bank["id"], next_date=day(settings, -2))
    assert sub["status"] == "overdue"
    await spending.renew_sub(store, settings, sub["id"], record=False, deduct=True)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_spend"))["n"] == 0
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks WHERE id = ?", (bank["id"],)))["balance_minor"] == 100000 - 50000


async def test_pausing_cancels_the_reminder_and_blocks_renewing_until_resumed(store, settings):
    sub = await spending.create_sub(store, settings, name="Netflix", amount=649, next_date=day(settings, 5))
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 1
    paused = await spending.update_sub(store, settings, sub["id"], active=False)
    assert paused["status"] == "paused"
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0
    with pytest.raises(ExpenseError, match="paused"):
        await spending.renew_sub(store, settings, sub["id"])
    summary = (await spending.list_subs(store, settings))["summary"]
    assert summary["active"] == 0 and summary["paused"] == 1 and summary["monthly_minor"] == 0       # paused ones cost nothing
    await spending.update_sub(store, settings, sub["id"], active=True)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 1


async def test_editing_a_subscription_resyncs_one_reminder_and_turning_reminders_off_removes_it(store, settings):
    sub = await spending.create_sub(store, settings, name="Netflix", amount=649, next_date=day(settings, 6))
    await spending.update_sub(store, settings, sub["id"], amount=799, remind_days=3)
    live = await store.fetchall("SELECT title FROM reminders WHERE status = 'pending'")
    assert len(live) == 1 and live[0]["title"] == "Subscription · Netflix · ₹799 renews in 3 days"
    await spending.update_sub(store, settings, sub["id"], remind_days=None)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0


async def test_deleting_a_subscription_keeps_the_money_it_cost_and_removes_its_reminder(store, settings):
    sub = await spending.create_sub(store, settings, name="Netflix", amount=649, next_date=day(settings, 5))
    await spending.renew_sub(store, settings, sub["id"])
    await spending.delete_sub(store, sub["id"])
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_subs"))["n"] == 0
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0
    rows = await store.fetchall("SELECT sub_id, amount_minor FROM ex_spend")
    assert len(rows) == 1 and rows[0]["sub_id"] is None and rows[0]["amount_minor"] == 64900     # history is not erased
    with pytest.raises(NotFound):
        await spending.delete_sub(store, sub["id"])


async def test_changing_the_next_date_resets_the_anchor_day(store, settings):
    sub = await spending.create_sub(store, settings, name="Rent", amount=100, next_date="2027-01-31")
    await spending.update_sub(store, settings, sub["id"], next_date="2027-03-15")
    row = await store.fetchone("SELECT anchor_day FROM ex_subs WHERE id = ?", (sub["id"],))
    assert row["anchor_day"] == 15


async def test_the_overview_card_and_rules_mention_subscriptions(store, settings):
    await spending.create_sub(store, settings, name="Netflix", amount=649, next_date=day(settings, 5))
    card = await spending.card(store, settings)
    assert card["subs_active"] == 1 and card["subs_monthly_minor"] == 64900 and card["subs_due_7"] == 1
    assert "649" in spending.card_insights(card, "INR")[0]["text"] and "a year" in spending.card_insights(card, "INR")[0]["text"]


# ── chat skills ────────────────────────────────────────────────────────
@pytest.fixture
async def run(store, settings):
    import httpx

    from src.agent.skill import SkillContext
    from src.agent.skills import build_registry

    registry = build_registry(settings)
    async with httpx.AsyncClient() as http:
        ctx = SkillContext(settings=settings, store=store, http=http, session_id="t")

        async def call(skill, **args):
            return await registry.skills[skill].handler(ctx, args)
        yield call


async def test_the_new_skills_are_registered_with_valid_schemas(settings):
    from src.agent.skills import build_registry

    registry = build_registry(settings)
    for name in ("log_expense", "spending_summary", "add_subscription", "add_owed_payment", "add_payment_plan"):
        tool = registry.skills[name].to_openai_tool()
        assert tool["function"]["name"] == name and tool["function"]["parameters"]["type"] == "object"
    assert "emi_amount" in registry.skills["add_payment_plan"].to_openai_tool()["function"]["parameters"]["properties"]
    assert registry.skills["add_payment_plan"].to_openai_tool()["function"]["parameters"]["required"] == ["title", "emis", "first_due_date"]


async def test_chat_logs_an_expense_and_reports_the_month_and_budget(run, store, settings):
    await spending.set_budget(store, 1000)
    reply = await run("log_expense", amount=250, category="food", note="lunch")
    assert "Logged ₹250 on food (lunch)" in reply and "This month so far: ₹250" in reply and "₹750 left of this month's budget" in reply
    over = await run("log_expense", amount=900, category="travel")
    assert "over this month's budget" in over and "₹150" in over
    assert "more than zero" in await run("log_expense", amount=0)
    assert "category must be one of" in await run("log_expense", amount=5, category="yachts")
    summary = await run("spending_summary")
    assert summary["spent"] == "₹1,150" and summary["entries"] == 2 and summary["budget"]["left"] == "-₹150"
    assert [c["category"] for c in summary["by_category"]] == ["travel", "food"]
    assert "must look like" in (await run("spending_summary", month="soon"))["error"]


async def test_chat_adds_a_subscription_and_an_owed_payment(run, store, settings):
    reply = await run("add_subscription", name="Netflix", amount=649, cycle="monthly", next_renewal_date=day(settings, 4))
    assert "Tracking Netflix: ₹649 monthly" in reply and "remind you the day before" in reply
    assert "billing cycle" in await run("add_subscription", name="X", amount=1, cycle="daily")
    owed = await run("add_owed_payment", title="Owe Rahul", amount=5000, group="Personal")
    assert "no due date" in owed and "no reminders" in owed
    pay = (await expenses.snapshot(store, settings))["payments"][0]
    assert pay["kind"] == "open" and pay["grp"] == "Personal" and pay["category"] == "personal"
    summary = await run("expense_summary")
    assert summary["owed_with_no_due_date"] == {"count": 1, "amount": "₹5,000"} and summary["payments"][0]["paid"] == "no schedule"


async def test_chat_can_add_a_plan_from_the_emi_amount_and_a_group(run, store, settings):
    reply = await run("add_payment_plan", title="Laptop", emi_amount=2500, emis=4, first_due_date=day(settings, 6), group="Gadgets")
    assert "₹10,000 in 4 EMI(s)" in reply and "₹2,500 each" in reply
    assert (await expenses.snapshot(store, settings))["payments"][0]["grp"] == "Gadgets"
