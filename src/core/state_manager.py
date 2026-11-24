"""StateManager: Real-time database state management and validation.

Provides visibility into current database state and validates operation safety.
This is the foundation layer enabling the AI to make informed decisions about data operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.models import (
    ColumnMetadata,
    DatabaseState,
    Operation,
    SafetyReport,
    StateDiff,
    TableSnapshot,
)
from src.storage.sqlite_store import SQLiteStore


class StateManager:
    """Manages real-time database state snapshots and operation safety validation."""

    def __init__(self, sqlite_store: SQLiteStore):
        """Initialize StateManager with database access.

        Args:
            sqlite_store: SQLiteStore instance for database access
        """
        self.sqlite_store = sqlite_store
        self.logger = logging.getLogger(self.__class__.__name__)

    async def probe_database_state(self) -> DatabaseState:
        """Probe current database state and create snapshot.

        Returns:
            DatabaseState: Complete snapshot of database state
        """
        try:
            # Get all table names
            tables = await asyncio.to_thread(self._get_all_tables)

            snapshots: dict[str, TableSnapshot] = {}
            table_stats: dict[str, dict[str, Any]] = {}
            integrity_issues: list[str] = []
            total_size = 0.0

            for table_name in tables:
                # Get row count
                row_count = await asyncio.to_thread(self._count_rows, table_name)

                # Get column metadata
                columns = await asyncio.to_thread(
                    self._get_column_metadata, table_name
                )

                # Get sample rows
                sample_rows = await asyncio.to_thread(
                    self._get_sample_rows, table_name
                )

                # Get last modified time
                last_modified = await asyncio.to_thread(
                    self._get_table_modified_time, table_name
                )

                # Create snapshot
                snapshot = TableSnapshot(
                    table_name=table_name,
                    row_count=row_count,
                    columns=columns,
                    sample_rows=sample_rows,
                    last_modified=last_modified,
                )

                snapshots[table_name] = snapshot

                # Store stats
                table_stats[table_name] = {
                    "row_count": row_count,
                    "column_count": len(columns),
                    "last_modified": last_modified.isoformat(),
                }

            # Estimate database size
            total_size = await asyncio.to_thread(self._estimate_db_size)

            state = DatabaseState(
                snapshots=snapshots,
                table_stats=table_stats,
                integrity_issues=integrity_issues,
                estimated_size_mb=total_size,
                last_probed_at=datetime.now(timezone.utc),
            )

            self.logger.debug(
                f"Database state probed: {len(tables)} tables, {total_size:.2f}MB"
            )
            return state

        except Exception as e:
            self.logger.error(f"Failed to probe database state: {e}")
            raise

    async def compare_states(
        self, before: DatabaseState, after: DatabaseState
    ) -> StateDiff:
        """Compare two database states and identify changes.

        Args:
            before: State snapshot before changes
            after: State snapshot after changes

        Returns:
            StateDiff: Differences between the two states
        """
        diff = StateDiff()

        # Compare table stats
        before_stats = before.table_stats
        after_stats = after.table_stats

        for table_name in after_stats:
            if table_name not in before_stats:
                diff.new_tables.append(table_name)
                diff.rows_added[table_name] = after_stats[table_name].get(
                    "row_count", 0
                )
            else:
                before_count = before_stats[table_name].get("row_count", 0)
                after_count = after_stats[table_name].get("row_count", 0)

                if after_count > before_count:
                    diff.rows_added[table_name] = after_count - before_count
                elif after_count < before_count:
                    diff.rows_deleted[table_name] = before_count - after_count
                elif after_count == before_count and after_count > 0:
                    # Table may have been updated
                    diff.rows_modified[table_name] = after_count

        # Check for removed tables
        for table_name in before_stats:
            if table_name not in after_stats:
                diff.removed_tables.append(table_name)
                diff.rows_deleted[table_name] = before_stats[table_name].get(
                    "row_count", 0
                )

        # Calculate size difference
        diff.size_diff_mb = after.estimated_size_mb - before.estimated_size_mb

        return diff

    async def create_checkpoint(
        self, name: str, created_by: str = "system", description: str = ""
    ) -> str:
        """Create a savepoint of current database state.

        Args:
            name: Unique name for checkpoint
            created_by: User or system creating checkpoint
            description: Optional description

        Returns:
            str: Checkpoint ID
        """
        try:
            # Get current state
            state = await self.probe_database_state()

            # Serialize state to JSON
            state_json = json.dumps(state.model_dump(), default=str)

            # Store in database
            checkpoint_id = await asyncio.to_thread(
                self._save_checkpoint,
                name,
                state_json,
                created_by,
                description,
            )

            self.logger.info(f"Checkpoint '{name}' created: {checkpoint_id}")
            return checkpoint_id

        except Exception as e:
            self.logger.error(f"Failed to create checkpoint: {e}")
            raise

    async def restore_checkpoint(self, checkpoint_name: str) -> Optional[DatabaseState]:
        """Retrieve a saved checkpoint state.

        Args:
            checkpoint_name: Name of checkpoint to retrieve

        Returns:
            DatabaseState: The saved state, or None if not found
        """
        try:
            checkpoint_json = await asyncio.to_thread(
                self._load_checkpoint, checkpoint_name
            )

            if not checkpoint_json:
                self.logger.warning(f"Checkpoint '{checkpoint_name}' not found")
                return None

            state_dict = json.loads(checkpoint_json)
            state = DatabaseState(**state_dict)
            return state

        except Exception as e:
            self.logger.error(f"Failed to restore checkpoint: {e}")
            raise

    async def validate_operation_safety(self, operation: Operation) -> SafetyReport:
        """Validate whether an operation is safe to execute.

        Args:
            operation: Proposed database operation

        Returns:
            SafetyReport: Safety assessment and recommendations
        """
        try:
            warnings: list[str] = []
            recommendations: list[str] = []
            risk_level = operation.risk_level
            is_safe = True

            # Get current state
            state = await self.probe_database_state()

            if operation.type == "delete":
                # DELETE operations are risky
                if operation.affected_table:
                    table_stats = state.table_stats.get(operation.affected_table, {})
                    row_count = table_stats.get("row_count", 0)

                    if operation.row_count_affected >= row_count:
                        warnings.append(
                            f"Operation would delete {operation.row_count_affected} "
                            f"rows from {operation.affected_table} "
                            f"(total: {row_count})"
                        )
                        risk_level = "high"
                        is_safe = False

                        recommendations.append("Create checkpoint before deletion")
                        recommendations.append("Verify selection criteria carefully")
                    elif operation.row_count_affected > row_count * 0.5:
                        warnings.append(
                            f"Operation would delete >50% of {operation.affected_table} "
                            f"({operation.row_count_affected}/{row_count} rows)"
                        )
                        risk_level = "high"
                        recommendations.append("Create checkpoint before deletion")

            elif operation.type == "update":
                # UPDATE operations less risky but still need caution
                if operation.row_count_affected >= 100:
                    warnings.append(
                        f"Operation would update {operation.row_count_affected} rows"
                    )
                    risk_level = "medium"
                    recommendations.append("Verify update criteria")

                recommendations.append("Create checkpoint before large updates")

            elif operation.type == "transfer":
                # Financial transfers need special care
                warnings.append("Financial operation detected - verify amounts")
                risk_level = "high"
                recommendations.append("Verify transfer amount and recipient")
                recommendations.append("Check insufficient balance protection")

            if operation.constraints_affected:
                warnings.append(
                    f"Operation affects constraints: {', '.join(operation.constraints_affected)}"
                )
                risk_level = "high"

            # Check for integrity issues
            if state.integrity_issues:
                warnings.append(
                    f"Database has {len(state.integrity_issues)} existing integrity issues"
                )
                recommendations.append("Run data inspector first")
                is_safe = False

            # Create checkpoint recommendation for any risky operation
            if risk_level in ("high", "medium"):
                recommendations.insert(0, "Create checkpoint before execution")

            report = SafetyReport(
                is_safe=is_safe,
                risk_level=risk_level,
                warnings=warnings,
                estimated_impact=self._estimate_operation_impact(
                    operation, state
                ),
                reversible=operation.type != "delete",
                recommended_precautions=recommendations,
                confidence_score=0.95 if is_safe else 0.6,
            )

            return report

        except Exception as e:
            self.logger.error(f"Failed to validate operation safety: {e}")
            raise

    async def get_constraint_violations(self) -> list[str]:
        """Get list of constraint violations in current database.

        Returns:
            list[str]: List of constraint violation descriptions
        """
        try:
            violations: list[str] = []
            state = await self.probe_database_state()

            for issue in state.integrity_issues:
                violations.append(issue)

            return violations

        except Exception as e:
            self.logger.error(f"Failed to get constraint violations: {e}")
            return []

    # === Private methods ===

    def _get_all_tables(self) -> list[str]:
        """Get list of all tables in database."""
        with self.sqlite_store._connect() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            return [row[0] for row in cursor.fetchall()]

    def _count_rows(self, table_name: str) -> int:
        """Count rows in a table."""
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception:
            return 0

    def _get_column_metadata(self, table_name: str) -> list[ColumnMetadata]:
        """Get metadata about columns in a table."""
        columns: list[ColumnMetadata] = []
        try:
            with self.sqlite_store._connect() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                for cid, name, ctype, not_null, dflt_value, pk in cursor.fetchall():
                    columns.append(
                        ColumnMetadata(
                            column_name=name,
                            data_type=ctype,
                            is_nullable=not not_null,
                            is_unique=pk > 0,
                            sample_values=[],
                        )
                    )
        except Exception:
            pass

        return columns

    def _get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get sample rows from a table."""
        rows: list[dict[str, Any]] = []
        try:
            with self.sqlite_store._connect() as conn:
                conn.row_factory = __import__("sqlite3").Row
                cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
                rows = [dict(row) for row in cursor.fetchall()]
        except Exception:
            pass

        return rows

    def _get_table_modified_time(self, table_name: str) -> datetime:
        """Get last modified time for a table."""
        try:
            with self.sqlite_store._connect() as conn:
                # Try to get from WAL metadata
                cursor = conn.execute(
                    "SELECT MAX(datetime(CURRENT_TIMESTAMP, '-1 second')) FROM sqlite_master"
                )
                result = cursor.fetchone()
                if result and result[0]:
                    return datetime.fromisoformat(result[0])
        except Exception:
            pass

        return datetime.now(timezone.utc)

    def _estimate_db_size(self) -> float:
        """Estimate database file size in MB."""
        try:
            db_path = Path(self.sqlite_store.db_path)
            if db_path.exists():
                return db_path.stat().st_size / (1024 * 1024)
        except Exception:
            pass

        return 0.0

    def _save_checkpoint(
        self, name: str, state_json: str, created_by: str, description: str
    ) -> str:
        """Save checkpoint to database."""
        with self.sqlite_store._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO state_checkpoints (name, state_json, created_at, created_by, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    name,
                    state_json,
                    datetime.now(timezone.utc).isoformat(),
                    created_by,
                    description,
                ),
            )
            conn.commit()
            return f"checkpoint_{cursor.lastrowid}"

    def _load_checkpoint(self, checkpoint_name: str) -> Optional[str]:
        """Load checkpoint from database."""
        with self.sqlite_store._connect() as conn:
            cursor = conn.execute(
                "SELECT state_json FROM state_checkpoints WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (checkpoint_name,),
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def _estimate_operation_impact(
        self, operation: Operation, state: DatabaseState
    ) -> str:
        """Estimate impact of an operation."""
        if operation.affected_table:
            table_stats = state.table_stats.get(operation.affected_table, {})
            row_count = table_stats.get("row_count", 0)

            if operation.row_count_affected == 0:
                return "No rows affected"
            elif operation.row_count_affected == 1:
                return "Affects 1 row"
            elif operation.row_count_affected < row_count:
                pct = (operation.row_count_affected / row_count) * 100
                return f"Affects {operation.row_count_affected}/{row_count} rows ({pct:.1f}%)"
            else:
                return f"Affects all {operation.row_count_affected} rows in table"

        return f"Affects {operation.row_count_affected} rows"
