"""Smoke tests for import, instantiation, and basic logic of core modules."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


# Ensure the project root is on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_imports():
    """All major modules should import without error."""
    modules = [
        "src.models",
        "src.config.settings",
        "src.utils.constants",
        "src.utils.date_time_parser",
        "src.storage.sqlite_store",
        "src.storage.vector_store",
        "src.storage.graph_store",
        "src.memory.semantic_memory",
        "src.memory.persona_memory",
        "src.llm.llm_dispatcher",
        "src.llm.semantic_intent_classifier",
        "src.core.emotional_engine",
        "src.core.perception_engine",
        "src.core.reasoning_engine",
        "src.core.planning_engine",
        "src.core.output_sanitizer",
        "src.core.proactive_engine",
        "src.core.orchestrator",
        "src.tools.finance_tool",
        "src.tools.calendar_tool",
        "src.tools.reminder_tool",
        "src.tools.people_tool",
        "src.tools.tool_registry",
    ]
    for module_name in modules:
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Failed to import {module_name}"


def test_settings_defaults():
    """Settings should load with sane defaults (may be overridden by .env)."""
    from src.config.settings import Settings

    settings = Settings.from_env()
    # Provider should be 'ollama' unless overridden by env
    assert settings.llm_provider in {"ollama", "mock"}, f"Unexpected provider: {settings.llm_provider}"
    assert "ollama" in settings.ollama_url or "localhost" in settings.ollama_url
    assert settings.ollama_model is not None and len(settings.ollama_model) > 0


def test_output_sanitizer():
    """Output sanitizer should strip leaks and detect echoes."""
    from src.core.output_sanitizer import OutputSanitizer

    sanitizer = OutputSanitizer()

    # Basic leak removal
    out = sanitizer.sanitize("Here's my reasoning based on system prompt data")
    assert "system prompt" not in out.lower()

    # JSON extraction
    out = sanitizer.sanitize('{"response": "Hello there"}')
    assert out == "Hello there"

    # Echo detection
    user = "I want to order some coffee today"
    echo = "I want to order some coffee today"
    out = sanitizer.sanitize(echo, user_text=user)
    assert "coffee" not in out.lower()

    # Non-echo should pass through
    normal = "Sure, I can help with your coffee order!"
    out = sanitizer.sanitize(normal, user_text=user)
    assert "coffee" in out.lower()


def test_no_deprecated_utcnow():
    """No source file should use deprecated datetime.utcnow()."""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    violations: list[str] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if "datetime.utcnow" in text:
            violations.append(str(py_file.relative_to(src_dir)))
    assert not violations, f"datetime.utcnow found in: {violations}"


def test_constants_exist():
    """Shared constants should be populated."""
    from src.utils.constants import (
        AFFIRMATION_WORDS,
        BANK_KEYWORDS,
        EMOTIONAL_NEGATIVE,
        EMOTIONAL_POSITIVE,
        EMOTIONAL_STRESS,
        is_affirmation,
    )

    assert len(AFFIRMATION_WORDS) > 5
    assert len(BANK_KEYWORDS) > 3
    assert len(EMOTIONAL_POSITIVE) > 3
    assert len(EMOTIONAL_NEGATIVE) > 3
    assert len(EMOTIONAL_STRESS) > 3
    assert is_affirmation("yes")
    assert is_affirmation("haan")
    assert not is_affirmation("banana")


def test_date_parser_basic():
    """Date parser should handle relative phrases."""
    from src.utils.date_time_parser import RelativeDateTimeParser

    parser = RelativeDateTimeParser()
    result, parsed = parser.parse("tomorrow at 5 pm")
    assert result is not None
    assert parsed is True
    assert result.hour == 17


def test_emotional_engine_basic():
    """EmotionalEngine should return a non-empty state."""
    from src.core.emotional_engine import EmotionalEngine

    engine = EmotionalEngine()
    result = asyncio.run(engine.analyze("I am so happy today, really feeling great!"))
    assert result.state in {"positive", "negative", "neutral", "stressed"}
    assert result.intensity >= 0.0


def test_intent_prototypes_yaml_loadable():
    """Intent prototypes YAML file should be loadable."""
    import yaml  # type: ignore

    config_path = Path(__file__).resolve().parent.parent / "src" / "config" / "intent_prototypes.yaml"
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert len(data) > 0, "YAML file is empty"
    # Check at least one expected key is present
    assert any(
        key in data for key in ["general_conversation", "emotional_support", "financial_update"]
    ), f"Missing expected keys. Got: {list(data.keys())}"


def test_orchestrator_multi_step_verification_flow():
    """Orchestrator should execute a multi-step tool plan with verification metadata."""
    from src.config.settings import Settings
    from src.main import build_runtime

    async def _run():
        settings = Settings.from_env()
        settings.llm_provider = "mock"
        settings.sqlite_path = ":memory:"

        runtime = await build_runtime(settings=settings)
        response = await runtime.orchestrator.handle_user_input(
            "smoke_multi_step",
            "create account savings with 1000 and show accounts",
        )

        assert response.action_type == "tool"
        assert response.tool_used == "finance_tool"
        assert "Step 1:" in response.text
        assert "verification" in response.debug
        assert isinstance(response.debug["verification"], list)
        assert len(response.debug["verification"]) >= 1

    asyncio.run(_run())


def test_orchestrator_error_recovery_clarifies_missing_amount():
    """Orchestrator should recover or clarify when tool execution fails."""
    from src.config.settings import Settings
    from src.main import build_runtime

    async def _run():
        settings = Settings.from_env()
        settings.llm_provider = "mock"
        settings.sqlite_path = ":memory:"

        runtime = await build_runtime(settings=settings)
        response = await runtime.orchestrator.handle_user_input(
            "smoke_recovery",
            "transfer from savings to wallet",
        )

        assert response.action_type == "tool"
        assert response.tool_used == "finance_tool"
        assert "amount" in response.text.lower()
        assert "recovery" in response.debug
        assert isinstance(response.debug["recovery"], list)
        assert len(response.debug["recovery"]) >= 1

    asyncio.run(_run())
