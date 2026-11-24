"""Authenticated REST routes for the expense tracker. Every route needs the access token; nothing here is public."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.agent import expenses, spending
from src.config.settings import Settings

ADVICE_CACHE_SECONDS = 120
ADVICE_TIMEOUT_SECONDS = 45
ADVICE_MAX_CHARS = 2000


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BankIn(_Body):
    name: str = Field(max_length=200)
    balance: Any = 0
    note: str = Field(default="", max_length=400)


class BankPatch(_Body):
    name: str | None = Field(default=None, max_length=200)
    balance: Any = None
    note: str | None = Field(default=None, max_length=400)


class PaymentIn(_Body):
    title: str = Field(max_length=300)
    kind: str = Field(default="emi", max_length=10)           # emi | due (one dated amount) | open (no date)
    total: Any = None
    emi_amount: Any = None                                    # per-EMI amount: the total is worked out from it
    emis: Any = 1
    first_due: str | None = Field(default=None, max_length=40)
    day: Any = None
    bank_id: int | None = None
    category: str = Field(default="other", max_length=30)
    grp: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=1000)
    remind_days: Any = 1


class PaymentPatch(_Body):
    title: str | None = Field(default=None, max_length=300)
    total: Any = None
    bank_id: int | None = None
    category: str | None = Field(default=None, max_length=30)
    grp: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    remind_days: Any = None
    open_paid: Any = None
    settled: bool | None = None


class EmiPatch(_Body):
    amount: Any = None
    due_date: str | None = Field(default=None, max_length=40)
    paid: bool | None = None
    custom: bool | None = None                                # keep this amount when the rest are spread
    deduct: bool = False


class BulkPaidIn(_Body):
    ids: list[int] = Field(max_length=expenses.MAX_BULK)
    paid: bool = True
    deduct: bool = False


class RebalanceIn(_Body):
    reset: bool = False                                       # also replace the amounts the user fixed by hand


class SpendIn(_Body):
    amount: Any
    spent_on: str | None = Field(default=None, max_length=40)
    category: str = Field(default="other", max_length=30)
    note: str = Field(default="", max_length=400)


class SpendPatch(_Body):
    amount: Any = None
    spent_on: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=400)


class BudgetIn(_Body):
    amount: Any = None


class SubIn(_Body):
    name: str = Field(max_length=200)
    amount: Any
    cycle: str = Field(default="monthly", max_length=20)
    next_date: str | None = Field(default=None, max_length=40)
    category: str = Field(default="other", max_length=30)
    bank_id: int | None = None
    notes: str = Field(default="", max_length=600)
    remind_days: Any = 1


class SubPatch(_Body):
    name: str | None = Field(default=None, max_length=200)
    amount: Any = None
    cycle: str | None = Field(default=None, max_length=20)
    next_date: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=30)
    bank_id: int | None = None
    notes: str | None = Field(default=None, max_length=600)
    active: bool | None = None
    remind_days: Any = None


class RenewIn(_Body):
    record: bool = True                                       # log the charge as spending
    deduct: bool = False                                      # and take it off the bank balance


class EmiIn(_Body):
    amount: Any = None
    due_date: str | None = Field(default=None, max_length=40)


class RedateIn(_Body):
    day: Any


class NextPaidIn(_Body):
    deduct: bool = False


def register(app: FastAPI, *, runtime: Any, settings: Settings, require_auth: Callable, limiter: Any) -> None:
    store = runtime.sqlite_store
    auth = [Depends(require_auth)]
    advice_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def guarded(coro: Any) -> Any:
        try:
            return await coro
        except expenses.ExpenseError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    def provided(body: _Body, *names: str) -> dict[str, Any]:
        """Only the fields the client actually sent, so an explicit null can clear a value and an absent field is left alone."""
        return {n: getattr(body, n) for n in names if n in body.model_fields_set}

    # ── everything the screen needs, in one round trip ─────────────
    @app.get("/api/expenses", dependencies=auth)
    async def snapshot(exclude: str = "") -> dict[str, Any]:
        """``exclude``: comma-separated group names ('~ungrouped' for payments without one) left out of the overview totals."""
        data, card = await asyncio.gather(guarded(expenses.snapshot(store, settings, exclude=exclude[:600])), guarded(spending.card(store, settings)))
        data["spending"] = card
        data["insights"] = data["insights"] + spending.card_insights(card, settings.currency)
        return data

    # ── banks ──────────────────────────────────────────────────────
    @app.post("/api/expenses/banks", dependencies=auth)
    async def add_bank(body: BankIn) -> dict[str, Any]:
        return await guarded(expenses.create_bank(store, body.name, body.balance, body.note))

    @app.patch("/api/expenses/banks/{bank_id}", dependencies=auth)
    async def edit_bank(bank_id: int, body: BankPatch) -> dict[str, Any]:
        fields = provided(body, "name", "balance", "note")
        if any(v is None for v in fields.values()):
            raise HTTPException(status_code=400, detail="A bank's name, balance and note cannot be empty values.")
        return await guarded(expenses.update_bank(store, bank_id, **fields))

    @app.delete("/api/expenses/banks/{bank_id}", dependencies=auth)
    async def remove_bank(bank_id: int) -> dict[str, bool]:
        await guarded(expenses.delete_bank(store, bank_id))
        return {"ok": True}

    # ── payments ───────────────────────────────────────────────────
    @app.post("/api/expenses/payments", dependencies=auth)
    async def add_payment(body: PaymentIn) -> dict[str, Any]:
        return await guarded(expenses.create_payment(
            store, settings, title=body.title, kind=body.kind, total=body.total, emi_amount=body.emi_amount, emis=body.emis,
            first_due=body.first_due, day=body.day, bank_id=body.bank_id, category=body.category, grp=body.grp,
            notes=body.notes, remind_days=body.remind_days))

    @app.patch("/api/expenses/payments/{payment_id}", dependencies=auth)
    async def edit_payment(payment_id: int, body: PaymentPatch) -> dict[str, Any]:
        fields = provided(body, "title", "total", "bank_id", "category", "notes", "remind_days", "grp", "open_paid", "settled")
        for required in ("title", "total", "category", "notes", "grp", "open_paid", "settled"):
            if required in fields and fields[required] is None:
                raise HTTPException(status_code=400, detail=f"The {required} cannot be empty.")
        return await guarded(expenses.update_payment(store, settings, payment_id, **fields))

    @app.delete("/api/expenses/payments/{payment_id}", dependencies=auth)
    async def remove_payment(payment_id: int) -> dict[str, bool]:
        await guarded(expenses.delete_payment(store, payment_id))
        return {"ok": True}

    @app.post("/api/expenses/payments/{payment_id}/redate", dependencies=auth)
    async def redate(payment_id: int, body: RedateIn) -> dict[str, Any]:
        return await guarded(expenses.redate(store, settings, payment_id, body.day))

    @app.post("/api/expenses/payments/{payment_id}/rebalance", dependencies=auth)
    async def rebalance(payment_id: int, body: RebalanceIn | None = None) -> dict[str, Any]:
        return await guarded(expenses.rebalance(store, settings, payment_id, reset=bool(body and body.reset)))

    @app.post("/api/expenses/payments/{payment_id}/pay-next", dependencies=auth)
    async def pay_next(payment_id: int, body: NextPaidIn) -> dict[str, Any]:
        return await guarded(expenses.mark_next_paid(store, settings, payment_id, deduct=body.deduct))

    @app.post("/api/expenses/payments/{payment_id}/emis", dependencies=auth)
    async def add_emi(payment_id: int, body: EmiIn) -> dict[str, Any]:
        return await guarded(expenses.add_emi(store, settings, payment_id, amount=body.amount, due_date=body.due_date))

    # ── single EMIs ────────────────────────────────────────────────
    @app.patch("/api/expenses/emis/{emi_id}", dependencies=auth)
    async def edit_emi(emi_id: int, body: EmiPatch) -> dict[str, Any]:
        fields = provided(body, "amount", "due_date", "paid", "custom")
        if any(v is None for v in fields.values()):
            raise HTTPException(status_code=400, detail="Send a value for each field you change.")
        return await guarded(expenses.update_emi(store, settings, emi_id, deduct=body.deduct, **fields))

    @app.post("/api/expenses/emis/bulk", dependencies=auth)
    async def bulk_paid(body: BulkPaidIn) -> dict[str, Any]:
        return await guarded(expenses.set_emis_paid(store, settings, body.ids, paid=body.paid, deduct=body.deduct))

    @app.delete("/api/expenses/emis/{emi_id}", dependencies=auth)
    async def remove_emi(emi_id: int) -> dict[str, Any]:
        return await guarded(expenses.delete_emi(store, settings, emi_id))

    # ── day-to-day spending ────────────────────────────────────────
    @app.get("/api/expenses/spending", dependencies=auth)
    async def spending_list(month: str | None = None, category: str | None = None) -> dict[str, Any]:
        return await guarded(spending.list_spend(store, settings, month, category))

    @app.post("/api/expenses/spending", dependencies=auth)
    async def spending_add(body: SpendIn) -> dict[str, Any]:
        return await guarded(spending.add_spend(store, settings, amount=body.amount, spent_on=body.spent_on, category=body.category, note=body.note))

    @app.patch("/api/expenses/spending/{spend_id}", dependencies=auth)
    async def spending_edit(spend_id: int, body: SpendPatch) -> dict[str, Any]:
        fields = provided(body, "amount", "spent_on", "category", "note")
        if any(v is None for v in fields.values()):
            raise HTTPException(status_code=400, detail="Send a value for each field you change.")
        return await guarded(spending.update_spend(store, settings, spend_id, **fields))

    @app.delete("/api/expenses/spending/{spend_id}", dependencies=auth)
    async def spending_remove(spend_id: int) -> dict[str, bool]:
        await guarded(spending.delete_spend(store, spend_id))
        return {"ok": True}

    @app.put("/api/expenses/budget", dependencies=auth)
    async def budget_set(body: BudgetIn) -> dict[str, Any]:
        return {"budget_minor": await guarded(spending.set_budget(store, body.amount))}

    @app.get("/api/expenses/spending-export", dependencies=auth)
    async def spending_export() -> Response:
        data = await guarded(spending.export_spend_csv(store))
        return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="tapan-spending.csv"'})

    # ── subscriptions ──────────────────────────────────────────────
    @app.get("/api/expenses/subscriptions", dependencies=auth)
    async def subs_list() -> dict[str, Any]:
        return await guarded(spending.list_subs(store, settings))

    @app.post("/api/expenses/subscriptions", dependencies=auth)
    async def subs_add(body: SubIn) -> dict[str, Any]:
        return await guarded(spending.create_sub(
            store, settings, name=body.name, amount=body.amount, cycle=body.cycle, next_date=body.next_date,
            category=body.category, bank_id=body.bank_id, notes=body.notes, remind_days=body.remind_days))

    @app.patch("/api/expenses/subscriptions/{sub_id}", dependencies=auth)
    async def subs_edit(sub_id: int, body: SubPatch) -> dict[str, Any]:
        fields = provided(body, "name", "amount", "cycle", "next_date", "category", "bank_id", "notes", "active", "remind_days")
        for required in ("name", "amount", "cycle", "next_date", "category", "notes", "active"):
            if required in fields and fields[required] is None:
                raise HTTPException(status_code=400, detail=f"The {required.replace('_', ' ')} cannot be empty.")
        return await guarded(spending.update_sub(store, settings, sub_id, **fields))

    @app.delete("/api/expenses/subscriptions/{sub_id}", dependencies=auth)
    async def subs_remove(sub_id: int) -> dict[str, bool]:
        await guarded(spending.delete_sub(store, sub_id))
        return {"ok": True}

    @app.post("/api/expenses/subscriptions/{sub_id}/renew", dependencies=auth)
    async def subs_renew(sub_id: int, body: RenewIn | None = None) -> dict[str, Any]:
        body = body or RenewIn()
        return await guarded(spending.renew_sub(store, settings, sub_id, record=body.record, deduct=body.deduct))

    # ── export ─────────────────────────────────────────────────────
    @app.get("/api/expenses/export", dependencies=auth)
    async def export() -> Response:
        data = await guarded(expenses.export_csv(store, settings))
        return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="tapan-expenses.csv"'})

    # ── advice: rules always, the language model when one is configured ─
    @app.post("/api/expenses/advice", dependencies=auth)
    async def advice(request: Request) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"expense-advice:{ip}"):
            raise HTTPException(status_code=429, detail="Too many requests")
        payments, _banks, ov = await expenses.gather(store, settings)
        card = await guarded(spending.card(store, settings))
        month = await guarded(spending.month_summary(store, settings))
        subs = (await guarded(spending.list_subs(store, settings)))["subs"]
        rules = expenses.insights(ov, settings.currency) + spending.card_insights(card, settings.currency)
        result: dict[str, Any] = {"insights": rules, "advice": None, "source": "rules"}
        dispatcher = getattr(runtime, "llm_dispatcher", None)
        if not (payments or month["total_minor"] or subs) or dispatcher is None or settings.llm_provider.lower() == "mock":
            return result

        # Figures only. Notes and free-text descriptions of spending are never sent; names are the user's own labels, quoted as data.
        extra = {
            "spending_this_month": {"total": month["total_minor"] / 100, "previous_month": month["previous_total_minor"] / 100,
                                    "projected": None if month["projected_minor"] is None else month["projected_minor"] / 100,
                                    "budget": None if month["budget_minor"] is None else month["budget_minor"] / 100,
                                    "by_category": [{"category": c["category"], "amount": c["amount_minor"] / 100} for c in month["categories"]]},
            "subscriptions": [{"name": s["name"], "per_month": s["monthly_minor"] / 100, "cycle": s["cycle"]} for s in subs if s["active"]][:40],
        }
        context = expenses.llm_context(ov, payments, rules, settings.currency, extra)
        key = hashlib.sha256(context.encode()).hexdigest()
        cached = advice_cache.get(key)
        if cached and time.monotonic() - cached[0] < ADVICE_CACHE_SECONDS:
            return cached[1]
        try:
            text = await asyncio.wait_for(
                dispatcher.generate_text(expenses.ADVICE_SYSTEM, "DATA:\n" + context, "Review my payments and tell me what to do.", temperature=0.3),
                timeout=ADVICE_TIMEOUT_SECONDS,
            )
        except Exception:                                       # a slow or failing model must not break the screen: the rules still answer
            return result
        text = (text or "").strip()[:ADVICE_MAX_CHARS]
        if text:
            result = {**result, "advice": text, "source": "ai"}
            advice_cache[key] = (time.monotonic(), result)
            if len(advice_cache) > 20:
                advice_cache.pop(next(iter(advice_cache)))
        return result
