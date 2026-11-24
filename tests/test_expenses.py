"""Expense tracker: money maths, schedules, paid/unpaid with bank balances, reminders, advice rules."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.agent import expenses, timeutil
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


def days(settings, n: int) -> str:
    return (today(settings) + timedelta(days=n)).isoformat()


# ── money and dates ────────────────────────────────────────────────────
def test_amounts_become_exact_integer_minor_units():
    assert expenses.to_minor("1,234.56") == 123456
    assert expenses.to_minor(0.1 + 0.2) == 30                      # the float that is 0.30000000000000004
    assert expenses.to_minor("10.005") == 1001                     # half-up, not banker's rounding
    assert expenses.to_minor(5) == 500


@pytest.mark.parametrize("bad", ["", None, "abc", "nan", "inf", True, -5, 0, "1e30", 10**12])
def test_bad_amounts_are_refused(bad):
    with pytest.raises(ExpenseError):
        expenses.to_minor(bad)


def test_zero_and_negative_are_allowed_only_where_they_make_sense():
    assert expenses.to_minor(0, allow_zero=True) == 0
    assert expenses.to_minor(-250.5, allow_zero=True, allow_negative=True) == -25050      # an overdrawn bank


def test_money_formatting_uses_indian_grouping_for_inr_only():
    assert expenses.money(12345678, "INR") == "₹1,23,456.78"
    assert expenses.money(500000, "INR") == "₹5,000"
    assert expenses.money(99, "INR") == "₹0.99"
    assert expenses.money(123456789, "USD") == "$1,234,567.89"
    assert expenses.money(-150000, "INR") == "-₹1,500"
    assert expenses.money(100, "CHF") == "CHF 1"


def test_month_end_days_are_clamped_not_skipped():
    assert expenses.emi_date(2027, 2, 31) == date(2027, 2, 28)
    assert expenses.emi_date(2028, 2, 31) == date(2028, 2, 29)
    assert expenses.emi_date(2027, 4, 31) == date(2027, 4, 30)


def test_a_schedule_adds_up_exactly_and_crosses_year_ends():
    rows = expenses.build_schedule(100_000, 3, date(2026, 11, 30), None)       # 1000.00 over 3 months, day 30
    assert [a for _, a in rows] == [33333, 33333, 33334] and sum(a for _, a in rows) == 100_000
    assert [d for d, _ in rows] == [date(2026, 11, 30), date(2026, 12, 30), date(2027, 1, 30)]
    feb = expenses.build_schedule(300, 3, date(2027, 1, 31), None)
    assert [d for d, _ in feb] == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]   # back to the 31st, not stuck on the 28th


def test_a_common_day_applies_after_the_first_emi():
    rows = expenses.build_schedule(1200, 3, date(2026, 12, 20), 5)
    assert [d for d, _ in rows] == [date(2026, 12, 20), date(2027, 1, 5), date(2027, 2, 5)]


@pytest.mark.parametrize("count,total", [(0, 1000), (361, 100000), (5, 4)])
def test_impossible_schedules_are_refused(count, total):
    with pytest.raises(ExpenseError):
        expenses.build_schedule(total, count, date(2026, 12, 1), None)


def test_dates_must_be_real():
    for bad in ("", "2026-02-30", "tomorrow", "2026-13-01", "5/12/2026", None):
        with pytest.raises(ExpenseError):
            expenses.parse_date(bad)
    assert expenses.parse_date("2026-12-05") == date(2026, 12, 5)


# ── banks ──────────────────────────────────────────────────────────────
async def test_banks_are_unique_by_name_ignoring_case(store):
    await expenses.create_bank(store, "HDFC", 1000)
    with pytest.raises(ExpenseError):
        await expenses.create_bank(store, "hdfc", 5)
    other = await expenses.create_bank(store, "SBI", 0)
    with pytest.raises(ExpenseError):
        await expenses.update_bank(store, other["id"], name=" Hdfc ")
    renamed = await expenses.update_bank(store, other["id"], name="State Bank", balance="2,500.50")
    assert renamed["name"] == "State Bank" and renamed["balance_minor"] == 250050


async def test_deleting_a_bank_detaches_it_but_keeps_the_payments(store, settings):
    bank = await expenses.create_bank(store, "HDFC", 100)
    pay = await expenses.create_payment(store, settings, title="Phone", total=1200, emis=3, first_due=days(settings, 10), bank_id=bank["id"])
    await expenses.delete_bank(store, bank["id"])
    assert (await expenses.get_payment(store, settings, pay["id"]))["bank_id"] is None
    with pytest.raises(NotFound):
        await expenses.delete_bank(store, bank["id"])


# ── payments ───────────────────────────────────────────────────────────
async def make(store, settings, **kw):
    args = dict(title="Car loan", total=12000, emis=4, first_due=days(settings, 5))
    args.update(kw)
    return await expenses.create_payment(store, settings, **args)


async def test_creating_a_payment_builds_its_schedule(store, settings):
    pay = await make(store, settings, total="10000.01", emis=3)
    amounts = [e["amount_minor"] for e in pay["emis"]]
    assert amounts == [333333, 333333, 333335] and sum(amounts) == pay["total_minor"] == 1000001
    assert [e["seq"] for e in pay["emis"]] == [1, 2, 3]
    assert pay["emi_count"] == 3 and pay["paid_count"] == 0 and pay["mismatch_minor"] == 0
    assert pay["remaining_minor"] == 1000001 and pay["next_due"] == days(settings, 5)


async def test_a_one_off_payment_is_a_single_emi(store, settings):
    pay = await make(store, settings, title="Insurance", total=5000, emis=1)
    assert pay["emi_count"] == 1 and pay["emis"][0]["amount_minor"] == 500000


async def test_invalid_payments_are_refused_and_leave_nothing_behind(store, settings):
    for bad in (dict(title="  "), dict(total=0), dict(emis=0), dict(emis="x"), dict(first_due="soon"), dict(category="gambling"),
                dict(bank_id=999), dict(remind_days=9), dict(title="x" * 121)):
        with pytest.raises(ExpenseError):
            await make(store, settings, **bad)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_payments"))["n"] == 0
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_emis"))["n"] == 0


async def test_editing_the_total_does_not_silently_rewrite_the_emis_but_flags_it(store, settings):
    pay = await make(store, settings)
    edited = await expenses.update_payment(store, settings, pay["id"], total=13000)
    assert [e["amount_minor"] for e in edited["emis"]] == [300000] * 4
    assert edited["mismatch_minor"] == -100000                       # EMIs add up to 1000.00 less than the total
    fixed = await expenses.rebalance(store, settings, pay["id"])
    assert fixed["mismatch_minor"] == 0 and sum(e["amount_minor"] for e in fixed["emis"]) == 1300000


async def test_rebalance_keeps_paid_emis_and_spreads_only_what_is_left(store, settings):
    pay = await make(store, settings)                                # 4 x 3000
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    await expenses.update_payment(store, settings, pay["id"], total=10000)
    fixed = await expenses.rebalance(store, settings, pay["id"])
    assert fixed["emis"][0]["amount_minor"] == 300000 and fixed["emis"][0]["status"] == "paid"
    assert [e["amount_minor"] for e in fixed["emis"][1:]] == [233333, 233333, 233334]


async def test_rebalance_refuses_when_nothing_is_left_to_spread(store, settings):
    pay = await make(store, settings)
    await expenses.update_payment(store, settings, pay["id"], total="0.03")       # 3 paise cannot be spread over 4 unpaid EMIs
    with pytest.raises(ExpenseError):
        await expenses.rebalance(store, settings, pay["id"])
    for e in pay["emis"]:
        await expenses.update_emi(store, settings, e["id"], paid=True)
    with pytest.raises(ExpenseError):
        await expenses.rebalance(store, settings, pay["id"])


async def test_one_common_day_moves_every_unpaid_emi_but_not_paid_ones(store, settings):
    pay = await make(store, settings, first_due="2027-01-15")
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    moved = await expenses.redate(store, settings, pay["id"], 31)
    assert [e["due_date"] for e in moved["emis"]] == ["2027-01-15", "2027-02-28", "2027-03-31", "2027-04-30"]
    assert moved["due_day"] == 31
    with pytest.raises(ExpenseError):
        await expenses.redate(store, settings, pay["id"], 32)


async def test_each_emi_amount_and_date_can_be_edited_and_order_follows_dates(store, settings):
    pay = await make(store, settings, first_due="2027-01-10")
    first, second = pay["emis"][0], pay["emis"][1]
    edited = await expenses.update_emi(store, settings, first["id"], amount="3,500.50", due_date="2027-03-20")
    by_id = {e["id"]: e for e in edited["emis"]}
    assert by_id[first["id"]]["amount_minor"] == 350050 and by_id[first["id"]]["due_date"] == "2027-03-20"
    assert [e["due_date"] for e in edited["emis"]] == sorted(e["due_date"] for e in edited["emis"])
    assert [e["seq"] for e in edited["emis"]] == [1, 2, 3, 4] and by_id[first["id"]]["seq"] == 3
    with pytest.raises(ExpenseError):
        await expenses.update_emi(store, settings, second["id"], amount=0)
    with pytest.raises(ExpenseError):
        await expenses.update_emi(store, settings, second["id"], due_date="31/02/2027")


async def test_a_paid_emi_cannot_be_edited_until_it_is_unmarked(store, settings):
    pay = await make(store, settings)
    emi = pay["emis"][0]
    await expenses.update_emi(store, settings, emi["id"], paid=True)
    with pytest.raises(ExpenseError):
        await expenses.update_emi(store, settings, emi["id"], amount=1)
    again = await expenses.update_emi(store, settings, emi["id"], paid=False, amount=1)      # un-mark and edit together
    assert again["emis"][0]["status"] != "paid" and again["emis"][0]["amount_minor"] == 100


async def test_emis_can_be_added_and_removed_with_numbering_kept_in_order(store, settings):
    pay = await make(store, settings, first_due="2027-01-10", emis=2, total=2000)
    added = await expenses.add_emi(store, settings, pay["id"])
    assert [e["due_date"] for e in added["emis"]] == ["2027-01-10", "2027-02-10", "2027-03-10"] and added["emis"][2]["amount_minor"] == 100000
    custom = await expenses.add_emi(store, settings, pay["id"], amount=50, due_date="2027-01-25")
    assert [e["due_date"] for e in custom["emis"]] == ["2027-01-10", "2027-01-25", "2027-02-10", "2027-03-10"]
    assert [e["seq"] for e in custom["emis"]] == [1, 2, 3, 4]
    after = await expenses.delete_emi(store, settings, custom["emis"][1]["id"])
    assert after["emi_count"] == 3 and [e["seq"] for e in after["emis"]] == [1, 2, 3]
    await expenses.update_emi(store, settings, after["emis"][0]["id"], paid=True)
    with pytest.raises(ExpenseError):
        await expenses.delete_emi(store, settings, after["emis"][0]["id"])             # paid: unmark first


async def test_the_last_emi_cannot_be_deleted_on_its_own(store, settings):
    pay = await make(store, settings, emis=1)
    with pytest.raises(ExpenseError):
        await expenses.delete_emi(store, settings, pay["emis"][0]["id"])


async def test_deleting_a_payment_removes_its_emis_and_cancels_their_reminders(store, settings):
    pay = await make(store, settings, first_due=days(settings, 10))
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status='pending'"))["n"] == 4
    await expenses.delete_payment(store, pay["id"])
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_emis"))["n"] == 0
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status='pending'"))["n"] == 0
    with pytest.raises(NotFound):
        await expenses.delete_payment(store, pay["id"])


# ── paid / unpaid and bank balances ────────────────────────────────────
async def test_mark_and_unmark_paid_is_idempotent(store, settings):
    pay = await make(store, settings)
    emi = pay["emis"][0]["id"]
    for _ in range(2):
        p = await expenses.update_emi(store, settings, emi, paid=True)
    assert p["paid_count"] == 1 and p["paid_minor"] == 300000 and p["emis"][0]["status"] == "paid"
    for _ in range(2):
        p = await expenses.update_emi(store, settings, emi, paid=False)
    assert p["paid_count"] == 0 and p["emis"][0]["status"] != "paid"


async def test_paying_can_deduct_from_the_bank_and_unpaying_restores_exactly(store, settings):
    bank = await expenses.create_bank(store, "HDFC", "10000.50")
    pay = await make(store, settings, total="1000.01", emis=3, bank_id=bank["id"])
    last = pay["emis"][2]
    assert last["amount_minor"] == 33335
    await expenses.update_emi(store, settings, last["id"], paid=True, deduct=True)
    await expenses.update_emi(store, settings, last["id"], paid=True, deduct=True)         # second tap must not deduct again
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 1000050 - 33335
    await expenses.update_emi(store, settings, last["id"], paid=False)
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 1000050
    await expenses.update_emi(store, settings, last["id"], paid=False)
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 1000050


async def test_the_balance_is_untouched_unless_deduct_is_requested(store, settings):
    bank = await expenses.create_bank(store, "HDFC", 500)
    pay = await make(store, settings, bank_id=bank["id"])
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 50000
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=False)
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 50000


async def test_unmarking_restores_to_the_bank_it_was_taken_from_even_if_the_payment_moved(store, settings):
    a = await expenses.create_bank(store, "A", 1000)
    b = await expenses.create_bank(store, "B", 1000)
    pay = await make(store, settings, bank_id=a["id"])
    emi = pay["emis"][0]["id"]
    await expenses.update_emi(store, settings, emi, paid=True, deduct=True)
    await expenses.update_payment(store, settings, pay["id"], bank_id=b["id"])
    await expenses.update_emi(store, settings, emi, paid=False)
    rows = {r["name"]: r["balance_minor"] for r in await store.fetchall("SELECT name, balance_minor FROM ex_banks")}
    assert rows == {"A": 100000, "B": 100000}


async def test_deduct_does_nothing_without_a_bank(store, settings):
    pay = await make(store, settings)
    p = await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True, deduct=True)
    assert p["emis"][0]["status"] == "paid" and p["emis"][0]["deducted"] is False


async def test_mark_next_paid_takes_the_earliest_unpaid_emi(store, settings):
    pay = await make(store, settings)
    one = await expenses.mark_next_paid(store, settings, pay["id"])
    two = await expenses.mark_next_paid(store, settings, pay["id"])
    assert [e["status"] == "paid" for e in two["emis"]] == [True, True, False, False] and one["paid_count"] == 1
    for _ in range(2):
        await expenses.mark_next_paid(store, settings, pay["id"])
    with pytest.raises(ExpenseError):
        await expenses.mark_next_paid(store, settings, pay["id"])


async def test_status_reflects_the_calendar(store, settings):
    pay = await make(store, settings, first_due=days(settings, -40), emis=4)           # one overdue month, then later ones
    statuses = [e["status"] for e in pay["emis"]]
    assert statuses[0] == "overdue" and statuses[-1] == "upcoming"
    due_today = await make(store, settings, title="Today", first_due=days(settings, 0), emis=1)
    assert due_today["emis"][0]["status"] == "today"


# ── reminders ──────────────────────────────────────────────────────────
async def reminders(store):
    return await store.fetchall("SELECT title, due_at, status FROM reminders WHERE session_id = 'expenses' AND status = 'pending' ORDER BY due_at")


async def test_upcoming_emis_get_a_reminder_the_day_before_at_nine(store, settings):
    await make(store, settings, first_due=days(settings, 10), emis=3, total=3000)
    rows = await reminders(store)
    assert len(rows) == 3
    due = timeutil.as_aware(rows[0]["due_at"], settings)
    assert due.date() == today(settings) + timedelta(days=9) and (due.hour, due.minute) == (9, 0)
    assert "EMI 1/3" in rows[0]["title"] and "Car loan" in rows[0]["title"] and "₹1,000" in rows[0]["title"] and "tomorrow" in rows[0]["title"]


async def test_reminders_can_be_switched_off_and_nothing_is_set_for_the_past(store, settings):
    await make(store, settings, remind_days=None)
    assert await reminders(store) == []
    await make(store, settings, title="Old", first_due=days(settings, -90), emis=2, total=100)
    assert await reminders(store) == []                                                  # both fire times are long gone


async def test_paying_removes_that_reminder_and_unpaying_brings_it_back(store, settings):
    pay = await make(store, settings, first_due=days(settings, 10))
    assert len(await reminders(store)) == 4
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    assert len(await reminders(store)) == 3
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=False)
    assert len(await reminders(store)) == 4


async def test_editing_moves_the_reminder_without_duplicating_it(store, settings):
    pay = await make(store, settings, first_due=days(settings, 10), emis=2, total=2000)
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], due_date=days(settings, 20))
    rows = await reminders(store)
    assert len(rows) == 2
    dates = {timeutil.as_aware(r["due_at"], settings).date() for r in rows}
    assert today(settings) + timedelta(days=19) in dates          # the moved EMI now reminds the day before its new date
    assert today(settings) + timedelta(days=9) not in dates       # ...and no longer on the old one


async def test_syncing_twice_changes_nothing(store, settings):
    pay = await make(store, settings, first_due=days(settings, 10))
    before = await store.fetchall("SELECT id, status FROM reminders ORDER BY id")
    await expenses.sync_reminders(store, settings, pay["id"])
    await expenses.sync_reminders(store, settings, pay["id"])
    assert await store.fetchall("SELECT id, status FROM reminders ORDER BY id") == before


async def test_only_the_next_twelve_emis_have_reminders(store, settings):
    await make(store, settings, first_due=days(settings, 10), emis=36, total=36000)
    assert len(await reminders(store)) == expenses.REMINDER_WINDOW


async def test_changing_the_title_rewrites_the_reminders(store, settings):
    pay = await make(store, settings, first_due=days(settings, 10), emis=2, total=2000)
    await expenses.update_payment(store, settings, pay["id"], title="Bike loan")
    rows = await reminders(store)
    assert len(rows) == 2 and all("Bike loan" in r["title"] for r in rows)


# ── overview, advice, search, export ───────────────────────────────────
async def test_overview_totals_banks_and_months(store, settings):
    hdfc = await expenses.create_bank(store, "HDFC", 1000)
    await make(store, settings, title="Car", total=4000, emis=2, first_due=days(settings, -3), bank_id=hdfc["id"])          # one overdue
    await make(store, settings, title="Phone", total=900, emis=3, first_due=days(settings, 5))                               # no bank
    snap = await expenses.snapshot(store, settings)
    ov = snap["overview"]
    assert ov["overdue"] == {"count": 1, "amount_minor": 200000}
    assert ov["remaining_minor"] == 400000 + 90000
    assert ov["due_7"]["count"] == 1 and ov["due_7"]["amount_minor"] == 30000
    assert ov["next"]["payment"] == "Car" and ov["next"]["seq"] == 1
    bank = ov["banks"][0]
    assert bank["due_30_minor"] >= 200000 and bank["shortfall_minor"] == bank["due_30_minor"] - 100000
    assert ov["unassigned_due_minor"] >= 30000
    assert ov["months"][0]["month"] == "overdue" and ov["balance_minor"] == 100000
    assert ov["free_by"] >= days(settings, 5)


async def test_advice_rules_name_the_real_problems_first(store, settings):
    hdfc = await expenses.create_bank(store, "HDFC", 100)
    await make(store, settings, title="Car", total=4000, emis=2, first_due=days(settings, -3), bank_id=hdfc["id"])
    snap = await expenses.snapshot(store, settings)
    texts = [i["text"] for i in snap["insights"]]
    assert snap["insights"][0]["level"] == "warn" and "overdue" in texts[0]
    assert any("HDFC is short by" in t for t in texts)


async def test_advice_on_an_empty_tracker_just_says_how_to_start(store, settings):
    snap = await expenses.snapshot(store, settings)
    assert len(snap["insights"]) == 1 and "Add your first payment" in snap["insights"][0]["text"]


async def test_a_fully_paid_tracker_says_so(store, settings):
    pay = await make(store, settings, emis=1, total=100)
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    snap = await expenses.snapshot(store, settings)
    assert snap["payments"][0]["finished"] and snap["overview"]["remaining_minor"] == 0
    assert any("paid" in i["text"].lower() for i in snap["insights"]) and snap["overview"]["free_by"] is None


async def test_the_llm_context_has_figures_but_no_ids_notes_or_tokens(store, settings):
    bank = await expenses.create_bank(store, "HDFC", 1000, note="acct 1234 secret")
    await make(store, settings, title="Car", notes="private note", bank_id=bank["id"])
    snap = await expenses.snapshot(store, settings)
    context = expenses.llm_context(snap["overview"], snap["payments"], snap["insights"], "INR")
    assert "Car" in context and "HDFC" in context
    assert "private note" not in context and "acct 1234" not in context


async def test_find_payment_by_name(store, settings):
    await make(store, settings, title="Car loan")
    await make(store, settings, title="Car insurance", total=100, emis=1)
    await make(store, settings, title="Phone", total=100, emis=1)
    assert (await expenses.find_payment(store, settings, "phone"))["title"] == "Phone"
    assert (await expenses.find_payment(store, settings, "CAR LOAN"))["title"] == "Car loan"
    with pytest.raises(ExpenseError, match="several"):
        await expenses.find_payment(store, settings, "car")
    with pytest.raises(NotFound):
        await expenses.find_payment(store, settings, "boat")


async def test_csv_export_neutralises_spreadsheet_formulas(store, settings):
    await make(store, settings, title="=HYPERLINK(\"http://evil\")", total=100, emis=1)
    await make(store, settings, title="+cmd", total=100, emis=1)
    out = await expenses.export_csv(store, settings)
    lines = out.strip().splitlines()
    assert lines[0].startswith("payment,category,bank,emi_number")
    assert "\n=" not in "\n" + out and "'=HYPERLINK" in out and "'+cmd" in out


# ── chat skills ────────────────────────────────────────────────────────
@pytest.fixture
async def run(store, settings):
    import httpx

    from src.agent.skill import SkillContext
    from src.agent.skills import build_registry

    registry = build_registry(settings)
    async with httpx.AsyncClient() as http:
        ctx = SkillContext(settings=settings, store=store, http=http, session_id="t")

        async def call(name, **args):
            return await registry.skills[name].handler(ctx, args)
        yield call


async def test_the_skills_are_registered_with_valid_schemas(settings):
    from src.agent.skills import build_registry

    registry = build_registry(settings)
    for name in ("add_payment_plan", "mark_emi_paid", "expense_summary"):
        tool = registry.skills[name].to_openai_tool()
        assert tool["function"]["name"] == name and tool["function"]["parameters"]["type"] == "object"


async def test_chat_can_add_a_plan_and_mark_emis_paid(run, store, settings):
    reply = await run("add_payment_plan", title="Phone", total_amount=12000, emis=3, first_due_date=days(settings, 7))
    assert "Added 'Phone'" in reply and "₹4,000 each" in reply
    paid = await run("mark_emi_paid", payment="phone")
    assert "EMI 1 of 3" in paid and "2 left" in paid and "₹8,000 remaining" in paid
    assert "EMI 3 of 3" in await run("mark_emi_paid", payment="phone", emi_number=3)
    assert "unpaid again" in await run("mark_emi_paid", payment="phone", emi_number=3, paid=False)
    summary = await run("expense_summary")
    assert summary["payments_tracked"] == 1 and summary["remaining_to_pay"] == "₹8,000" and summary["next_emi"]["number"] == 2


async def test_chat_problems_come_back_as_plain_sentences_not_exceptions(run, settings):
    assert "number" in await run("add_payment_plan", title="X", total_amount="lots", emis=3, first_due_date=days(settings, 3))
    assert "real date" in await run("add_payment_plan", title="X", total_amount=100, emis=3, first_due_date="whenever")
    assert "don't have a bank" in await run("add_payment_plan", title="X", total_amount=100, emis=1, first_due_date=days(settings, 3), bank="Nowhere")
    assert "can't find" in await run("mark_emi_paid", payment="boat")
    await run("add_payment_plan", title="Phone", total_amount=300, emis=3, first_due_date=days(settings, 3))
    assert "no number 9" in await run("mark_emi_paid", payment="phone", emi_number=9)
    assert "must be a number" in await run("mark_emi_paid", payment="phone", emi_number="third")
    assert "true or false" in await run("mark_emi_paid", payment="phone", paid="yes")
    assert "Which EMI" in await run("mark_emi_paid", payment="phone", paid=False)


async def test_chat_uses_an_existing_bank_by_name(run, store, settings):
    bank = await expenses.create_bank(store, "HDFC", 1000)
    await run("add_payment_plan", title="Phone", total_amount=300, emis=3, first_due_date=days(settings, 3), bank="hdfc")
    assert (await expenses.find_payment(store, settings, "phone"))["bank_id"] == bank["id"]
