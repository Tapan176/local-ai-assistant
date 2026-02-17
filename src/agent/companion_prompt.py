"""Utilities for building companion-style LLM context.

This module centralizes persona, sentiment, and memory context composition so
Orchestrator can consistently prepare prompts that feel conversational and
personalized instead of command-only.
"""
from typing import Dict, List, Optional

PERSONA_BLOCK = (
  "You are a personal AI companion with memory of past conversations. "
  "Be friendly, conversational, and emotionally aware. "
  "Use context from memories naturally, avoid sounding robotic, "
  "and keep responses helpful and safe."
)


def _sentiment_guidance(label: str) -> str:
  """Return tone guidance based on inferred user sentiment label."""
  normalized = (label or "neutral").lower()
  if normalized in {"sad", "angry", "stressed", "depressed"}:
    return (
      "User seems emotionally low or stressed. Respond with empathy first, "
      "then provide practical help."
    )
  if normalized in {"happy", "excited"}:
    return "User sounds positive. Match their energy while staying clear and useful."
  return "Use a calm, warm, and concise companion tone."


def build_companion_context(
  base_context: str,
  *,
  sentiment_label: str = "neutral",
  recent_history: str = "",
  memories: Optional[List[Dict[str, str]]] = None,
) -> str:
  """Build a single context string for LLM generation.

  Args:
    base_context: Existing system context from ContextBuilder.
    sentiment_label: User sentiment label for tone adaptation.
    recent_history: Recent dialogue turns from conversation manager.
    memories: Retrieved memory rows containing ``text`` keys.
  """
  parts = [f"PERSONA:\n{PERSONA_BLOCK}"]
  parts.append(f"\nTONE_GUIDANCE:\n{_sentiment_guidance(sentiment_label)}")

  if recent_history:
    parts.append(f"\nRECENT_CHAT:\n{recent_history}")

  if memories:
    memory_lines = [m.get("text", "") for m in memories if m.get("text")]
    if memory_lines:
      parts.append("\nRELEVANT_LONG_TERM_MEMORY:")
      parts.extend(f"- {line}" for line in memory_lines[:5])

  if base_context:
    parts.append(f"\nSYSTEM_CONTEXT:\n{base_context}")

  return "\n".join(parts)
