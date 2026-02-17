"""
Orchestrator - Central Intelligence (Jarvis Mode)
Phase 17: Adaptive intelligence - learning, multi-turn, proactive, personalization
"""
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

from src.agent.intent_parser import IntentParser
from src.agent.semantic_intent_parser import SemanticIntentParser
from src.agent.output_sanitizer import OutputSanitizer
from src.agent.tools.base import BaseTool, ToolResult
from src.agent.tools.finance_tool import FinanceTool
from src.agent.tools.experience_tool import ExperienceTool
from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.relation_tool import RelationTool
from src.agent.tools.cognee_tool import CogneeTool
from src.agent.memory_router import MemoryRouter
from src.agent.companion_prompt import build_companion_context

# Context & Intelligence modules (lazy-loaded to avoid circular imports)
_context_builder = None
_decision_engine = None
_planner = None
_tone_manager = None
_llm = None
_user_profile = None
_proactive_engine = None
_perf_monitor = None
_prediction_engine = None
_smart_notifier = None


def _get_context_builder(data_dir: Path):
  global _context_builder
  if _context_builder is None:
    from src.agent.context import ContextBuilder
    _context_builder = ContextBuilder(data_dir)
  return _context_builder


def _get_decision_engine(data_dir: Path):
  global _decision_engine
  if _decision_engine is None:
    try:
      from src.agent.decision_engine_v2 import DecisionEngineV2
      _decision_engine = DecisionEngineV2(data_dir)
    except Exception:
      # Fallback to v1 if v2 fails
      try:
        from src.agent.decision_engine import DecisionEngine
        _decision_engine = DecisionEngine(data_dir)
      except Exception:
        _decision_engine = None
  return _decision_engine


def _get_planner(data_dir: Path):
  global _planner
  if _planner is None:
    try:
      from src.agent.planner_v2 import PlannerV2
      _planner = PlannerV2(data_dir)
    except Exception:
      _planner = None
  return _planner


def _get_tone_manager():
  global _tone_manager
  if _tone_manager is None:
    try:
      from src.agent.persona_tone import get_tone_manager
      _tone_manager = get_tone_manager()
    except Exception:
      _tone_manager = None
  return _tone_manager


def _get_llm(data_dir: Path):
  global _llm
  if _llm is None:
    try:
      from src.service.brain_service import get_llm as _brain_get_llm
      _llm = _brain_get_llm(data_dir)
    except Exception:
      _llm = None
  return _llm


def _get_user_profile(data_dir: Path):
  global _user_profile
  if _user_profile is None:
    try:
      from src.agent.user_profile import UserProfile
      _user_profile = UserProfile(data_dir)
    except Exception:
      _user_profile = None
  return _user_profile


def _get_proactive_engine(data_dir: Path):
  global _proactive_engine
  if _proactive_engine is None:
    try:
      from src.agent.proactive_engine import ProactiveEngine
      profile = _get_user_profile(data_dir)
      _proactive_engine = ProactiveEngine(data_dir, user_profile=profile)
    except Exception:
      _proactive_engine = None
  return _proactive_engine


def _get_perf_monitor():
  global _perf_monitor
  if _perf_monitor is None:
    try:
      from src.optimization.performance_monitor import get_perf_monitor
      _perf_monitor = get_perf_monitor()
    except Exception:
      _perf_monitor = None
  return _perf_monitor


def _get_prediction_engine(data_dir: Path):
  global _prediction_engine
  if _prediction_engine is None:
    try:
      from src.intelligence.predictor import PredictiveIntelligence
      profile = _get_user_profile(data_dir)
      _prediction_engine = PredictiveIntelligence(data_dir, user_profile=profile)
    except Exception:
      _prediction_engine = None
  return _prediction_engine


def _get_smart_notifier(data_dir: Path):
  global _smart_notifier
  if _smart_notifier is None:
    try:
      from src.notifications.smart_notifier import SmartNotifier
      profile = _get_user_profile(data_dir)
      _smart_notifier = SmartNotifier(user_profile=profile)
    except Exception:
      _smart_notifier = None
  return _smart_notifier


class Orchestrator:
  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.data_dir.mkdir(parents=True, exist_ok=True)
    self.data_dir.mkdir(parents=True, exist_ok=True)
    self.intent_parser = IntentParser()
    self.semantic_parser = None  # Lazy init with LLM
    self.sanitizer = OutputSanitizer()
    self.current_backend = "sqlite"  # default memory backend

    # Register tools
    self.tools: Dict[str, BaseTool] = {}
    self._register_tools()

    # Memory Router: wires SQLite (MemoryTool) + Cognee (CogneeTool)
    memory_tool = self.tools.get("memory")
    cognee_tool = self.tools.get("cognee")
    self.memory_router = MemoryRouter(memory_tool, cognee_tool)

    # Phase 17: Adaptive intelligence modules (lazy init)
    self._conversation_mgr = None
    self._personalizer = None

  def _register_tools(self):
    self.register(FinanceTool(self.data_dir))
    self.register(ExperienceTool(self.data_dir))
    self.register(MemoryTool(self.data_dir))
    self.register(ReminderTool(self.data_dir))
    self.register(RelationTool(self.data_dir))
    self.register(CogneeTool(self.data_dir))

  def register(self, tool: BaseTool):
    self.tools[tool.name] = tool

  def _get_conversation_mgr(self):
    """Lazy-init ConversationManager with data_dir for persistence."""
    if self._conversation_mgr is None:
      try:
        from src.agent.conversation_manager import ConversationManager
        self._conversation_mgr = ConversationManager(data_dir=self.data_dir)
      except Exception:
        pass
    return self._conversation_mgr

  def _get_personalizer(self):
    """Lazy-init ResponsePersonalizer."""
    if self._personalizer is None:
      try:
        from src.agent.response_personalizer import ResponsePersonalizer
        profile = _get_user_profile(self.data_dir)
        self._personalizer = ResponsePersonalizer(user_profile=profile)
      except Exception:
        pass
    return self._personalizer

  def process(self, text: str, source: str = "text") -> str:
    """
    Main Event Loop:
    1. Resolve references (multi-turn)
    2. Deterministic Intent (regex + fuzzy)
    3. Route to tool / decision engine / planner / LLM
    4. Apply PersonaTone + Personalizer formatting
    5. Learn from interaction + save conversation turn

    Args:
      text: User input text
      source: Source of input ("text", "voice", etc.)
    """
    text = text.strip()
    if not text:
      return ""

    # Direct shortcuts
    if text.lower() in ["help", "?"]:
      return self._show_help()
    if text.lower() in ["cls", "clear"]:
      print("\033[H\033[J", end="")
      return ""

    # Phase 17: Resolve pronoun references from conversation context
    conv = self._get_conversation_mgr()
    if conv:
      text = conv.resolve_reference(text)

    # 1. Parse intent (System 1: Regex)
    intent = self.intent_parser.parse(text)

    # 2. Semantic Parse (System 2: LLM)
    if not intent:
        # Initialize semantic parser if needed
        if not self.semantic_parser:
            llm = _get_llm(self.data_dir)
            if llm:
                self.semantic_parser = SemanticIntentParser(self.data_dir, llm)

        if self.semantic_parser:
             # Fetch short context for disambiguation
             context_str = ""
             if conv:
                 # Get last 2 turns for context
                 context_str = conv.get_recent_history(limit=2)

             intent = self.semantic_parser.parse(text, context=context_str)

    if intent:
      response = self._handle_intent(intent, text)
      intent_name = intent.get("tool", "")
    else:
      # No match → LLM fallback (Chat)
      response = self._llm_fallback(text)
      intent_name = "llm_fallback"

    # Phase 17: Track conversation turn with source information
    if conv:
      entities = intent.get("params", {}) if intent else {}
      conv.add_turn(text, response, intent_name, entities, source=source)

    # Phase 17: Learn from interaction
    try:
      profile = _get_user_profile(self.data_dir)
      if profile:
        action = intent.get("method", "") if intent else ""
        profile.learn_from_interaction(text, action=action, intent=intent_name)
    except Exception:
      pass

    # Save conversation turn (existing context builder)
    self._save_turn(text, response)

    return response

  def _handle_intent(self, intent: Dict, original_text: str) -> str:
    """Route an intent to the right handler."""
    tool = intent["tool"]
    method = intent["method"]
    params = intent["params"]
    confidence = intent.get("confidence", 1.0)

    # System commands
    if tool == "system":
      return self._handle_system_command(method, params)

    # Decision queries → DecisionEngineV2
    if tool == "decision":
      return self._handle_decision(params)

    # Planning queries → PlannerV2
    if tool == "planning":
      return self._handle_planning(params)

    # Ask (RAG query) → BrainService.ask()
    if tool == "ask":
      return self._handle_ask(params)

    # Free chat → LLM
    if tool == "free_chat":
      return self._handle_greeting(original_text)

    # Memory/Cognee → MemoryRouter
    if tool in ("memory", "cognee"):
      result = self.memory_router.route(method, params)
      return self._format_response(result.message)

    # All other tools
    return self._execute_tool(tool, method, params)

  # === DECISION ENGINE ===

  def _handle_decision(self, params: Dict) -> str:
    """Route to DecisionEngineV2 for purchase/decision evaluation."""
    engine = _get_decision_engine(self.data_dir)
    if engine is None:
      return self._format_response("Decision engine is not available right now.")

    query = params.get("query", "")
    amount = params.get("amount")

    try:
      # If we have DecisionEngineV2 with full_pipeline
      if hasattr(engine, 'full_pipeline'):
        pipeline = engine.full_pipeline(query)
        if hasattr(engine, 'format_pipeline_result'):
          formatted = engine.format_pipeline_result(pipeline)
          return self._format_response(formatted)
        # Fallback: format the pipeline dict manually
        result = pipeline.get("result")
        if result and hasattr(result, 'recommendation'):
          parts = [f"📊 {result.recommendation}"]
          if result.reasoning:
            parts.append(f"💡 {result.reasoning}")
          if result.alternatives:
            parts.append("🔄 Alternatives: " + ", ".join(result.alternatives[:2]))
          return self._format_response("\n".join(parts))

      # Fallback: v1 engine with analyze_purchase
      if amount and hasattr(engine, 'format_purchase_analysis'):
        formatted = engine.format_purchase_analysis(amount)
        return self._format_response(formatted)

      # Generic advice context
      if hasattr(engine, 'format_context_summary'):
        return self._format_response(engine.format_context_summary())

    except Exception as e:
      return self._format_response(f"Decision analysis failed: {str(e)}")

    return self._format_response("I couldn't analyze that decision. Try: 'should I buy X for Y rupees?'")

  # === PLANNER ===

  def _handle_planning(self, params: Dict) -> str:
    """Route to PlannerV2 for daily planning."""
    planner = _get_planner(self.data_dir)
    if planner is None:
      return self._format_response("Planner is not available. Make sure habits and reminders are set up.")

    try:
      plan = planner.generate_plan()
      formatted = planner.format_plan(plan)
      return self._format_response(formatted)
    except Exception as e:
      return self._format_response(f"Planning failed: {str(e)}")

  # === FREE CHAT / GREETING ===

  def _handle_greeting(self, text: str) -> str:
    """Handle greetings with PersonaTone or LLM."""
    tone = _get_tone_manager()

    if tone:
      try:
        greeting = tone.get_greeting()
        return self._format_response(greeting)
      except Exception:
        pass

    # Simple fallback greetings
    greetings = [
      "Hey Tapan! Kya haal hai? Bolo kya help chahiye 😊",
      "Hello! Main yahin hoon — batao kya karna hai?",
      "Hey! Ready to help. 'help' type karo commands ke liye.",
    ]
    import random
    return greetings[hash(text) % len(greetings)]

  # === LLM FALLBACK ===

  def _llm_fallback(self, text: str) -> str:
    """
    When no intent matches, use LLM with companion-oriented context.
    If no LLM is available, fall back to memory capture/help text.
    """
    llm = _get_llm(self.data_dir)

    if llm:
      try:
        ctx = _get_context_builder(self.data_dir)
        base_context = ctx.build_full_context() if ctx else ""

        conv = self._get_conversation_mgr()
        recent_history = conv.get_recent_history(limit=4) if conv else ""

        sentiment_label = "neutral"
        try:
          from src.agent.sentiment import SentimentEngine
          sentiment_label = SentimentEngine().analyze(text).get("label", "neutral")
        except Exception:
          pass

        relevant_memories = ctx.get_memories_snapshot(query=text) if ctx else []

        context_str = build_companion_context(
          base_context,
          sentiment_label=sentiment_label,
          recent_history=recent_history,
          memories=relevant_memories,
        )

        response = llm.generate(text, context=context_str)
        if response and not response.startswith("(placeholder)"):
          return self._format_response(response)
      except Exception:
        pass

    # No LLM or error → save long text as memory, short text gets help
    words = text.split()
    if len(words) >= 4:
      # Looks like a narrative → save as memory
      mem_tool = self.tools.get("memory")
      if mem_tool:
        result = mem_tool.execute("remember", {"text": text})
        return self._format_response(f"Got it! Saved as memory. {result.message}")
    
    return self._format_response(
      "Samajh nahi aaya. Commands ke liye 'help' type karo, "
      "ya sentence mein batao to memory mein save kar dunga."
    )

  # === FORMATTING ===

  def _format_response(self, text: str) -> str:
    """Apply PersonaTone + ResponsePersonalizer + OutputSanitizer."""
    sanitized = self.sanitizer.sanitize(text)

    # PersonaTone formatting
    tone = _get_tone_manager()
    if tone:
      try:
        sanitized = tone.format_response(sanitized)
      except Exception:
        pass

    # Phase 17: ResponsePersonalizer (mood-aware)
    personalizer = self._get_personalizer()
    if personalizer:
      try:
        profile = _get_user_profile(self.data_dir)
        context = profile.get_current_context() if profile else {}
        conv = self._get_conversation_mgr()
        is_first = conv.get_turn_count() <= 1 if conv else True
        sanitized = personalizer.personalize(sanitized, context, is_first=is_first)
      except Exception:
        pass

    return sanitized

  # === CONVERSATION MEMORY ===

  def _save_turn(self, user_msg: str, assistant_msg: str):
    """Save conversation turn for context."""
    try:
      ctx = _get_context_builder(self.data_dir)
      if ctx:
        ctx.save_chat_turn(user_msg, assistant_msg)
    except Exception:
      pass  # Never let chat logging break the main flow

  # === SYSTEM COMMANDS ===

  def _handle_system_command(self, method: str, params: Dict) -> str:
    if method == "help":
      return self._show_help()
    if method == "list_commands":
      return self._list_commands()
    if method == "clear":
      print("\033[H\033[J", end="")
      return "Cleared console."
    if method == "reset":
      return self._system_reset()
    if method == "toggle_backend":
      backend = params.get("backend", "sqlite")
      self.current_backend = backend
      return self._format_response(f"Memory backend switched to: {backend}")

    # LLM system commands
    if method == "llm_status":
      return self._handle_llm_status()
    if method == "llm_models":
      return self._handle_llm_models()
    if method == "llm_switch":
      return self._handle_llm_switch(params.get("model", ""))

    # Phase 17: Adaptive intelligence commands
    if method == "suggestions":
      return self._handle_suggestions()
    if method == "profile_show":
      return self._handle_profile_show()
    if method == "profile_stats":
      return self._handle_profile_stats()
    if method == "perf_report":
      return self._handle_perf_report()
    if method == "session_summary":
      return self._handle_session_summary()
    if method == "end_session":
      return self._handle_end_session()

    return "Unknown system command."

  # === ASK (RAG Pipeline) ===

  def _handle_ask(self, params: Dict) -> str:
    """Route to BrainService.ask() for RAG-augmented answers."""
    query = params.get("query", "")
    if not query:
      return self._format_response("Ask me something! Example: ask what are my hobbies?")

    try:
      from src.service.brain_service import ask as brain_ask
      response = brain_ask(query, data_dir=self.data_dir)
      if response:
        return self._format_response(response)
    except Exception as e:
      # Brain service failed — try direct LLM
      llm = _get_llm(self.data_dir)
      if llm:
        try:
          response = llm.generate(query)
          if response and not response.startswith("(placeholder)"):
            return self._format_response(response)
        except Exception:
          pass

    return self._format_response(
      "LLM not available for answering. Make sure Ollama is running: ollama serve"
    )

  # === LLM COMMANDS ===

  def _handle_llm_status(self) -> str:
    """Show Ollama/LLM connection status."""
    try:
      from src.brain.ollama_backend import get_ollama
      ollama = get_ollama()
      return ollama.get_status()
    except Exception:
      return "LLM status unavailable. Ollama module not loaded."

  def _handle_llm_models(self) -> str:
    """List available LLM models."""
    try:
      from src.brain.ollama_backend import get_ollama
      ollama = get_ollama()
      models = ollama.list_models()
      if not models:
        return "No models found. Is Ollama running? Try: ollama serve"
      active = ollama._get_model()
      lines = ["Available models:"]
      for m in models:
        marker = " (active)" if m == active else ""
        lines.append(f"  • {m}{marker}")
      return "\n".join(lines)
    except Exception:
      return "Cannot list models. Ollama module not loaded."

  def _handle_llm_switch(self, model_name: str) -> str:
    """Switch active LLM model."""
    if not model_name:
      return "Usage: llm switch <model_name>"
    try:
      from src.brain.ollama_backend import get_ollama
      ollama = get_ollama()
      if ollama.switch_model(model_name):
        return self._format_response(f"✅ Switched to model: {model_name}")
      else:
        available = ", ".join(ollama.list_models() or ["none"])
        return self._format_response(f"Model '{model_name}' not found. Available: {available}")
    except Exception:
      return "Cannot switch model. Ollama module not loaded."

  # === PHASE 17: ADAPTIVE COMMAND HANDLERS ===

  def _handle_suggestions(self) -> str:
    engine = _get_proactive_engine(self.data_dir)
    if engine:
      return engine.format_suggestions()
    return "💡 Proactive engine not available."

  def _handle_profile_show(self) -> str:
    profile = _get_user_profile(self.data_dir)
    if profile:
      return profile.get_profile_summary()
    return "No profile data yet."

  def _handle_profile_stats(self) -> str:
    profile = _get_user_profile(self.data_dir)
    if profile:
      return profile.get_context_string()
    return "No profile data yet."

  def _handle_perf_report(self) -> str:
    monitor = _get_perf_monitor()
    if monitor:
      return monitor.get_report()
    return "📊 Performance monitor not available."

  # === PHASE 18: AUTONOMOUS CHECKS ===

  def autonomous_check(self, check_type: str):
    """
    Called by BackgroundService to check for proactive notifications.
    Returns: List[str] or str or None
    """
    # 1. Reminders
    if check_type == "reminders":
      engine = _get_proactive_engine(self.data_dir)
      if engine:
        # We need a method in ProactiveEngine to return raw suggestions
        # For now, we use format_suggestions() and parse if needed, 
        # or better, access internal logic.
        # Assuming get_suggestions() returns list of dicts.
        sugs = engine.get_suggestions()
        notifier = _get_smart_notifier(self.data_dir)
        valid_sugs = []
        for s in sugs:
          priority = s.get("priority", "medium")
          if notifier and notifier.should_notify(s.get("type", "routine"), priority):
            valid_sugs.append(s.get("message", ""))
        return valid_sugs
      return []

    # 2. System
    if check_type == "system":
        # Placeholder for system health check
        # Could use psutil here if allowed
        return None

    # 3. Prediction
    if check_type == "prediction":
      predictor = _get_prediction_engine(self.data_dir)
      if predictor:
        preds = predictor.predict_next_action()
        if preds and preds[0]["confidence"] > 0.8:
          return f"Prediction: Likely to {preds[0]['action']} ({preds[0]['reason']})"
      return None

    # 4. Patterns
    if check_type == "patterns":
      profile = _get_user_profile(self.data_dir)
      if profile:
        # Trigger pattern detection logic inside UserProfile
        # (Assuming it exposes _detect_patterns or we simulate interaction)
        # Profile learns on interaction, so maybe we just ping it?
        pass
      return None
      
    return None

  def _handle_session_summary(self) -> str:
    conv = self._get_conversation_mgr()
    if conv:
      return conv.get_session_summary()
    return "No session data."

  def _handle_end_session(self) -> str:
    conv = self._get_conversation_mgr()
    if conv:
      conv.end_session()
    personalizer = self._get_personalizer()
    if personalizer:
      personalizer.reset_session()
    return "Session ended. Fresh start!"

  def _show_help(self) -> str:
    return """
[JARVIS] TAPAN_AI - Your Personal Companion

[FINANCE] Financial Management:
  expense 500 food        -> Add expense
  income 1000 salary      -> Add income
  transfer 100 from A to B -> Transfer
  show accounts / balance  -> View accounts
  add account savings 5000 -> New account

[MEMORY] Memory Management:
  remember I like pizza    -> Save fact
  show memories            -> List all
  recall food preferences  -> Semantic search (Cognee)
  search memory pizza      -> Search memories

[EXPERIENCE] Activity Logging:
  log went to gym          -> Log event
  show experiences / stats -> View activity

[REMINDER] Task Management:
  remind me to buy milk    -> Set reminder
  show reminders           -> List reminders

[DECISION] Decision Support:
  should I buy PS5 for 50000? -> Finance-aware advice
  can I afford a trip?        -> Budget analysis

[PLANNING] Daily Planning:
  daily plan / aaj ka plan -> Smart daily schedule
  what should I do today?  -> Next action

[ASK] Knowledge & AI:
  ask what are my hobbies? -> Memory-augmented answer
  ask about my spending patterns -> Insights from data
  ask summarize my week    -> Context-aware summary

[LLM] Model Management:
  llm status               -> Check Ollama connection
  llm models               -> List available models
  llm switch <model>       -> Change model

[SENTIMENT] Emotional Tracking:
  I'm feeling great!       -> Automatic sentiment tracking
  feeling a bit sad today  -> Mood-aware responses

[INTELLIGENCE] Adaptive Intelligence:
  suggestions              -> Proactive tips & reminders
  profile / my profile     -> View learned profile
  profile stats            -> Profile context for LLM
  session / session summary -> Current conversation stats
  end session              -> Start fresh conversation
  perf report              -> Performance metrics

[CONFIG] Configuration:
  /use_cognee / /use_sqlite -> Toggle memory backend
  help / clear / exit       -> System commands
  reset system              -> Factory reset

[CHAT] Just Talk:
  Or just talk to me - I'll chat or save it as memory!
"""

  def _list_commands(self) -> str:
    tools_info = []
    for name, tool in self.tools.items():
      actions = ", ".join(tool.actions) if hasattr(tool, 'actions') else "?"
      tools_info.append(f"  {name}: {actions}")
    return "Active Tools:\n" + "\n".join(tools_info)

  def _system_reset(self) -> str:
    """Factory Reset: Clear all data from all tools."""
    results = []
    print("[WARNING] INITIATING FACTORY RESET...")

    for name, tool in self.tools.items():
      try:
        if hasattr(tool, 'execute'):
          # Try delete_all first
          res = tool.execute("delete_all", {})

          # If failed or not implemented, try reset_all_balances (legacy finance)
          if not res.success:
             # Only try fallback if distinct method exists handling
             # (checks inside execute usually handle this, but safe to retry if specific code)
             if name == "finance":
                 res = tool.execute("reset_all_balances", {})
                 
          if res.success:
            results.append(f"  {name}: {res.message}")
          else:
            results.append(f"  {name}: {res.message} (Soft Fail)")
            
      except Exception as e:
        results.append(f"  {name}: CRITICAL ERROR {str(e)}")
        
    return "FACTORY RESET COMPLETE:\n" + "\n".join(results)

  def _execute_tool(self, tool_name: str, method: str, params: Dict) -> str:
    tool = self.tools.get(tool_name)
    if not tool:
      return self._format_response(f"Tool '{tool_name}' not active.")

    result = tool.execute(method, params)
    formatted = self._format_response(result.message)

    if result.success:
      return formatted
    else:
      return f"Error: {formatted}"

  def run_cli_loop(self):
    print("🤖 TAPAN_AI (Jarvis Mode) Ready. Type 'exit' to quit.")
    print("   Type 'help' for commands, or just talk to me!\n")
    while True:
      try:
        user_in = input("You: ")
        if user_in.lower() in ["exit", "quit"]:
          print("Bye Tapan! Take care 👋")
          break
        resp = self.process(user_in)
        print(f"TAPAN: {resp}")
      except KeyboardInterrupt:
        print("\nBye!")
        break
      except Exception as e:
        print(f"System Error: {e}")
