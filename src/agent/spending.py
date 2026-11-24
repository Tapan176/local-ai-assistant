"""Day-to-day spending and subscriptions, alongside the payments/EMI tracker in ``expenses``.

* Spending is a simple ledger: amount, day, category, note. The month view totals it, compares it with last month, shows the
  split by category and, for the current month, projects where it will end. An optional monthly budget turns that into a bar.
* A subscription renews on a cycle (weekly / monthly / quarterly / yearly). Everything is also shown as a monthly figure so
  "what do my subscriptions really cost" has one honest answer. Renewing records the charge as spending (optional), moves the
  next date forward without day-of-month drift (31 Jan -> 28 Feb -> 31 Mar) and keeps one reminder pointing at the next one.
Money is integer minor units, exactly as in ``expenses``.
"""

from __future__ import annotations

import asyncio
import calendar
import csv
import io
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from src.agent import timeutil
from src.agent.expenses import (
    ExpenseError, NotFound, _UNSET, _csv_cell, _now_iso, _remind_days, _require_bank_id, _today, _when_phrase,
    clean_text, emi_date, money, month_offset, parse_date, reminder_ops, to_minor,
)
from src.config.settings import Settings

SPEND_CATEGORIES = ("food", "groceries", "transport", "shopping", "bills", "rent", "health", "entertainment", "travel",
                    "education", "personal", "gifts", "other")
SUB_CATEGORIES = ("entertainment", "music", "software", "cloud", "news", "fitness", "education", "shopping", "bills", "other")
CYCLES = ("weekly", "monthly", "quarterly", "yearly")
MAX_SPEND_ROWS = 50_000
MAX_LIST = 500
MAX_SUBS = 100
BUDGET_KEY = "ex_budget"
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_lock = asyncio.Lock()


# ── months ─────────────────────────────────────────────────────────────
def month_range(month: Any, today: date) -> tuple[str, date, date]:
    """('2026-11', first day, first day of next month). Defaults to the month of ``today``."""
    key = today.strftime("%Y-%m") if month in (None, "") else str(month).strip()
    if not _MONTH.match(key):
        raise ExpenseError("The month must look like 2026-11.")
    year, mon = int(key[:4]), int(key[5:])
    nxt_year, nxt_mon = month_offset(date(year, mon, 1), 1)
    return key, date(year, mon, 1), date(nxt_year, nxt_mon, 1)


def _prev_month(start: date) -> tuple[date, date]:
    year, mon = month_offset(start, -1)
    return date(year, mon, 1), start


# ── spending ledger ────────────────────────────────────────────────────
def _spend_row(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "spent_on": r["spent_on"], "amount_minor": int(r["amount_minor"]), "category": r["category"], "note": r["note"], "sub_id": r["sub_id"]}


def _category(value: Any, allowed: tuple[str, ...]) -> str:
    text = str(value or "other").strip().lower()
    if text not in allowed:
        raise ExpenseError(f"The category must be one of: {', '.join(allowed)}.")
    return text


def _spend_date(value: Any, settings: Settings) -> date:
    today = _today(settings)
    if value in (None, ""):
        return today
    day = parse_date(value, "date")
    if day > today + timedelta(days=1):
        raise ExpenseError("That date is in the future. Spending is something you have already done.")
    if day.year < 2000:
        raise ExpenseError("That date is too far in the past.")
    return day


async def add_spend(store: Any, settings: Settings, *, amount: Any, spent_on: Any = None, category: Any = "other", note: Any = "",
                    sub_id: int | None = None) -> dict[str, Any]:
    minor = to_minor(amount)
    day = _spend_date(spent_on, settings)
    cat = _category(category, SPEND_CATEGORIES)
    text = clean_text(note, "note", limit=200)
    if (await store.fetchone("SELECT COUNT(*) AS n FROM ex_spend"))["n"] >= MAX_SPEND_ROWS:
        raise ExpenseError("The spending log is full. Export it and delete old entries first.")
    new_id = await store.execute(
        "INSERT INTO ex_spend (spent_on, amount_minor, category, note, sub_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (day.isoformat(), minor, cat, text, sub_id, _now_iso()),
    )
    return {"id": new_id, "spent_on": day.isoformat(), "amount_minor": minor, "category": cat, "note": text, "sub_id": sub_id}    # what was just written: no second read


async def _spend_one(store: Any, spend_id: int) -> dict[str, Any]:
    row = await store.fetchone("SELECT * FROM ex_spend WHERE id = ?", (spend_id,))
    if not row:
        raise NotFound("That entry no longer exists.")
    return _spend_row(row)


async def update_spend(store: Any, settings: Settings, spend_id: int, *, amount: Any = _UNSET, spent_on: Any = _UNSET,
                       category: Any = _UNSET, note: Any = _UNSET) -> dict[str, Any]:
    await _spend_one(store, spend_id)
    sets: list[str] = []
    params: list[Any] = []
    if amount is not _UNSET:
        sets.append("amount_minor = ?"); params.append(to_minor(amount))
    if spent_on is not _UNSET:
        sets.append("spent_on = ?"); params.append(_spend_date(spent_on, settings).isoformat())
    if category is not _UNSET:
        sets.append("category = ?"); params.append(_category(category, SPEND_CATEGORIES))
    if note is not _UNSET:
        sets.append("note = ?"); params.append(clean_text(note, "note", limit=200))
    if sets:
        await store.execute(f"UPDATE ex_spend SET {', '.join(sets)} WHERE id = ?", (*params, spend_id))
    return await _spend_one(store, spend_id)


async def delete_spend(store: Any, spend_id: int) -> None:
    await _spend_one(store, spend_id)
    await store.execute("DELETE FROM ex_spend WHERE id = ?", (spend_id,))


async def get_budget(store: Any) -> int | None:
    row = await store.fetchone("SELECT value FROM app_settings WHERE id = ?", (BUDGET_KEY,))
    try:
        return int(row["value"]) if row and int(row["value"]) > 0 else None
    except (TypeError, ValueError):
        return None


async def set_budget(store: Any, amount: Any) -> int | None:
    """A monthly spending limit; ``None``/empty/0 removes it."""
    if amount in (None, "", 0, "0"):
        await store.execute("DELETE FROM app_settings WHERE id = ?", (BUDGET_KEY,))
        return None
    minor = to_minor(amount, what="budget")
    await store.execute(
        "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (BUDGET_KEY, str(minor), _now_iso()),
    )
    return minor


async def _total(store: Any, start: date, end: date) -> int:
    row = await store.fetchone("SELECT COALESCE(SUM(amount_minor), 0) AS t FROM ex_spend WHERE spent_on >= ? AND spent_on < ?", (start.isoformat(), end.isoformat()))
    return int(row["t"])                      # Postgres returns a Decimal for SUM(bigint)


async def month_summary(store: Any, settings: Settings, month: Any = None) -> dict[str, Any]:
    today = _today(settings)
    key, start, end = month_range(month, today)
    s, e = start.isoformat(), end.isoformat()
    prev_start, prev_end = _prev_month(start)
    # five independent reads, side by side: one network round trip instead of five
    by_cat, by_day, top, prev_total, budget = await asyncio.gather(
        store.fetchall("SELECT category, SUM(amount_minor) AS t, COUNT(*) AS n FROM ex_spend WHERE spent_on >= ? AND spent_on < ? GROUP BY category", (s, e)),
        store.fetchall("SELECT spent_on, SUM(amount_minor) AS t FROM ex_spend WHERE spent_on >= ? AND spent_on < ? GROUP BY spent_on ORDER BY spent_on", (s, e)),
        store.fetchall("SELECT * FROM ex_spend WHERE spent_on >= ? AND spent_on < ? ORDER BY amount_minor DESC, id DESC LIMIT 5", (s, e)),
        _total(store, prev_start, prev_end),
        get_budget(store),
    )
    total = sum(int(r["t"]) for r in by_cat)
    count = sum(int(r["n"]) for r in by_cat)
    days_in_month = (end - start).days
    current = start <= today < end
    elapsed = (today - start).days + 1 if current else (days_in_month if today >= end else 0)
    categories = sorted(({"category": r["category"], "amount_minor": int(r["t"]), "count": int(r["n"]),
                          "share": round(int(r["t"]) * 100 / total) if total else 0} for r in by_cat), key=lambda c: -c["amount_minor"])
    return {
        "month": key, "current": current, "total_minor": total, "count": count, "previous_total_minor": prev_total,
        "change_pct": round((total - prev_total) * 100 / prev_total) if prev_total else None,
        "average_per_day_minor": total // elapsed if elapsed else 0,
        "projected_minor": total * days_in_month // elapsed if current and elapsed else None,
        "days_in_month": days_in_month, "day_of_month": elapsed if current else None,
        "categories": categories, "by_day": [{"date": r["spent_on"], "amount_minor": int(r["t"])} for r in by_day],
        "top": [_spend_row(r) for r in top],
        "budget_minor": budget, "budget_left_minor": None if budget is None else budget - total,
    }


async def list_spend(store: Any, settings: Settings, month: Any = None, category: Any = None, limit: int = MAX_LIST) -> dict[str, Any]:
    key, start, end = month_range(month, _today(settings))
    where, params = "spent_on >= ? AND spent_on < ?", [start.isoformat(), end.isoformat()]
    if category not in (None, ""):
        where += " AND category = ?"; params.append(_category(category, SPEND_CATEGORIES))
    rows = await store.fetchall(f"SELECT * FROM ex_spend WHERE {where} ORDER BY spent_on DESC, id DESC LIMIT ?", (*params, max(1, min(int(limit), MAX_LIST))))
    return {"month": key, "items": [_spend_row(r) for r in rows], "summary": await month_summary(store, settings, key), "categories": list(SPEND_CATEGORIES)}


async def export_spend_csv(store: Any) -> str:
    rows = await store.fetchall("SELECT * FROM ex_spend ORDER BY spent_on, id")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["date", "amount", "category", "note"])
    for r in rows:
        writer.writerow([r["spent_on"], f"{int(r['amount_minor']) / 100:.2f}", r["category"], _csv_cell(r["note"])])
    return out.getvalue()


# ── subscriptions ──────────────────────────────────────────────────────
def add_cycle(day: date, cycle: str, anchor_day: int) -> date:
    """The next renewal after ``day``. Monthly-style cycles return to the original day of month when the month allows it."""
    if cycle == "weekly":
        return day + timedelta(days=7)
    return emi_date(*month_offset(day, {"monthly": 1, "quarterly": 3, "yearly": 12}[cycle]), anchor_day)


def monthly_equivalent(amount_minor: int, cycle: str) -> int:
    num, den = {"weekly": (52, 12), "monthly": (1, 1), "quarterly": (1, 3), "yearly": (1, 12)}[cycle]
    return (amount_minor * num * 2 + den) // (den * 2)                  # rounded half up, in integers


def _shape_sub(r: dict[str, Any], today: date) -> dict[str, Any]:
    nxt = date.fromisoformat(r["next_date"])
    days = (nxt - today).days
    active = bool(r["active"])
    status = "paused" if not active else "overdue" if days < 0 else "soon" if days <= 7 else "ok"
    return {"id": r["id"], "name": r["name"], "amount_minor": int(r["amount_minor"]), "cycle": r["cycle"], "next_date": r["next_date"],
            "category": r["category"], "bank_id": r["bank_id"], "active": active, "notes": r["notes"], "remind_days": r["remind_days"],
            "monthly_minor": monthly_equivalent(int(r["amount_minor"]), r["cycle"]), "yearly_minor": monthly_equivalent(int(r["amount_minor"]), r["cycle"]) * 12,
            "days_until": days, "status": status}


async def _sub_row(store: Any, sub_id: int) -> dict[str, Any]:
    row = await store.fetchone("SELECT * FROM ex_subs WHERE id = ?", (sub_id,))
    if not row:
        raise NotFound("That subscription no longer exists.")
    return row


async def list_subs(store: Any, settings: Settings) -> dict[str, Any]:
    today = _today(settings)
    rows = await store.fetchall("SELECT * FROM ex_subs ORDER BY active DESC, next_date, id")
    subs = [_shape_sub(r, today) for r in rows]
    live = [s for s in subs if s["active"]]
    by_cat: dict[str, int] = {}
    for s in live:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + s["monthly_minor"]
    return {
        "subs": subs, "categories": list(SUB_CATEGORIES), "cycles": list(CYCLES),
        "summary": {"active": len(live), "paused": len(subs) - len(live), "monthly_minor": sum(s["monthly_minor"] for s in live),
                    "yearly_minor": sum(s["yearly_minor"] for s in live),
                    "due_7": {"count": sum(1 for s in live if s["days_until"] <= 7), "amount_minor": sum(s["amount_minor"] for s in live if s["days_until"] <= 7)},
                    "by_category": sorted(({"category": k, "monthly_minor": v} for k, v in by_cat.items()), key=lambda c: -c["monthly_minor"])},
    }


async def sync_sub_reminder(store: Any, settings: Settings, sub_id: int) -> None:
    """One reminder per subscription, always pointing at the next renewal (and gone when paused or switched off)."""
    sub = await store.fetchone("SELECT * FROM ex_subs WHERE id = ?", (sub_id,))
    if not sub:
        return
    want: tuple[str, str] | None = None
    if sub["active"] and sub["remind_days"] is not None:
        tz = timeutil.get_tz(settings)
        fire = datetime.combine(date.fromisoformat(sub["next_date"]) - timedelta(days=int(sub["remind_days"])), time(9, 0), tzinfo=tz)
        if fire > timeutil.now(settings):
            title = f"Subscription · {sub['name']} · {money(int(sub['amount_minor']), settings.currency)} renews {_when_phrase(int(sub['remind_days']))}"
            want = (fire.isoformat(), title[:200])
    current = await store.fetchone("SELECT id, title, due_at, status FROM reminders WHERE id = ?", (sub["reminder_id"],)) if sub["reminder_id"] else None
    ops = reminder_ops("ex_subs", sub_id, current, want, "expenses", bool(sub["reminder_id"]))
    if ops:
        await store.execute_transaction(ops)


async def create_sub(store: Any, settings: Settings, *, name: Any, amount: Any, cycle: Any = "monthly", next_date: Any = None,
                     category: Any = "other", bank_id: Any = None, notes: Any = "", remind_days: Any = 1) -> dict[str, Any]:
    name = clean_text(name, "subscription", limit=80, required=True)
    cycle = str(cycle or "monthly").lower()
    if cycle not in CYCLES:
        raise ExpenseError(f"The billing cycle must be one of: {', '.join(CYCLES)}.")
    minor = to_minor(amount)
    nxt = parse_date(next_date, "next renewal date") if next_date not in (None, "") else _today(settings)
    cat = _category(category, SUB_CATEGORIES)
    bank = await _require_bank_id(store, bank_id)
    remind = _remind_days(remind_days)
    if (await store.fetchone("SELECT COUNT(*) AS n FROM ex_subs"))["n"] >= MAX_SUBS:
        raise ExpenseError(f"You can track up to {MAX_SUBS} subscriptions.")
    now = _now_iso()
    sub_id = await store.execute(
        "INSERT INTO ex_subs (name, amount_minor, cycle, next_date, anchor_day, category, bank_id, active, notes, remind_days, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (name, minor, cycle, nxt.isoformat(), nxt.day, cat, bank, clean_text(notes, "note", limit=300), remind, now, now),
    )
    await sync_sub_reminder(store, settings, sub_id)
    return _shape_sub(await _sub_row(store, sub_id), _today(settings))


async def update_sub(store: Any, settings: Settings, sub_id: int, *, name: Any = _UNSET, amount: Any = _UNSET, cycle: Any = _UNSET,
                     next_date: Any = _UNSET, category: Any = _UNSET, bank_id: Any = _UNSET, notes: Any = _UNSET, active: Any = _UNSET,
                     remind_days: Any = _UNSET) -> dict[str, Any]:
    await _sub_row(store, sub_id)
    sets: list[str] = []
    params: list[Any] = []
    if name is not _UNSET:
        sets.append("name = ?"); params.append(clean_text(name, "subscription", limit=80, required=True))
    if amount is not _UNSET:
        sets.append("amount_minor = ?"); params.append(to_minor(amount))
    if cycle is not _UNSET:
        value = str(cycle or "").lower()
        if value not in CYCLES:
            raise ExpenseError(f"The billing cycle must be one of: {', '.join(CYCLES)}.")
        sets.append("cycle = ?"); params.append(value)
    if next_date is not _UNSET:
        nxt = parse_date(next_date, "next renewal date")
        sets.append("next_date = ?"); params.append(nxt.isoformat())
        sets.append("anchor_day = ?"); params.append(nxt.day)
    if category is not _UNSET:
        sets.append("category = ?"); params.append(_category(category, SUB_CATEGORIES))
    if bank_id is not _UNSET:
        sets.append("bank_id = ?"); params.append(await _require_bank_id(store, bank_id))
    if notes is not _UNSET:
        sets.append("notes = ?"); params.append(clean_text(notes, "note", limit=300))
    if active is not _UNSET:
        sets.append("active = ?"); params.append(1 if active else 0)
    if remind_days is not _UNSET:
        sets.append("remind_days = ?"); params.append(_remind_days(remind_days))
    if sets:
        await store.execute(f"UPDATE ex_subs SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*params, _now_iso(), sub_id))
        await sync_sub_reminder(store, settings, sub_id)
    return _shape_sub(await _sub_row(store, sub_id), _today(settings))


async def delete_sub(store: Any, sub_id: int) -> None:
    sub = await _sub_row(store, sub_id)
    if sub["reminder_id"]:
        await store.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (sub["reminder_id"],))
    await store.execute_transaction([
        ("UPDATE ex_spend SET sub_id = NULL WHERE sub_id = ?", (sub_id,)),           # the money was spent; only the link goes
        ("DELETE FROM ex_subs WHERE id = ?", (sub_id,)),
    ])


async def renew_sub(store: Any, settings: Settings, sub_id: int, *, record: bool = True, deduct: bool = False) -> dict[str, Any]:
    """The renewal has been paid: log it as spending, optionally take it off the bank balance, and move to the next date."""
    async with _lock:
        sub = await _sub_row(store, sub_id)
        if not sub["active"]:
            raise ExpenseError("This subscription is paused. Resume it first.")
        today = _today(settings)
        due = date.fromisoformat(sub["next_date"])
        nxt = add_cycle(due, sub["cycle"], int(sub["anchor_day"]) or due.day)
        ops: list[tuple[str, tuple[Any, ...]]] = [("UPDATE ex_subs SET next_date = ?, updated_at = ? WHERE id = ?", (nxt.isoformat(), _now_iso(), sub_id))]
        if record:
            ops.append(("INSERT INTO ex_spend (spent_on, amount_minor, category, note, sub_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (min(due, today).isoformat(), int(sub["amount_minor"]), _spend_category_for(sub["category"]), sub["name"], sub_id, _now_iso())))
        if deduct and sub["bank_id"] and await store.fetchone("SELECT id FROM ex_banks WHERE id = ?", (sub["bank_id"],)):
            ops.append(("UPDATE ex_banks SET balance_minor = balance_minor - ?, updated_at = ? WHERE id = ?", (int(sub["amount_minor"]), _now_iso(), sub["bank_id"])))
        await store.execute_transaction(ops)
        await sync_sub_reminder(store, settings, sub_id)
    return _shape_sub(await _sub_row(store, sub_id), today)


def _spend_category_for(sub_category: str) -> str:
    return sub_category if sub_category in SPEND_CATEGORIES else "bills" if sub_category in ("software", "cloud", "news", "music") else "other"


# ── cards and rules for the overview ───────────────────────────────────
async def card(store: Any, settings: Settings) -> dict[str, Any]:
    """The small summary the Money overview shows: this month's spending and what subscriptions cost."""
    month, listing = await asyncio.gather(month_summary(store, settings), list_subs(store, settings))
    subs = listing["summary"]
    return {"month": month["month"], "spent_minor": month["total_minor"], "previous_minor": month["previous_total_minor"],
            "projected_minor": month["projected_minor"], "budget_minor": month["budget_minor"], "budget_left_minor": month["budget_left_minor"],
            "subs_monthly_minor": subs["monthly_minor"], "subs_yearly_minor": subs["yearly_minor"], "subs_active": subs["active"], "subs_due_7": subs["due_7"]["count"]}


def card_insights(c: dict[str, Any], currency: str) -> list[dict[str, str]]:
    fmt = lambda minor: money(minor, currency)   # noqa: E731
    out: list[dict[str, str]] = []
    if c["budget_minor"]:
        used = c["spent_minor"] * 100 // c["budget_minor"]
        if c["spent_minor"] > c["budget_minor"]:
            out.append({"level": "warn", "text": f"You have spent {fmt(c['spent_minor'])} this month, {fmt(c['spent_minor'] - c['budget_minor'])} over your {fmt(c['budget_minor'])} budget."})
        elif c["projected_minor"] and c["projected_minor"] > c["budget_minor"]:
            out.append({"level": "warn", "text": f"{used}% of your {fmt(c['budget_minor'])} budget is gone, and at this pace you will end the month near {fmt(c['projected_minor'])}."})
        elif used >= 80:
            out.append({"level": "info", "text": f"{used}% of this month's budget is used."})
    if c["subs_active"]:
        out.append({"level": "info", "text": f"Your {c['subs_active']} active subscription(s) cost {fmt(c['subs_monthly_minor'])} a month, {fmt(c['subs_yearly_minor'])} a year. Cancel what you no longer use."})
    return out
