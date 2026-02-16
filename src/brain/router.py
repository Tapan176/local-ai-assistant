"""
Model Router - Routes tasks to appropriate model backends
Decides which model to use based on task complexity
"""
from typing import Dict, Optional, Callable
from enum import Enum
from dataclasses import dataclass


class TaskType(Enum):
  """Types of tasks the router can handle"""
  REASONING = "reasoning"      # Complex reasoning, analysis
  CHAT = "chat"                # General conversation
  SUMMARIZE = "summarize"      # Text summarization
  CLASSIFY = "classify"        # Intent/topic classification
  EXTRACT = "extract"          # Information extraction
  GENERATE = "generate"        # Text generation


class ModelTier(Enum):
  """Model tiers based on capability/size"""
  HEAVY = "heavy"      # Large models (BitNet, Llama 70B) - best quality
  MEDIUM = "medium"    # Medium models (Llama 7B, Mistral) - balanced
  SMALL = "small"      # Small models (Phi, TinyLlama) - fast
  TINY = "tiny"        # Minimal models (rule-based, embeddings) - instant
  INTENT = "intent"    # Intent classification (keyword/rule-based)


@dataclass
class RouteDecision:
  """Result of routing decision"""
  model_tier: ModelTier
  backend_name: str
  reason: str
  fallback_tier: Optional[ModelTier] = None


class ModelRouter:
  """Routes tasks to appropriate model backends

  Routing strategy:
  - reasoning → heavy model (complex thinking)
  - chat → small model (fast responses)
  - summarize → tiny model (simple extraction)
  - classify → intent model (rule-based)
  """

  # Task to model tier mapping
  TASK_ROUTING = {
    TaskType.REASONING: ModelTier.HEAVY,
    TaskType.CHAT: ModelTier.SMALL,
    TaskType.SUMMARIZE: ModelTier.TINY,
    TaskType.CLASSIFY: ModelTier.INTENT,
    TaskType.EXTRACT: ModelTier.SMALL,
    TaskType.GENERATE: ModelTier.MEDIUM,
  }

  # Model tier to backend mapping
  TIER_BACKENDS = {
    ModelTier.HEAVY: "bitnet",
    ModelTier.MEDIUM: "small",  # Could be llama-7b
    ModelTier.SMALL: "small",
    ModelTier.TINY: "tiny",
    ModelTier.INTENT: "intent",
  }

  # Fallback chain
  FALLBACKS = {
    ModelTier.HEAVY: ModelTier.MEDIUM,
    ModelTier.MEDIUM: ModelTier.SMALL,
    ModelTier.SMALL: ModelTier.TINY,
    ModelTier.TINY: None,
    ModelTier.INTENT: ModelTier.TINY,
  }

  def __init__(self):
    self.available_backends = set()
    self.backend_status = {}
    self._active_model = None
    self._user_preference = None

  def register_backend(self, name: str, tier: ModelTier, check_fn: Optional[Callable[[], bool]] = None):
    """Register an available backend

    Args:
      name: Backend identifier
      tier: Model tier this backend belongs to
      check_fn: Optional function to check if backend is ready
    """
    is_ready = check_fn() if check_fn else True
    self.backend_status[name] = {
      'tier': tier,
      'ready': is_ready,
      'check_fn': check_fn
    }
    if is_ready:
      self.available_backends.add(name)

  def set_user_preference(self, model_name: Optional[str]):
    """Set user's preferred model

    Args:
      model_name: Name of preferred model, or None to reset
    """
    self._user_preference = model_name

  def get_active_model(self) -> Optional[str]:
    """Get currently active/preferred model"""
    return self._user_preference or self._active_model

  def route(self, task: TaskType, context: Optional[Dict] = None) -> RouteDecision:
    """Decide which model to use for a task

    Args:
      task: Type of task to perform
      context: Optional context (length, complexity hints)

    Returns:
      RouteDecision with model selection
    """
    context = context or {}

    # Check user preference first
    if self._user_preference and self._user_preference in self.available_backends:
      status = self.backend_status.get(self._user_preference, {})
      return RouteDecision(
        model_tier=status.get('tier', ModelTier.SMALL),
        backend_name=self._user_preference,
        reason="User preference"
      )

    # Get default tier for task
    target_tier = self.TASK_ROUTING.get(task, ModelTier.SMALL)

    # Adjust based on context
    if context.get('text_length', 0) > 5000:
      # Long text - might need bigger model for reasoning
      if task == TaskType.SUMMARIZE:
        target_tier = ModelTier.SMALL

    if context.get('simple', False):
      # Simple task - downgrade
      target_tier = self._downgrade_tier(target_tier)

    # Find available backend for tier
    backend_name = self._find_backend_for_tier(target_tier)
    fallback = self.FALLBACKS.get(target_tier)

    # If no backend available, try fallbacks
    if not backend_name:
      current_tier = target_tier
      while current_tier and not backend_name:
        fallback = self.FALLBACKS.get(current_tier)
        if fallback:
          backend_name = self._find_backend_for_tier(fallback)
          if backend_name:
            target_tier = fallback
            break
        current_tier = fallback

    # Final fallback to placeholder
    if not backend_name:
      backend_name = "placeholder"
      target_tier = ModelTier.TINY

    return RouteDecision(
      model_tier=target_tier,
      backend_name=backend_name,
      reason=f"Task '{task.value}' → {target_tier.value}",
      fallback_tier=self.FALLBACKS.get(target_tier)
    )

  def _find_backend_for_tier(self, tier: ModelTier) -> Optional[str]:
    """Find an available backend for a tier"""
    for name, status in self.backend_status.items():
      if status['tier'] == tier and status['ready']:
        return name
    return None

  def _downgrade_tier(self, tier: ModelTier) -> ModelTier:
    """Downgrade to a smaller tier"""
    downgrades = {
      ModelTier.HEAVY: ModelTier.MEDIUM,
      ModelTier.MEDIUM: ModelTier.SMALL,
      ModelTier.SMALL: ModelTier.TINY,
      ModelTier.TINY: ModelTier.TINY,
      ModelTier.INTENT: ModelTier.INTENT,
    }
    return downgrades.get(tier, tier)

  def list_models(self) -> str:
    """List all available models

    Returns:
      Formatted string of available models
    """
    output = "\n🤖 AVAILABLE MODELS\n"
    output += "=" * 40 + "\n\n"

    if not self.backend_status:
      output += "No models registered.\n"
      output += "Default: placeholder (rule-based)\n"
      return output

    for name, status in self.backend_status.items():
      tier = status['tier'].value
      ready = "✓" if status['ready'] else "✗"
      active = " ← active" if name == self.get_active_model() else ""
      output += f"  {ready} {name:15} [{tier:8}]{active}\n"

    output += "\n"
    output += "Tier Legend:\n"
    output += "  heavy  - Complex reasoning (BitNet, Llama 70B)\n"
    output += "  medium - Balanced (Llama 7B, Mistral)\n"
    output += "  small  - Fast responses (Phi, TinyLlama)\n"
    output += "  tiny   - Instant (rule-based, embeddings)\n"

    if self._user_preference:
      output += f"\nPreferred: {self._user_preference}\n"

    return output

  def infer_task_type(self, text: str) -> TaskType:
    """Infer task type from user input

    Args:
      text: User's input text

    Returns:
      Inferred TaskType
    """
    text_lower = text.lower()

    # Reasoning patterns
    reasoning_keywords = ['why', 'how come', 'explain', 'analyze', 'reason', 
              'think about', 'what if', 'compare']
    if any(kw in text_lower for kw in reasoning_keywords):
      return TaskType.REASONING

    # Summarization patterns
    summarize_keywords = ['summarize', 'summary', 'brief', 'tldr', 'short version']
    if any(kw in text_lower for kw in summarize_keywords):
      return TaskType.SUMMARIZE

    # Classification patterns
    classify_keywords = ['is this', 'classify', 'categorize', 'what type', 'which']
    if any(kw in text_lower for kw in classify_keywords):
      return TaskType.CLASSIFY

    # Extraction patterns
    extract_keywords = ['extract', 'find', 'get', 'list all', 'what are']
    if any(kw in text_lower for kw in extract_keywords):
      return TaskType.EXTRACT

    # Default to chat
    return TaskType.CHAT


# Singleton router instance
_router_instance = None

def get_router() -> ModelRouter:
  """Get the global router instance"""
  global _router_instance
  if _router_instance is None:
    _router_instance = ModelRouter()
  return _router_instance
