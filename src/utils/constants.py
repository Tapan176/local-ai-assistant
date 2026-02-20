"""Shared constants and helpers — single source of truth for all modules."""

from __future__ import annotations

# ── Affirmation detection ───────────────────────────────────────────
AFFIRMATION_WORDS: frozenset[str] = frozenset({
    "yes", "yep", "yeah", "yup", "sure", "ok", "okay", "confirm",
    "confirmed", "haan", "ha", "theek", "thik", "sahi", "bilkul",
    "zaroor", "done", "proceed", "go ahead", "absolutely",
    "definitely", "of course", "right", "correct", "agreed",
})


def is_affirmation(text: str) -> bool:
    """Return True when *text* looks like an affirmative answer."""
    tokens = set(text.lower().split())
    return bool(tokens & AFFIRMATION_WORDS)


# ── Bank / financial-institution keywords ───────────────────────────
BANK_KEYWORDS: tuple[str, ...] = (
    "axis", "hdfc", "icici", "sbi", "kotak", "bob", "pnb", "canara",
    "union", "idbi", "yes bank", "indusind", "federal", "rbl",
    "bandhan", "paytm", "phonepe", "gpay", "google pay", "amazon pay",
    "bank of baroda", "bank of india", "central bank",
    "cash", "wallet", "savings", "current", "credit card",
)


# ── Emotional-state word sets ───────────────────────────────────────
EMOTIONAL_POSITIVE: frozenset[str] = frozenset({
    "happy", "glad", "great", "wonderful", "awesome", "fantastic",
    "excited", "love", "enjoy", "pleased", "grateful", "thankful",
    "amazing", "excellent", "brilliant", "superb", "delighted",
    "cheerful", "joyful", "optimistic",
})

EMOTIONAL_NEGATIVE: frozenset[str] = frozenset({
    "sad", "unhappy", "angry", "frustrated", "annoyed", "upset",
    "depressed", "miserable", "terrible", "awful", "horrible",
    "disappointed", "heartbroken", "lonely", "hopeless", "worried",
    "anxious", "nervous", "afraid", "scared",
})

EMOTIONAL_STRESS: frozenset[str] = frozenset({
    "stressed", "overwhelmed", "burned out", "burnout", "exhausted",
    "tired", "drained", "overloaded", "pressured", "tense",
    "panicked", "frantic",
})
