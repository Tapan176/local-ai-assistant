"""Resolves short pronoun references from recent episodic context."""

from __future__ import annotations

import re
from typing import Any


class ReferenceResolver:
    GENERAL_PRONOUNS = {"it", "that", "this", "there", "one", "them"}
    PERSON_PRONOUNS = {"he", "she", "him", "her"}
    PRONOUNS = GENERAL_PRONOUNS | PERSON_PRONOUNS

    def resolve(self, user_text: str, episodic_memories: list[dict[str, Any]]) -> str:
        words = re.findall(r"[a-zA-Z0-9_]+", user_text.lower())
        if not words:
            return user_text
        if len(words) > 8:
            return user_text
        if not any(token in self.PRONOUNS for token in words):
            return user_text

        person_mode = any(token in self.PERSON_PRONOUNS for token in words)
        candidate = (
            self._infer_recent_person_entity(episodic_memories)
            if person_mode
            else self._infer_recent_entity(episodic_memories)
        )
        if not candidate:
            return user_text

        resolved = user_text
        target_tokens = self.PERSON_PRONOUNS if person_mode else self.GENERAL_PRONOUNS
        for token in target_tokens:
            resolved = re.sub(rf"\b{token}\b", candidate, resolved, count=1, flags=re.IGNORECASE)
        return resolved

    @staticmethod
    def _infer_recent_entity(episodic_memories: list[dict[str, Any]]) -> str | None:
        if not episodic_memories:
            return None
        for turn in reversed(episodic_memories[-4:]):
            user_text = str(turn.get("user_text", ""))
            account_match = re.search(r"\b(?:to|from|in|into)\s+([A-Za-z][A-Za-z0-9_\-\s]{1,25})", user_text)
            if account_match:
                return account_match.group(1).strip().title()
            account_hinglish = re.search(r"\b([A-Za-z][A-Za-z0-9_\-]{1,25})\s+me\b", user_text, flags=re.IGNORECASE)
            if account_hinglish:
                return account_hinglish.group(1).strip().title()
            relation_match = re.search(r"\b([A-Z][a-z]{1,20})\s+is my\s+[a-z]{2,20}", user_text)
            if relation_match:
                return relation_match.group(1).strip().title()
            number_match = re.search(r"(?<!\w)\d+(?:\.\d+)?(?!\w)", user_text)
            if number_match:
                return number_match.group(0)
        return None

    @staticmethod
    def _infer_recent_person_entity(episodic_memories: list[dict[str, Any]]) -> str | None:
        if not episodic_memories:
            return None
        for turn in reversed(episodic_memories[-8:]):
            user_text = str(turn.get("user_text", ""))
            relation_match = re.search(
                r"\b([A-Z][a-z]{1,24})\s+is my\s+[a-z]{2,24}",
                user_text,
                flags=re.IGNORECASE,
            )
            if relation_match:
                return relation_match.group(1).title()
            who_match = re.search(r"\bwho is\s+([A-Z][a-z]{1,24})", user_text, flags=re.IGNORECASE)
            if who_match:
                return who_match.group(1).title()
        return None
