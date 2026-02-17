"""Emotional state analysis component."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class EmotionAnalysis:
    state: str
    intensity: float
    confidence: float


class EmotionalEngine:
    POSITIVE = {"good", "great", "happy", "excited", "relieved", "awesome", "love"}
    NEGATIVE = {"sad", "tired", "bad", "upset", "angry", "hurt", "frustrated"}
    STRESS = {"stressed", "anxious", "overwhelmed", "panic", "worried", "burnt"}

    async def analyze(self, text: str, baseline: str = "neutral") -> EmotionAnalysis:
        lowered = text.lower()
        tokens = set(re.findall(r"[a-zA-Z']+", lowered))
        pos_hits = len(tokens & self.POSITIVE)
        neg_hits = len(tokens & self.NEGATIVE)
        stress_hits = len(tokens & self.STRESS)
        punctuation_boost = min(0.25, text.count("!") * 0.05 + text.count("?") * 0.03)

        if stress_hits > 0:
            intensity = min(1.0, 0.45 + 0.12 * stress_hits + punctuation_boost)
            return EmotionAnalysis("stressed", intensity, confidence=0.85)
        if neg_hits > pos_hits:
            intensity = min(1.0, 0.35 + 0.1 * neg_hits + punctuation_boost)
            return EmotionAnalysis("sad", intensity, confidence=0.78)
        if pos_hits > 0:
            intensity = min(1.0, 0.3 + 0.1 * pos_hits + punctuation_boost)
            return EmotionAnalysis("positive", intensity, confidence=0.76)

        baseline_state = baseline if baseline in {"neutral", "positive", "sad", "stressed"} else "neutral"
        return EmotionAnalysis(baseline_state, intensity=0.2, confidence=0.55)

