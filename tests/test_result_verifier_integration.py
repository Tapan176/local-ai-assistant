"""Integration tests for ResultVerifier with StateManager and DataInspector.

Tests verify:
1. ResultVerifier + StateManager workflow
2. Verification after real financial operations
3. Chain of verifications across multiple tools
"""

import asyncio
import sys
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
        print(f"Integration Test Summary: {self.passed}/{total} passed ({pass_rate:.1f}%)")
        print(f"{'='*60}\n")
        return self.failed == 0


class TestIntegration:
    """Integration tests with StateManager and DataInspector."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None
        self.state_manager: StateManager | None = None
        self.inspector: DataInspector | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        self.state_manager = StateManager(self.sqlite_store)
        self.inspector = DataInspector(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, self.inspector, self.state_manager)

    async def test_verifier_with_state_tracking(self):
        """Test: Verification works with state tracking."""
        await self.setup()

        try:
            # Get initial state
            state_before = await self.state_manager.probe_database_state()
            accounts_before = state_before.table_stats.get("financial_accounts", {}).get("row_count", 0)

            # Perform operation
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("integration_test", 5000.0),
            )

            # Get final state
            state_after = await self.state_manager.probe_database_state()
            accounts_after = state_after.table_stats.get("financial_accounts", {}).get("row_count", 0)

            # Create result
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created: integration_test with $5000",
                data={"account": "integration_test", "balance": 5000.0},
            )

            # Verify
            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                row_count_affected=1,
                description="Create account",
            )
            report = await self.verifier.verify(tool_result, operation)

            # Check state change
            state_changed = accounts_after > accounts_before

            passed = report.success and state_changed

            self.results.test(
                "Integration: Verifier with state tracking",
                passed,
                f"Account added: {state_changed}, Verified: {report.success}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Verifier with state tracking",
                False,
                str(e),
            )

    async def test_verifier_with_data_inspection(self):
        """Test: Verification uses DataInspector for validation."""
        await self.setup()

        try:
            # Add account
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("test_account", 1000.0),
            )

            # Create result
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created successfully",
                data={"account": "test_account"},
            )

            # Verify
            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                description="Create account",
            )
            report = await self.verifier.verify(tool_result, operation)

            # Get health check
            health = await self.inspector.get_table_health_score("financial_accounts")

            passed = report.success and health > 0.8

            self.results.test(
                "Integration: Verifier with DataInspector",
                passed,
                f"Account health: {health:.2f}, Verified: {report.success}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Verifier with DataInspector",
                False,
                str(e),
            )

    async def test_verification_chain_across_operations(self):
        """Test: Multiple verifications in sequence."""
        await self.setup()

        try:
            all_verified = True

            # Operation 1: Create account
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("chain_test", 5000.0),
            )

            result1 = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created",
                data={"account": "chain_test"},
            )
            op1 = Operation(
                type="insert",
                affected_table="financial_accounts",
                description="Create account",
            )
            report1 = await self.verifier.verify(result1, op1)
            all_verified = all_verified and report1.success

            # Operation 2: Add transaction
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("chain_test", 500.0, "debit", "test"),
            )

            result2 = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Transaction recorded: $500",
                data={"amount": 500.0},
            )
            op2 = Operation(
                type="insert",
                affected_table="financial_transactions",
                description="Add transaction",
            )
            report2 = await self.verifier.verify(result2, op2)
            all_verified = all_verified and report2.success

            # Operation 3: Add person
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("ChainTest", "friend"),
            )

            result3 = ToolExecutionResult(
                tool_name="people_tool",
                success=True,
                output_text="Added person: ChainTest",
                data={"person_name": "ChainTest"},
            )
            op3 = Operation(
                type="insert",
                affected_table="people",
                description="Add person",
            )
            report3 = await self.verifier.verify(result3, op3)
            all_verified = all_verified and report3.success

            passed = all_verified

            self.results.test(
                "Integration: Verification chain across operations",
                passed,
                f"Verified operations: {sum([report1.success, report2.success, report3.success])}/3",
            )
        except Exception as e:
            self.results.test(
                "Integration: Verification chain across operations",
                False,
                str(e),
            )

    async def test_verification_detects_corruption(self):
        """Test: Verification can identify inconsistent data."""
        await self.setup()

        try:
            # Add transaction without account (orphaned)
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("nonexistent", 500.0, "debit", "orphaned"),
            )

            # Create result claiming success
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Transaction recorded",
                data={"amount": 500.0},
            )

            # Verify - should detect the issue in database state
            operation = Operation(
                type="insert",
                affected_table="financial_transactions",
                description="Add transaction",
            )

            # Get health score
            health = await self.inspector.get_table_health_score("financial_transactions")

            # Verify the result
            report = await self.verifier.verify(tool_result, operation)

            # Orphaned transaction should show in inspection
            corrupted = await self.inspector.find_corrupted_records()

            has_orphaned = any(
                c.corruption_type == "foreign_key_orphan"
                for c in corrupted
            )

            passed = has_orphaned or health < 1.0

            self.results.test(
                "Integration: Verification detects corruption",
                passed,
                f"Orphaned detected: {has_orphaned}, Health: {health:.2f}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Verification detects corruption",
                False,
                str(e),
            )

    async def test_verification_with_checkpoint(self):
        """Test: Verification works with state checkpoints."""
        await self.setup()

        try:
            # Create checkpoint before
            await self.state_manager.create_checkpoint("before_test", created_by="test")

            # Perform operation
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checkpoint_test", 1000.0),
            )

            # Verify operation
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created",
                data={"account": "checkpoint_test"},
            )

            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                description="Create account",
            )
            report = await self.verifier.verify(tool_result, operation)

            # Restore checkpoint
            checkpoint = await self.state_manager.restore_checkpoint("before_test")

            passed = report.success and checkpoint is not None

            self.results.test(
                "Integration: Verification with checkpoint",
                passed,
                f"Verified: {report.success}, Checkpoint exists: {checkpoint is not None}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Verification with checkpoint",
                False,
                str(e),
            )


async def run_all_tests():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("ResultVerifier Integration Tests")
    print("=" * 60 + "\n")

    results = TestResults()

    print("Running Integration Tests...")
    print("-" * 40)
    tests = TestIntegration(results)
    await tests.test_verifier_with_state_tracking()
    await tests.test_verifier_with_data_inspection()
    await tests.test_verification_chain_across_operations()
    await tests.test_verification_detects_corruption()
    await tests.test_verification_with_checkpoint()

    # Summary
    success = results.summary()
    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
