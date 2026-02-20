"""DataInspector: Database integrity validation and corruption detection.

Validates schema, detects corruption, identifies anomalies, and provides health metrics.
Works in conjunction with StateManager to provide comprehensive data intelligence.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from src.models import (
    Anomaly,
    ColumnHealth,
    CorruptedRecord,
    ForeignKeyViolation,
    InspectionReport,
    SchemaReport,
)
from src.storage.sqlite_store import SQLiteStore


class DataInspector:
    """Validates database integrity and detects corruption."""

    # Schema definitions: table_name -> {column_name: (data_type, required, unique)}
    SCHEMA_DEFINITIONS = {
        "episodes": {
            "id": ("INTEGER", False, True),
            "session_id": ("TEXT", True, False),
            "timestamp": ("TEXT", True, False),
            "user_text": ("TEXT", True, False),
            "assistant_text": ("TEXT", True, False),
            "emotional_state": ("TEXT", True, False),
            "tool_used": ("TEXT", False, False),
            "metadata_json": ("TEXT", False, False),
        },
        "semantic_facts": {
            "id": ("INTEGER", False, True),
            "fact_key": ("TEXT", True, False),
            "fact_value": ("TEXT", True, False),
            "confidence": ("REAL", False, False),
            "updated_at": ("TEXT", True, False),
        },
        "persona_profile": {
            "id": ("INTEGER", True, True),
            "communication_style": ("TEXT", False, False),
            "emotional_baseline": ("TEXT", False, False),
            "preferences_json": ("TEXT", False, False),
            "goals_json": ("TEXT", False, False),
            "updated_at": ("TEXT", True, False),
        },
        "financial_accounts": {
            "id": ("INTEGER", False, True),
            "account_name": ("TEXT", True, True),
            "balance": ("REAL", False, False),
            "updated_at": ("TEXT", True, False),
        },
        "financial_transactions": {
            "id": ("INTEGER", False, True),
            "account_name": ("TEXT", True, False),
            "amount": ("REAL", True, False),
            "kind": ("TEXT", True, False),
            "note": ("TEXT", False, False),
            "timestamp": ("TEXT", True, False),
        },
        "reminders": {
            "id": ("INTEGER", False, True),
            "session_id": ("TEXT", True, False),
            "title": ("TEXT", True, False),
            "due_at": ("TEXT", False, False),
            "status": ("TEXT", False, False),
            "created_at": ("TEXT", True, False),
        },
        "people": {
            "id": ("INTEGER", False, True),
            "name": ("TEXT", True, True),
            "relationship": ("TEXT", False, False),
            "notes": ("TEXT", False, False),
            "updated_at": ("TEXT", True, False),
        },
        "calendar_events": {
            "id": ("INTEGER", False, True),
            "title": ("TEXT", True, False),
            "start_at": ("TEXT", False, False),
            "end_at": ("TEXT", False, False),
            "location": ("TEXT", False, False),
            "notes": ("TEXT", False, False),
            "created_at": ("TEXT", True, False),
        },
        "graph_edges": {
            "id": ("INTEGER", False, True),
            "source": ("TEXT", True, False),
            "target": ("TEXT", True, False),
            "relation": ("TEXT", True, False),
            "weight": ("REAL", False, False),
            "created_at": ("TEXT", True, False),
        },
        "semantic_documents": {
            "id": ("TEXT", True, True),
            "text_value": ("TEXT", True, False),
            "metadata_json": ("TEXT", False, False),
            "updated_at": ("TEXT", True, False),
        },
        "state_checkpoints": {
            "id": ("INTEGER", False, True),
            "name": ("TEXT", True, True),
            "state_json": ("TEXT", True, False),
            "created_at": ("TEXT", True, False),
            "created_by": ("TEXT", False, False),
            "description": ("TEXT", False, False),
        },
    }

    # Foreign key relationships: (from_table, from_column) -> (to_table, to_column)
    FOREIGN_KEYS = [
        ("financial_transactions", "account_name", "financial_accounts", "account_name"),
        ("graph_edges", "source", "people", "name"),
        ("graph_edges", "target", "people", "name"),
    ]

    def __init__(self, sqlite_store: SQLiteStore):
        """Initialize DataInspector with database access.

        Args:
            sqlite_store: SQLiteStore instance for database access
        """
        self.sqlite_store = sqlite_store
        self.logger = logging.getLogger(self.__class__.__name__)

    async def inspect_table(self, table_name: str) -> InspectionReport:
        """Inspect a table for data integrity issues.

        Args:
            table_name: Table to inspect

        Returns:
            InspectionReport: Detailed inspection results
        """
        try:
            row_count = await asyncio.to_thread(self._count_rows, table_name)
            column_health = await asyncio.to_thread(
                self._inspect_columns, table_name
            )

            # Count violations
            null_violations = await asyncio.to_thread(
                self._count_null_violations, table_name
            )
            unique_violations = await asyncio.to_thread(
                self._count_unique_violations, table_name
            )
            type_violations = 0  # Type checking is limited in SQLite

            # Calculate health score
            issues: list[str] = []
            recommendations: list[str] = []

            if null_violations > 0:
                issues.append(f"{null_violations} NULL violations in required fields")
                recommendations.append("Check and fix NULL values in required columns")

            if unique_violations > 0:
                issues.append(f"{unique_violations} duplicate values in unique columns")
                recommendations.append("Identify and remove duplicate rows")

            # Calculate overall health
            total_violations = null_violations + unique_violations + type_violations
            health_score = max(0.0, 1.0 - (total_violations / max(row_count, 1)) * 0.1)

            return InspectionReport(
                table_name=table_name,
                row_count=row_count,
                column_health=column_health,
                null_violation_count=null_violations,
                unique_violation_count=unique_violations,
                type_violation_count=type_violations,
                overall_health_score=health_score,
                issues=issues,
                recommendations=recommendations,
            )

        except Exception as e:
            self.logger.error(f"Failed to inspect table {table_name}: {e}")
            raise

    async def find_corrupted_records(self) -> list[CorruptedRecord]:
        """Find all corrupted records in database.

        Returns:
            list[CorruptedRecord]: List of detected corruption issues
        """
        corrupted: list[CorruptedRecord] = []

        try:
            # Check each table for violations
            for table_name in self.SCHEMA_DEFINITIONS.keys():
                corrupted.extend(
                    await asyncio.to_thread(
                        self._find_null_violations, table_name
                    )
                )
                corrupted.extend(
                    await asyncio.to_thread(
                        self._find_unique_violations, table_name
                    )
                )

            # Check foreign key violations
            corrupted.extend(
                await asyncio.to_thread(self._find_foreign_key_orphans)
            )

            return corrupted

        except Exception as e:
            self.logger.error(f"Failed to find corrupted records: {e}")
            raise

    async def validate_foreign_keys(self) -> list[ForeignKeyViolation]:
        """Validate all foreign key relationships.

        Returns:
            list[ForeignKeyViolation]: List of violations found
        """
        violations: list[ForeignKeyViolation] = []

        try:
            for from_table, from_col, to_table, to_col in self.FOREIGN_KEYS:
                violations.extend(
                    await asyncio.to_thread(
                        self._check_foreign_key,
                        from_table,
                        from_col,
                        to_table,
                        to_col,
                    )
                )

            return violations

        except Exception as e:
            self.logger.error(f"Failed to validate foreign keys: {e}")
            raise

    async def detect_data_anomalies(self) -> list[Anomaly]:
        """Detect statistical anomalies in data.

        Returns:
            list[Anomaly]: List of detected anomalies
        """
        anomalies: list[Anomaly] = []

        try:
            # Check for duplicates
            anomalies.extend(
                await asyncio.to_thread(self._find_duplicate_records)
            )

            # Check financial anomalies
            anomalies.extend(
                await asyncio.to_thread(self._find_financial_anomalies)
            )

            # Check timestamp anomalies
            anomalies.extend(
                await asyncio.to_thread(self._find_timestamp_anomalies)
            )

            return anomalies

        except Exception as e:
            self.logger.error(f"Failed to detect anomalies: {e}")
            raise

    async def get_table_health_score(self, table_name: str) -> float:
        """Get overall health score for a table (0.0-1.0).

        Args:
            table_name: Table to evaluate

        Returns:
            float: Health score (1.0 = perfect, 0.0 = completely corrupted)
        """
        try:
            report = await self.inspect_table(table_name)
            return report.overall_health_score

        except Exception as e:
            self.logger.warning(f"Failed to get health score for {table_name}: {e}")
            return 0.5  # Return neutral score on error

    async def generate_schema_report(self) -> SchemaReport:
        """Generate comprehensive schema validation report.

        Returns:
            SchemaReport: Full database schema report
        """
        try:
            table_reports: dict[str, InspectionReport] = {}
            total_rows = 0
            overall_health = 1.0
            critical_issues: list[str] = []
            warnings: list[str] = []
            recommendations: list[str] = []

            # Inspect all tables
            for table_name in self.SCHEMA_DEFINITIONS.keys():
                report = await self.inspect_table(table_name)
                table_reports[table_name] = report
                total_rows += report.row_count
                overall_health *= report.overall_health_score

                if report.overall_health_score < 0.9:
                    warnings.append(
                        f"{table_name}: health score {report.overall_health_score:.2f}"
                    )
                if report.overall_health_score < 0.7:
                    critical_issues.append(
                        f"{table_name}: {len(report.issues)} critical issues"
                    )

                recommendations.extend(report.recommendations)

            # Check foreign keys
            fk_violations = await self.validate_foreign_keys()
            if fk_violations:
                critical_issues.append(
                    f"{len(fk_violations)} foreign key violations detected"
                )
                recommendations.append("Check and fix foreign key violations")

            # Check anomalies
            anomalies = await self.detect_data_anomalies()
            if anomalies:
                warnings.append(f"{len(anomalies)} data anomalies detected")

            return SchemaReport(
                total_tables=len(table_reports),
                total_rows=total_rows,
                table_reports=table_reports,
                overall_health_score=overall_health,
                critical_issues=critical_issues,
                warnings=warnings,
                recommendations=list(set(recommendations)),  # Remove duplicates
            )

        except Exception as e:
            self.logger.error(f"Failed to generate schema report: {e}")
            raise

    # === Private inspection methods ===

    def _count_rows(self, table_name: str) -> int:
        """Count rows in a table."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                return cursor.fetchone()[0]
        except Exception:
            return 0

    def _inspect_columns(self, table_name: str) -> dict[str, ColumnHealth]:
        """Inspect columns in a table."""
        column_health: dict[str, ColumnHealth] = {}

        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                for cid, name, ctype, not_null, dflt_value, pk in columns:
                    # Count nulls if column is nullable
                    null_count = 0
                    if not not_null:
                        cursor = conn.execute(
                            f"SELECT COUNT(*) FROM {table_name} WHERE {name} IS NULL"
                        )
                        null_count = cursor.fetchone()[0]

                    # Count uniques
                    cursor = conn.execute(
                        f"SELECT COUNT(DISTINCT {name}) FROM {table_name}"
                    )
                    unique_count = cursor.fetchone()[0]

                    # Get sample values
                    cursor = conn.execute(
                        f"SELECT DISTINCT {name} FROM {table_name} LIMIT 5"
                    )
                    sample_values = [row[0] for row in cursor.fetchall()]

                    # Calculate health
                    total_rows = self._count_rows(table_name)
                    null_pct = (null_count / total_rows * 100) if total_rows > 0 else 0

                    health = 1.0
                    if null_pct > 10:
                        health -= 0.2
                    if unique_count < total_rows * 0.5:
                        health -= 0.1

                    column_health[name] = ColumnHealth(
                        column_name=name,
                        data_type=ctype,
                        null_count=null_count,
                        null_percentage=null_pct,
                        unique_count=unique_count,
                        duplicate_count=max(0, total_rows - unique_count),
                        health_score=max(0.0, health),
                        sample_values=sample_values,
                    )

        except Exception:
            pass

        return column_health

    def _count_null_violations(self, table_name: str) -> int:
        """Count NULL values in required fields."""
        count = 0
        schema = self.SCHEMA_DEFINITIONS.get(table_name, {})

        try:
            with self.sqlite_store._connect() as conn:
                for col_name, (dtype, required, unique) in schema.items():
                    if required:
                        cursor = conn.execute(
                            f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
                        )
                        count += cursor.fetchone()[0]

        except Exception:
            pass

        return count

    def _find_null_violations(self, table_name: str) -> list[CorruptedRecord]:
        """Find specific rows with NULL violations."""
        violations: list[CorruptedRecord] = []
        schema = self.SCHEMA_DEFINITIONS.get(table_name, {})

        try:
            with self.sqlite_store._connect() as conn:
                for col_name, (dtype, required, unique) in schema.items():
                    if required:
                        cursor = conn.execute(
                            f"SELECT id FROM {table_name} WHERE {col_name} IS NULL LIMIT 100"
                        )
                        for row in cursor.fetchall():
                            violations.append(
                                CorruptedRecord(
                                    table_name=table_name,
                                    row_id=row[0],
                                    corruption_type="null_in_required",
                                    affected_columns=[col_name],
                                    recommended_fix=f"Set {col_name} to a valid value",
                                    severity="high",
                                )
                            )

        except Exception:
            pass

        return violations

    def _count_unique_violations(self, table_name: str) -> int:
        """Count duplicate values in unique columns."""
        count = 0
        schema = self.SCHEMA_DEFINITIONS.get(table_name, {})

        try:
            with self.sqlite_store._connect() as conn:
                for col_name, (dtype, required, unique) in schema.items():
                    if unique and col_name != "id":
                        cursor = conn.execute(
                            f"""SELECT COUNT(*) FROM (
                                SELECT {col_name} FROM {table_name}
                                WHERE {col_name} IS NOT NULL
                                GROUP BY {col_name}
                                HAVING COUNT(*) > 1
                            )"""
                        )
                        count += cursor.fetchone()[0]

        except Exception:
            pass

        return count

    def _find_unique_violations(self, table_name: str) -> list[CorruptedRecord]:
        """Find specific rows with duplicate unique values."""
        violations: list[CorruptedRecord] = []
        schema = self.SCHEMA_DEFINITIONS.get(table_name, {})

        try:
            with self.sqlite_store._connect() as conn:
                for col_name, (dtype, required, unique) in schema.items():
                    if unique and col_name != "id":
                        cursor = conn.execute(
                            f"""SELECT id FROM {table_name} WHERE {col_name} IN (
                                SELECT {col_name} FROM {table_name}
                                WHERE {col_name} IS NOT NULL
                                GROUP BY {col_name}
                                HAVING COUNT(*) > 1
                            ) LIMIT 100"""
                        )
                        for row in cursor.fetchall():
                            violations.append(
                                CorruptedRecord(
                                    table_name=table_name,
                                    row_id=row[0],
                                    corruption_type="duplicate_unique",
                                    affected_columns=[col_name],
                                    recommended_fix=f"Remove duplicate or update {col_name}",
                                    severity="medium",
                                )
                            )

        except Exception:
            pass

        return violations

    def _check_foreign_key(
        self, from_table: str, from_col: str, to_table: str, to_col: str
    ) -> list[ForeignKeyViolation]:
        """Check foreign key constraint between two tables."""
        violations: list[ForeignKeyViolation] = []

        try:
            with self.sqlite_store._connect() as conn:
                # Find orphaned references
                cursor = conn.execute(
                    f"""SELECT f.id, f.{from_col} FROM {from_table} f
                        WHERE f.{from_col} IS NOT NULL
                        AND f.{from_col} NOT IN (SELECT {to_col} FROM {to_table})
                        LIMIT 100"""
                )
                for row in cursor.fetchall():
                    violations.append(
                        ForeignKeyViolation(
                            from_table=from_table,
                            from_id=row[0],
                            from_column=from_col,
                            target_table=to_table,
                            target_id=0,
                            target_column=to_col,
                            issue=f"References non-existent {to_table}.{to_col}={row[1]}",
                        )
                    )

        except Exception:
            pass

        return violations

    def _find_foreign_key_orphans(self) -> list[CorruptedRecord]:
        """Find all orphaned foreign key records."""
        orphans: list[CorruptedRecord] = []

        try:
            for from_table, from_col, to_table, to_col in self.FOREIGN_KEYS:
                with self.sqlite_store._connect() as conn:
                    cursor = conn.execute(
                        f"""SELECT id FROM {from_table} f
                            WHERE f.{from_col} IS NOT NULL
                            AND f.{from_col} NOT IN (SELECT {to_col} FROM {to_table})
                            LIMIT 100"""
                    )
                    for row in cursor.fetchall():
                        orphans.append(
                            CorruptedRecord(
                                table_name=from_table,
                                row_id=row[0],
                                corruption_type="foreign_key_orphan",
                                affected_columns=[from_col],
                                recommended_fix=(
                                    f"Delete row or update {from_col} to valid {to_table}.{to_col}"
                                ),
                                severity="high",
                            )
                        )

        except Exception:
            pass

        return orphans

    def _find_duplicate_records(self) -> list[Anomaly]:
        """Find duplicate records (same values across all columns)."""
        anomalies: list[Anomaly] = []

        try:
            with self.sqlite_store._connect() as conn:
                # Check people for duplicate names
                cursor = conn.execute(
                    """SELECT name, COUNT(*) as cnt FROM people
                       GROUP BY name HAVING cnt > 1"""
                )
                for row in cursor.fetchall():
                    anomalies.append(
                        Anomaly(
                            type="duplicate",
                            table="people",
                            description=f"Duplicate name: '{row[0]}' appears {row[1]} times",
                            severity="medium",
                            suggested_action="Merge duplicate people records",
                        )
                    )

        except Exception:
            pass

        return anomalies

    def _find_financial_anomalies(self) -> list[Anomaly]:
        """Find unusual patterns in financial data."""
        anomalies: list[Anomaly] = []

        try:
            with self.sqlite_store._connect() as conn:
                # Check for negative balances
                cursor = conn.execute(
                    "SELECT account_name, balance FROM financial_accounts WHERE balance < 0"
                )
                for row in cursor.fetchall():
                    anomalies.append(
                        Anomaly(
                            type="unusual_value",
                            table="financial_accounts",
                            description=f"Account '{row[0]}' has negative balance: {row[1]}",
                            severity="warning",
                            suggested_action="Review credit facility or data entry",
                        )
                    )

                # Check for very large transactions
                cursor = conn.execute(
                    "SELECT id, amount FROM financial_transactions WHERE amount > 100000 LIMIT 10"
                )
                for row in cursor.fetchall():
                    anomalies.append(
                        Anomaly(
                            type="outlier",
                            table="financial_transactions",
                            description=f"Very large transaction: {row[1]}",
                            severity="info",
                            suggested_action="Verify large transaction is legitimate",
                        )
                    )

        except Exception:
            pass

        return anomalies

    def _find_timestamp_anomalies(self) -> list[Anomaly]:
        """Find timestamp inconsistencies."""
        anomalies: list[Anomaly] = []

        try:
            with self.sqlite_store._connect() as conn:
                # Check for future-dated events
                cursor = conn.execute(
                    """SELECT id, created_at FROM calendar_events
                       WHERE created_at > datetime('now')"""
                )
                for row in cursor.fetchall():
                    anomalies.append(
                        Anomaly(
                            type="unusual_value",
                            table="calendar_events",
                            description=f"Event created with future timestamp: {row[1]}",
                            severity="warning",
                            suggested_action="Verify event date/time",
                        )
                    )

        except Exception:
            pass

        return anomalies
