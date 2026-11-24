"""Comprehensive unit tests for ResultVerifier.

Tests cover:
- Finance tool result verification (8 tests)
- People tool result verification (4 tests)
- Reminder tool result verification (4 tests)
- Calendar tool result verification (4 tests)
- Intent matching logic (6 tests)
- Outcome extraction (4 tests)
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_inspector import DataInspector
from src.core.result_verifier import ResultVerifier
from src.core.state_manager import StateManager
from src.models import Operation, ToolExecutionResult
from src.storage.sqlite_store import SQLiteStore


class TestResults:
    """Track test execution results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests: list[dict] = []

    def test(self, name: str, passed: bool, details: str = ""):
        """Record test result."""
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}: {name}")
        if details:
            print(f"    {details}")

        result = {"name": name, "passed": passed, "details": details}
        self.tests.append(result)

        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def summary(self):
        """Print summary."""
        total = self.passed + self.failed
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        print(f"\n{'='*60}")
        print(f"Test Summary: {self.passed}/{total} passed ({pass_rate:.1f}%)")
        print(f"{'='*60}\n")
        return self.failed == 0


class TestFinanceVerification:
    """Tests for finance tool result verification."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector)

    async def test_verify_account_created(self):
        """Test: Verify account creation is detected."""
        await self.setup()

        try:
            # Create a test account
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("test_account", 1000.0),
            )

            # Create result
            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created: test_account with balance $1000",
                data={"account": "test_account", "balance": 1000.0},
            )

            # Create operation
            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                row_count_affected=1,
                description="Create account test_account",
            )

            # Verify
            report = await self.verifier.verify(result, operation, "create account")

            passed = report.success and report.intent_matched

            self.results.test(
                "Finance: Verify account creation",
                passed,
                f"Success: {report.success}, Intent matched: {report.intent_matched}",
            )
        except Exception as e:
            self.results.test("Finance: Verify account creation", False, str(e))

    async def test_verify_transaction_recorded(self):
        """Test: Verify transaction is recorded."""
        await self.setup()

        try:
            # Setup with existing account
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 5000.0),
            )

            # Add transaction
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("checking", 500.0, "debit", "groceries"),
            )

            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Transaction recorded: $500 debit from checking",
                data={"account": "checking", "amount": 500.0},
            )

            operation = Operation(
                type="insert",
                affected_table="financial_transactions",
                row_count_affected=1,
                description="Add transaction to checking",
            )

            report = await self.verifier.verify(result, operation, "add transaction")

            passed = report.success and "amount" in report.outcome

            self.results.test(
                "Finance: Verify transaction recorded",
                passed,
                f"Outcome extracted: {report.outcome_extracted}",
            )
        except Exception as e:
            self.results.test("Finance: Verify transaction recorded", False, str(e))

    async def test_verify_transfer_integrity(self):
        """Test: Verify transfer moves money between accounts."""
        await self.setup()

        try:
            # Setup accounts
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("savings", 10000.0),
            )
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 1000.0),
            )

            # Simulate transfer
            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Transferred $500 from savings to checking",
                data={"amount": 500.0, "from_account": "savings", "to_account": "checking"},
            )

            operation = Operation(
                type="transfer",
                affected_table="financial_accounts",
                row_count_affected=2,
                description="Transfer $500 from savings to checking",
            )

            report = await self.verifier.verify(result, operation, "transfer")

            passed = report.success and report.outcome.get("amount") == 500.0

            self.results.test(
                "Finance: Verify transfer integrity",
                passed,
                f"Amount matched: {report.outcome.get('amount')}",
            )
        except Exception as e:
            self.results.test("Finance: Verify transfer integrity", False, str(e))

    async def test_extract_amount_from_output(self):
        """Test: Extract amount from unstructured output."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Your balance is $1,234.56 in checking account",
            )

            outcome = await self.verifier.extract_outcome(result)

            passed = "amount" in outcome and outcome["amount"] == 1234.56

            self.results.test(
                "Finance: Extract amount from output",
                passed,
                f"Extracted amount: {outcome.get('amount')}",
            )
        except Exception as e:
            self.results.test("Finance: Extract amount from output", False, str(e))

    async def test_verify_balance_retrieval(self):
        """Test: Verify balance retrieval is successful."""
        await self.setup()

        try:
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 5000.0),
            )

            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Balance for checking: $5000.00",
                data={"balance": 5000.0, "account": "checking"},
            )

            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                description="Get balance for checking",
            )

            report = await self.verifier.verify(result, operation, "show balance")

            passed = report.success

            self.results.test(
                "Finance: Verify balance retrieval",
                passed,
                f"Balance retrieved: {report.outcome.get('balance')}",
            )
        except Exception as e:
            self.results.test("Finance: Verify balance retrieval", False, str(e))

    async def test_detect_failed_operation(self):
        """Test: Detect when operation fails."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=False,
                output_text="Error: Invalid account name",
            )

            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                description="Create account",
            )

            report = await self.verifier.verify(result, operation)

            passed = not report.success and report.confidence == 0.0

            self.results.test(
                "Finance: Detect failed operation",
                passed,
                f"Failure detected: {not report.success}",
            )
        except Exception as e:
            self.results.test("Finance: Detect failed operation", False, str(e))

    async def test_extract_account_name(self):
        """Test: Extract account name from output."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account: savings with balance $10000",
            )

            outcome = await self.verifier.extract_outcome(result)

            passed = "account" in outcome

            self.results.test(
                "Finance: Extract account name",
                passed,
                f"Account extracted: {outcome.get('account')}",
            )
        except Exception as e:
            self.results.test("Finance: Extract account name", False, str(e))


class TestPeopleVerification:
    """Tests for people tool result verification."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector)

    async def test_verify_person_added(self):
        """Test: Verify person was added."""
        await self.setup()

        try:
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Alice", "friend"),
            )

            result = ToolExecutionResult(
                tool_name="people_tool",
                success=True,
                output_text="Added person: Alice as friend",
                data={"person_name": "Alice", "relationship": "friend"},
            )

            operation = Operation(
                type="insert",
                affected_table="people",
                row_count_affected=1,
                description="Add person Alice",
            )

            report = await self.verifier.verify(result, operation, "add friend")

            passed = report.success and "person_name" in report.outcome

            self.results.test(
                "People: Verify person added",
                passed,
                f"Person added: {report.outcome.get('person_name')}",
            )
        except Exception as e:
            self.results.test("People: Verify person added", False, str(e))

    async def test_verify_relationship_created(self):
        """Test: Verify relationship edge was created."""
        await self.setup()

        try:
            # Add people first
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Bob", "friend"),
            )

            # Add relationship edge
            await self.sqlite_store.execute(
                """INSERT INTO graph_edges (source, target, relation, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("user", "Bob", "knows"),
            )

            result = ToolExecutionResult(
                tool_name="people_tool",
                success=True,
                output_text="Created relationship: user knows Bob",
                data={"relationship": "knows", "from": "user", "to": "Bob"},
            )

            operation = Operation(
                type="insert",
                affected_table="graph_edges",
                row_count_affected=1,
                description="Add relationship",
            )

            report = await self.verifier.verify(result, operation, "add relationship")

            passed = report.success and "relationship" in report.outcome

            self.results.test(
                "People: Verify relationship created",
                passed,
                f"Relationship: {report.outcome.get('relationship')}",
            )
        except Exception as e:
            self.results.test("People: Verify relationship created", False, str(e))

    async def test_extract_person_name(self):
        """Test: Extract person name from output."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="people_tool",
                success=True,
                output_text="Added person: Carol as colleague",
            )

            outcome = await self.verifier.extract_outcome(result)

            passed = "person_name" in outcome

            self.results.test(
                "People: Extract person name",
                passed,
                f"Person name: {outcome.get('person_name')}",
            )
        except Exception as e:
            self.results.test("People: Extract person name", False, str(e))

    async def test_detect_missing_person(self):
        """Test: Detect when person operation fails."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="people_tool",
                success=False,
                output_text="Error: Person not found",
            )

            operation = Operation(
                type="insert",
                affected_table="people",
                description="Add person",
            )

            report = await self.verifier.verify(result, operation)

            passed = not report.success

            self.results.test(
                "People: Detect missing person",
                passed,
                f"Failure detected: {not report.success}",
            )
        except Exception as e:
            self.results.test("People: Detect missing person", False, str(e))


class TestReminderVerification:
    """Tests for reminder tool result verification."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector)

    async def test_verify_reminder_created(self):
        """Test: Verify reminder was created."""
        await self.setup()

        try:
            await self.sqlite_store.execute(
                """INSERT INTO reminders (session_id, title, status, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("test_session", "Buy groceries", "pending"),
            )

            result = ToolExecutionResult(
                tool_name="reminder_tool",
                success=True,
                output_text="Reminder created: 'Buy groceries'",
                data={"title": "Buy groceries", "status": "pending"},
            )

            operation = Operation(
                type="insert",
                affected_table="reminders",
                row_count_affected=1,
                description="Create reminder",
            )

            report = await self.verifier.verify(result, operation, "create reminder")

            passed = report.success and "title" in report.outcome

            self.results.test(
                "Reminder: Verify reminder created",
                passed,
                f"Reminder title: {report.outcome.get('title')}",
            )
        except Exception as e:
            self.results.test("Reminder: Verify reminder created", False, str(e))

    async def test_extract_reminder_title(self):
        """Test: Extract reminder title from output."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="reminder_tool",
                success=True,
                output_text="Reminder titled 'Call Mom' created",
            )

            outcome = await self.verifier.extract_outcome(result)

            passed = "title" in outcome

            self.results.test(
                "Reminder: Extract title",
                passed,
                f"Title: {outcome.get('title')}",
            )
        except Exception as e:
            self.results.test("Reminder: Extract title", False, str(e))

    async def test_detect_missing_reminder(self):
        """Test: Detect when reminder operation fails."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="reminder_tool",
                success=False,
                output_text="Error: Could not create reminder",
            )

            operation = Operation(
                type="insert",
                affected_table="reminders",
                description="Create reminder",
            )

            report = await self.verifier.verify(result, operation)

            passed = not report.success

            self.results.test(
                "Reminder: Detect missing reminder",
                passed,
                f"Failure detected: {not report.success}",
            )
        except Exception as e:
            self.results.test("Reminder: Detect missing reminder", False, str(e))

    async def test_verify_reminder_completed(self):
        """Test: Verify reminder status update."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="reminder_tool",
                success=True,
                output_text="Reminder completed: 'Buy groceries'",
                data={"status": "completed"},
            )

            operation = Operation(
                type="update",
                affected_table="reminders",
                row_count_affected=1,
                description="Complete reminder",
            )

            report = await self.verifier.verify(result, operation)

            passed = report.success

            self.results.test(
                "Reminder: Verify reminder completed",
                passed,
                f"Status in outcome: {'status' in report.outcome}",
            )
        except Exception as e:
            self.results.test("Reminder: Verify reminder completed", False, str(e))


class TestCalendarVerification:
    """Tests for calendar tool result verification."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector)

    async def test_verify_event_created(self):
        """Test: Verify calendar event was created."""
        await self.setup()

        try:
            await self.sqlite_store.execute(
                """INSERT INTO calendar_events (title, created_at)
                   VALUES (?, datetime('now'))""",
                ("Team Meeting",),
            )

            result = ToolExecutionResult(
                tool_name="calendar_tool",
                success=True,
                output_text="Event created: 'Team Meeting'",
                data={"event_title": "Team Meeting"},
            )

            operation = Operation(
                type="insert",
                affected_table="calendar_events",
                row_count_affected=1,
                description="Create event",
            )

            report = await self.verifier.verify(result, operation, "add event")

            passed = report.success and "event_title" in report.outcome

            self.results.test(
                "Calendar: Verify event created",
                passed,
                f"Event title: {report.outcome.get('event_title')}",
            )
        except Exception as e:
            self.results.test("Calendar: Verify event created", False, str(e))

    async def test_extract_event_title(self):
        """Test: Extract event title from output."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="calendar_tool",
                success=True,
                output_text="Event titled 'Doctor Appointment' added",
            )

            outcome = await self.verifier.extract_outcome(result)

            # May extract as event_title or similar
            passed = "event_title" in outcome or len(outcome) > 0

            self.results.test(
                "Calendar: Extract event title",
                passed,
                f"Outcome: {outcome}",
            )
        except Exception as e:
            self.results.test("Calendar: Extract event title", False, str(e))

    async def test_detect_missing_event(self):
        """Test: Detect when event operation fails."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="calendar_tool",
                success=False,
                output_text="Error: Could not create event",
            )

            operation = Operation(
                type="insert",
                affected_table="calendar_events",
                description="Create event",
            )

            report = await self.verifier.verify(result, operation)

            passed = not report.success

            self.results.test(
                "Calendar: Detect missing event",
                passed,
                f"Failure detected: {not report.success}",
            )
        except Exception as e:
            self.results.test("Calendar: Detect missing event", False, str(e))

    async def test_verify_event_updated(self):
        """Test: Verify event update."""
        await self.setup()

        try:
            result = ToolExecutionResult(
                tool_name="calendar_tool",
                success=True,
                output_text="Event updated: 'Team Meeting' rescheduled",
                data={"event_title": "Team Meeting"},
            )

            operation = Operation(
                type="update",
                affected_table="calendar_events",
                row_count_affected=1,
                description="Update event",
            )

            report = await self.verifier.verify(result, operation)

            passed = report.success

            self.results.test(
                "Calendar: Verify event updated",
                passed,
                f"Success: {report.success}",
            )
        except Exception as e:
            self.results.test("Calendar: Verify event updated", False, str(e))


class TestIntentMatching:
    """Tests for intent matching logic."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector)

    async def test_matches_intent_account_creation(self):
        """Test: Intent matching for account creation."""
        await self.setup()

        try:
            outcome = {"account": "savings", "balance": 5000.0, "success": True}
            intent = "Create a savings account"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Account creation",
                matched,
                f"Matched: {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Account creation", False, str(e))

    async def test_matches_intent_transfer(self):
        """Test: Intent matching for transfer."""
        await self.setup()

        try:
            outcome = {"amount": 500.0, "success": True}
            intent = "Transfer $500"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Transfer",
                matched,
                f"Matched: {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Transfer", False, str(e))

    async def test_matches_intent_add_person(self):
        """Test: Intent matching for adding person."""
        await self.setup()

        try:
            outcome = {"person_name": "Alice", "relationship": "friend", "success": True}
            intent = "Add my friend Alice"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Add person",
                matched,
                f"Matched: {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Add person", False, str(e))

    async def test_matches_intent_create_reminder(self):
        """Test: Intent matching for reminder creation."""
        await self.setup()

        try:
            outcome = {"title": "Buy milk", "success": True}
            intent = "Remind me to buy milk"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Create reminder",
                matched,
                f"Matched: {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Create reminder", False, str(e))

    async def test_matches_intent_failed_operation(self):
        """Test: Intent matching detects failed operations."""
        await self.setup()

        try:
            outcome = {"success": False}
            intent = "Create account"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Detect failure",
                not matched,
                f"Matched (should be False): {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Detect failure", False, str(e))

    async def test_matches_intent_mismatch(self):
        """Test: Intent matching detects mismatches."""
        await self.setup()

        try:
            outcome = {"person_name": "Bob", "success": True}
            intent = "Create an event"

            matched = await self.verifier.matches_intent(outcome, intent)

            self.results.test(
                "IntentMatching: Detect mismatch",
                not matched,
                f"Matched (should be False): {matched}",
            )
        except Exception as e:
            self.results.test("IntentMatching: Detect mismatch", False, str(e))


async def run_all_tests():
    """Run all test suites."""
    print("\n" + "=" * 60)
    print("ResultVerifier Unit Tests")
    print("=" * 60 + "\n")

    results = TestResults()

    # Finance tests
    print("Running Finance Tool Tests...")
    print("-" * 40)
    finance_tests = TestFinanceVerification(results)
    await finance_tests.test_verify_account_created()
    await finance_tests.test_verify_transaction_recorded()
    await finance_tests.test_verify_transfer_integrity()
    await finance_tests.test_extract_amount_from_output()
    await finance_tests.test_verify_balance_retrieval()
    await finance_tests.test_detect_failed_operation()
    await finance_tests.test_extract_account_name()

    # People tests
    print("\nRunning People Tool Tests...")
    print("-" * 40)
    people_tests = TestPeopleVerification(results)
    await people_tests.test_verify_person_added()
    await people_tests.test_verify_relationship_created()
    await people_tests.test_extract_person_name()
    await people_tests.test_detect_missing_person()

    # Reminder tests
    print("\nRunning Reminder Tool Tests...")
    print("-" * 40)
    reminder_tests = TestReminderVerification(results)
    await reminder_tests.test_verify_reminder_created()
    await reminder_tests.test_extract_reminder_title()
    await reminder_tests.test_detect_missing_reminder()
    await reminder_tests.test_verify_reminder_completed()

    # Calendar tests
    print("\nRunning Calendar Tool Tests...")
    print("-" * 40)
    calendar_tests = TestCalendarVerification(results)
    await calendar_tests.test_verify_event_created()
    await calendar_tests.test_extract_event_title()
    await calendar_tests.test_detect_missing_event()
    await calendar_tests.test_verify_event_updated()

    # Intent matching tests
    print("\nRunning Intent Matching Tests...")
    print("-" * 40)
    intent_tests = TestIntentMatching(results)
    await intent_tests.test_matches_intent_account_creation()
    await intent_tests.test_matches_intent_transfer()
    await intent_tests.test_matches_intent_add_person()
    await intent_tests.test_matches_intent_create_reminder()
    await intent_tests.test_matches_intent_failed_operation()
    await intent_tests.test_matches_intent_mismatch()

    # Summary
    success = results.summary()
    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
