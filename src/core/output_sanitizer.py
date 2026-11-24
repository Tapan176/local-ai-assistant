"""Response sanitizer to prevent system leakage, raw-JSON artifacts, and echo."""

from __future__ import annotations

import json
import re


class OutputSanitizer:
    _LEAK_PATTERNS = (
        r"\b(system prompt|internal architecture|policy text|chain[- ]of[- ]thought)\b",
        r"\bhere(?:'s| is) (?:my )?reasoning\b",
        r"\bdeveloper instructions\b",
        r"\btool output is available\b",
    )

    def sanitize(self, text: str, user_text: str = "") -> str:
        if not text:
            return ""

        cleaned = str(text)
        cleaned = re.sub(r"```(?:json|yaml|python)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\[AUDIT\].*", "", cleaned, flags=re.IGNORECASE)
        cleaned = self._extract_from_json(cleaned)

        for pattern in self._LEAK_PATTERNS:
            cleaned = re.sub(pattern, "internal context", cleaned, flags=re.IGNORECASE)

        # Echo detection: if response repeats user's words, replace with generic
        if user_text and self._is_echo(user_text, cleaned):
            cleaned = "I hear you. Tell me what specific outcome you want, and I'll act on it."

        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _is_echo(user_text: str, response: str) -> bool:
        """Detect if the response is just parroting the user's input."""
        u_norm = re.sub(r"\s+", " ", user_text.strip().lower())
        r_norm = re.sub(r"\s+", " ", response.strip().lower())
        if not u_norm or not r_norm:
            return False
        # Exact echo
        if u_norm == r_norm:
            return True
        # Wrapped echo: response is "You said: <user text>"
        if r_norm.startswith("you said") and u_norm in r_norm:
            return True
        # Substantial overlap: >80% of user words appear in response verbatim
        u_words = set(u_norm.split())
        r_words = set(r_norm.split())
        if len(u_words) >= 4:
            overlap = len(u_words & r_words) / len(u_words)
            if overlap > 0.8 and len(r_words) <= len(u_words) * 1.3:
                return True
        return False

    @staticmethod
    def _extract_from_json(text: str) -> str:
        trimmed = text.strip()
        if not ((trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]"))):
            return text
        try:
            data = json.loads(trimmed)
        except Exception:
            return text
        if isinstance(data, dict):
            for key in ("response", "message", "text", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return text
