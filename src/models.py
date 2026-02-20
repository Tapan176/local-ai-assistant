"""Shared Pydantic models for TAPAN_AI v2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class PerceptionOutput(BaseModel):
    tone: str
    emotional_state: str
    emotional_intensity: float = Field(ge=0.0, le=1.0)
    ambiguity_score: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    detected_language: str = "en"


class MemoryContext(BaseModel):
    episodic_memories: list[dict[str, Any]] = Field(default_factory=list)
    semantic_memories: list[dict[str, Any]] = Field(default_factory=list)
    persona_profile: dict[str, Any] = Field(default_factory=dict)
    relationship_graph: list[dict[str, Any]] = Field(default_factory=list)


class ReasoningOutput(BaseModel):
    inferred_intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_question: str | None = None
    possible_actions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    uncertainty: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""


class PlanDecision(BaseModel):
    action_type: Literal["respond", "clarify", "tool"]
    tool_name: str | None = None
    response_temperature: float = Field(ge=0.0, le=1.0, default=0.5)
    clarification_question: str | None = None
    should_store_memory: bool = True
    should_schedule_followup: bool = False


class ToolExecutionResult(BaseModel):
    tool_name: str
    success: bool
    output_text: str
    data: dict[str, Any] = Field(default_factory=dict)
    should_store_semantic: bool = False


class ReflectionReport(BaseModel):
    coherence_score: float = Field(ge=0.0, le=1.0)
    missed_context: bool = False
    contradiction_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    should_store_semantic: bool = False
    persona_updates: dict[str, Any] = Field(default_factory=dict)
    emotional_shift: str | None = None


class ConversationTurn(BaseModel):
    session_id: str
    user_text: str
    assistant_text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    emotional_state: str = "neutral"
    tool_used: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestratorResponse(BaseModel):
    session_id: str
    text: str
    action_type: str
    tool_used: str | None = None
    emotional_state: str = "neutral"
    reflection_score: float = 0.0
    memory_references: list[str] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str
    action_type: str
    tool_used: str | None = None
    emotional_state: str


# ===== StateManager & DataInspector Models =====


class ColumnMetadata(BaseModel):
    """Metadata about a database column."""
    column_name: str
    data_type: str
    is_nullable: bool
    is_unique: bool
    sample_values: list[Any] = Field(default_factory=list)


class TableSnapshot(BaseModel):
    """Snapshot of a database table at a point in time."""
    table_name: str
    row_count: int
    columns: list[ColumnMetadata] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    integrity_checks: list[str] = Field(default_factory=list)
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatabaseState(BaseModel):
    """Complete snapshot of database state."""
    snapshots: dict[str, TableSnapshot] = Field(default_factory=dict)
    table_stats: dict[str, dict[str, Any]] = Field(default_factory=dict)
    integrity_issues: list[str] = Field(default_factory=list)
    estimated_size_mb: float = 0.0
    last_probed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FileMetadata(BaseModel):
    """Metadata about a file."""
    file_path: str
    size_bytes: int
    modified_at: datetime
    is_readable: bool = True


class FileSystemState(BaseModel):
    """Snapshot of filesystem state."""
    files: dict[str, FileMetadata] = Field(default_factory=dict)
    total_size_mb: float = 0.0
    modified_count: int = 0
    integrity_errors: list[str] = Field(default_factory=list)


class Operation(BaseModel):
    """Proposed database operation for safety validation."""
    type: Literal["insert", "update", "delete", "file_operation", "transfer"]
    affected_table: str | None = None
    row_count_affected: int = 0
    risk_level: Literal["low", "medium", "high"] = "medium"
    constraints_affected: list[str] = Field(default_factory=list)
    description: str = ""


class SafetyReport(BaseModel):
    """Report on whether an operation is safe to execute."""
    is_safe: bool
    risk_level: Literal["low", "medium", "high"]
    warnings: list[str] = Field(default_factory=list)
    estimated_impact: str = ""
    reversible: bool = True
    recommended_precautions: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.9)


class StateDiff(BaseModel):
    """Difference between two database states."""
    rows_added: dict[str, int] = Field(default_factory=dict)
    rows_deleted: dict[str, int] = Field(default_factory=dict)
    rows_modified: dict[str, int] = Field(default_factory=dict)
    new_tables: list[str] = Field(default_factory=list)
    removed_tables: list[str] = Field(default_factory=list)
    size_diff_mb: float = 0.0


class ColumnHealth(BaseModel):
    """Health metrics for a database column."""
    column_name: str
    data_type: str
    null_count: int = 0
    null_percentage: float = 0.0
    unique_count: int = 0
    duplicate_count: int = 0
    health_score: float = Field(ge=0.0, le=1.0, default=1.0)
    sample_values: list[Any] = Field(default_factory=list)


class InspectionReport(BaseModel):
    """Detailed inspection report for a table."""
    table_name: str
    row_count: int
    column_health: dict[str, ColumnHealth] = Field(default_factory=dict)
    null_violation_count: int = 0
    unique_violation_count: int = 0
    type_violation_count: int = 0
    overall_health_score: float = Field(ge=0.0, le=1.0, default=1.0)
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class CorruptedRecord(BaseModel):
    """Record with integrity issues."""
    table_name: str
    row_id: int
    corruption_type: str  # "null_in_required", "type_mismatch", "foreign_key_orphan", etc.
    affected_columns: list[str] = Field(default_factory=list)
    recommended_fix: str = ""
    severity: Literal["low", "medium", "high"] = "medium"


class ForeignKeyViolation(BaseModel):
    """Foreign key constraint violation."""
    from_table: str
    from_id: int
    from_column: str
    target_table: str
    target_id: int
    target_column: str
    issue: str


class Anomaly(BaseModel):
    """Data anomaly detected."""
    type: str  # "unusual_value", "outlier", "duplicate", "inconsistency"
    table: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"
    affected_rows: list[int] = Field(default_factory=list)
    suggested_action: str = ""


class SchemaReport(BaseModel):
    """Complete schema validation report."""
    total_tables: int
    total_rows: int
    table_reports: dict[str, InspectionReport] = Field(default_factory=dict)
    overall_health_score: float = Field(ge=0.0, le=1.0, default=1.0)
    critical_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ToolExecutionWithState(BaseModel):
    """Tool execution result with state tracking."""
    tool_result: ToolExecutionResult
    state_before: DatabaseState | None = None
    state_after: DatabaseState | None = None
    state_diff: StateDiff | None = None
    safety_report: SafetyReport | None = None
    validation_passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0


class StateCheckpoint(BaseModel):
    """Saved database state checkpoint."""
    checkpoint_name: str
    state: DatabaseState
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "system"
    description: str = ""


# ===== ResultVerifier Models =====


class ResultVerification(BaseModel):
    """Result of verifying a tool execution outcome."""
    verified: bool
    outcome: dict[str, Any] = Field(default_factory=dict)
    matches_intent: bool
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)
    details: str = ""


class VerificationReport(BaseModel):
    """Complete report on result verification."""
    success: bool
    outcome_extracted: bool
    outcome: dict[str, Any] = Field(default_factory=dict)
    intent_matched: bool
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)
    suggestions: list[str] = Field(default_factory=list)
    tool_name: str = ""
    verification_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def model_dump_compat(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
