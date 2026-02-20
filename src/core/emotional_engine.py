"""Emotional state analysis component."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.constants import EMOTIONAL_NEGATIVE, EMOTIONAL_POSITIVE, EMOTIONAL_STRESS


@dataclass(slots=True)
class EmotionAnalysis:
    state: str
    intensity: float
    confidence: float


class EmotionalEngine:
    def __init__(self) -> None:
        self._vader = None
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            self._vader = SentimentIntensityAnalyzer()
        except Exception:
            self._vader = None

    async def analyze(self, text: str, baseline: str = "neutral") -> EmotionAnalysis:
        lowered = text.lower()
        tokens = set(re.findall(r"[a-zA-Z']+", lowered))
        pos_hits = len(tokens & EMOTIONAL_POSITIVE)
        neg_hits = len(tokens & EMOTIONAL_NEGATIVE)
        stress_hits = len(tokens & EMOTIONAL_STRESS)
        punctuation_boost = min(0.25, text.count("!") * 0.05 + text.count("?") * 0.03)
        vader_compound = 0.0
        if self._vader is not None:
            try:
                vader_compound = float(self._vader.polarity_scores(text).get("compound", 0.0))
            except Exception:
                vader_compound = 0.0

        if stress_hits > 0:
            intensity = min(1.0, 0.45 + 0.12 * stress_hits + punctuation_boost)
            return EmotionAnalysis("stressed", intensity, confidence=0.85)
        if vader_compound <= -0.45:
            intensity = min(1.0, 0.35 + abs(vader_compound) * 0.45 + punctuation_boost)
            return EmotionAnalysis("negative", intensity, confidence=0.82)
        if vader_compound >= 0.45:
            intensity = min(1.0, 0.3 + abs(vader_compound) * 0.4 + punctuation_boost)
            return EmotionAnalysis("positive", intensity, confidence=0.8)
        if neg_hits > pos_hits:
            intensity = min(1.0, 0.35 + 0.1 * neg_hits + punctuation_boost)
            return EmotionAnalysis("negative", intensity, confidence=0.78)
        if pos_hits > 0:
            intensity = min(1.0, 0.3 + 0.1 * pos_hits + punctuation_boost)
            return EmotionAnalysis("positive", intensity, confidence=0.76)

        baseline_state = baseline if baseline in {"neutral", "positive", "negative", "stressed"} else "neutral"
        if baseline_state != "neutral" and len(tokens) <= 3:
            return EmotionAnalysis(baseline_state, intensity=0.22, confidence=0.5)
        return EmotionAnalysis("neutral", intensity=0.18, confidence=0.55)
