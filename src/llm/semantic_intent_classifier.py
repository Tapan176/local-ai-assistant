"""Semantic intent classifier powered by sentence-transformers (data-driven)."""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SemanticIntentMatch:
    intent: str
    confidence: float
    rationale: str


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "intent_prototypes.yaml"


class SemanticIntentClassifier:
    """Maps natural language to intent clusters using embedding similarity."""

    def __init__(self, model_name: str, threshold: float = 0.62) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self._model: Any = None
        self._intent_vectors: dict[str, list[float]] = {}
        self._load()

    @property
    def enabled(self) -> bool:
        return self._model is not None and bool(self._intent_vectors)

    def classify(self, text: str) -> SemanticIntentMatch | None:
        if not self.enabled:
            return None
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return None

        try:
            vector = self._to_float_list(self._model.encode([cleaned], normalize_embeddings=True)[0])
        except Exception:
            return None

        best_intent = ""
        best_score = -1.0
        for intent, centroid in self._intent_vectors.items():
            score = self._dot(vector, centroid)
            if score > best_score:
                best_score = score
                best_intent = intent

        if not best_intent:
            return None

        confidence = max(0.0, min(1.0, (best_score + 1.0) / 2.0))
        if confidence < self.threshold:
            return None

        return SemanticIntentMatch(
            intent=best_intent,
            confidence=round(confidence, 2),
            rationale=f"Semantic classifier matched intent '{best_intent}' (score={best_score:.2f}).",
        )

    def _load_prototypes(self) -> dict[str, list[str]]:
        """Load intent prototypes from YAML config file."""
        if _CONFIG_PATH.exists():
            try:
                with open(_CONFIG_PATH, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    logger.info("Loaded intent prototypes from %s", _CONFIG_PATH.name)
                    return data
            except Exception as exc:
                logger.warning("Failed to load %s: %s, using built-in defaults", _CONFIG_PATH, exc)

        # Built-in fallback prototypes
        return {
            "financial_update": [
                "update my account balance",
                "add money to a bank account",
                "show all my account balances",
            ],
            "reminder_management": [
                "set a reminder for me",
                "show my pending reminders",
                "don't let me forget something later",
            ],
            "calendar_management": [
                "schedule an event on my calendar",
                "show upcoming meetings",
            ],
            "people_memory_update": [
                "remember this person and relationship",
                "who is this person in my contacts",
            ],
            "emotional_support": [
                "i feel stressed and need support",
                "i am anxious and overwhelmed",
            ],
            "self_data_request": [
                "show all data you have about me",
                "what do you know about me",
            ],
            "next_step_guidance": [
                "what should i do next",
                "what is the next step",
            ],
            "social_greeting": [
                "hey how are you",
                "hello",
                "hi there",
            ],
        }

    def _load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception:
            return

        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception:
            self._model = None
            return

        prototypes = self._load_prototypes()

        texts: list[str] = []
        owners: list[str] = []
        for intent, examples in prototypes.items():
            for example in examples:
                texts.append(example)
                owners.append(intent)

        try:
            vectors = self._model.encode(texts, normalize_embeddings=True)
        except Exception:
            self._model = None
            return

        grouped: dict[str, list[list[float]]] = {}
        for idx, intent in enumerate(owners):
            grouped.setdefault(intent, []).append(self._to_float_list(vectors[idx]))

        centroids: dict[str, list[float]] = {}
        for intent, items in grouped.items():
            centroids[intent] = self._normalize(self._mean(items))
        self._intent_vectors = centroids

    @staticmethod
    def _to_float_list(values: Any) -> list[float]:
        return [float(item) for item in values]

    @staticmethod
    def _mean(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []
        size = len(vectors[0])
        totals = [0.0] * size
        for vector in vectors:
            for idx, value in enumerate(vector):
                totals[idx] += value
        return [value / len(vectors) for value in totals]

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        if not vector:
            return vector
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0.0:
            return vector
        return [value / norm for value in vector]

    @staticmethod
    def _dot(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        return sum(left[i] * right[i] for i in range(size))
