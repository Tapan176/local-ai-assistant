"""Authenticated REST routes for the expense tracker. Every route needs the access token; nothing here is public."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.agent import expenses
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
    total: Any
    emis: Any = 1
    first_due: str = Field(max_length=40)
    day: Any = None
    bank_id: int | None = None
    category: str = Field(default="other", max_length=30)
    notes: str = Field(default="", max_length=1000)
    remind_days: Any = 1


class PaymentPatch(_Body):
    title: str | None = Field(default=None, max_length=300)
    total: Any = None
    bank_id: int | None = None
    category: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)
    remind_days: Any = None


class EmiPatch(_Body):
    amount: Any = None
    due_date: str | None = Field(default=None, max_length=40)
    paid: bool | None = None
    deduct: bool = False


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
    async def snapshot() -> dict[str, Any]:
        return await guarded(expenses.snapshot(store, settings))

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
            store, settings, title=body.title, total=body.total, emis=body.emis, first_due=body.first_due, day=body.day,
            bank_id=body.bank_id, category=body.category, notes=body.notes, remind_days=body.remind_days))

    @app.patch("/api/expenses/payments/{payment_id}", dependencies=auth)
    async def edit_payment(payment_id: int, body: PaymentPatch) -> dict[str, Any]:
        fields = provided(body, "title", "total", "bank_id", "category", "notes", "remind_days")
        for required in ("title", "total", "category", "notes"):
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
    async def rebalance(payment_id: int) -> dict[str, Any]:
        return await guarded(expenses.rebalance(store, settings, payment_id))

    @app.post("/api/expenses/payments/{payment_id}/pay-next", dependencies=auth)
    async def pay_next(payment_id: int, body: NextPaidIn) -> dict[str, Any]:
        return await guarded(expenses.mark_next_paid(store, settings, payment_id, deduct=body.deduct))

    @app.post("/api/expenses/payments/{payment_id}/emis", dependencies=auth)
    async def add_emi(payment_id: int, body: EmiIn) -> dict[str, Any]:
        return await guarded(expenses.add_emi(store, settings, payment_id, amount=body.amount, due_date=body.due_date))

    # ── single EMIs ────────────────────────────────────────────────
    @app.patch("/api/expenses/emis/{emi_id}", dependencies=auth)
    async def edit_emi(emi_id: int, body: EmiPatch) -> dict[str, Any]:
        fields = provided(body, "amount", "due_date", "paid")
        if any(v is None for v in fields.values()):
            raise HTTPException(status_code=400, detail="Send a value for each field you change.")
        return await guarded(expenses.update_emi(store, settings, emi_id, deduct=body.deduct, **fields))

    @app.delete("/api/expenses/emis/{emi_id}", dependencies=auth)
    async def remove_emi(emi_id: int) -> dict[str, Any]:
        return await guarded(expenses.delete_emi(store, settings, emi_id))

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
        rules = expenses.insights(ov, settings.currency)
        result: dict[str, Any] = {"insights": rules, "advice": None, "source": "rules"}
        dispatcher = getattr(runtime, "llm_dispatcher", None)
        if not payments or dispatcher is None or settings.llm_provider.lower() == "mock":
            return result

        context = expenses.llm_context(ov, payments, rules, settings.currency)
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
