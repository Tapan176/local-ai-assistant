"""Finance operations with persistent balances and transactions."""

from __future__ import annotations

import re
from datetime import datetime

from tapan_ai.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from tapan_ai.storage.sqlite_store import SQLiteStore


class FinanceTool:
    name = "finance_tool"
    description = "Manage account balances and financial transactions."

    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del session_id, reasoning, memory
        lowered = user_text.lower()
        amount = self._extract_amount(user_text)
        account = await self._extract_account_name(user_text)
        kind = self._detect_kind(lowered)

        if "balance" in lowered and amount is None:
            accounts = await self.sqlite_store.fetchall(
                """
                SELECT account_name, balance
                FROM financial_accounts
                ORDER BY account_name
                """
            )
            if not accounts:
                text = "You don't have any financial accounts stored yet."
            else:
                lines = [f"{row['account_name']}: Rs {row['balance']:.2f}" for row in accounts]
                text = "Here are your account balances:\n" + "\n".join(lines)
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=text,
                data={"accounts": accounts},
            )

        if amount is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I can handle this, but I need an amount to update the account.",
            )

        await self._ensure_account(account)
        current_balance = await self._get_balance(account)
        new_balance = current_balance + amount if kind == "credit" else current_balance - amount
        await self.sqlite_store.execute(
            """
            UPDATE financial_accounts
            SET balance = ?, updated_at = ?
            WHERE account_name = ?
            """,
            (new_balance, datetime.utcnow().isoformat(), account),
        )
        await self.sqlite_store.execute(
            """
            INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account, amount, kind, user_text[:200], datetime.utcnow().isoformat()),
        )

        action_word = "added to" if kind == "credit" else "deducted from"
        text = (
            f"Done. I {action_word} {self._fmt_amount(amount)} in {account}. "
            f"New balance is {self._fmt_amount(new_balance)}."
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=text,
            data={
                "account_name": account,
                "amount": amount,
                "kind": kind,
                "new_balance": new_balance,
            },
            should_store_semantic=True,
        )

    @staticmethod
    def _extract_amount(text: str) -> float | None:
        match = re.search(r"(?<!\w)([+-]?\d+(?:\.\d+)?)(?!\w)", text.replace(",", ""))
        if not match:
            return None
        return abs(float(match.group(1)))

    @staticmethod
    def _detect_kind(lowered: str) -> str:
        expense_cues = ("spent", "expense", "pay", "paid", "debit", "withdraw", "deduct", "bought")
        if any(cue in lowered for cue in expense_cues):
            return "debit"
        return "credit"

    async def _extract_account_name(self, text: str) -> str:
        known_accounts = await self.sqlite_store.fetchall(
            "SELECT account_name FROM financial_accounts ORDER BY account_name"
        )
        lowered = text.lower()
        for row in known_accounts:
            name = row["account_name"]
            if name.lower() in lowered:
                return name

        capture = re.search(r"\b(?:to|in|into|from)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})", text)
        if capture:
            candidate = capture.group(1).strip()
            candidate = re.sub(r"\s+(account|wallet)\b.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate:
                return candidate.title()
        return "Primary"

    async def _ensure_account(self, account_name: str) -> None:
        await self.sqlite_store.execute(
            """
            INSERT OR IGNORE INTO financial_accounts (account_name, balance, updated_at)
            VALUES (?, 0.0, ?)
            """,
            (account_name, datetime.utcnow().isoformat()),
        )

    async def _get_balance(self, account_name: str) -> float:
        row = await self.sqlite_store.fetchone(
            """
            SELECT balance
            FROM financial_accounts
            WHERE account_name = ?
            """,
            (account_name,),
        )
        if not row:
            return 0.0
        return float(row.get("balance", 0.0))

    @staticmethod
    def _fmt_amount(amount: float) -> str:
        return f"Rs {amount:.2f}"

