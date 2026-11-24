"""Perception layer: tone, ambiguity, entities, emotion detection."""

from __future__ import annotations

import re
from typing import Any

from src.models import PerceptionOutput
from src.utils.constants import BANK_KEYWORDS

from .emotional_engine import EmotionalEngine


class PerceptionEngine:
    def __init__(self, emotional_engine: EmotionalEngine, spacy_model: str = "en_core_web_sm") -> None:
        self.emotional_engine = emotional_engine
        self._spacy_nlp: Any | None = None
        try:
            import spacy

            self._spacy_nlp = spacy.load(spacy_model, disable=["parser", "tagger", "lemmatizer", "textcat"])
        except Exception:
            self._spacy_nlp = None

    async def perceive(self, user_text: str, emotional_baseline: str = "neutral") -> PerceptionOutput:
        tone = self._detect_tone(user_text)
        ambiguity_score = self._detect_ambiguity(user_text)
        entities = self._extract_entities(user_text)
        emotional = await self.emotional_engine.analyze(user_text, baseline=emotional_baseline)
        language = self._detect_language(user_text)

        return PerceptionOutput(
            tone=tone,
            emotional_state=emotional.state,
            emotional_intensity=emotional.intensity,
            ambiguity_score=ambiguity_score,
            entities=entities,
            detected_language=language,
        )

    @staticmethod
    def _detect_tone(text: str) -> str:
        lowered = text.lower()
        informal_cues = ("bro", "yaar", "kya", "chal", "lol", "yo", "sup", "hey")
        formal_cues = ("could you", "would you", "please", "kindly", "regarding")
        if any(cue in lowered for cue in informal_cues):
            return "informal"
        if any(cue in lowered for cue in formal_cues):
            return "formal"
        if len(text.split()) <= 3:
            return "brief"
        return "balanced"

    @staticmethod
    def _detect_ambiguity(text: str) -> float:
        lowered = text.lower().strip()
        words = re.findall(r"\w+", lowered)
        if not words:
            return 1.0
        pronoun_like = any(token in {"it", "that", "this", "there", "thing"} for token in words)
        base = 0.15
        if len(words) <= 2:
            base += 0.45
        if pronoun_like:
            base += 0.25
        if lowered in {"ok", "okay", "do it", "handle this", "same as before"}:
            base += 0.2
        return min(1.0, base)

    def _extract_entities(self, text: str) -> list[str]:
        entities: list[str] = []
        if self._spacy_nlp is not None:
            try:
                doc = self._spacy_nlp(text)
                for ent in doc.ents:
                    value = ent.text.strip()
                    if not value:
                        continue
                    if ent.label_ in {"PERSON", "ORG", "GPE", "MONEY", "DATE", "TIME", "EVENT", "PRODUCT"}:
                        entities.append(value)
            except Exception:
                pass
        for match in re.finditer(r"\b([A-Z][a-zA-Z0-9_]{1,30})\b", text):
            entities.append(match.group(1))
        for match in re.finditer(r"(?<!\w)([+-]?\d+(?:\.\d+)?)(?!\w)", text):
            entities.append(match.group(1))
        accounts = re.findall(
            r"\b(?:" + "|".join(re.escape(k) for k in BANK_KEYWORDS[:10]) + r")\b",
            text.lower(),
        )
        entities.extend(item.title() for item in accounts)
        deduped: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            key = entity.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(entity)
        return deduped

    @staticmethod
    def _detect_language(text: str) -> str:
        # Check for Devanagari script (Hindi)
        if re.search(r"[\u0900-\u097F]", text):
            return "hi"
        if re.search(r"[a-zA-Z]", text):
            return "en"
        return "unknown"
