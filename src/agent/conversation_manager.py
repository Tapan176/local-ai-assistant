"""
Conversation Manager - Multi-turn context tracking.

Phase 17: Maintains conversation state across turns:
- Tracks recent turns with intent/entities
- Provides context for LLM prompts
- Resolves pronoun references ("it" → last entity)
- Detects topic continuity
"""
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List, Any


class ConversationManager:
  """Manages multi-turn conversation context for the Orchestrator."""

  def __init__(self, max_history: int = 10):
    self.max_history = max_history
    self.turns: deque = deque(maxlen=max_history)
    self.session_start = datetime.now()
    self.current_topic: Optional[str] = None
    self.last_entities: Dict[str, str] = {}
    self.last_intent: Optional[str] = None

  def add_turn(self, user_input: str, assistant_response: str,
               intent: str = "", entities: Dict[str, Any] = None):
    """Record a conversation turn."""
    turn = {
      "ts": datetime.now().isoformat(),
      "user": user_input,
      "assistant": assistant_response,
      "intent": intent,
      "entities": entities or {}
    }
    self.turns.append(turn)

    # Track last entities and intent
    if entities:
      self.last_entities.update(entities)
    self.last_intent = intent

    # Update topic
    self._update_topic(intent)

  def get_context_for_llm(self) -> str:
    """Format recent conversation as context string for LLM."""
    if not self.turns:
      return ""

    parts = ["=== Recent Conversation ==="]
    for turn in list(self.turns)[-5:]:
      parts.append(f"User: {turn['user']}")
      # Truncate long assistant responses
      resp = turn['assistant']
      if len(resp) > 200:
        resp = resp[:200] + "..."
      parts.append(f"Assistant: {resp}")

    if self.current_topic:
      parts.append(f"\nCurrent topic: {self.current_topic}")

    return "\n".join(parts)

  def resolve_reference(self, text: str) -> str:
    """Resolve pronoun/demonstrative references using conversation context.

    Examples:
      "that was lunch" → resolves "that" to last expense
      "delete it" → resolves "it" to last mentioned item
      "more about it" → resolves "it" to last topic
    """
    if not self.turns:
      return text

    text_lower = text.lower().strip()

    # Pattern: "that was <category>" → update last expense/income
    if text_lower.startswith("that was ") and self.last_intent in ("expense", "income"):
      # Return as-is — the orchestrator handles the correction
      return text

    # Pattern: pronouns referencing last entity
    last_turn = self.turns[-1]
    entities = last_turn.get("entities", {})

    if not entities:
      return text

    # Find the most recent meaningful entity value
    last_value = None
    for key in ("text", "item", "category", "name", "query"):
      if key in entities:
        last_value = str(entities[key])
        break

    if not last_value:
      # Try last_entities accumulator
      for key in ("text", "item", "category", "name", "query"):
        if key in self.last_entities:
          last_value = str(self.last_entities[key])
          break

    if not last_value:
      return text

    # Simple replacements — only for very short references
    words = text_lower.split()
    if len(words) <= 6:
      # "it" or "that" as standalone pronoun
      for pronoun in ("it", "that", "this"):
        if pronoun in words:
          resolved = text.replace(pronoun, last_value, 1)
          resolved = resolved.replace(pronoun.capitalize(), last_value.capitalize(), 1)
          return resolved

    return text

  def should_continue_topic(self) -> bool:
    """Check if conversation is still within same topic window."""
    if not self.turns:
      return False

    last_turn = self.turns[-1]
    try:
      last_time = datetime.fromisoformat(last_turn["ts"])
      elapsed = (datetime.now() - last_time).total_seconds()
      return elapsed < 120  # 2-minute window
    except (ValueError, KeyError):
      return False

  def get_last_turn(self) -> Optional[Dict]:
    """Get the most recent turn."""
    return self.turns[-1] if self.turns else None

  def get_last_intent(self) -> Optional[str]:
    """Get the intent from the last turn."""
    return self.last_intent

  def get_turn_count(self) -> int:
    """Get number of turns in current session."""
    return len(self.turns)

  def end_session(self):
    """End current session and clear state."""
    self.turns.clear()
    self.current_topic = None
    self.last_entities.clear()
    self.last_intent = None
    self.session_start = datetime.now()

  def get_session_summary(self) -> str:
    """Get a summary of the current session."""
    if not self.turns:
      return "No conversation yet."

    duration = (datetime.now() - self.session_start).total_seconds()
    minutes = int(duration / 60)

    intents = [t.get("intent", "") for t in self.turns if t.get("intent")]
    unique_intents = list(dict.fromkeys(intents))  # preserve order

    parts = [
      f"📊 Session: {len(self.turns)} turns in {minutes}m",
      f"🎯 Topics: {', '.join(unique_intents[:5]) if unique_intents else 'general chat'}"
    ]

    if self.current_topic:
      parts.append(f"📌 Current: {self.current_topic}")

    return " | ".join(parts)

  def _update_topic(self, intent: str):
    """Update conversation topic from intent."""
    topic_map = {
      "expense": "finance",
      "income": "finance",
      "balance": "finance",
      "account": "finance",
      "budget": "finance",
      "remember": "memory",
      "recall": "memory",
      "memory": "memory",
      "experience": "activities",
      "journal": "activities",
      "habit": "habits",
      "reminder": "reminders",
      "plan": "planning",
      "agenda": "planning",
      "ask": "knowledge",
      "decide": "decision",
    }
    new_topic = topic_map.get(intent)
    if new_topic:
      self.current_topic = new_topic
