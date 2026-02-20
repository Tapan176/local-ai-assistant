"""Human testing scenarios for ResultVerifier.

Demonstrates realistic user workflows with verification:
1. Create account and verify
2. Transfer money and verify integrity
3. Add person and create relationship
4. Detect failed operations
5. Sequential transaction verification
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_inspector import DataInspector
from src.core.result_verifier import ResultVerifier
from src.core.state_manager import StateManager
from src.models import Operation, ToolExecutionResult
from src.storage.sqlite_store import SQLiteStore


class HumanScenario:
    """Base class for human testing scenarios."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[dict] = []
        self.sqlite_store: SQLiteStore | None = None
        self.verifier: ResultVerifier | None = None
        self.state_manager: StateManager | None = None

    async def setup(self):
        """Initialize database for scenario."""
        self.sqlite_store = SQLiteStore(":memory:")
        await self.sqlite_store.initialize()
        data_inspector = DataInspector(self.sqlite_store)
        self.state_manager = StateManager(self.sqlite_store)
        self.verifier = ResultVerifier(self.sqlite_store, data_inspector, self.state_manager)

    def log(self, message: str):
        """Log a message to console and results."""
        print(f"  {message}")
        self.results.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message
        })

    async def run(self) -> bool:
        """Run scenario."""
        print(f"\n{'='*60}")
        print(f"SCENARIO: {self.name}")
        print(f"{'='*60}")
        return True


class ScenarioCreateAccountAndVerify(HumanScenario):
    """Scenario 1: Create Account and Verify.

    User action: Create checking account with $1000
    Verification: ResultVerifier confirms account exists with correct balance
    Expected result: VERIFIED [OK]
    """

    async def run(self) -> bool:
        """Run scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Create a checking account with $1000'")

            # STEP 1: Simulate tool execution
            self.log("[SYSTEM] Creating account...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 1000.0),
            )
            self.log("  Account created in database")

            # STEP 2: Create result as if tool returned it
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Account created: checking with balance $1000.00",
                data={"account": "checking", "balance": 1000.0},
            )
            self.log("[TOOL] Returned successful result")

            # STEP 3: Verify the result
            operation = Operation(
                type="insert",
                affected_table="financial_accounts",
                row_count_affected=1,
                description="Create checking account with $1000",
            )
            self.log("[VERIFICATION] Verifying result...")
            report = await self.verifier.verify(tool_result, operation, "create account")

            self.log(f"  Success: {report.success}")
            self.log(f"  Intent matched: {report.intent_matched}")
            self.log(f"  Confidence: {report.confidence:.1%}")
            self.log(f"  Outcome: {report.outcome}")

            # STEP 4: Verify database state
            self.log("[DATABASE CHECK] Querying account...")
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT account_name, balance FROM financial_accounts WHERE account_name = 'checking'"
                )
                row = cursor.fetchone()
            if row:
                self.log(f"  Account found: {row[0]} with balance ${row[1]}")
            else:
                self.log("  ERROR: Account not found in database!")
                return False

            # RESULT
            if report.success and report.intent_matched:
                self.log("[RESULT] [OK] VERIFIED - Account created and verified successfully")
                return True
            else:
                self.log("[RESULT] [FAIL] FAILED - Verification did not pass")
                return False

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioTransferMoneyAndVerify(HumanScenario):
    """Scenario 2: Transfer Money and Verify Integrity.

    User action: Transfer $200 from checking to savings
    Verification: Check both accounts updated correctly ($200 moved)
    Expected result: VERIFIED [OK]
    """

    async def run(self) -> bool:
        """Run scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Transfer $200 from checking to savings'")

            # STEP 1: Setup accounts
            self.log("[SYSTEM] Setting up accounts...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 1000.0),
            )
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("savings", 5000.0),
            )
            self.log("  Accounts created: checking ($1000), savings ($5000)")

            # STEP 2: Simulate transfer
            self.log("[SYSTEM] Processing transfer...")
            await self.sqlite_store.execute(
                "UPDATE financial_accounts SET balance = balance - 200 WHERE account_name = 'checking'"
            )
            await self.sqlite_store.execute(
                "UPDATE financial_accounts SET balance = balance + 200 WHERE account_name = 'savings'"
            )
            self.log("  Transfer executed")

            # STEP 3: Create result
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=True,
                output_text="Transferred $200 from checking to savings. Checking: $800, Savings: $5200",
                data={
                    "amount": 200.0,
                    "from_account": "checking",
                    "to_account": "savings",
                    "from_balance": 800.0,
                    "to_balance": 5200.0,
                },
            )
            self.log("[TOOL] Returned transfer result")

            # STEP 4: Verify the transfer
            operation = Operation(
                type="transfer",
                affected_table="financial_accounts",
                row_count_affected=2,
                description="Transfer $200 from checking to savings",
            )
            self.log("[VERIFICATION] Verifying transfer integrity...")
            report = await self.verifier.verify(tool_result, operation, "transfer money")

            self.log(f"  Transfer verified: {report.intent_matched}")
            self.log(f"  Amount: ${report.outcome.get('amount', 'N/A')}")

            # STEP 5: Check database integrity
            self.log("[DATABASE CHECK] Verifying balances...")
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT account_name, balance FROM financial_accounts ORDER BY account_name"
                )
                rows = cursor.fetchall()

            checking_balance = None
            savings_balance = None
            for row in rows:
                if row[0] == "checking":
                    checking_balance = row[1]
                elif row[0] == "savings":
                    savings_balance = row[1]

            self.log(f"  Checking balance: ${checking_balance}")
            self.log(f"  Savings balance: ${savings_balance}")

            # RESULT
            if (checking_balance == 800.0 and savings_balance == 5200.0 and
                report.success and report.intent_matched):
                self.log("[RESULT] [OK] VERIFIED - Transfer integrity confirmed")
                return True
            else:
                self.log("[RESULT] [FAIL] FAILED - Transfer verification failed or balances incorrect")
                return False

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioAddPersonAndRelationship(HumanScenario):
    """Scenario 3: Add Person and Complex Relationship.

    User action: Add friend "Alice" and create shared_expenses relationship
    Verification: Person exists AND relationship edge created
    Expected result: VERIFIED [OK]
    """

    async def run(self) -> bool:
        """Run scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Add my friend Alice and track shared expenses'")

            # STEP 1: Add person
            self.log("[SYSTEM] Adding person...")
            await self.sqlite_store.execute(
                """INSERT INTO people (name, relationship, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("Alice", "friend"),
            )
            self.log("  Person added: Alice (friend)")

            # STEP 2: Create relationship edge
            self.log("[SYSTEM] Creating relationship graph...")
            await self.sqlite_store.execute(
                """INSERT INTO graph_edges (source, target, relation, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                ("user", "Alice", "shares_expenses"),
            )
            self.log("  Relationship created: user --[shares_expenses]--> Alice")

            # STEP 3: Create result
            tool_result = ToolExecutionResult(
                tool_name="people_tool",
                success=True,
                output_text="Added friend Alice and created shared_expenses relationship",
                data={
                    "person_name": "Alice",
                    "relationship": "friend",
                    "graph_relation": "shares_expenses",
                },
            )
            self.log("[TOOL] Returned person addition result")

            # STEP 4: Verify result
            operation = Operation(
                type="insert",
                affected_table="people",
                row_count_affected=1,
                description="Add friend Alice with shared_expenses relationship",
            )
            self.log("[VERIFICATION] Verifying person and relationship...")
            report = await self.verifier.verify(tool_result, operation, "add friend")

            self.log(f"  Person verified: {report.intent_matched}")
            self.log(f"  Outcome: {report.outcome}")

            # STEP 5: Check database
            self.log("[DATABASE CHECK] Verifying data...")
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM people WHERE name = 'Alice'"
                )
                person_count = cursor.fetchone()[0]

                cursor = conn.execute(
                    "SELECT COUNT(*) FROM graph_edges WHERE source = 'user' AND target = 'Alice'"
                )
                edge_count = cursor.fetchone()[0]

            self.log(f"  People records: {person_count}")
            self.log(f"  Relationship edges: {edge_count}")

            # RESULT
            if person_count == 1 and edge_count == 1 and report.success:
                self.log("[RESULT] [OK] VERIFIED - Person and relationship created successfully")
                return True
            else:
                self.log("[RESULT] [FAIL] FAILED - Person or relationship verification failed")
                return False

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioDetectFailedOperation(HumanScenario):
    """Scenario 4: Detect Failed Operation.

    User action: Try to transfer from nonexistent account
    Verification: ResultVerifier reports operation failed
    Expected result: FAILED [OK] (correctly identified as failure)
    """

    async def run(self) -> bool:
        """Run scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Transfer $500 from my secret account to checking'")

            # STEP 1: Try operation with nonexistent account
            self.log("[SYSTEM] Attempting transfer...")
            self.log("  ERROR: Account 'secret account' not found")

            # STEP 2: Create failed result
            tool_result = ToolExecutionResult(
                tool_name="finance_tool",
                success=False,
                output_text="Error: Account 'secret account' does not exist",
                data={"error": "account_not_found"},
            )
            self.log("[TOOL] Returned failure result")

            # STEP 3: Verify the failure
            operation = Operation(
                type="transfer",
                affected_table="financial_accounts",
                row_count_affected=0,
                description="Transfer from nonexistent account",
            )
            self.log("[VERIFICATION] Analyzing failure...")
            report = await self.verifier.verify(tool_result, operation)

            self.log(f"  Operation successful: {report.success}")
            self.log(f"  Intent matched: {report.intent_matched}")
            self.log(f"  Confidence: {report.confidence:.1%}")
            if report.suggestions:
                for suggestion in report.suggestions[:2]:
                    self.log(f"  Suggestion: {suggestion}")

            # RESULT
            if not report.success and report.confidence == 0.0:
                self.log("[RESULT] [OK] DETECTED - Failure correctly identified")
                return True
            else:
                self.log("[RESULT] [FAIL] FAILED - Failure not detected")
                return False

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


class ScenarioSequentialTransactions(HumanScenario):
    """Scenario 5: Multiple Sequential Transactions.

    User action: Create 3 sequential transactions and verify each
    Verification: Each transaction independently verified
    Expected result: ALL VERIFIED [OK]
    """

    async def run(self) -> bool:
        """Run scenario."""
        await super().run()
        await self.setup()

        try:
            self.log("[USER] 'Process my transactions and verify each'")

            # STEP 1: Setup account
            self.log("[SYSTEM] Setting up account...")
            await self.sqlite_store.execute(
                """INSERT INTO financial_accounts (account_name, balance, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                ("checking", 10000.0),
            )
            self.log("  Checking account created: $10,000")

            # STEP 2: Process 3 transactions
            transactions = [
                ("Salary", 5000.0, "credit", "Monthly salary"),
                ("Groceries", 150.0, "debit", "Weekly shopping"),
                ("Utilities", 100.0, "debit", "Monthly bills"),
            ]

            all_verified = True
            for desc, amount, kind, note in transactions:
                self.log(f"\n  [TRANSACTION] {desc}: ${amount} ({kind})")

                # Record transaction
                await self.sqlite_store.execute(
                    """INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    ("checking", amount, kind, note),
                )

                # Create result
                tool_result = ToolExecutionResult(
                    tool_name="finance_tool",
                    success=True,
                    output_text=f"Transaction recorded: {desc} ${amount} ({kind})",
                    data={"description": desc, "amount": amount, "kind": kind},
                )

                # Verify
                operation = Operation(
                    type="insert",
                    affected_table="financial_transactions",
                    row_count_affected=1,
                    description=f"Record {desc} transaction",
                )
                report = await self.verifier.verify(tool_result, operation)

                verified = report.success and report.intent_matched
                status = "[OK] VERIFIED" if verified else "[FAIL] FAILED"
                self.log(f"    Verification: {status}")

                if not verified:
                    all_verified = False

            # STEP 3: Final database check
            self.log("\n  [DATABASE CHECK] Verifying all transactions...")
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM financial_transactions WHERE account_name = 'checking'"
                )
                transaction_count = cursor.fetchone()[0]

            self.log(f"    Transactions recorded: {transaction_count}")

            # RESULT
            if all_verified and transaction_count == 3:
                self.log("\n[RESULT] [OK] VERIFIED - All transactions verified successfully")
                return True
            else:
                self.log("\n[RESULT] [FAIL] FAILED - Some transactions failed verification")
                return False

        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            return False


async def run_all_scenarios():
    """Run all human testing scenarios."""
    print("\n" + "=" * 70)
    print("HUMAN TESTING SCENARIOS: ResultVerifier")
    print("=" * 70)

    scenarios = [
        ScenarioCreateAccountAndVerify("Create Account and Verify"),
        ScenarioTransferMoneyAndVerify("Transfer Money and Verify Integrity"),
        ScenarioAddPersonAndRelationship("Add Person and Complex Relationship"),
        ScenarioDetectFailedOperation("Detect Failed Operation"),
        ScenarioSequentialTransactions("Multiple Sequential Transactions"),
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
    with open("tests/result_verifier_human_results.json", "w") as f:
        json.dump(results_summary, f, indent=2)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_scenarios())
    sys.exit(0 if success else 1)
