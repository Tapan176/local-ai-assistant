"""Finance operations with persistent balances and transactions."""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.storage.sqlite_store import SQLiteStore
from src.utils.constants import BANK_KEYWORDS, is_affirmation


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
        del session_id, memory
        lowered = user_text.lower()
        amount = self._extract_amount(user_text)
        rationale = reasoning.rationale.lower()

        if is_affirmation(lowered) and "finance summary prompt" in rationale:
            return await self._history()
        if "account creation clarification" in rationale:
            return await self._create_account(user_text, opening_balance=amount)

        if any(token in lowered for token in ("show accounts", "list accounts", "all accounts")):
            return await self._list_accounts()
        if "balance" in lowered and amount is None:
            account = await self._extract_account_name(user_text)
            return await self._show_balance(account if "all" not in lowered else None)
        if any(token in lowered for token in ("transaction history", "show history", "recent transactions")):
            return await self._history()
        if any(token in lowered for token in ("transactions for", "transactions from", "transactions in")):
            account = await self._extract_account_name(user_text)
            return await self._list_transactions_by_account(account)
        if any(token in lowered for token in ("update transaction", "edit transaction", "modify transaction")):
            return await self._update_transaction(user_text)
        if any(token in lowered for token in ("delete transaction", "remove transaction")):
            return await self._delete_transaction(user_text)
        if any(token in lowered for token in ("monthly summary", "month summary", "summary for")):
            return await self._handle_monthly_summary(user_text)
        if any(token in lowered for token in ("category summary", "expense by category", "spending by category")):
            return await self._category_summary(user_text)
        if any(token in lowered for token in ("get account", "account details", "account info")):
            account_id = self._extract_account_id(user_text)
            if account_id:
                return await self._get_account_by_id(account_id)
            account = await self._extract_account_name(user_text)
            return await self._get_account_by_name(account)
        if any(token in lowered for token in ("transfer", "move")):
            return await self._transfer(user_text, amount)
        if any(token in lowered for token in ("set balance", "update balance")):
            return await self._set_balance(user_text, amount)
        if any(token in lowered for token in ("rename account", "rename ")) and "account" in lowered:
            return await self._rename_account(user_text)
        if any(token in lowered for token in ("delete account", "remove account")):
            return await self._delete_account(user_text)
        if self._is_account_creation_request(lowered):
            return await self._create_account(user_text, opening_balance=amount)

        if amount is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=(
                    "I can handle this, but I need an amount to update a balance. "
                    "If you want a new account, say 'create account <name>'."
                ),
            )

        account = await self._extract_account_name(user_text)
        kind = self._detect_kind(lowered)
        await self._ensure_account(account)
        current_balance = await self._get_balance(account)
        if kind == "debit" and current_balance < amount:
            fallback = await self._find_sufficient_account(amount, exclude=account)
            if fallback is not None:
                account = fallback
                current_balance = await self._get_balance(account)
        new_balance = current_balance + amount if kind == "credit" else current_balance - amount
        now = datetime.now(timezone.utc).isoformat()
        
        # Use transaction for atomic balance update
        operations = [
            (
                """
                UPDATE financial_accounts
                SET balance = ?, updated_at = ?
                WHERE account_name = ?
                """,
                (new_balance, now, account),
            ),
            (
                """
                INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account, amount, kind, user_text[:200], now),
            ),
        ]
        await self.sqlite_store.execute_transaction(operations)

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

    async def _list_accounts(self) -> ToolExecutionResult:
        accounts = await self.sqlite_store.fetchall(
            """
            SELECT account_name, balance
            FROM financial_accounts
            ORDER BY account_name
            """
        )
        if not accounts:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text="You don't have any financial accounts stored yet.",
                data={"accounts": []},
            )
        total = sum(float(item["balance"]) for item in accounts)
        lines = [f"{row['account_name']}: Rs {row['balance']:.2f}" for row in accounts]
        lines.append(f"Total Net Balance: Rs {total:.2f}")
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text="Here are your account balances:\n" + "\n".join(lines),
            data={"accounts": accounts, "total": total},
        )

    async def _show_balance(self, account_name: str | None) -> ToolExecutionResult:
        if not account_name:
            return await self._list_accounts()
        await self._ensure_account(account_name)
        balance = await self._get_balance(account_name)
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"{account_name} balance is {self._fmt_amount(balance)}.",
            data={"account_name": account_name, "balance": balance},
        )

    async def monthly_summary(self, year: int | None = None, month: int | None = None) -> ToolExecutionResult:
        """Generate monthly financial summary."""
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        target_year = year or now.year
        target_month = month or now.month
        
        start_date = f"{target_year}-{target_month:02d}-01"
        if target_month == 12:
            end_date = f"{target_year + 1}-01-01"
        else:
            end_date = f"{target_year}-{target_month + 1:02d}-01"
        
        rows = await self.sqlite_store.fetchall(
            """
            SELECT account_name, kind, SUM(amount) as total
            FROM financial_transactions
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY account_name, kind
            ORDER BY account_name, kind
            """,
            (start_date, end_date),
        )
        
        if not rows:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"No transactions found for {target_year}-{target_month:02d}.",
                data={"year": target_year, "month": target_month, "transactions": []},
            )
        
        credits = sum(float(r["total"]) for r in rows if r["kind"] == "credit")
        debits = sum(float(r["total"]) for r in rows if r["kind"] == "debit")
        net = credits - debits
        
        lines = [
            f"Monthly Summary for {target_year}-{target_month:02d}:",
            f"Total Credits: Rs {credits:.2f}",
            f"Total Debits: Rs {debits:.2f}",
            f"Net: Rs {net:.2f}",
        ]
        
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text="\n".join(lines),
            data={
                "year": target_year,
                "month": target_month,
                "credits": credits,
                "debits": debits,
                "net": net,
                "transactions": rows,
            },
        )

    async def _history(self, limit: int = 10) -> ToolExecutionResult:
        rows = await self.sqlite_store.fetchall(
            """
            SELECT id, account_name, amount, kind, note, timestamp
            FROM financial_transactions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        if not rows:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text="No transaction history found.",
                data={"transactions": []},
            )
        lines = []
        for row in rows:
            sign = "+" if row["kind"] == "credit" else "-"
            lines.append(
                f"#{row['id']} {row['timestamp'][:16]} | {row['account_name']} | {sign}Rs {float(row['amount']):.2f}"
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text="Recent transactions:\n" + "\n".join(lines),
            data={"transactions": rows},
        )

    async def _transfer(self, user_text: str, amount: float | None) -> ToolExecutionResult:
        if amount is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Transfer needs an amount, source account, and destination account.",
            )

        transfer_match = re.search(
            r"(?:from)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})\s+(?:to|into)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})",
            user_text,
            flags=re.IGNORECASE,
        )
        if not transfer_match:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Use format like: transfer 500 from savings to wallet.",
            )
        source = transfer_match.group(1).strip().title()
        target = transfer_match.group(2).strip().title()

        await self._ensure_account(source)
        await self._ensure_account(target)
        source_balance = await self._get_balance(source)
        if source_balance < amount:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"{source} has insufficient balance for {self._fmt_amount(amount)}.",
                data={"source": source, "target": target, "amount": amount},
            )

        target_balance = await self._get_balance(target)
        now = datetime.now(timezone.utc).isoformat()
        
        # Use transaction for atomic transfer
        operations = [
            (
                "UPDATE financial_accounts SET balance = ?, updated_at = ? WHERE account_name = ?",
                (source_balance - amount, now, source),
            ),
            (
                "UPDATE financial_accounts SET balance = ?, updated_at = ? WHERE account_name = ?",
                (target_balance + amount, now, target),
            ),
            (
                """
                INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                VALUES (?, ?, 'debit', ?, ?)
                """,
                (source, amount, f"transfer to {target}", now),
            ),
            (
                """
                INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                VALUES (?, ?, 'credit', ?, ?)
                """,
                (target, amount, f"transfer from {source}", now),
            ),
        ]
        await self.sqlite_store.execute_transaction(operations)
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Transferred {self._fmt_amount(amount)} from {source} to {target}.",
            data={"source": source, "target": target, "amount": amount},
            should_store_semantic=True,
        )

    async def _set_balance(self, user_text: str, amount: float | None) -> ToolExecutionResult:
        if amount is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I need a numeric amount to set account balance.",
            )
        account = self._extract_account_for_set_balance(user_text) or await self._extract_account_name(user_text)
        await self._ensure_account(account)
        await self.sqlite_store.execute(
            """
            UPDATE financial_accounts
            SET balance = ?, updated_at = ?
            WHERE account_name = ?
            """,
            (amount, datetime.now(timezone.utc).isoformat(), account),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Set {account} balance to {self._fmt_amount(amount)}.",
            data={"account_name": account, "new_balance": amount},
            should_store_semantic=True,
        )

    async def _rename_account(self, user_text: str) -> ToolExecutionResult:
        match = re.search(
            r"rename(?:\s+account)?\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})\s+to\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})",
            user_text,
            flags=re.IGNORECASE,
        )
        if not match:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Use format like: rename account cash to wallet.",
            )
        old_name = match.group(1).strip().title()
        new_name = match.group(2).strip().title()
        row = await self.sqlite_store.fetchone(
            "SELECT account_name FROM financial_accounts WHERE account_name = ?",
            (old_name,),
        )
        if not row:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"Account '{old_name}' not found.",
            )
        await self.sqlite_store.execute(
            "UPDATE financial_accounts SET account_name = ?, updated_at = ? WHERE account_name = ?",
            (new_name, datetime.now(timezone.utc).isoformat(), old_name),
        )
        await self.sqlite_store.execute(
            "UPDATE financial_transactions SET account_name = ? WHERE account_name = ?",
            (new_name, old_name),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Renamed account {old_name} to {new_name}.",
            data={"old_name": old_name, "new_name": new_name},
            should_store_semantic=True,
        )

    async def _delete_account(self, user_text: str) -> ToolExecutionResult:
        account = await self._extract_account_name(user_text)
        if account.lower() == "primary":
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Primary account is protected. Rename it instead of deleting.",
            )
        await self.sqlite_store.execute(
            "DELETE FROM financial_accounts WHERE account_name = ?",
            (account,),
        )
        await self.sqlite_store.execute(
            "DELETE FROM financial_transactions WHERE account_name = ?",
            (account,),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Deleted account {account} and related transactions.",
            data={"account_name": account},
            should_store_semantic=True,
        )

    async def _create_account(self, user_text: str, opening_balance: float | None = None) -> ToolExecutionResult:
        account = await self._extract_account_name_for_create(user_text)
        existing = await self.sqlite_store.fetchone(
            "SELECT account_name, balance FROM financial_accounts WHERE lower(account_name) = lower(?)",
            (account,),
        )
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            current_balance = float(existing.get("balance", 0.0))
            if opening_balance is None:
                return ToolExecutionResult(
                    tool_name=self.name,
                    success=True,
                    output_text=f"{account} account already exists with balance {self._fmt_amount(current_balance)}.",
                    data={"account_name": account, "balance": current_balance, "created": False},
                )

            await self.sqlite_store.execute(
                """
                UPDATE financial_accounts
                SET balance = ?, updated_at = ?
                WHERE lower(account_name) = lower(?)
                """,
                (opening_balance, now, account),
            )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"{account} already existed. I set opening balance to {self._fmt_amount(opening_balance)}.",
                data={"account_name": account, "balance": opening_balance, "created": False},
                should_store_semantic=True,
            )

        start_balance = float(opening_balance or 0.0)
        await self.sqlite_store.execute(
            """
            INSERT INTO financial_accounts (account_name, balance, updated_at)
            VALUES (?, ?, ?)
            """,
            (account, start_balance, now),
        )
        if opening_balance is not None and opening_balance > 0:
            await self.sqlite_store.execute(
                """
                INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                VALUES (?, ?, 'credit', ?, ?)
                """,
                (account, opening_balance, "opening balance", now),
            )

        if start_balance > 0:
            text = f"Created account {account} with opening balance {self._fmt_amount(start_balance)}."
        else:
            text = f"Created account {account} with zero balance."
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=text,
            data={"account_name": account, "balance": start_balance, "created": True},
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

    @staticmethod
    def _is_affirmation_text(lowered: str) -> bool:
        return is_affirmation(lowered)

    @staticmethod
    def _is_account_creation_request(lowered: str) -> bool:
        keyword_hit = any(
            token in lowered
            for token in (
                "add new account",
                "add one account",
                "create account",
                "open account",
                "new account",
                "add account",
                "added account",
                "created account",
                "opened account",
            )
        )
        if keyword_hit:
            return True
        return bool(re.search(r"\b(?:added|created|opened)\b.+\baccount\b", lowered))

    async def _extract_account_name_for_create(self, text: str) -> str:
        patterns = [
            r"(?:create|open|add)(?:\s+new|\s+one)?\s+account(?:\s+(?:named|called))?\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})",
            r"account\s+(?:name|named|called)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip()
            candidate = re.sub(r"\s+(with|having)\s+.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate:
                return candidate.title()
        return await self._extract_account_name(text)

    async def _extract_account_name(self, text: str) -> str:
        known_accounts = await self.sqlite_store.fetchall(
            "SELECT account_name FROM financial_accounts ORDER BY account_name"
        )
        lowered = text.lower()
        for row in known_accounts:
            name = row["account_name"]
            if name.lower() in lowered:
                return name

        bank_hint = re.search(
            r"\b(" + "|".join(re.escape(k) for k in BANK_KEYWORDS[:6]) + r")\b",
            lowered,
        )
        if bank_hint:
            candidate = bank_hint.group(1).title()
            close = self._closest_account_name(candidate, [row["account_name"] for row in known_accounts])
            return close or candidate

        capture_hinglish = re.search(r"\b([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})\s+me\b", text, flags=re.IGNORECASE)
        if capture_hinglish:
            candidate = capture_hinglish.group(1).strip()
            candidate = re.sub(r"\s+(account|wallet)\b.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate:
                candidate = candidate.title()
                close = self._closest_account_name(candidate, [row["account_name"] for row in known_accounts])
                return close or candidate

        capture = re.search(r"\b(?:to|in|into|from)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})", text)
        if capture:
            candidate = capture.group(1).strip()
            candidate = re.sub(r"\s+(account|wallet)\b.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate:
                candidate = candidate.title()
                close = self._closest_account_name(candidate, [row["account_name"] for row in known_accounts])
                return close or candidate
        return "Primary"

    @staticmethod
    def _closest_account_name(candidate: str, existing_accounts: list[str]) -> str | None:
        if not existing_accounts:
            return None
        matches = difflib.get_close_matches(candidate, existing_accounts, n=1, cutoff=0.78)
        if matches:
            return matches[0]
        return None

    async def _ensure_account(self, account_name: str) -> None:
        await self.sqlite_store.execute(
            """
            INSERT OR IGNORE INTO financial_accounts (account_name, balance, updated_at)
            VALUES (?, 0.0, ?)
            """,
            (account_name, datetime.now(timezone.utc).isoformat()),
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

    async def _find_sufficient_account(self, amount: float, exclude: str) -> str | None:
        rows = await self.sqlite_store.fetchall(
            """
            SELECT account_name, balance
            FROM financial_accounts
            WHERE account_name <> ?
            ORDER BY balance DESC
            """,
            (exclude,),
        )
        for row in rows:
            if float(row.get("balance", 0.0)) >= amount:
                return str(row["account_name"])
        return None

    @staticmethod
    def _fmt_amount(amount: float) -> str:
        return f"Rs {amount:.2f}"

    async def _get_account_by_id(self, account_id: int) -> ToolExecutionResult:
        """Get account details by ID."""
        row = await self.sqlite_store.fetchone(
            """
            SELECT id, account_name, balance, updated_at
            FROM financial_accounts
            WHERE id = ?
            """,
            (account_id,),
        )
        if not row:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"Account with ID {account_id} not found.",
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=(
                f"Account #{row['id']}: {row['account_name']} - "
                f"Balance: {self._fmt_amount(float(row['balance']))}"
            ),
            data=dict(row),
        )

    async def _get_account_by_name(self, account_name: str) -> ToolExecutionResult:
        """Get account details by name."""
        row = await self.sqlite_store.fetchone(
            """
            SELECT id, account_name, balance, updated_at
            FROM financial_accounts
            WHERE account_name = ?
            """,
            (account_name,),
        )
        if not row:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"Account '{account_name}' not found.",
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=(
                f"Account #{row['id']}: {row['account_name']} - "
                f"Balance: {self._fmt_amount(float(row['balance']))}"
            ),
            data=dict(row),
        )

    async def _list_transactions_by_account(self, account_name: str, limit: int = 50) -> ToolExecutionResult:
        """List all transactions for a specific account."""
        await self._ensure_account(account_name)
        rows = await self.sqlite_store.fetchall(
            """
            SELECT id, account_name, amount, kind, note, timestamp
            FROM financial_transactions
            WHERE account_name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (account_name, limit),
        )
        if not rows:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"No transactions found for {account_name}.",
                data={"account_name": account_name, "transactions": []},
            )
        lines = []
        for row in rows:
            sign = "+" if row["kind"] == "credit" else "-"
            lines.append(
                f"#{row['id']} {row['timestamp'][:16]} | {sign}Rs {float(row['amount']):.2f} | {row['note']}"
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Transactions for {account_name}:\n" + "\n".join(lines),
            data={"account_name": account_name, "transactions": rows},
        )

    async def _update_transaction(self, user_text: str) -> ToolExecutionResult:
        """Update an existing transaction."""
        transaction_id = self._extract_transaction_id(user_text)
        if transaction_id is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Please specify transaction ID to update, e.g., 'update transaction 5'.",
            )

        existing = await self.sqlite_store.fetchone(
            "SELECT id, account_name, amount, kind, note FROM financial_transactions WHERE id = ?",
            (transaction_id,),
        )
        if not existing:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"Transaction #{transaction_id} not found.",
            )

        # Extract new values from user text
        new_amount = self._extract_amount(user_text)
        new_note_match = re.search(r"note\s*[:=]\s*(.+)", user_text, flags=re.IGNORECASE)
        new_note = new_note_match.group(1).strip() if new_note_match else None

        # Update transaction
        update_sql = "UPDATE financial_transactions SET "
        params = []
        if new_amount is not None:
            update_sql += "amount = ?, "
            params.append(new_amount)
        if new_note:
            update_sql += "note = ?, "
            params.append(new_note[:200])
        if not params:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Please specify what to update (amount or note).",
            )

        update_sql = update_sql.rstrip(", ") + " WHERE id = ?"
        params.append(transaction_id)
        await self.sqlite_store.execute(update_sql, tuple(params))

        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Updated transaction #{transaction_id}.",
            data={"id": transaction_id, "amount": new_amount, "note": new_note},
            should_store_semantic=True,
        )

    async def _delete_transaction(self, user_text: str) -> ToolExecutionResult:
        """Delete a transaction."""
        transaction_id = self._extract_transaction_id(user_text)
        if transaction_id is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Please specify transaction ID to delete, e.g., 'delete transaction 5'.",
            )

        existing = await self.sqlite_store.fetchone(
            "SELECT id, account_name, amount, kind FROM financial_transactions WHERE id = ?",
            (transaction_id,),
        )
        if not existing:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"Transaction #{transaction_id} not found.",
            )

        # Note: Deleting transaction doesn't reverse balance - user should handle manually
        await self.sqlite_store.execute("DELETE FROM financial_transactions WHERE id = ?", (transaction_id,))

        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Deleted transaction #{transaction_id}. Note: Account balance was not adjusted.",
            data={"id": transaction_id},
            should_store_semantic=True,
        )

    async def _handle_monthly_summary(self, user_text: str) -> ToolExecutionResult:
        """Handle monthly summary request with date parsing."""
        # Try to extract year and month from text
        year_match = re.search(r"\b(20\d{2})\b", user_text)
        month_match = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|\d{1,2})\b", user_text, re.IGNORECASE)
        
        year = int(year_match.group(1)) if year_match else None
        month = None
        if month_match:
            month_str = month_match.group(1).lower()
            month_map = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12
            }
            month = month_map.get(month_str) or (int(month_str) if month_str.isdigit() else None)
        
        return await self.monthly_summary(year=year, month=month)

    async def _category_summary(self, user_text: str) -> ToolExecutionResult:
        """Generate summary by transaction category/note."""
        # Extract date range if specified
        year_match = re.search(r"\b(20\d{2})\b", user_text)
        year = int(year_match.group(1)) if year_match else None
        
        rows = await self.sqlite_store.fetchall(
            """
            SELECT note, kind, SUM(amount) as total, COUNT(*) as count
            FROM financial_transactions
            WHERE timestamp LIKE ?
            GROUP BY note, kind
            ORDER BY total DESC
            LIMIT 20
            """,
            (f"{year or datetime.now(timezone.utc).year}%",) if year else ("%",),
        )
        
        if not rows:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text="No transactions found for category summary.",
                data={"categories": []},
            )
        
        lines = ["Category Summary:"]
        for row in rows:
            category = row["note"][:30] or "Uncategorized"
            lines.append(f"{category} ({row['kind']}): Rs {float(row['total']):.2f} ({row['count']} transactions)")
        
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text="\n".join(lines),
            data={"categories": rows},
        )

    @staticmethod
    def _extract_account_id(text: str) -> int | None:
        """Extract account ID from text."""
        match = re.search(r"account\s*(?:id|#)?\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_transaction_id(text: str) -> int | None:
        """Extract transaction ID from text."""
        match = re.search(r"transaction\s*(?:id|#)?\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        # Also try just #number
        match = re.search(r"#(\d+)", text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_account_for_set_balance(text: str) -> str | None:
        patterns = [
            r"set\s+balance\s+of\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})\s+to\s+[+-]?\d+(?:\.\d+)?",
            r"set\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})\s+balance\s+to\s+[+-]?\d+(?:\.\d+)?",
            r"update\s+balance\s+of\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,40})\s+to\s+[+-]?\d+(?:\.\d+)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        return None
