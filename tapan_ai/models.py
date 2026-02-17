"""Shared Pydantic models for TAPAN_AI v2."""

from __future__ import annotations

from datetime import datetime
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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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


def model_dump_compat(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
