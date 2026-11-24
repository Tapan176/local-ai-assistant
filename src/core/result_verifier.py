"""ResultVerifier: Validates tool execution results against user intent.

Verifies that tool outputs match user expectations, detects when operations
failed or produced unexpected results, and supports all tool types.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from src.core.data_inspector import DataInspector
from src.core.state_manager import StateManager
from src.models import Operation, ToolExecutionResult, VerificationReport
from src.storage.sqlite_store import SQLiteStore


class ResultVerifier:
    """Verifies tool execution results against user intent and expectations."""

    def __init__(
        self,
        sqlite_store: SQLiteStore,
        data_inspector: DataInspector | None = None,
        state_manager: StateManager | None = None,
    ):
        """Initialize ResultVerifier with database access.

        Args:
            sqlite_store: SQLiteStore instance for database access
            data_inspector: Optional DataInspector for validation
            state_manager: Optional StateManager for state tracking
        """
        self.sqlite_store = sqlite_store
        self.data_inspector = data_inspector
        self.state_manager = state_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    async def verify(
        self,
        result: ToolExecutionResult,
        operation: Operation,
        user_intent: str = "",
    ) -> VerificationReport:
        """Verify a tool execution result against the intended operation.

        Args:
            result: The tool execution result to verify
            operation: The operation that was performed
            user_intent: The user's stated intent (for matching)

        Returns:
            VerificationReport: Detailed verification results
        """
        try:
            # Extract outcome from the result
            outcome = await self.extract_outcome(result)

            # Route to appropriate verification based on tool
            if result.tool_name == "finance_tool":
                extracted = outcome_extracted = True
                intent_matched = await self._verify_finance_operation(
                    result, operation, outcome, user_intent
                )
            elif result.tool_name == "people_tool":
                extracted = outcome_extracted = True
                intent_matched = await self._verify_people_operation(
                    result, operation, outcome, user_intent
                )
            elif result.tool_name == "reminder_tool":
                extracted = outcome_extracted = True
                intent_matched = await self._verify_reminder_operation(
                    result, operation, outcome, user_intent
                )
            elif result.tool_name == "calendar_tool":
                extracted = outcome_extracted = True
                intent_matched = await self._verify_calendar_operation(
                    result, operation, outcome, user_intent
                )
            else:
                # Generic verification for unknown tools
                extracted = len(outcome) > 0
                intent_matched = result.success
                outcome_extracted = extracted

            # Determine confidence
            confidence = 0.95 if intent_matched and extracted else 0.5
            if not result.success:
                confidence = 0.0

            # Generate suggestions if verification failed
            suggestions: list[str] = []
            if not result.success:
                suggestions.append(f"Tool operation failed: check error in result")
            if extracted and not intent_matched:
                suggestions.append("Operation succeeded but result doesn't match intent")
            if not extracted:
                suggestions.append("Could not extract operation outcome from result")

            return VerificationReport(
                success=result.success and intent_matched,
                outcome_extracted=outcome_extracted,
                outcome=outcome,
                intent_matched=intent_matched,
                confidence=confidence,
                suggestions=suggestions,
                tool_name=result.tool_name,
            )

        except Exception as e:
            self.logger.error(f"Verification failed: {e}")
            return VerificationReport(
                success=False,
                outcome_extracted=False,
                outcome={},
                intent_matched=False,
                confidence=0.0,
                suggestions=[f"Verification error: {str(e)}"],
                tool_name=result.tool_name,
            )

    async def extract_outcome(self, result: ToolExecutionResult) -> dict[str, Any]:
        """Extract meaningful outcome from a tool result.

        Args:
            result: The tool execution result

        Returns:
            dict: Extracted outcome data
        """
        try:
            # If result.data exists and is non-empty, use it as base
            if result.data and isinstance(result.data, dict):
                outcome = dict(result.data)  # Make a copy to avoid mutating original
            else:
                outcome = {}

            output = result.output_text.lower()

            # Always add success indicator
            outcome["success"] = result.success

            # Normalize common field aliases across tools
            if "account" not in outcome and "account_name" in outcome:
                outcome["account"] = outcome.get("account_name")
            if "from_account" not in outcome and "source_account" in outcome:
                outcome["from_account"] = outcome.get("source_account")
            if "to_account" not in outcome and "target_account" in outcome:
                outcome["to_account"] = outcome.get("target_account")
            if "person_name" not in outcome and "target" in outcome:
                outcome["person_name"] = outcome.get("target")
            if "person_name" not in outcome and "name" in outcome:
                outcome["person_name"] = outcome.get("name")
            if "relationship" not in outcome and "relation" in outcome:
                outcome["relationship"] = outcome.get("relation")
            if "event_title" not in outcome and result.tool_name == "calendar_tool" and "title" in outcome:
                outcome["event_title"] = outcome.get("title")

            # Ensure "complete" is set from "status" if present
            status_value = str(outcome.get("status", "")).lower()
            if status_value in {"completed", "done"} and "complete" not in outcome:
                outcome["complete"] = True

            # Extract amounts (e.g., "$500", "500.00")
            amount_match = re.search(r"\$?([\d,]+\.?\d*)", result.output_text)
            if amount_match:
                try:
                    amount_str = amount_match.group(1).replace(",", "")
                    outcome["amount"] = float(amount_str)
                except ValueError:
                    pass

            # Extract account names (only if not already in outcome from data)
            if "account" not in outcome and "account" in output:
                # Look for account name patterns - more flexible to handle underscores, hyphens
                account_match = re.search(
                    r"(?:account(?:\s+name)?|acc(?:ount)?)\s*(?:is|=|:)?\s*['\"]?([a-zA-Z0-9_-]+(?:\s+(?!with\b|has\b|balance\b|at\b|from\b|to\b)[a-zA-Z0-9_-]+)?)['\"]?(?=\s+(?:with|has|balance|at|from|to)\b|$)",
                    result.output_text,
                    re.IGNORECASE,
                )
                if account_match:
                    outcome["account"] = account_match.group(1).strip()

            # Extract person names (only if not already in outcome from data)
            if "person_name" not in outcome and ("person" in output or "people" in output or "friend" in output):
                # Look for name patterns after key words
                name_patterns = [
                    r"(?:added|added person|person|friend)[\s:]*([A-Z][a-z]+)",
                    r"(?:name|person name)[\s:]*([A-Z][a-z]+)",
                ]
                for pattern in name_patterns:
                    name_match = re.search(pattern, result.output_text)
                    if name_match:
                        outcome["person_name"] = name_match.group(1).strip()
                        break

            # Extract relationship type
            if "relationship" in output or "friend" in output:
                rel_patterns = ["friend", "colleague", "family", "contact"]
                for rel in rel_patterns:
                    if rel in output:
                        outcome["relationship"] = rel
                        break

            # Extract reminder title
            if "reminder" in output or "remind" in output:
                # Try multiple patterns to find the title
                title_patterns = [
                    r"['\"]([^'\"]+)['\"]",  # Quoted text
                    r"(?:reminder|titled)[\s:]+([a-zA-Z\s]+?)(?:\s*(?:on|at|by|with|for)|\s*$)",  # After reminder/titled
                    r"title[\s:]*['\"]?([^'\":\n]+)",  # After 'title'
                ]
                for pattern in title_patterns:
                    title_match = re.search(pattern, result.output_text, re.IGNORECASE)
                    if title_match:
                        outcome["title"] = title_match.group(1).strip()
                        break

                # Check if reminder is completed
                if "completed" in output or "complete" in output or "done" in output:
                    outcome["status"] = "completed"
                    outcome["complete"] = True
                else:
                    outcome["status"] = "pending"
                    outcome["complete"] = False

            # Extract event details (only if not already in outcome from data)
            if "event_title" not in outcome and ("event" in output or "calendar" in output):
                # Try multiple patterns to find the event title
                event_patterns = [
                    r"['\"]([^'\"]+)['\"]",  # Quoted text first (highest priority)
                    r"(?:event|created|titled)[\s:]+([a-zA-Z][a-zA-Z\s]*?)(?:\s*$|\.|\n)",  # After keywords
                ]
                for pattern in event_patterns:
                    event_match = re.search(pattern, result.output_text, re.IGNORECASE)
                    if event_match:
                        outcome["event_title"] = event_match.group(1).strip()
                        break

            return outcome

        except Exception as e:
            self.logger.warning(f"Failed to extract outcome: {e}")
            return {"success": result.success}

    async def matches_intent(
        self, outcome: dict[str, Any], intent: str
    ) -> bool:
        """Check if an outcome matches the stated user intent.

        Args:
            outcome: Extracted outcome from tool result
            intent: The user's stated intent

        Returns:
            bool: True if outcome matches intent
        """
        if not intent or not outcome:
            return outcome.get("success", False)

        intent_lower = intent.lower()

        # Check for account creation intent
        if "create" in intent_lower and "account" in intent_lower:
            if ("account" in outcome or "account_name" in outcome) and outcome.get("success"):
                return True

        # Check for transfer intent
        if "transfer" in intent_lower or "move" in intent_lower:
            if "amount" in outcome and outcome.get("success"):
                return True

        # Check for person addition intent - must have both person creation keywords AND person_name
        if ("add" in intent_lower and "person" in intent_lower) or \
           ("add" in intent_lower and "friend" in intent_lower):
            if "person_name" in outcome and outcome.get("success"):
                return True

        # Check for relationship intent - must have relationship type
        if "relationship" in intent_lower:
            if "relationship" in outcome and outcome.get("success"):
                return True

        # Check for reminder intent
        if "remind" in intent_lower or "reminder" in intent_lower:
            if "title" in outcome and outcome.get("success"):
                return True

        # Check for calendar/event intent
        if "event" in intent_lower or "calendar" in intent_lower:
            if "event_title" in outcome and outcome.get("success"):
                return True

        # If we get here, the intent didn't match any specific pattern
        # Only return success if there's no explicit intent (empty intent defaults to success above)
        # But if intent is specified and doesn't match, return False
        return False

    # === Finance Tool Verification ===

    async def _verify_finance_operation(
        self,
        result: ToolExecutionResult,
        operation: Operation,
        outcome: dict[str, Any],
        user_intent: str,
    ) -> bool:
        """Verify finance tool operation."""
        if not result.success:
            return False

        try:
            output_lower = result.output_text.lower()

            # Verify account creation
            if "create" in operation.description.lower() and "account" in operation.description.lower():
                if "account" in outcome or "account_name" in outcome:
                    # Check if account exists in database
                    account_name = str(outcome.get("account") or outcome.get("account_name") or "").strip()
                    exists = await asyncio.to_thread(
                        self._account_exists, account_name
                    )
                    return exists

            # Verify balance/account retrieval
            if "balance" in output_lower or "show" in output_lower:
                return "balance" in outcome or result.success

            # Verify transaction
            if "transaction" in operation.description.lower():
                return "amount" in outcome and result.success

            # Verify transfer
            if "transfer" in operation.description.lower():
                return "amount" in outcome and result.success

            return result.success

        except Exception as e:
            self.logger.error(f"Finance verification failed: {e}")
            return False

    # === People Tool Verification ===

    async def _verify_people_operation(
        self,
        result: ToolExecutionResult,
        operation: Operation,
        outcome: dict[str, Any],
        user_intent: str,
    ) -> bool:
        """Verify people tool operation."""
        if not result.success:
            return False

        try:
            output_lower = result.output_text.lower()

            # Verify person addition
            if "add" in operation.description.lower() and "person" in operation.description.lower():
                if "person_name" in outcome:
                    person_name = outcome.get("person_name", "").strip()
                    exists = await asyncio.to_thread(
                        self._person_exists, person_name
                    )
                    return exists

            # Verify relationship
            if "relationship" in operation.description.lower():
                return "relationship" in outcome and result.success

            return result.success

        except Exception as e:
            self.logger.error(f"People verification failed: {e}")
            return False

    # === Reminder Tool Verification ===

    async def _verify_reminder_operation(
        self,
        result: ToolExecutionResult,
        operation: Operation,
        outcome: dict[str, Any],
        user_intent: str,
    ) -> bool:
        """Verify reminder tool operation."""
        if not result.success:
            return False

        try:
            output_lower = result.output_text.lower()

            # Verify reminder creation
            if "create" in operation.description.lower() or "add" in operation.description.lower():
                if "title" in outcome:
                    title = outcome.get("title", "").strip()
                    exists = await asyncio.to_thread(
                        self._reminder_exists, title
                    )
                    return exists

            # Verify reminder completion
            if "complete" in operation.description.lower():
                status_value = str(outcome.get("status", "")).lower()
                return (outcome.get("complete") is True or status_value in {"completed", "done"}) and result.success

            return result.success

        except Exception as e:
            self.logger.error(f"Reminder verification failed: {e}")
            return False

    # === Calendar Tool Verification ===

    async def _verify_calendar_operation(
        self,
        result: ToolExecutionResult,
        operation: Operation,
        outcome: dict[str, Any],
        user_intent: str,
    ) -> bool:
        """Verify calendar tool operation."""
        if not result.success:
            return False

        try:
            output_lower = result.output_text.lower()

            # Verify event creation
            if "create" in operation.description.lower() or "add" in operation.description.lower():
                if "event_title" in outcome:
                    title = outcome.get("event_title", "").strip()
                    exists = await asyncio.to_thread(
                        self._event_exists, title
                    )
                    return exists

            # Verify event update
            if "update" in operation.description.lower():
                return "event_title" in outcome and result.success

            return result.success

        except Exception as e:
            self.logger.error(f"Calendar verification failed: {e}")
            return False

    # === Database Query Methods ===

    def _account_exists(self, account_name: str) -> bool:
        """Check if account exists in database."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM financial_accounts WHERE account_name = ? LIMIT 1",
                    (account_name,),
                )
                return cursor.fetchone() is not None
        except Exception:
            return False

    def _person_exists(self, person_name: str) -> bool:
        """Check if person exists in database."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM people WHERE name = ? LIMIT 1",
                    (person_name,),
                )
                return cursor.fetchone() is not None
        except Exception:
            return False

    def _reminder_exists(self, title: str) -> bool:
        """Check if reminder exists in database."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM reminders WHERE title = ? LIMIT 1",
                    (title,),
                )
                return cursor.fetchone() is not None
        except Exception:
            return False

    def _event_exists(self, title: str) -> bool:
        """Check if calendar event exists in database."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM calendar_events WHERE title = ? LIMIT 1",
                    (title,),
                )
                return cursor.fetchone() is not None
        except Exception:
            return False
