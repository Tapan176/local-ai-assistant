from src.agent.companion_prompt import build_companion_context


def test_build_companion_context_includes_persona_and_tone_guidance():
    ctx = build_companion_context(
        "BASE",
        sentiment_label="stressed",
        recent_history="User: I'm overwhelmed",
        memories=[{"text": "User prefers evening workout"}],
    )

    assert "PERSONA:" in ctx
    assert "emotionally low or stressed" in ctx
    assert "RECENT_CHAT:" in ctx
    assert "RELEVANT_LONG_TERM_MEMORY" in ctx
    assert "SYSTEM_CONTEXT:\nBASE" in ctx


def test_build_companion_context_handles_empty_optional_sections():
    ctx = build_companion_context("", sentiment_label="neutral")

    assert "PERSONA:" in ctx
    assert "TONE_GUIDANCE:" in ctx
    assert "RECENT_CHAT:" not in ctx
    assert "RELEVANT_LONG_TERM_MEMORY" not in ctx
    assert "SYSTEM_CONTEXT:" not in ctx
