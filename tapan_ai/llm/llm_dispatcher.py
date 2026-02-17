"""Provider-aware LLM dispatch with robust local fallback."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from tapan_ai.config.settings import Settings


class LLMDispatcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def infer_reasoning(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        return self._heuristic_reasoning(payload)

    async def generate_text(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.5,
        json_mode: bool = False,
    ) -> str:
        provider = self.settings.llm_provider.lower()
        if provider == "openai":
            text = await self._openai_chat(system, context, user, temperature, json_mode)
            if text:
                return text
        if provider == "ollama":
            text = await self._ollama_chat(system, context, user, temperature, json_mode)
            if text:
                return text
        return self._mock_generation(system, context, user, temperature, json_mode)

    async def _openai_chat(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
        try:
            from openai import AsyncOpenAI
        except Exception:
            return None
        if not self.settings.openai_api_key:
            return None
        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = await client.chat.completions.create(**kwargs)
        return completion.choices[0].message.content or ""

    async def _ollama_chat(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
        try:
            import httpx
        except Exception:
            return None
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "format": "json" if json_mode else "",
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(self.settings.ollama_url, json=payload)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                return str(message.get("content", "")).strip()
        except Exception:
            return None

    def _mock_generation(
        self,
        _system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str:
        if json_mode:
            return json.dumps(self._heuristic_reasoning({"user_text": user}))

        emotion = "neutral"
        tone = "balanced"
        for line in context.splitlines():
            if line.strip().startswith("- Emotional State:"):
                emotion = line.split(":", 1)[1].strip().split(" ", 1)[0]
            if line.strip().startswith("- Tone:"):
                tone = line.split(":", 1)[1].strip()

        user_text = self._extract_user_message(user)
        memory_hint = ""
        recalled_name = None
        if "user_name:" in context.lower():
            match = re.search(r"user_name:\s*([a-zA-Z][a-zA-Z\s]{1,30})", context, flags=re.IGNORECASE)
            if match:
                recalled_name = match.group(1).strip()
                memory_hint = f" {recalled_name},"

        if recalled_name and re.search(r"\bwhat(?:'s| is)\s+my\s+name\b", user_text, flags=re.IGNORECASE):
            return f"Your name is {recalled_name}. Want me to keep using it naturally?"

        if emotion in {"sad", "stressed", "anxious"}:
            prefix = f"I hear you{memory_hint}. "
        elif tone in {"informal", "casual"}:
            prefix = f"Got it{memory_hint}. " if memory_hint else "Got it. "
        else:
            prefix = f"Understood{memory_hint}. " if memory_hint else "Understood. "

        if temperature >= 0.75:
            suffix = " Want to brainstorm a few creative options?"
        elif temperature <= 0.25:
            suffix = " I can keep this precise and actionable."
        else:
            suffix = " Tell me if you want me to take the next step."
        return f"{prefix}{self._compress_user_text(user_text)}.{suffix}"

    @staticmethod
    def _compress_user_text(user_text: str) -> str:
        clean = re.sub(r"\s+", " ", user_text).strip()
        if len(clean) <= 150:
            return clean
        return clean[:147].rstrip() + "..."

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
            "Analyze the following message and return JSON only with keys: "
            "inferred_intent, confidence, needs_clarification, clarification_question, "
            "possible_actions, tool_candidates, uncertainty, rationale.\n"
            f"INPUT: {json.dumps(payload, ensure_ascii=True)}"
        )

    def _heuristic_reasoning(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_text = str(payload.get("user_text", "")).strip()
        lowered = user_text.lower()

        has_amount = bool(re.search(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?!\w)", lowered))
        money_cues = any(word in lowered for word in ("balance", "expense", "spent", "income", "account", "wallet"))
        balance_query = "balance" in lowered or "accounts" in lowered
        finance_verbs = any(
            word in lowered for word in ("add", "deposit", "credit", "credited", "debit", "withdraw", "paid", "pay")
        )
        bank_cues = any(word in lowered for word in ("axis", "hdfc", "icici", "sbi"))
        reminder_cues = any(word in lowered for word in ("remind", "remember to", "don't let me forget", "reminder"))
        calendar_cues = any(word in lowered for word in ("meeting", "schedule", "calendar", "appointment", "event"))
        people_cues = any(word in lowered for word in ("my friend", "my brother", "my sister", "my manager", "relationship", "contact"))
        people_query = bool(re.search(r"\bwho is\s+[a-z]", lowered))
        support_cues = any(word in lowered for word in ("sad", "stressed", "overwhelmed", "anxious", "lonely", "down"))

        tool_candidates: list[str] = []
        inferred_intent = "general_conversation"
        confidence = 0.42
        possible_actions = ["respond_conversationally"]
        rationale = "Default conversational response."

        if reminder_cues:
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
        elif balance_query and (money_cues or bank_cues):
            inferred_intent = "financial_update"
            confidence = 0.72
            possible_actions = ["execute_tool", "respond_with_summary"]
            tool_candidates = ["finance_tool"]
            rationale = "Detected account/balance query."
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

        word_count = len(re.findall(r"\w+", lowered))
        ambiguous = word_count <= 2 or lowered in {"do it", "handle this", "okay", "hmm"} or "that one" in lowered
        uncertainty = max(0.0, 1.0 - confidence)
        needs_clarification = ambiguous or (confidence < 0.5 and bool(tool_candidates))
        clarification_question = None
        if needs_clarification:
            clarification_question = "Can you share a bit more detail so I can do the right thing?"
            possible_actions = ["ask_clarification"]

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
