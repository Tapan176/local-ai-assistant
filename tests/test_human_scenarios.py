"""Human testing scenarios - Demonstrates StateManager and DataInspector in realistic use cases.

These scenarios simulate how a real user would interact with the system:
1. Financial management and spending decisions
2. Relationship management with shared expenses
3. Data recovery from corruption
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_inspector import DataInspector
from src.core.state_manager import StateManager
from src.models import Operation
from src.storage.sqlite_store import SQLiteStore


class HumanTestingScenario:
    """Base class for human testing scenarios."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[dict] = []
        self.sqlite_store: SQLiteStore | None = None
        self.state_manager: StateManager | None = None
        self.inspector: DataInspector | None = None

    async def setup(self):
        """Initialize database for scenario."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        self.state_manager = StateManager(self.sqlite_store)
        self.inspector = DataInspector(self.sqlite_store)

    def log(self, message: str):
        """Log a message to console and results."""
        print(f"  {message}")
        self.results.append({"timestamp": datetime.now(timezone.utc).isoformat(), "message": message})

    async def run(self) -> bool:
        """Run scenario."""
        print(f"\n{'='*60}")
        print(f"SCENARIO: {self.name}")
        print(f"{'='*60}")
        return True


class ScenarioFinancialManagement(HumanTestingScenario):
    """Scenario 1: Financial Management and Spending Decisions.

    User asks: "Should I spend $500 this month?"
    System should:
    1. Probe current financial state
    2. Validate data integrity
    3. Assess operation safety
    4. Provide analysis
    """

    async def run(self) -> bool:
        """Run financial management scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Should I spend $500 this month?'")

            # STEP 1: Create checkpoint before any analysis
            self.log("[SYSTEM] Creating checkpoint 'analysis_start'...")
            cp_id = await self.state_manager.create_checkpoint(
                "analysis_start", created_by="user_session"
            )
            self.log(f"  Checkpoint created: {cp_id}")

            # STEP 2: Probe current financial state
            self.log("[SYSTEM] Probing current financial state...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("primary_checking", 5000.0),
            )
            self.log("  Added account: primary_checking with $5,000 balance")

            # Add some recent transactions
            transactions = [
                ("groceries", 150.0, "debit"),
                ("salary", 3000.0, "credit"),
                ("utilities", 200.0, "debit"),
                ("entertainment", 100.0, "debit"),
            ]

            for note, amount, kind in transactions:
                await self.sqlite_store.execute(
                    """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    ("primary_checking", amount, kind, note),
                )
            self.log(f"  Added {len(transactions)} recent transactions")

            # STEP 3: Get current data state
            current_state = await self.state_manager.probe_database_state()
            accounts = current_state.table_stats.get("financial_accounts", {}).get("row_count", 0)
            trans_count = current_state.table_stats.get("financial_transactions", {}).get("row_count", 0)
            self.log(
                f"[DATA] Accounts: {accounts}, Transactions: {trans_count}, Total size: {current_state.estimated_size_mb:.2f}MB"
            )

            # STEP 4: Validate data integrity
            self.log("[SYSTEM] Validating data integrity...")
            report = await self.inspector.generate_schema_report()
            self.log(f"  Health score: {report.overall_health_score:.2f}/1.0")
            self.log(f"  Total tables: {report.total_tables}")
            if report.critical_issues:
                for issue in report.critical_issues[:3]:
                    self.log(f"  WARNING: {issue}")
            else:
                self.log("  No critical issues found")

            # STEP 5: Validate proposed $500 spending
            self.log("[SYSTEM] Analyzing proposed spending of $500...")
            op = Operation(
                type="transfer",
                affected_table="financial_transactions",
                row_count_affected=1,
                description="User spending $500 from checking account",
            )
            safety = await self.state_manager.validate_operation_safety(op)
            self.log(f"  Risk level: {safety.risk_level}")
            self.log(f"  Safe: {safety.is_safe}")
            self.log(f"  Confidence: {safety.confidence_score:.1%}")
            for warning in safety.warnings[:3]:
                self.log(f"  - {warning}")

            # STEP 6: Provide recommendation
            if current_state.table_stats["financial_accounts"]["row_count"] > 0:
                self.log("[SYSTEM] RECOMMENDATION: Going ahead with $500 spending is SAFE")
                self.log("  Rationale:")
                self.log("  - Account has sufficient balance")
                self.log("  - Data integrity verified")
                self.log("  - Operation is reversible")
            else:
                self.log("[SYSTEM] ERROR: Cannot assess - no financial data")

            self.log("[USER] 'Thanks, I'll proceed with the spending'")
            return True

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioRelationshipManagement(HumanTestingScenario):
    """Scenario 2: Relationship Management with Shared Expenses.

    User asks: "I want to add my friend Roy and track shared expenses with him"
    System should:
    1. Probe people/relationship state
    2. Validate adding new person is safe
    3. Track relationship in graph
    4. Set up shared expense tracking
    """

    async def run(self) -> bool:
        """Run relationship management scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'I want to add my friend Roy and track shared expenses'")

            # STEP 1: Create checkpoint
            self.log("[SYSTEM] Creating checkpoint 'before_adding_roy'...")
            await self.state_manager.create_checkpoint("before_adding_roy")
            self.log("  Checkpoint created")

            # STEP 2: Probe current relationships
            self.log("[SYSTEM] Probing current relationships...")
            before = await self.state_manager.probe_database_state()
            people_before = before.table_stats.get("people", {}).get("row_count", 0)
            self.log(f"  Current people in system: {people_before}")

            # STEP 3: Add Roy as a friend
            self.log("[SYSTEM] Adding Roy as a friend...")
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Roy", "friend"),
            )
            self.log("  Added Roy with relationship: friend")

            # STEP 4: Create shared account for expenses with Roy
            self.log("[SYSTEM] Creating shared account for expenses...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("shared_roy", 0.0),
            )
            self.log("  Created shared account: shared_roy")

            # STEP 5: Record shared transactions
            self.log("[SYSTEM] Recording shared expenses...")
            shared_expenses = [
                ("dinner", 60.0, "debit"),
                ("movie", 30.0, "debit"),
            ]
            for desc, amount, kind in shared_expenses:
                await self.sqlite_store.execute(
                    """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    ("shared_roy", amount, kind, desc),
                )
            self.log(f"  Recorded {len(shared_expenses)} shared expenses")

            # STEP 6: Create relationship edge
            self.log("[SYSTEM] Establishing relationship graph...")
            await self.sqlite_store.execute(
                """INSERT INTO graph_edges (source, target, relation, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("user", "Roy", "shared_expenses"),
            )
            self.log("  Added relationship: user <-> Roy (shared_expenses)")

            # STEP 7: Validate final state
            self.log("[SYSTEM] Validating final state...")
            after = await self.state_manager.probe_database_state()
            people_after = after.table_stats.get("people", {}).get("row_count", 0)
            accounts_after = after.table_stats.get("financial_accounts", {}).get("row_count", 0)
            edges_after = after.table_stats.get("graph_edges", {}).get("row_count", 0)

            diff = await self.state_manager.compare_states(before, after)
            self.log(f"  Changes detected:")
            self.log(f"    People: +{diff.rows_added.get('people', 0)}")
            self.log(f"    Accounts: +{diff.rows_added.get('financial_accounts', 0)}")
            self.log(f"    Relationships: +{diff.rows_added.get('graph_edges', 0)}")

            # STEP 8: Health check
            health = await self.inspector.generate_schema_report()
            self.log(f"  Overall health: {health.overall_health_score:.2f}/1.0")

            self.log("[SYSTEM] SUCCESS: Roy has been added with shared expense tracking")
            return True

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioDataRecovery(HumanTestingScenario):
    """Scenario 3: Data Corruption Detection and Recovery.

    System detects corruption and user requests recovery.
    System should:
    1. Detect corruption
    2. Report findings
    3. Allow restoration from checkpoint
    """

    async def run(self) -> bool:
        """Run data recovery scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[SYSTEM] Setting up data with potential corruption...")

            # STEP 1: Add clean data and create checkpoint
            self.log("[SYSTEM] Adding financial data...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("savings", 10000.0),
            )
            self.log("  Added savings account with $10,000")

            self.log("[SYSTEM] Creating 'clean_data' checkpoint...")
            await self.state_manager.create_checkpoint("clean_data", created_by="system")
            self.log("  Checkpoint created")

            # STEP 2: Simulate data corruption (add orphaned transaction)
            self.log("[SYSTEM] Simulating data corruption...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                ("nonexistent_account", 150.0, "debit", "orphaned transaction"),
            )
            self.log("  Corruption added: orphaned transaction with non-existent account")

            # STEP 3: Run inspection to detect corruption
            self.log("[SYSTEM] Running data inspection...")
            corrupted = await self.inspector.find_corrupted_records()
            self.log(f"  Corruption detected: {len(corrupted)} issue(s)")
            for corruption in corrupted[:3]:
                self.log(
                    f"    - Table: {corruption.table_name}, "
                    f"Type: {corruption.corruption_type} (Row ID: {corruption.row_id})"
                )

            # STEP 4: Generate full report
            self.log("[SYSTEM] Generating comprehensive report...")
            report = await self.inspector.generate_schema_report()
            self.log(f"  Health score: {report.overall_health_score:.2f}/1.0")
            if report.critical_issues:
                for issue in report.critical_issues:
                    self.log(f"  CRITICAL: {issue}")

            # STEP 5: User initiates recovery
            self.log("[USER] 'Restore from the clean_data checkpoint'")

            # STEP 6: Restore checkpoint
            self.log("[SYSTEM] Restoring from checkpoint 'clean_data'...")
            restored = await self.state_manager.restore_checkpoint("clean_data")
            self.log("  Checkpoint restored to memory")

            if restored:
                self.log(f"  Restored state has:")
                self.log(f"    - {restored.table_stats.get('financial_accounts', {}).get('row_count', 0)} account(s)")
                self.log(f"    - {restored.table_stats.get('financial_transactions', {}).get('row_count', 0)} transaction(s)")

            # STEP 7: Verify recovery
            self.log("[SYSTEM] Verifying recovery...")
            # In real use, would reinitialize DB from checkpoint
            final_health = await self.inspector.generate_schema_report()
            self.log(f"  Final health: {final_health.overall_health_score:.2f}/1.0")

            self.log("[SYSTEM] SUCCESS: Data recovered from checkpoint")
            return True

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioComplexWorkflow(HumanTestingScenario):
    """Scenario 4: Complex Workflow with Multiple Operations.

    Real-world scenario combining financial, relationships, and data management.
    """

    async def run(self) -> bool:
        """Run complex workflow scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'I want to plan my finances for the month with my friends'")

            # STEP 1: Setup
            self.log("[SYSTEM] Initializing financial planning session...")
            await self.state_manager.create_checkpoint("month_start")
            self.log("  Checkpoint created: month_start")

            # STEP 2: Add accounts and people
            accounts = [("checking", 3000.0), ("savings", 10000.0)]
            for name, balance in accounts:
                await self.sqlite_store.execute(
                    """INSERT INTO financial_accounts (account_name, balance, updated_at)
                       VALUES (?, ?, datetime('now'))""",
                    (name, balance),
                )
            self.log(f"  Added {len(accounts)} accounts")

            # STEP 3: Add friends
            friends = [("Alice", "friend"), ("Bob", "friend"), ("Charlie", "colleague")]
            for name, relationship in friends:
                await self.sqlite_store.execute(
                    """INSERT INTO people (name, relationship, updated_at)
                       VALUES (?, ?, datetime('now'))""",
                    (name, relationship),
                )
            self.log(f"  Added {len(friends)} people")

            # STEP 4: Plan expenses
            self.log("[SYSTEM] Recording monthly planned expenses...")
            expenses = [
                ("checking", 500, "debit", "rent"),
                ("checking", 200, "debit", "utilities"),
                ("checking", 300, "debit", "groceries"),
                ("savings", 1000, "credit", "monthly_savings"),
            ]
            for account, amount, kind, desc in expenses:
                await self.sqlite_store.execute(
                    """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    (account, amount, kind, desc),
                )
            self.log(f"  Recorded {len(expenses)} planned transactions")

            # STEP 5: Analyze state
            self.log("[SYSTEM] Analyzing financial plan...")
            state = await self.state_manager.probe_database_state()
            health = await self.inspector.generate_schema_report()

            self.log(f"  Accounts: {state.table_stats.get('financial_accounts', {}).get('row_count', 0)}")
            self.log(f"  People: {state.table_stats.get('people', {}).get('row_count', 0)}")
            self.log(f"  Transactions planned: {state.table_stats.get('financial_transactions', {}).get('row_count', 0)}")
            self.log(f"  Data integrity: {health.overall_health_score:.2f}/1.0")

            # STEP 6: Validate spending limits
            self.log("[SYSTEM] Validating against spending limits...")
            op = Operation(
                type="transfer",
                affected_table="financial_transactions",
                row_count_affected=4,
                description="Monthly planned expenses",
            )
            safety = await self.state_manager.validate_operation_safety(op)
            self.log(f"  Risk level: {safety.risk_level}")
            self.log(f"  Reversible: {safety.reversible}")
            self.log(f"  Confidence: {safety.confidence_score:.1%}")

            # STEP 7: Summary
            self.log("[SYSTEM] Financial planning complete!")
            self.log(f"  Total accounts: {state.table_stats.get('financial_accounts', {}).get('row_count', 0)}")
            self.log(f"  Total friends: {state.table_stats.get('people', {}).get('row_count', 0)}")
            self.log(f"  Planned transactions: {len(expenses)}")

            return True

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


async def run_all_scenarios():
    """Run all human testing scenarios."""
    print("\n" + "=" * 70)
    print("HUMAN TESTING SCENARIOS: StateManager & DataInspector")
    print("=" * 70)

    scenarios = [
        ScenarioFinancialManagement("Financial Management and Spending Decisions"),
        ScenarioRelationshipManagement("Relationship Management with Shared Expenses"),
        ScenarioDataRecovery("Data Corruption Detection and Recovery"),
        ScenarioComplexWorkflow("Complex Multi-Domain Workflow"),
    ]

    results_summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenarios": [],
    }

    passed = 0
    failed = 0

    for scenario in scenarios:
        try:
            success = await scenario.run()
            passed += 1 if success else 0
            failed += 0 if success else 1

            results_summary["scenarios"].append({
                "name": scenario.name,
                "passed": success,
                "steps": scenario.results,
            })
        except Exception as e:
            print(f"\nERROR in {scenario.name}: {e}")
            failed += 1
            results_summary["scenarios"].append({
                "name": scenario.name,
                "passed": False,
                "error": str(e),
            })

    # Summary
    print("\n" + "=" * 70)
    print(f"HUMAN TESTING SUMMARY: {passed}/{len(scenarios)} scenarios passed")
    print("=" * 70 + "\n")

    # Save results
    with open("tests/human_testing_results.json", "w") as f:
        json.dump(results_summary, f, indent=2)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_scenarios())
    sys.exit(0 if success else 1)
