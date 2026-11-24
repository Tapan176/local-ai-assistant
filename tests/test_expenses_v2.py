"""Expense tracker v2: fixed amounts survive "spread equally", payment kinds, auto-total, groups, bulk paid, and the
one-time protection of amounts that were set by hand before the 'fixed' flag existed (tested on realistic data)."""

from __future__ import annotations

import random
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


def days(settings, n: int) -> str:
    return (timeutil.now(settings).date() + timedelta(days=n)).isoformat()


async def make(store, settings, **kw):
    body = {"title": "Car loan", "total": 12000, "emis": 4, "first_due": days(settings, 10)}
    body.update(kw)
    return await expenses.create_payment(store, settings, **body)


def amounts(pay):
    return [e["amount_minor"] for e in pay["emis"]]


def paid_ids(pay):
    return [e["id"] for e in pay["emis"] if e["status"] == "paid"]


# ── "spread equally" respects amounts you set (the reported bug) ─────────
async def test_a_custom_last_emi_survives_spreading(store, settings):
    pay = await make(store, settings, total=10000, emis=4)                       # 2500 each
    last = pay["emis"][-1]["id"]
    await expenses.update_emi(store, settings, last, amount=1000)                # user sets the LAST emi to 1000
    first = await expenses.get_payment(store, settings, pay["id"])
    assert first["mismatch_minor"] != 0
    done = await expenses.rebalance(store, settings, pay["id"])
    assert amounts(done)[-1] == 100000                                           # untouched
    assert amounts(done)[:3] == [300000] * 3                                     # the other three share 9000 equally
    assert done["mismatch_minor"] == 0 and sum(amounts(done)) == done["total_minor"]


async def test_a_custom_first_emi_also_survives(store, settings):
    pay = await make(store, settings, total=10000, emis=4)
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], amount=4000)
    done = await expenses.rebalance(store, settings, pay["id"])
    assert amounts(done) == [400000, 200000, 200000, 200000]


async def test_several_custom_emis_anywhere_the_rest_split_equally(store, settings):
    pay = await make(store, settings, total=100000, emis=6)                      # 1000 each
    await expenses.update_emi(store, settings, pay["emis"][1]["id"], amount=3000)
    await expenses.update_emi(store, settings, pay["emis"][5]["id"], amount=500)
    done = await expenses.rebalance(store, settings, pay["id"])
    got = amounts(done)
    assert got[1] == 300000 and got[5] == 50000
    assert got == [2412500, 300000, 2412500, 2412500, 2412500, 50000]           # (100000 - 3000 - 500) / 4 auto emis = 24125.00 each
    assert done["mismatch_minor"] == 0


async def test_remainder_paise_go_to_the_last_auto_emi_not_a_fixed_one(store, settings):
    pay = await make(store, settings, total=100, emis=4, first_due=days(settings, 3))      # 25.00 each
    await expenses.update_emi(store, settings, pay["emis"][3]["id"], amount=10)            # last is fixed at 10.00
    await expenses.update_payment(store, settings, pay["id"], total="100.01")              # 90.01 left over 3 -> 30.00, 30.00, 30.01
    done = await expenses.rebalance(store, settings, pay["id"])
    assert amounts(done) == [3000, 3000, 3001, 1000]


async def test_paid_emis_are_never_touched(store, settings):
    pay = await make(store, settings, total=10000, emis=4)
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    await expenses.update_emi(store, settings, pay["emis"][2]["id"], amount=1000)
    await expenses.update_payment(store, settings, pay["id"], total=12000)
    done = await expenses.rebalance(store, settings, pay["id"])
    assert amounts(done)[0] == 250000                                            # paid: history
    assert amounts(done)[2] == 100000                                            # fixed
    assert amounts(done)[1] + amounts(done)[3] == 12000 * 100 - 250000 - 100000


async def test_nothing_to_spread_when_every_unpaid_emi_is_fixed(store, settings):
    pay = await make(store, settings, total=10000, emis=2)
    for e in pay["emis"]:
        await expenses.update_emi(store, settings, e["id"], amount=1234)
    with pytest.raises(ExpenseError, match="nothing to spread"):
        await expenses.rebalance(store, settings, pay["id"])


async def test_too_little_left_for_the_auto_emis_is_explained(store, settings):
    pay = await make(store, settings, total=100, emis=3, first_due=days(settings, 3))
    await expenses.update_emi(store, settings, pay["emis"][0]["id"], amount=99.99)
    await expenses.update_emi(store, settings, pay["emis"][1]["id"], amount=0.01)           # 100.00 fixed; nothing left for the third
    with pytest.raises(ExpenseError, match="is left for 1 EMI"):
        await expenses.rebalance(store, settings, pay["id"])


async def test_reset_spreads_over_all_and_clears_the_fixed_flags(store, settings):
    pay = await make(store, settings, total=10000, emis=4)
    await expenses.update_emi(store, settings, pay["emis"][3]["id"], amount=1000)
    done = await expenses.rebalance(store, settings, pay["id"], reset=True)
    assert amounts(done) == [250000] * 4 and not any(e["custom"] for e in done["emis"])


async def test_typing_an_amount_fixes_it_and_it_can_be_unlocked_or_created_unfixed(store, settings):
    pay = await make(store, settings, total=10000, emis=4)
    emi = pay["emis"][1]["id"]
    assert not any(e["custom"] for e in pay["emis"])
    pay = await expenses.update_emi(store, settings, emi, amount=2600)
    assert [e["custom"] for e in pay["emis"]] == [False, True, False, False]
    pay = await expenses.update_emi(store, settings, emi, custom=False)                    # unlock without changing the amount
    assert pay["emis"][1]["custom"] is False and pay["emis"][1]["amount_minor"] == 260000
    pay = await expenses.update_emi(store, settings, emi, amount=2700, custom=False)       # typed but explicitly not fixed
    assert pay["emis"][1]["custom"] is False
    pay = await expenses.add_emi(store, settings, pay["id"], amount=999)                    # an added EMI with a typed amount is fixed
    assert pay["emis"][-1]["custom"] is True
    pay = await expenses.add_emi(store, settings, pay["id"])                                # one that copies the last is not
    assert pay["emis"][-1]["custom"] is False


@pytest.mark.parametrize("seed", range(25))
async def test_spreading_always_keeps_the_total_and_never_moves_paid_or_fixed_emis(store, settings, seed):
    rng = random.Random(seed)
    count = rng.randint(2, 18)
    total = rng.randint(count * 100, 5_000_000)
    pay = await make(store, settings, total=total / 100, emis=count)
    fixed: dict[int, int] = {}
    for e in rng.sample(pay["emis"], rng.randint(0, count - 1)):
        value = rng.randint(1, max(1, total // count * 2))
        fixed[e["id"]] = value
        pay = await expenses.update_emi(store, settings, e["id"], amount=value / 100)
    paid = [e["id"] for e in rng.sample(pay["emis"], rng.randint(0, count // 2)) if e["id"] not in fixed]
    for emi_id in paid:
        pay = await expenses.update_emi(store, settings, emi_id, paid=True)
    before = {e["id"]: e["amount_minor"] for e in pay["emis"]}
    auto = [e for e in pay["emis"] if e["id"] not in fixed and e["id"] not in paid]
    try:
        done = await expenses.rebalance(store, settings, pay["id"])
    except ExpenseError:
        return                                                                   # legitimately impossible (all fixed / too little left)
    after = {e["id"]: e["amount_minor"] for e in done["emis"]}
    assert all(after[i] == before[i] for i in list(fixed) + paid)                # fixed and paid untouched
    assert sum(after.values()) == done["total_minor"]                            # the total is exact
    shares = [after[e["id"]] for e in auto]
    assert max(shares) - min(shares) < len(auto) and shares[:-1] == [shares[0]] * (len(shares) - 1)   # equal, the last takes the remainder


# ── payments typed as an amount per EMI: the total is worked out ─────────
async def test_total_is_calculated_from_the_emi_amount(store, settings):
    pay = await expenses.create_payment(store, settings, title="Phone", emi_amount="1234.56", emis=6, first_due=days(settings, 5))
    assert pay["total_minor"] == 123456 * 6 and amounts(pay) == [123456] * 6 and pay["mismatch_minor"] == 0


async def test_total_and_emi_amount_must_agree_when_both_are_given(store, settings):
    ok = await expenses.create_payment(store, settings, title="A", total=6000, emi_amount=1000, emis=6, first_due=days(settings, 5))
    assert ok["total_minor"] == 600000
    with pytest.raises(ExpenseError, match="don't match: 6 × ₹1,000 is ₹6,000"):
        await expenses.create_payment(store, settings, title="B", total=6001, emi_amount=1000, emis=6, first_due=days(settings, 5))
    with pytest.raises(ExpenseError, match="total amount, or the amount of each EMI"):
        await expenses.create_payment(store, settings, title="C", emis=6, first_due=days(settings, 5))
    with pytest.raises(ExpenseError, match="too large"):
        await expenses.create_payment(store, settings, title="D", emi_amount=999_999_999, emis=360, first_due=days(settings, 5))
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM ex_payments"))["n"] == 1        # nothing half-created


# ── one-off payments with a due date ("minimum due") ─────────────────────
async def test_a_one_off_due_payment_is_a_single_dated_amount(store, settings):
    pay = await expenses.create_payment(store, settings, title="Card bill", kind="due", emi_amount=1500, total=48000, first_due=days(settings, 6), grp="Cards")
    assert pay["kind"] == "due" and pay["emi_count"] == 1 and pay["total_minor"] == 4800000 and amounts(pay) == [150000]
    assert pay["mismatch_minor"] == 0                                            # the outstanding total is not an instalment total
    ov = (await expenses.snapshot(store, settings))["overview"]
    assert ov["due_30"]["amount_minor"] == 150000 and ov["next"]["payment"] == "Card bill"
    reminder = await store.fetchone("SELECT title FROM reminders WHERE session_id = 'expenses' AND status = 'pending'")
    assert reminder["title"] == "Card bill · ₹1,500 due tomorrow"                                  # reads naturally, not "EMI 1/1"
    paid = await expenses.update_emi(store, settings, pay["emis"][0]["id"], paid=True)
    assert paid["finished"] is True
    with pytest.raises(ExpenseError, match="more EMIs"):
        await expenses.add_emi(store, settings, pay["id"])
    with pytest.raises(ExpenseError, match="Only a payment with EMIs can be spread"):
        await expenses.rebalance(store, settings, pay["id"])


async def test_due_amount_only_needs_one_figure_and_cannot_exceed_the_outstanding_total(store, settings):
    pay = await expenses.create_payment(store, settings, title="Bill", kind="due", total=700, first_due=days(settings, 2))
    assert pay["total_minor"] == 70000 and amounts(pay) == [70000]
    with pytest.raises(ExpenseError, match="cannot be more than the total"):
        await expenses.create_payment(store, settings, title="Bad", kind="due", emi_amount=900, total=800, first_due=days(settings, 2))
    with pytest.raises(ExpenseError, match="due date"):
        await expenses.create_payment(store, settings, title="NoDate", kind="due", total=100)
    with pytest.raises(ExpenseError, match="kind must be"):
        await expenses.create_payment(store, settings, title="X", kind="weekly", total=100, first_due=days(settings, 2))


# ── money owed with no date ──────────────────────────────────────────────
async def test_an_open_payment_has_no_date_no_reminder_and_is_never_overdue(store, settings):
    pay = await expenses.create_payment(store, settings, title="Owe Rahul", kind="open", total=5000, grp="Personal")
    assert pay["kind"] == "open" and pay["emis"] == [] and pay["next_due"] is None and pay["finished"] is False
    assert pay["remaining_minor"] == 500000 and pay["mismatch_minor"] == 0
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses'"))["n"] == 0
    snap = await expenses.snapshot(store, settings)
    ov = snap["overview"]
    assert ov["open"] == {"count": 1, "amount_minor": 500000} and ov["overdue"]["count"] == 0 and ov["due_30"]["count"] == 0
    assert any("no due date" in i["text"] for i in snap["insights"])
    with pytest.raises(ExpenseError, match="has no EMIs"):
        await expenses.mark_next_paid(store, settings, pay["id"])


async def test_open_payments_can_be_part_paid_settled_and_reopened(store, settings):
    pay = await expenses.create_payment(store, settings, title="Owe Rahul", kind="open", total=5000)
    pay = await expenses.update_payment(store, settings, pay["id"], open_paid=2000)
    assert pay["paid_minor"] == 200000 and pay["remaining_minor"] == 300000 and pay["finished"] is False
    pay = await expenses.update_payment(store, settings, pay["id"], open_paid=5000)             # paid in full settles it by itself
    assert pay["finished"] is True and pay["remaining_minor"] == 0 and pay["settled_at"]
    pay = await expenses.update_payment(store, settings, pay["id"], settled=False)              # reopen
    assert pay["finished"] is False
    pay = await expenses.update_payment(store, settings, pay["id"], open_paid=1000)
    pay = await expenses.update_payment(store, settings, pay["id"], settled=True)               # "settled" means paid in full
    assert pay["finished"] is True and pay["paid_minor"] == 500000
    pay = await expenses.update_payment(store, settings, pay["id"], total=8000)                 # owed more than thought: reopens itself
    assert pay["finished"] is False and pay["remaining_minor"] == 300000
    emi_pay = await make(store, settings)
    with pytest.raises(ExpenseError, match="Only a payment without a due date"):
        await expenses.update_payment(store, settings, emi_pay["id"], settled=True)


# ── groups: totals without a group, bank checks with everything ──────────
async def test_groups_filter_the_totals_but_not_the_bank_shortfall(store, settings):
    bank = await expenses.create_bank(store, "HDFC", 100)
    home = await make(store, settings, title="Home loan", total=60000, emis=12, grp="Home loan", bank_id=bank["id"], first_due=days(settings, 3))
    other = await make(store, settings, title="Phone", total=12000, emis=6, first_due=days(settings, 4))
    everything = await expenses.snapshot(store, settings)
    assert everything["overview"]["remaining_minor"] == 6000000 + 1200000
    assert [g["label"] for g in everything["groups"]] == ["Home loan", "Ungrouped"] and all(g["included"] for g in everything["groups"])

    without_home = await expenses.snapshot(store, settings, exclude="Home loan")
    assert without_home["overview"]["remaining_minor"] == 1200000                              # the phone only
    assert without_home["overview"]["payments"] == 1 and without_home["hidden"]["payments"] == 1
    assert [g["included"] for g in without_home["groups"]] == [False, True]
    assert without_home["overview"]["banks"][0]["shortfall_minor"] > 0                        # the hidden EMI still has to be paid
    assert len(without_home["payments"]) == 2                                                  # the list is complete; only the totals filter
    assert {p["title"]: p["included"] for p in without_home["payments"]} == {"Home loan": False, "Phone": True}

    only_home = await expenses.snapshot(store, settings, exclude="~ungrouped")
    assert only_home["overview"]["remaining_minor"] == 6000000
    assert (await expenses.snapshot(store, settings, exclude=" HOME LOAN ,"))["overview"]["remaining_minor"] == 1200000   # case/space tolerant
    assert other["grp"] == "" and home["grp"] == "Home loan"


async def test_hidden_overdue_emis_are_reported_so_they_are_not_forgotten(store, settings):
    await make(store, settings, title="Old loan", total=1000, emis=2, grp="Old", first_due=days(settings, -40))
    snap = await expenses.snapshot(store, settings, exclude="Old")
    assert snap["overview"]["overdue"]["count"] == 0 and snap["hidden"]["overdue"] >= 1


async def test_group_names_are_cleaned(store, settings):
    pay = await make(store, settings, grp="  Home,   loan  ")
    assert pay["grp"] == "Home loan"
    with pytest.raises(ExpenseError, match="too long"):
        await make(store, settings, grp="x" * 41)
    pay = await expenses.update_payment(store, settings, pay["id"], grp="")
    assert pay["grp"] == ""


# ── several EMIs at once ─────────────────────────────────────────────────
async def test_marking_several_emis_paid_at_once_with_the_bank_deduction(store, settings):
    bank = await expenses.create_bank(store, "SBI", 10000)
    pay = await make(store, settings, total=4000, emis=4, bank_id=bank["id"])
    ids = [e["id"] for e in pay["emis"][:3]]
    result = await expenses.set_emis_paid(store, settings, ids, paid=True, deduct=True)
    assert result == {"changed": 3, "skipped": 0}
    pay = await expenses.get_payment(store, settings, pay["id"])
    assert pay["paid_count"] == 3
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks WHERE id = ?", (bank["id"],)))["balance_minor"] == 1000000 - 300000
    again = await expenses.set_emis_paid(store, settings, ids + [pay["emis"][3]["id"]], paid=True)     # already-paid ones are skipped, not errors
    assert again == {"changed": 1, "skipped": 3}
    undone = await expenses.set_emis_paid(store, settings, ids, paid=False)
    assert undone["changed"] == 3
    assert (await store.fetchone("SELECT balance_minor FROM ex_banks WHERE id = ?", (bank["id"],)))["balance_minor"] == 1000000   # exactly restored; the 4th was marked paid without a deduction, so it takes nothing back


async def test_bulk_validation_changes_nothing_when_any_id_is_bad(store, settings):
    pay = await make(store, settings)
    with pytest.raises(NotFound):
        await expenses.set_emis_paid(store, settings, [pay["emis"][0]["id"], 99999], paid=True)
    assert (await expenses.get_payment(store, settings, pay["id"]))["paid_count"] == 0
    with pytest.raises(ExpenseError, match="at least one"):
        await expenses.set_emis_paid(store, settings, [], paid=True)
    with pytest.raises(ExpenseError, match="at most"):
        await expenses.set_emis_paid(store, settings, list(range(1, expenses.MAX_BULK + 2)), paid=True)
    with pytest.raises(ExpenseError, match="could not be read"):
        await expenses.set_emis_paid(store, settings, ["abc"], paid=True)


# ── existing data: the one-time protection of hand-set amounts ───────────
async def seed_old_shape(store):
    """Invented amounts with the shapes that matter: a loan whose LAST emi was set lower by hand, a plan whose last emi is
    slightly lower, a plan whose last emi only carries the rounding remainder, and a plan with every emi equal. Rows are inserted as the old code (no flag) did."""
    async def payment(title, amounts_minor, paid):
        pid = await store.execute(
            "INSERT INTO ex_payments (title, category, notes, total_minor, bank_id, due_day, remind_days, created_at, updated_at) VALUES (?, 'card', '', ?, NULL, 8, NULL, 'x', 'x')",
            (title, sum(amounts_minor)))
        for i, a in enumerate(amounts_minor):
            await store.execute("INSERT INTO ex_emis (payment_id, seq, amount_minor, due_date, paid_at) VALUES (?, ?, ?, ?, ?)",
                                (pid, i + 1, a, f"2027-{(i % 12) + 1:02d}-08", "2026-11-24T00:00:00+00:00" if i < paid else None))
        return pid

    return {
        "Loan A": await payment("Loan A", [120000] * 23 + [85000], 2),                                   # last set lower by hand
        "plan_b": await payment("Plan B", [60000] + [70000] * 10 + [69400], 1),                    # last slightly lower
        "plan_c": await payment("Plan C", [50000] * 24, 5),                                      # untouched
        "remainder": await payment("remainder", [100000] * 11 + [100007], 0),                         # last = base + rounding remainder
    }


async def test_existing_hand_set_amounts_are_protected_and_nothing_is_rewritten(store, settings):
    ids = await seed_old_shape(store)
    before = {r["id"]: r["amount_minor"] for r in await store.fetchall("SELECT id, amount_minor FROM ex_emis")}
    snap = await expenses.snapshot(store, settings)                                     # first read triggers the one-time pass
    after = {r["id"]: r["amount_minor"] for r in await store.fetchall("SELECT id, amount_minor FROM ex_emis")}
    assert after == before                                                              # not a single amount changed
    flagged = {p["title"]: [e["seq"] for e in p["emis"] if e["custom"]] for p in snap["payments"]}
    assert flagged["Loan A"] == [24] and flagged["Plan B"] == [12]                        # lower-than-usual last emi: the user set it
    assert flagged["Plan C"] == [] and flagged["remainder"] == []                # all equal / plain rounding remainder: not fixed
    again = await expenses.snapshot(store, settings)                                    # runs once: a second pass flags nothing new
    assert [e["custom"] for p in again["payments"] for e in p["emis"]] == [e["custom"] for p in snap["payments"] for e in p["emis"]]
    row = await store.fetchone("SELECT value FROM app_settings WHERE id = ?", (expenses.BACKFILL_KEY,))
    assert row and int(row["value"]) == 2
    assert ids["Loan A"]


async def test_spreading_after_the_upgrade_keeps_the_amount_the_user_set(store, settings):
    ids = await seed_old_shape(store)
    done = await expenses.rebalance(store, settings, ids["Loan A"])
    got = amounts(done)
    assert got[-1] == 85000                                                            # the hand-set last emi is exactly what it was
    assert got[:2] == [120000, 120000] and got[2:-1] == [120000] * 21                   # the rest were already equal, still are
    assert sum(got) == done["total_minor"]


async def test_paid_emis_are_not_flagged_by_the_backfill(store, settings):
    pid = await store.execute("INSERT INTO ex_payments (title, category, notes, total_minor, bank_id, due_day, remind_days, created_at, updated_at) VALUES ('p', 'other', '', 300, NULL, 1, NULL, 'x', 'x')")
    for seq, (amount, paid) in enumerate([(100, "2026-01-01"), (50, None), (100, None)], start=1):
        await store.execute("INSERT INTO ex_emis (payment_id, seq, amount_minor, due_date, paid_at) VALUES (?, ?, ?, '2027-01-01', ?)", (pid, seq, amount, paid))
    pay = await expenses.get_payment(store, settings, pid)
    assert [e["custom"] for e in pay["emis"]] == [False, True, False]


async def test_a_fresh_database_gets_the_flag_set_without_flagging_anything(store, settings):
    pay = await make(store, settings, total=1000, emis=7)                                # 142.86 x6 + remainder, created by the new code
    assert not any(e["custom"] for e in pay["emis"])
    assert (await store.fetchone("SELECT value FROM app_settings WHERE id = ?", (expenses.BACKFILL_KEY,)))["value"] == "0"


async def test_csv_has_group_and_kind_and_includes_open_payments(store, settings):
    await make(store, settings, title="Home loan", grp="Mine", total=100, emis=1)
    await expenses.create_payment(store, settings, title="=cmd", kind="open", total=50, grp="Friends")
    out = await expenses.export_csv(store, settings)
    lines = out.strip().splitlines()
    assert lines[0].startswith("payment,group,kind,category")
    assert any(l.startswith("Home loan,Mine,emi,") for l in lines)
    assert any(l.startswith("'=cmd,Friends,open,") and ",owed," in l for l in lines)      # formula-neutralised, shown as owed
