"""Chat skills for the expense tracker: the same service the Money tab uses, so both always agree."""

from __future__ import annotations

from typing import Any

from src.agent import expenses
from src.agent.skill import SkillContext, SkillRegistry, schema


def _fmt(ctx: SkillContext, minor: int) -> str:
    return expenses.money(minor, ctx.settings.currency)


async def add_payment_plan(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        bank_id = None
        if args.get("bank"):
            banks = await ctx.store.fetchall("SELECT id, name FROM ex_banks WHERE LOWER(name) = ?", (str(args["bank"]).strip().lower(),))
            if not banks:
                known = ", ".join(r["name"] for r in await ctx.store.fetchall("SELECT name FROM ex_banks ORDER BY name")) or "none yet"
                return f"I don't have a bank called '{args['bank']}' (known banks: {known}). Add it in the Money tab, or leave the bank out."
            bank_id = banks[0]["id"]
        pay = await expenses.create_payment(
            ctx.store, ctx.settings, title=args.get("title"), total=args.get("total_amount"), emis=args.get("emis", 1),
            first_due=args.get("first_due_date"), day=args.get("day_of_month"), bank_id=bank_id,
            category=args.get("category") or "other", remind_days=args.get("remind_days_before", 1),
        )
    except expenses.ExpenseError as exc:
        return str(exc)
    first, last = pay["emis"][0], pay["emis"][-1]
    return (f"Added '{pay['title']}': {_fmt(ctx, pay['total_minor'])} in {pay['emi_count']} EMI(s), "
            f"{_fmt(ctx, first['amount_minor'])} each from {first['due_date']} to {last['due_date']}. "
            "You can change any EMI's amount or date, or mark EMIs paid, in the Money tab.")


async def mark_emi_paid(ctx: SkillContext, args: dict[str, Any]) -> str:
    paid = args.get("paid", True)
    if not isinstance(paid, bool):
        return "'paid' must be true or false."
    try:
        pay = await expenses.find_payment(ctx.store, ctx.settings, args.get("payment", ""))
        number = args.get("emi_number")
        if paid:
            if number in (None, "", "next"):
                updated = await expenses.mark_next_paid(ctx.store, ctx.settings, pay["id"], deduct=bool(args.get("deduct_from_bank")))
                done = next(e for e in reversed(updated["emis"]) if e["status"] == "paid")
            else:
                done = _by_number(pay, number)
                updated = await expenses.update_emi(ctx.store, ctx.settings, done["id"], paid=True, deduct=bool(args.get("deduct_from_bank")))
            return (f"Marked EMI {done['seq']} of {updated['emi_count']} for '{updated['title']}' as paid "
                    f"({_fmt(ctx, done['amount_minor'])}). {updated['emi_count'] - updated['paid_count']} left, "
                    f"{_fmt(ctx, updated['remaining_minor'])} remaining.")
        if number in (None, "", "next"):
            return "Which EMI should I mark as unpaid? Give its number."
        target = _by_number(pay, number)
        updated = await expenses.update_emi(ctx.store, ctx.settings, target["id"], paid=False)
        return f"EMI {target['seq']} of '{updated['title']}' is marked unpaid again."
    except expenses.ExpenseError as exc:
        return str(exc)


def _by_number(pay: dict[str, Any], number: Any) -> dict[str, Any]:
    try:
        wanted = int(number)
    except (TypeError, ValueError):
        raise expenses.ExpenseError("The EMI number must be a number, like 3, or 'next'.") from None
    for e in pay["emis"]:
        if e["seq"] == wanted:
            return e
    raise expenses.NotFound(f"'{pay['title']}' has {pay['emi_count']} EMIs; there is no number {wanted}.")


async def expense_summary(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    snap = await expenses.snapshot(ctx.store, ctx.settings)
    ov = snap["overview"]
    fmt = lambda minor: _fmt(ctx, minor)   # noqa: E731
    return {
        "payments_tracked": ov["payments"], "remaining_to_pay": fmt(ov["remaining_minor"]),
        "overdue": {"count": ov["overdue"]["count"], "amount": fmt(ov["overdue"]["amount_minor"])},
        "due_in_7_days": {"count": ov["due_7"]["count"], "amount": fmt(ov["due_7"]["amount_minor"])},
        "due_in_30_days": {"count": ov["due_30"]["count"], "amount": fmt(ov["due_30"]["amount_minor"])},
        "next_emi": ({"payment": ov["next"]["payment"], "number": ov["next"]["seq"], "of": ov["next"]["of"], "due": ov["next"]["due_date"],
                      "amount": fmt(ov["next"]["amount_minor"])} if ov["next"] else None),
        "last_emi_on": ov["free_by"],
        "banks": [{"name": b["name"], "balance": fmt(b["balance_minor"]), "short_for_next_30_days": fmt(b["shortfall_minor"])} for b in ov["banks"]],
        "payments": [{"title": p["title"], "paid": f"{p['paid_count']}/{p['emi_count']}", "remaining": fmt(p["remaining_minor"]), "next_due": p["next_due"]}
                     for p in snap["payments"] if not p["finished"]][:30],
        "advice": [i["text"] for i in snap["insights"]],
    }


def register(registry: SkillRegistry) -> None:
    registry.add(
        "add_payment_plan",
        "Track a payment the user must make, split into monthly EMIs (a loan, card bill, phone/appliance on EMI, insurance, rent). "
        "Needs the total, number of EMIs and the date of the first EMI; later EMIs fall on the same day each month. "
        "Reminders are created automatically.",
        schema({
            "title": {"type": "string", "description": "What it is, e.g. 'Car loan'."},
            "total_amount": {"type": "number", "description": "Total amount to pay in all, in the user's currency."},
            "emis": {"type": "integer", "description": "Number of monthly EMIs (1 for a one-off payment).", "minimum": 1, "maximum": 360},
            "first_due_date": {"type": "string", "description": "Date of the first EMI, ISO format YYYY-MM-DD."},
            "day_of_month": {"type": "integer", "description": "Optional common day (1-31) for every EMI after the first.", "minimum": 1, "maximum": 31},
            "bank": {"type": "string", "description": "Optional name of a bank the user already added."},
            "category": {"type": "string", "enum": list(expenses.CATEGORIES)},
            "remind_days_before": {"type": "integer", "description": "Remind this many days before each EMI (0-7). Default 1.", "minimum": 0, "maximum": 7},
        }, ["title", "total_amount", "emis", "first_due_date"]),
        add_payment_plan,
    )
    registry.add(
        "mark_emi_paid",
        "Mark an EMI as paid (or unpaid again). 'emi_number' omitted or 'next' means the earliest unpaid EMI.",
        schema({
            "payment": {"type": "string", "description": "Name of the payment, e.g. 'car loan'."},
            "emi_number": {"type": ["integer", "string"], "description": "EMI number, or 'next'."},
            "paid": {"type": "boolean", "description": "true to mark paid (default), false to undo."},
            "deduct_from_bank": {"type": "boolean", "description": "Also reduce the linked bank's balance by the EMI amount (only if the user asks)."},
        }, ["payment"]),
        mark_emi_paid,
    )
    registry.add(
        "expense_summary",
        "The user's payments and EMIs at a glance: what is overdue, due soon, next EMI, bank balances, shortfalls and rule-based advice. "
        "Use for 'what EMIs are due', 'how much do I owe', 'can I afford my EMIs', then answer conversationally.",
        schema(),
        expense_summary,
    )
