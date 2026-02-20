"""Comprehensive tests for StateManager and DataInspector.

Tests cover:
- StateManager: database state probing, comparison, checkpoints, safety validation
- DataInspector: table inspection, corruption detection, foreign key validation, anomaly detection
- Integration: realistic scenarios simulating human usage
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import get_settings
from src.core.data_inspector import DataInspector
from src.core.state_manager import StateManager
from src.models import Operation
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


class TestStateManager:
    """Tests for StateManager."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.state_manager: StateManager | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        self.state_manager = StateManager(self.sqlite_store)

    async def test_probe_database_state(self):
        """Test: probe_database_state returns all tables."""
        await self.setup()

        try:
            state = await self.state_manager.probe_database_state()

            # Should have all expected tables
            has_episodes = "episodes" in state.snapshots
            has_people = "people" in state.snapshots
            has_finance = "financial_accounts" in state.snapshots

            all_tables = len(state.snapshots) >= 10

            passed = has_episodes and has_people and has_finance and all_tables

            self.results.test(
                "StateManager: probe_database_state returns all tables",
                passed,
                f"Found {len(state.snapshots)} tables",
            )
        except Exception as e:
            self.results.test(
                "StateManager: probe_database_state returns all tables",
                False,
                str(e),
            )

    async def test_probe_captures_row_counts(self):
        """Test: probe_database_state captures row counts."""
        await self.setup()

        try:
            # Add data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Alice", "friend"),
            )

            state = await self.state_manager.probe_database_state()
            people_count = state.table_stats.get("people", {}).get("row_count", 0)

            passed = people_count == 1

            self.results.test(
                "StateManager: probe captures row counts correctly",
                passed,
                f"People table has {people_count} row(s)",
            )
        except Exception as e:
            self.results.test(
                "StateManager: probe captures row counts correctly",
                False,
                str(e),
            )

    async def test_compare_states_detects_additions(self):
        """Test: compare_states identifies added rows."""
        await self.setup()

        try:
            # Get first state
            before = await self.state_manager.probe_database_state()

            # Add data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Bob", "colleague"),
            )

            # Get second state
            after = await self.state_manager.probe_database_state()

            # Compare
            diff = await self.state_manager.compare_states(before, after)

            passed = "people" in diff.rows_added and diff.rows_added["people"] == 1

            self.results.test(
                "StateManager: compare_states detects added rows",
                passed,
                f"Rows added: {diff.rows_added}",
            )
        except Exception as e:
            self.results.test(
                "StateManager: compare_states detects added rows",
                False,
                str(e),
            )

    async def test_create_checkpoint(self):
        """Test: create_checkpoint saves state."""
        await self.setup()

        try:
            # Add data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Charlie", "manager"),
            )

            # Create checkpoint
            checkpoint_id = await self.state_manager.create_checkpoint(
                "test_checkpoint_1", created_by="test_user"
            )

            # Verify checkpoint was stored
            restored = await self.state_manager.restore_checkpoint(
                "test_checkpoint_1"
            )

            passed = (
                restored is not None
                and restored.table_stats.get("people", {}).get("row_count") == 1
            )

            self.results.test(
                "StateManager: create and restore checkpoint",
                passed,
                f"Checkpoint ID: {checkpoint_id}",
            )
        except Exception as e:
            self.results.test(
                "StateManager: create and restore checkpoint",
                False,
                str(e),
            )

    async def test_validate_operation_safety_delete(self):
        """Test: validate_operation_safety for DELETE."""
        await self.setup()

        try:
            # Add data
            for i in range(5):
                await self.sqlite_store.execute(
                    """INSERT INTO people (name, relationship, updated_at)
                       VALUES (?, ?, datetime('now'))""",
                    (f"Person{i}", "friend"),
                )

            # Validate delete operation
            op = Operation(
                type="delete",
                affected_table="people",
                row_count_affected=5,
                risk_level="high",
            )

            report = await self.state_manager.validate_operation_safety(op)

            passed = not report.is_safe and report.risk_level == "high"

            self.results.test(
                "StateManager: validate_operation_safety detects risky DELETE",
                passed,
                f"Risk level: {report.risk_level}, Safe: {report.is_safe}",
            )
        except Exception as e:
            self.results.test(
                "StateManager: validate_operation_safety detects risky DELETE",
                False,
                str(e),
            )

    async def test_validate_operation_safety_safe_insert(self):
        """Test: validate_operation_safety allows safe INSERT."""
        await self.setup()

        try:
            op = Operation(
                type="insert",
                affected_table="people",
                row_count_affected=1,
                risk_level="low",
            )

            report = await self.state_manager.validate_operation_safety(op)

            passed = report.is_safe and report.risk_level == "low"

            self.results.test(
                "StateManager: validate_operation_safety allows safe INSERT",
                passed,
                f"Risk level: {report.risk_level}, Safe: {report.is_safe}",
            )
        except Exception as e:
            self.results.test(
                "StateManager: validate_operation_safety allows safe INSERT",
                False,
                str(e),
            )


class TestDataInspector:
    """Tests for DataInspector."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.inspector: DataInspector | None = None

    async def setup(self, with_corruption: bool = False):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        self.inspector = DataInspector(self.sqlite_store)

        if with_corruption:
            await self._add_corrupted_data()

    async def _add_corrupted_data(self):
        """Add corrupted data for testing."""
        # Add NULL in required field
        await self.sqlite_store.execute(
            """INSERT INTO episodes (session_id, timestamp, user_text, assistant_text,
                emotional_state, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("session1", "2024-01-01T00:00:00Z", "hello", "world", "neutral", "{}"),
        )

        # Add negative balance (anomaly)
        await self.sqlite_store.execute(
            """INSERT INTO financial_accounts (account_name, balance, updated_at)
               VALUES (?, ?, datetime('now'))""",
            ("test_account", -500.0),
        )

        # Add orphaned transaction (foreign key violation)
        await self.sqlite_store.execute(
            """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            ("nonexistent_account", 100.0, "debit", "test"),
        )

    async def test_inspect_table(self):
        """Test: inspect_table returns report."""
        await self.setup()

        try:
            # Add clean data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Eve", "friend"),
            )

            report = await self.inspector.inspect_table("people")

            passed = (
                report.table_name == "people"
                and report.row_count == 1
                and report.overall_health_score >= 0.9
            )

            self.results.test(
                "DataInspector: inspect_table returns valid report",
                passed,
                f"Health: {report.overall_health_score:.2f}, Rows: {report.row_count}",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: inspect_table returns valid report",
                False,
                str(e),
            )

    async def test_find_corrupted_records(self):
        """Test: find_corrupted_records detects corruption."""
        await self.setup(with_corruption=True)

        try:
            corrupted = await self.inspector.find_corrupted_records()

            # Should find orphaned transactions and other issues
            has_orphaned_transactions = any(
                c.corruption_type == "foreign_key_orphan" for c in corrupted
            )

            passed = len(corrupted) > 0

            self.results.test(
                "DataInspector: find_corrupted_records detects issues",
                passed,
                f"Found {len(corrupted)} corrupted record(s)",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: find_corrupted_records detects issues",
                False,
                str(e),
            )

    async def test_validate_foreign_keys(self):
        """Test: validate_foreign_keys checks constraints."""
        await self.setup()

        try:
            # Add orphaned transaction (no matching account)
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("nonexistent_account", 100.0, "debit", "test"),
            )

            violations = await self.inspector.validate_foreign_keys()

            passed = len(violations) > 0

            self.results.test(
                "DataInspector: validate_foreign_keys finds orphaned records",
                passed,
                f"Found {len(violations)} violation(s)",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: validate_foreign_keys finds orphaned records",
                False,
                str(e),
            )

    async def test_detect_anomalies(self):
        """Test: detect_data_anomalies finds unusual data."""
        await self.setup()

        try:
            # Add negative balance (anomaly)
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", -1000.0),
            )

            anomalies = await self.inspector.detect_data_anomalies()

            # Should detect negative balance
            has_anomaly = any(
                a.type == "unusual_value"
                and "negative" in a.description.lower()
                for a in anomalies
            )

            passed = len(anomalies) > 0 and has_anomaly

            self.results.test(
                "DataInspector: detect_data_anomalies finds unusual values",
                passed,
                f"Found {len(anomalies)} anomaly(ies)",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: detect_data_anomalies finds unusual values",
                False,
                str(e),
            )

    async def test_table_health_score(self):
        """Test: get_table_health_score returns valid score."""
        await self.setup()

        try:
            score = await self.inspector.get_table_health_score("people")

            passed = 0.0 <= score <= 1.0

            self.results.test(
                "DataInspector: get_table_health_score returns valid range",
                passed,
                f"Health score: {score:.2f}",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: get_table_health_score returns valid range",
                False,
                str(e),
            )

    async def test_generate_schema_report(self):
        """Test: generate_schema_report provides complete report."""
        await self.setup()

        try:
            report = await self.inspector.generate_schema_report()

            passed = (
                report.total_tables > 0
                and len(report.table_reports) > 0
                and 0.0 <= report.overall_health_score <= 1.0
            )

            self.results.test(
                "DataInspector: generate_schema_report returns complete report",
                passed,
                f"Tables: {report.total_tables}, Health: {report.overall_health_score:.2f}",
            )
        except Exception as e:
            self.results.test(
                "DataInspector: generate_schema_report returns complete report",
                False,
                str(e),
            )


class TestIntegration:
    """Integration tests simulating human usage scenarios."""

    def __init__(self, results: TestResults):
        self.results = results
        self.sqlite_store: SQLiteStore | None = None
        self.state_manager: StateManager | None = None
        self.inspector: DataInspector | None = None

    async def setup(self):
        """Setup test database."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        self.state_manager = StateManager(self.sqlite_store)
        self.inspector = DataInspector(self.sqlite_store)

    async def test_scenario_financial_workflow(self):
        """Test: Full financial workflow with state tracking."""
        await self.setup()

        try:
            # Scenario: User adds account and transactions

            # Step 1: Create checkpoint
            cp1 = await self.state_manager.create_checkpoint("before_finance")

            # Step 2: Add account
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 1000.0),
            )

            # Step 3: Add transactions
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("checking", 500.0, "debit", "groceries"),
            )

            # Step 4: Get state after changes
            after = await self.state_manager.probe_database_state()

            # Step 5: Validate integrity
            report = await self.inspector.generate_schema_report()

            passed = (
                after.table_stats["financial_accounts"]["row_count"] == 1
                and after.table_stats["financial_transactions"]["row_count"] == 1
                and report.overall_health_score > 0.9
            )

            self.results.test(
                "Integration: Financial workflow with state tracking",
                passed,
                f"Accounts: {after.table_stats['financial_accounts']['row_count']}, "
                f"Transactions: {after.table_stats['financial_transactions']['row_count']}, "
                f"Health: {report.overall_health_score:.2f}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Financial workflow with state tracking",
                False,
                str(e),
            )

    async def test_scenario_people_management(self):
        """Test: People management with relationship tracking."""
        await self.setup()

        try:
            # Add people
            for name in ["Frank", "Grace", "Henry"]:
                await self.sqlite_store.execute(
                    """INSERT INTO people (name, relationship, updated_at)
                       VALUES (?, ?, datetime('now'))""",
                    (name, "friend"),
                )

            # Add relationships
            for source, target in [("Frank", "Grace"), ("Grace", "Henry")]:
                await self.sqlite_store.execute(
                    """INSERT INTO graph_edges (source, target, relation, created_at)
                       VALUES (?, ?, ?, datetime('now'))""",
                    (source, target, "knows"),
                )

            # Validate
            state = await self.state_manager.probe_database_state()
            people_count = state.table_stats["people"]["row_count"]
            edges_count = state.table_stats["graph_edges"]["row_count"]

            passed = people_count == 3 and edges_count == 2

            self.results.test(
                "Integration: People management with relationships",
                passed,
                f"People: {people_count}, Relationships: {edges_count}",
            )
        except Exception as e:
            self.results.test(
                "Integration: People management with relationships",
                False,
                str(e),
            )

    async def test_scenario_recovery_from_checkpoint(self):
        """Test: Restore from checkpoint after damage."""
        await self.setup()

        try:
            # Add initial data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Iris", "friend"),
            )

            # Create checkpoint
            await self.state_manager.create_checkpoint("safe_point", created_by="user")

            # Add more data
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Jack", "colleague"),
            )

            # Check current state
            current = await self.state_manager.probe_database_state()
            current_count = current.table_stats["people"]["row_count"]

            # Get checkpoint
            checkpoint = await self.state_manager.restore_checkpoint("safe_point")
            checkpoint_count = checkpoint.table_stats["people"]["row_count"]

            # The checkpoint should have 1 person, current should have 2
            passed = current_count == 2 and checkpoint_count == 1

            self.results.test(
                "Integration: Restore from checkpoint after changes",
                passed,
                f"Current: {current_count}, Checkpoint: {checkpoint_count}",
            )
        except Exception as e:
            self.results.test(
                "Integration: Restore from checkpoint after changes",
                False,
                str(e),
            )


async def run_all_tests():
    """Run all test suites."""
    print("\n" + "=" * 60)
    print("StateManager & DataInspector Test Suite")
    print("=" * 60 + "\n")

    results = TestResults()

    # StateManager tests
    print("Running StateManager Tests...")
    print("-" * 40)
    state_tests = TestStateManager(results)
    await state_tests.test_probe_database_state()
    await state_tests.test_probe_captures_row_counts()
    await state_tests.test_compare_states_detects_additions()
    await state_tests.test_create_checkpoint()
    await state_tests.test_validate_operation_safety_delete()
    await state_tests.test_validate_operation_safety_safe_insert()

    # DataInspector tests
    print("\nRunning DataInspector Tests...")
    print("-" * 40)
    inspector_tests = TestDataInspector(results)
    await inspector_tests.test_inspect_table()
    await inspector_tests.test_find_corrupted_records()
    await inspector_tests.test_validate_foreign_keys()
    await inspector_tests.test_detect_anomalies()
    await inspector_tests.test_table_health_score()
    await inspector_tests.test_generate_schema_report()

    # Integration tests
    print("\nRunning Integration Tests...")
    print("-" * 40)
    integration_tests = TestIntegration(results)
    await integration_tests.test_scenario_financial_workflow()
    await integration_tests.test_scenario_people_management()
    await integration_tests.test_scenario_recovery_from_checkpoint()

    # Summary
    success = results.summary()

    # Save results to file
    with open("tests/test_state_and_inspector_results.json", "w") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_tests": len(results.tests),
                "passed": results.passed,
                "failed": results.failed,
                "tests": results.tests,
            },
            f,
            indent=2,
        )

    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
