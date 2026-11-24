"""Provider-aware LLM dispatch with multi-model Ollama waterfall (fully local)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from src.config.settings import Settings
from .semantic_intent_classifier import SemanticIntentClassifier, SemanticIntentMatch
from src.utils.constants import AFFIRMATION_WORDS, BANK_KEYWORDS, is_affirmation
from .bitnet_backend import BitNetBackend, create_bitnet_backend

logger = logging.getLogger(__name__)


class LLMDispatcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        mode = settings.intent_classifier.lower().strip()
        self._intent_mode = mode
        self._semantic_intent_classifier: SemanticIntentClassifier | None = None
        if mode in {"hybrid", "semantic"}:
            self._semantic_intent_classifier = SemanticIntentClassifier(
                model_name=settings.semantic_intent_model,
                threshold=settings.semantic_intent_threshold,
            )
        # Initialize BitNet backend if enabled
        self._bitnet_backend: BitNetBackend | None = None
        if settings.bitnet_enabled:
            self._bitnet_backend = create_bitnet_backend(settings)

    # ── Public API ──────────────────────────────────────────────────

    async def infer_reasoning(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Infer intent using semantic classification first, then LLM fallback."""
        user_text = str(payload.get("user_text", "")).strip()
        lowered = user_text.lower().strip()

        # 0. Hard fast-path: identity & memory queries (NEVER send to tools)
        name_match = re.search(
            r"\b(?:my name is|call me|i am|i'm)\s+([a-zA-Z][a-zA-Z\s]{0,30})",
            lowered,
        )
        if name_match:
            return {
                "inferred_intent": "identity",
                "confidence": 0.95,
                "needs_clarification": False,
                "clarification_question": None,
                "possible_actions": ["respond_conversationally"],
                "tool_candidates": [],
                "uncertainty": 0.05,
                "rationale": "Name declaration detected — no tool needed.",
            }

        memory_query_phrases = (
            "what memories", "what do you remember", "do you know me",
            "do you remember me", "who am i", "what is my name",
            "what's my name", "what do you know about me",
            "memories in supermemory", "show my data", "my profile",
            "what have we talked about", "your memory",
        )
        if any(phrase in lowered for phrase in memory_query_phrases):
            return {
                "inferred_intent": "memory_query",
                "confidence": 0.92,
                "needs_clarification": False,
                "clarification_question": None,
                "possible_actions": ["respond_with_memory_snapshot"],
                "tool_candidates": [],
                "uncertainty": 0.08,
                "rationale": "Memory/identity query — respond from memory, no tool.",
            }

        # 1. Fast Path: Semantic Classification
        if self._semantic_intent_classifier:
            try:
                match = self._semantic_intent_classifier.classify(user_text)
                if match and match.confidence >= 0.55:  # Lowered threshold for better recall
                    actions, candidates = self._intent_actions(match.intent)
                    return {
                        "inferred_intent": match.intent,
                        "confidence": round(match.confidence, 2),
                        "needs_clarification": False,
                        "clarification_question": None,
                        "possible_actions": actions,
                        "tool_candidates": candidates,
                        "uncertainty": round(1.0 - match.confidence, 2),
                        "rationale": f"Fast-path semantic match: {match.rationale}",
                    }
            except Exception as e:
                logger.warning("Semantic classification failed: %s", e)

        # 2. LLM Path
        provider = self.settings.llm_provider.lower()
        if provider == "mock":
            return self._heuristic_reasoning(payload)

        prompt = self._reasoning_prompt(payload)
        try:
            text = await self.generate_text(
                system="Infer intent and return strict JSON.",
                context="You are a reasoning engine for a cognitive assistant.",
                user=prompt,
                temperature=0.1,
                json_mode=True,
            )
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        
        # 3. Fallback Path
        return self._heuristic_reasoning(payload)

    async def generate_text(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.5,
        json_mode: bool = False,
    ) -> str:
        """Try OpenRouter → Ollama → BitNet → heuristic fallback."""
        provider = self.settings.llm_provider.lower()
        if provider == "mock":
            return self._heuristic_generation(system, context, user, temperature, json_mode)

        # 1. OpenRouter (primary cloud LLM)
        if self.settings.openrouter_api_key:
            for model in [self.settings.openrouter_model, self.settings.openrouter_fallback_model]:
                text = await self._openrouter_chat(model, system, context, user, temperature, json_mode)
                if text:
                    return text

        # 2. Ollama fallback (local models)
        models = [self.settings.ollama_model] + list(self.settings.ollama_fallback_models)
        for model in models:
            text = await self._ollama_chat(model, system, context, user, temperature, json_mode)
            if text:
                return text

        # 3. BitNet fallback (last resort local)
        if self._bitnet_backend and self.settings.bitnet_enabled:
            text = await self._bitnet_backend.generate(system, context, user, temperature, json_mode)
            if text:
                return text

        logger.warning("All LLM backends failed, falling back to heuristic generation")
        return self._heuristic_generation(system, context, user, temperature, json_mode)

    # ── OpenRouter (OpenAI-compatible API) ──────────────────────────

    async def _openrouter_chat(
        self,
        model: str,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
        """Call OpenRouter using the OpenAI-compatible chat completions API."""
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tapan-ai.local",
            "X-Title": "TAPAN_AI",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            timeout = float(self.settings.openrouter_timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self.settings.openrouter_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    content = str(choices[0].get("message", {}).get("content", "")).strip()
                    if content:
                        logger.info("OpenRouter model %s responded successfully", model)
                        return content
        except httpx.TimeoutException:
            logger.warning("OpenRouter model %s timed out after %ss", model, self.settings.openrouter_timeout)
        except Exception as exc:
            logger.warning("OpenRouter model %s failed: %s", model, exc)
        return None

    # ── Ollama (parameterized by model) ─────────────────────────────

    async def _ollama_chat(
        self,
        model: str,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
        payload = {
            "model": model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["format"] = "json"
        try:
            timeout = float(self.settings.ollama_timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(self.settings.ollama_url, json=payload)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                content = str(message.get("content", "")).strip()
                if content:
                    logger.info("Ollama model %s responded successfully", model)
                    return content
        except httpx.TimeoutException:
            logger.warning("Ollama model %s timed out after %ss", model, self.settings.ollama_timeout)
        except Exception as exc:
            logger.warning("Ollama model %s failed: %s", model, exc)
        return None

    # ── Heuristic generation (replaces _mock_generation) ────────────

    def _heuristic_generation(
        self,
        _system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str:
        user_text = self._extract_user_message(user)
        if json_mode:
            return json.dumps(self._heuristic_reasoning({"user_text": user_text}))

        emotion = "neutral"
        tone = "balanced"
        for line in context.splitlines():
            if line.strip().startswith("- Emotional State:"):
                emotion = line.split(":", 1)[1].strip().split(" ", 1)[0]
            if line.strip().startswith("- Tone:"):
                tone = line.split(":", 1)[1].strip()

        inferred_intent = self._extract_inferred_intent(context)
        lowered = user_text.lower().strip()
        recalled_name = self._extract_recalled_name(context)

        # ── Intent-specific handler dispatch ────────────────────────
        _HANDLERS: dict[str, str] = {
            "self_data_request": "_handle_data_request",
            "quality_feedback": "_handle_quality_feedback",
            "next_step_guidance": "_handle_next_step",
            "social_greeting": "_handle_greeting",
            "emotional_support": "_handle_emotional_support",
        }

        # Name declaration
        name_declare_match = re.search(
            r"\b(?:my name is|call me)\s+([A-Za-z][A-Za-z\\s]{1,30})",
            user_text,
            flags=re.IGNORECASE,
        )
        if name_declare_match:
            new_name = name_declare_match.group(1).strip().split(" ")[0].title()
            return (
                f"Nice to meet you, {new_name}! 😊 I'll remember that. "
                "Now tell me a bit about yourself — what do you do, and what kind of help would be most useful to you?"
            )

        # Name recall
        if recalled_name and re.search(r"\bwhat(?:'s| is)\s+my\s+name\b", user_text, flags=re.IGNORECASE):
            return f"Of course! You're {recalled_name}. I always remember 😊"
        
        # "Do you know me?" type queries
        if re.search(r"\bdo you know me\b|\bdo you remember me\b|\bwho am i\b", user_text, flags=re.IGNORECASE):
            if recalled_name:
                return self._build_memory_snapshot(context, recalled_name)
            return (
                "We haven't properly met yet! I'd love to get to know you. "
                "What's your name? And tell me a bit about yourself — I'll remember everything 😊"
            )

        # Data request via text cues
        if self._is_data_request_text(lowered):
            inferred_intent = "self_data_request"

        # Dispatch via handler table
        handler_name = _HANDLERS.get(inferred_intent)
        if handler_name:
            handler = getattr(self, handler_name)
            return handler(context=context, tone=tone, emotion=emotion, recalled_name=recalled_name)

        if emotion in {"sad", "stressed", "anxious"}:
            return self._handle_emotional_support(context=context, tone=tone, emotion=emotion, recalled_name=recalled_name)

        # Final fallback based on temperature/tone — always warm
        name_bit = f" {recalled_name}" if recalled_name else ""
        if temperature >= 0.75:
            return f"Ooh, I love brainstorming{name_bit}! Let's explore some ideas together. What direction are you thinking?"
        if temperature <= 0.25:
            return f"Got it{name_bit}. Give me the details and I'll handle it precisely."

        if tone in {"informal", "casual"}:
            return f"I'm here for you{name_bit}! What do you need?"
        return f"I'm listening{name_bit}. What would you like to do?"

    # ── Handler methods (called from dispatch table) ────────────────

    def _handle_data_request(self, *, context: str, **_: Any) -> str:
        recalled_name = self._extract_recalled_name(context)
        snapshot = self._build_memory_snapshot(context, recalled_name)
        return snapshot

    def _handle_quality_feedback(self, *, context: str, **_: Any) -> str:
        recalled_name = self._extract_recalled_name(context)
        name_bit = f" {recalled_name}" if recalled_name else ""
        return (
            f"You're absolutely right{name_bit}, and I appreciate you telling me. "
            "I should be more helpful, not just echo things back. "
            "Tell me what you need done and I'll actually do it."
        )

    def _handle_next_step(self, *, context: str, tone: str, **_: Any) -> str:
        recalled_name = self._extract_recalled_name(context)
        name_bit = f" {recalled_name}" if recalled_name else ""
        if tone in {"informal", "casual"}:
            return (
                f"Alright{name_bit}! Here's what I can help with: "
                "💰 finances, ⏰ reminders, 👥 people notes, or 📅 calendar. "
                "What sounds most useful right now?"
            )
        return (
            f"Good question{name_bit}! I can help you with:\n"
            "• 💰 Track finances & budgets\n"
            "• ⏰ Set reminders & to-dos\n"
            "• 👥 Remember people & relationships\n"
            "• 📅 Manage your calendar\n"
            "What would be most helpful?"
        )

    def _handle_greeting(self, *, context: str, tone: str, **_: Any) -> str:
        recalled_name = self._extract_recalled_name(context)
        # Check if we have any persona data at all
        has_persona = recalled_name or "preferences:" in context and context.split("preferences:")[-1].strip()[:5] != "{}"
        
        if recalled_name:
            if tone in {"informal", "casual"}:
                return f"Hey {recalled_name}! Good to see you. What's on your mind today?"
            return f"Hey {recalled_name}! How's your day going? Anything I can help with?"
        elif not has_persona:
            # No memories at all — trigger onboarding
            return (
                "Hey! Great to meet you 😊 I'm Tapan, your personal AI companion. "
                "I get better the more I know about you. What should I call you?"
            )
        else:
            if tone in {"informal", "casual"}:
                return "Hey! Good to have you back. What are we working on today?"
            return "Hey! Nice to hear from you. What can I help you with today?"

    def _handle_emotional_support(self, *, context: str, **_: Any) -> str:
        recalled_name = self._extract_recalled_name(context)
        name_prefix = f"{recalled_name}, " if recalled_name else ""
        return f"{name_prefix}I hear you. We can take this one step at a time. Want to talk about it, make a plan, or both?"

    # ── Shared utility methods ──────────────────────────────────────

    @staticmethod
    def _extract_inferred_intent(context: str) -> str:
        match = re.search(r"- Inferred Intent:\s*([a-zA-Z_]+)", context)
        if not match:
            return "general_conversation"
        return match.group(1).strip().lower()

    @staticmethod
    def _build_memory_snapshot(context: str, recalled_name: str | None) -> str:
        recent_topics: list[str] = []
        for match in re.finditer(r"U:\s*(.+?)\s*\|\s*A:", context):
            text = match.group(1).strip()
            if not text or text.lower() in {"hi", "hey", "hello"}:
                continue
            recent_topics.append(text)

        semantic_items: list[str] = []
        for line in context.splitlines():
            clean = line.strip()
            if clean.startswith("-") and "(score=" in clean and "Semantic Memory" not in clean:
                value = clean.lstrip("- ").split("(score=", 1)[0].strip()
                if value and value.lower() != "none":
                    semantic_items.append(value)

        persona_match = re.search(r"preferences:\s*(\{.*\})", context)
        persona = persona_match.group(1).strip() if persona_match else "{}"
        goal_match = re.search(r"goals:\s*(\{.*\})", context)
        goals = goal_match.group(1).strip() if goal_match else "{}"

        parts: list[str] = []
        if recalled_name:
            parts.append(f"name: {recalled_name}")
        if semantic_items:
            parts.append("facts: " + "; ".join(semantic_items[:3]))
        if recent_topics:
            parts.append("recent topics: " + "; ".join(recent_topics[-3:]))
        if persona != "{}":
            parts.append(f"preferences: {persona}")
        if goals != "{}":
            parts.append(f"goals: {goals}")

        if not parts:
            return (
                "Honestly, I don't have much about you yet — we're just getting started! "
                "I'd love to change that though. Tell me a bit about yourself — "
                "your name, what you do, what's important to you. "
                "The more I know, the better I can help you day-to-day 😊"
            )

        name_greeting = f"Sure thing, {recalled_name}! " if recalled_name else ""
        return name_greeting + "Here's what I remember about you:\n" + "\n".join(f"• {p}" for p in parts)

    @staticmethod
    def _is_data_request_text(lowered_text: str) -> bool:
        cues = (
            "show my data",
            "all my data",
            "everything you have about me",
            "what do you know about me",
            "my profile data",
            "export my data",
        )
        return any(token in lowered_text for token in cues)

    @staticmethod
    def _extract_recalled_name(context: str) -> str | None:
        episodic_matches = re.findall(
            r"U:\s*(?:my name is|call me)\s+([A-Za-z][A-Za-z\s]{1,30})",
            context,
            flags=re.IGNORECASE,
        )
        if episodic_matches:
            candidate = episodic_matches[-1].strip().split(" ")[0].title()
            if candidate:
                return candidate

        semantic_match = re.search(r"user_name:\s*([a-zA-Z][a-zA-Z\s]{1,30})", context, flags=re.IGNORECASE)
        if semantic_match:
            candidate = semantic_match.group(1).strip().split(" ")[0].title()
            if candidate:
                return candidate

        persona_match = re.search(r"['\"]user_name['\"]\s*:\s*['\"]([A-Za-z][A-Za-z\s]{1,30})['\"]", context)
        if persona_match:
            candidate = persona_match.group(1).strip().split(" ")[0].title()
            if candidate:
                return candidate
        return None

    @staticmethod
    def _extract_user_message(user_block: str) -> str:
        if "USER" not in user_block:
            return user_block.strip()
        right = user_block.split("USER", 1)[1]
        if "INSTRUCTION" in right:
            right = right.split("INSTRUCTION", 1)[0]
        return right.strip()

    def _reasoning_prompt(self, payload: dict[str, Any]) -> str:
        return (
            "Analyze the message. Return JSON with keys: inferred_intent, confidence, needs_clarification, "
            "possible_actions, tool_candidates, rationale.\n"
            "ALLOWED TOOLS: ['finance_tool', 'reminder_tool', 'calendar_tool', 'people_tool']\n"
            "ALLOWED ACTIONS: ['execute_tool', 'respond_conversationally', 'ask_clarification']\n"
            "SCHEMA: inferred_intent must be one of [financial_update, reminder_management, calendar_management, "
            "people_memory_update, social_greeting, general_knowledge, identity, name_declaration, "
            "memory_query, recall_name, emotional_support, other].\n"
            "IMPORTANT RULES:\n"
            "- 'my name is X' or 'call me X' → identity intent, NO tool, respond_conversationally\n"
            "- 'do you know me' or 'what memories' or 'what do you remember' → memory_query intent, NO tool\n"
            "- 'who am i' or 'what is my name' → recall_name intent, NO tool\n"
            "- people_tool is ONLY for storing/querying OTHER people (friends, family), NOT the user themselves\n"
            f"INPUT: {json.dumps(payload, ensure_ascii=True)}"
        )

    def _heuristic_reasoning(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_text = str(payload.get("user_text", "")).strip()
        lowered = user_text.lower()
        memory = payload.get("memory", {})
        if not isinstance(memory, dict):
            memory = {}
        last_assistant_text = str(memory.get("last_assistant_text", "")).lower()

        has_amount = bool(re.search(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?!\w)", lowered))
        bank_cues = any(word in lowered for word in BANK_KEYWORDS[:6])
        money_cues = any(
            word in lowered
            for word in ("balance", "expense", "spent", "income", "account", "wallet", "transaction", "money")
        )
        balance_query = any(token in lowered for token in ("balance", "accounts", "show accounts", "list accounts", "kitna"))
        finance_query = any(
            phrase in lowered
            for phrase in (
                "how much", "how much did", "how much did i", "spent", "spend", "expenses", "expenditure",
                "income", "earned", "saved", "savings", "last month", "this month", "monthly", "summary"
            )
        )
        finance_verbs = any(
            word in lowered
            for word in ("add", "deposit", "credit", "credited", "debit", "withdraw", "paid", "pay", "transfer", "move")
        )
        account_create_cues = any(
            token in lowered
            for token in (
                "add new account", "create account", "open account",
                "new account", "add account", "added account",
                "created account", "opened account",
            )
        )

        reminder_cues = any(
            word in lowered for word in ("remind", "remember to", "don't let me forget", "reminder", "yaad dila", "yaad karana", "todo", "task")
        )
        calendar_cues = any(
            word in lowered for word in ("meeting", "schedule", "calendar", "appointment", "event", "plan", "milna", "agenda")
        )
        people_cues = any(
            word in lowered
            for word in (
                "my friend", "my brother", "my sister", "my manager",
                "my wife", "my husband", "my father", "my mother",
                "relationship", "contact", "friend list", "people",
                "person", "remove person", "delete person",
                "add a friend", "add friend", "add contact", "add person",
            )
        ) or (re.search(r"\bname\s+[a-z]+\s+(?:relation|rel)\b", lowered) is not None)
        people_query = bool(re.search(r"\bwho is\s+[a-z]", lowered))
        support_cues = any(word in lowered for word in ("sad", "stressed", "overwhelmed", "anxious", "lonely", "down"))
        support_cues = support_cues or any(word in lowered for word in ("thak", "pareshan", "udas", "tension"))

        memory_query_cues = any(
            phrase in lowered
            for phrase in (
                "memories", "memory", "what do you remember", "what have we talked",
                "what do you know about me", "do you know me", "do you remember me",
                "who am i", "what is my name", "what's my name", "recall our",
                "supermemory", "your memory", "in your memory",
            )
        )
        data_request_cues = self._is_data_request_text(lowered) or memory_query_cues
        next_step_cues = bool(re.search(r"\b(what|which)\s+next\s+step\b", lowered)) or lowered in {
            "what next", "next step", "what now", "now what",
        }
        quality_feedback_cues = any(
            phrase in lowered
            for phrase in (
                "just replying what i am entering", "just repeating",
                "only repeating", "echoing me", "you messed up",
                "not working", "command bot",
            )
        )
        greeting_cues = lowered in {"hi", "hey", "hello", "yo", "sup", "hola", "namaste"} or any(
            lowered.startswith(prefix) for prefix in ("hi ", "hey ", "hello ", "yo ", "namaste ")
        )

        tool_candidates: list[str] = []
        inferred_intent = "general_conversation"
        confidence = 0.42
        possible_actions = ["respond_conversationally"]
        rationale = "Default conversational response."
        clarification_question: str | None = None
        forced_clarification = False

        contextual_followup = is_affirmation(lowered)
        if contextual_followup:
            if any(token in last_assistant_text for token in ("transaction summary", "transaction history", "latest transaction")):
                inferred_intent = "financial_update"
                confidence = 0.79
                possible_actions = ["execute_tool", "respond_with_summary"]
                tool_candidates = ["finance_tool"]
                rationale = "Detected affirmative follow-up to finance summary prompt."
            elif any(token in last_assistant_text for token in ("create your first account", "create an account")):
                inferred_intent = "financial_update"
                confidence = 0.73
                possible_actions = ["ask_clarification"]
                tool_candidates = []
                forced_clarification = True
                clarification_question = "Sure. What should I name the account, and do you want an opening balance?"
                rationale = "Detected affirmative follow-up to account creation prompt."
            elif "another related reminder" in last_assistant_text:
                inferred_intent = "reminder_management"
                confidence = 0.72
                possible_actions = ["ask_clarification"]
                tool_candidates = []
                forced_clarification = True
                clarification_question = "Sure. What should I remind you about, and when?"
                rationale = "Detected affirmative follow-up to reminder prompt."

        account_name_reply = (
            "what should i name the account" in last_assistant_text
            and len(re.findall(r"\w+", lowered)) <= 5
            and lowered not in {"yes", "yup", "yeah", "sure", "ok", "okay"}
        )
        if inferred_intent == "general_conversation" and account_name_reply:
            inferred_intent = "financial_update"
            confidence = 0.78
            possible_actions = ["execute_tool", "respond_with_summary"]
            tool_candidates = ["finance_tool"]
            rationale = "Detected account name after account creation clarification."

        semantic_match = self._semantic_match(user_text)
        if inferred_intent == "general_conversation":
            if data_request_cues or memory_query_cues:
                inferred_intent = "self_data_request"
                confidence = 0.88
                possible_actions = ["respond_with_memory_snapshot"]
                rationale = "Detected request for stored user data or memory query."
            elif next_step_cues:
                inferred_intent = "next_step_guidance"
                confidence = 0.72
                possible_actions = ["respond_conversationally", "offer_actions"]
                rationale = "Detected request for suggested next action."
            elif quality_feedback_cues:
                inferred_intent = "quality_feedback"
                confidence = 0.78
                possible_actions = ["respond_conversationally", "offer_repair_action"]
                rationale = "Detected quality complaint."
            elif semantic_match is not None and self._intent_mode == "semantic":
                inferred_intent = semantic_match.intent
                confidence = max(confidence, semantic_match.confidence)
                rationale = semantic_match.rationale
                possible_actions, tool_candidates = self._intent_actions(inferred_intent)
            elif reminder_cues:
                inferred_intent = "reminder_management"
                confidence = 0.74
                possible_actions = ["execute_tool", "confirm_details"]
                tool_candidates = ["reminder_tool"]
                rationale = "Detected future-oriented reminder phrasing."
            elif calendar_cues:
                inferred_intent = "calendar_management"
                confidence = 0.71
                possible_actions = ["execute_tool", "confirm_schedule"]
                tool_candidates = ["calendar_tool"]
                rationale = "Detected scheduling language."
            elif has_amount and (money_cues or finance_verbs or bank_cues):
                inferred_intent = "financial_update"
                confidence = 0.82
                possible_actions = ["execute_tool", "respond_with_summary"]
                tool_candidates = ["finance_tool"]
                rationale = "Detected numeric amount and financial context."
            elif (account_create_cues and ("account" in lowered or bank_cues)) or (
                "account" in lowered and any(token in lowered for token in ("added", "created", "opened", "new"))
            ):
                inferred_intent = "financial_update"
                confidence = 0.76
                possible_actions = ["execute_tool", "respond_with_summary"]
                tool_candidates = ["finance_tool"]
                rationale = "Detected account creation or account-state change phrasing."
            elif (balance_query and (money_cues or bank_cues)) or finance_query or any(
                token in lowered for token in ("show accounts", "transaction history", "set balance", "rename account", "monthly summary", "category summary")
            ):
                inferred_intent = "financial_update"
                confidence = 0.75 if finance_query else 0.72
                possible_actions = ["execute_tool", "respond_with_summary"]
                tool_candidates = ["finance_tool"]
                rationale = "Detected financial query or account/balance query."
            elif people_cues or people_query:
                inferred_intent = "people_memory_update"
                confidence = 0.69
                possible_actions = ["execute_tool", "confirm_relationship"]
                tool_candidates = ["people_tool"]
                rationale = "Detected relationship context."
            elif support_cues:
                inferred_intent = "emotional_support"
                confidence = 0.7
                possible_actions = ["respond_supportively", "offer_small_next_step"]
                rationale = "Detected emotional distress language."
            elif greeting_cues:
                inferred_intent = "social_greeting"
                confidence = 0.8
                possible_actions = ["respond_conversationally"]
                rationale = "Detected greeting."
            elif semantic_match is not None:
                inferred_intent = semantic_match.intent
                confidence = max(confidence, semantic_match.confidence)
                rationale = semantic_match.rationale
                possible_actions, tool_candidates = self._intent_actions(inferred_intent)

        explicit_action = any(
            token in lowered
            for token in (
                "show accounts", "list accounts", "list reminders",
                "show reminders", "upcoming events", "transaction history",
                "who is", "delete person", "remove person", "list people",
                "show people", "friend list", "create account",
                "add account", "show my data", "what do you know about me",
            )
        )
        explicit_action = (
            explicit_action or data_request_cues or next_step_cues or quality_feedback_cues or contextual_followup or account_name_reply
        )

        word_count = len(re.findall(r"\w+", lowered))
        ambiguous = (
            (word_count <= 2 and not explicit_action and not greeting_cues)
            or lowered in {"handle this", "hmm"}
            or ("that one" in lowered and not explicit_action)
        )

        needs_clarification = forced_clarification or ambiguous or (confidence < 0.5 and bool(tool_candidates))
        if needs_clarification and not clarification_question:
            clarification_question = "Can you share a bit more detail so I can do the right thing?"
            possible_actions = ["ask_clarification"]

        uncertainty = max(0.0, 1.0 - confidence)
        return {
            "inferred_intent": inferred_intent,
            "confidence": round(confidence, 2),
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "possible_actions": possible_actions,
            "tool_candidates": tool_candidates,
            "uncertainty": round(uncertainty, 2),
            "rationale": rationale,
        }

    def _semantic_match(self, user_text: str) -> SemanticIntentMatch | None:
        if self._semantic_intent_classifier is None:
            return None
        try:
            return self._semantic_intent_classifier.classify(user_text)
        except Exception:
            return None

    @staticmethod
    def _intent_actions(intent: str) -> tuple[list[str], list[str]]:
        """Map semantic intent to (possible_actions, tool_candidates)."""
        finance_actions = (["execute_tool", "respond_with_summary"], ["finance_tool"])
        reminder_actions = (["execute_tool", "confirm_details"], ["reminder_tool"])
        calendar_actions = (["execute_tool", "confirm_schedule"], ["calendar_tool"])
        people_actions = (["execute_tool", "confirm_relationship"], ["people_tool"])
        conversational = (["respond_conversationally"], [])

        _MAP: dict[str, tuple[list[str], list[str]]] = {
            # Broad intents (legacy/built-in)
            "financial_update": finance_actions,
            "reminder_management": reminder_actions,
            "calendar_management": calendar_actions,
            "people_memory_update": people_actions,
            "emotional_support": (["respond_supportively", "offer_small_next_step"], []),
            "self_data_request": (["respond_with_memory_snapshot"], []),
            "next_step_guidance": (["respond_conversationally", "offer_actions"], []),
            "quality_feedback": (["respond_conversationally", "offer_repair_action"], []),
            "social_greeting": conversational,

            # Granular intents (YAML)
            "greeting": conversational,
            "farewell": conversational,
            "identity": conversational,
            "mood_check": conversational,
            "small_talk": conversational,
            "compliment": conversational,
            "general_knowledge": conversational,
            "help_request": (["respond_conversationally", "offer_actions"], []),
            "memory_query": (["respond_with_memory_snapshot"], []),
            "recall_name": (["respond_with_memory_snapshot"], []),
            "name_declaration": conversational,
            
            "check_balance": finance_actions,
            "transfer_money": finance_actions,
            "list_transactions": finance_actions,
            "create_account": finance_actions,
            
            "set_reminder": reminder_actions,
            "list_reminders": reminder_actions,
            
            "schedule_event": calendar_actions,
            "list_events": calendar_actions,
            
            "add_person": people_actions,
        }
        return _MAP.get(intent, conversational)
