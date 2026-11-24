"""Environment-driven settings and structured logging for TAPAN_AI v2."""

from __future__ import annotations

import json
import logging
import os
import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()                       # auto-load .env from project root
except ImportError:                     # pragma: no cover
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    app_name: str = "TAPAN_AI v1"
    environment: str = Field(default="local", description="local|dev|prod")
    sqlite_path: str = "data/tapan_ai_v1.db"
    database_url: str = Field(
        default="",
        description="Postgres connection URI (e.g. Supabase 'Session pooler'). When set it replaces SQLite.",
    )
    chroma_path: str = "data/chroma_v1"

    # ── LLM Provider Chain: openrouter → ollama → bitnet → heuristic ────────
    llm_provider: str = "openrouter"
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "qwen3.5:9b"
    ollama_fallback_models: list[str] = Field(
        default=["llama3.2:3b", "phi3:mini"],
        description="Fallback Ollama models tried in order when primary fails",
    )
    ollama_timeout: int = Field(default=60, description="Seconds per model attempt")
    ollama_embed_model: str = "nomic-embed-text"
    
    # ── BitNet backend ────────────────────────────────────────────────────
    bitnet_url: str = Field(default="http://localhost:8001", description="BitNet service URL")
    bitnet_model: str = Field(default="bitnet-7b", description="BitNet model name")
    bitnet_timeout: int = Field(default=60, description="BitNet timeout in seconds")
    bitnet_enabled: bool = Field(default=False, description="Enable BitNet backend")
    bitnet_mode: str = Field(default="auto", description="auto|cpp|service")
    bitnet_cpp_executable: str = Field(default="", description="Path to bitnet.cpp executable")
    bitnet_cpp_model_path: str = Field(default="", description="Path to local GGUF model for bitnet.cpp")
    bitnet_cpp_max_tokens: int = Field(default=256, description="Max generation tokens for bitnet.cpp backend")
    bitnet_cpp_threads: int = Field(default=0, description="Thread count for bitnet.cpp (0=backend default)")
    bitnet_cpp_ctx_size: int = Field(default=0, description="Context window size for bitnet.cpp (0=backend default)")
    bitnet_cpp_extra_args: list[str] = Field(default_factory=list, description="Additional CLI args for bitnet.cpp")

    # ── API ─────────────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "WARNING"
    max_memory_items: int = 8
    stream_chunk_size: int = 18

    # ── OpenRouter (Primary Cloud LLM) ──────────────────────────────────
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_model: str = Field(
        default="anthropic/claude-haiku-5.5",
        description="Primary OpenRouter model (cheap, strong at tool calling)",
    )
    openrouter_fallback_model: str = Field(
        default="deepseek/deepseek-v4.1-flash",
        description="Fallback OpenRouter model (different vendor, cheaper)",
    )
    openrouter_timeout: int = Field(default=60, description="OpenRouter timeout in seconds")

    # ── Supermemory (Unified Memory) ────────────────────────────────────
    supermemory_api_key: str = Field(
        default="", description="API key for Supermemory.ai"
    )

    # ── OmniRoute (OpenAI-compatible LLM gateway) ──────────────────────
    omniroute_url: str = Field(
        default="http://localhost:20128/v1",
        description="OmniRoute base URL (the /v1 root, not the full completions path)",
    )
    omniroute_api_key: str = Field(default="", description="OmniRoute API key (Dashboard -> Endpoints)")
    omniroute_model: str = Field(default="auto", description="OmniRoute model or combo, e.g. auto, auto/fast")
    omniroute_timeout: int = Field(default=60, description="OmniRoute timeout in seconds")

    # ── Agent (Jarvis mode) ─────────────────────────────────────────
    agent_enabled: bool = Field(default=True, description="Use the tool-calling agent as the primary path")
    agent_max_steps: int = Field(default=6, ge=1, le=15, description="Max tool-call rounds per message")
    agent_history_turns: int = Field(default=16, ge=0, le=50, description="Recent turns sent to the LLM")
    assistant_name: str = Field(default="Tapan", description="Name the assistant answers to")
    user_name: str = Field(default="", description="Optional owner name used in the system prompt")
    home_location: str = Field(default="", description="Default city for weather/briefing, e.g. 'Mumbai'")
    timezone: str = Field(default="", description="IANA timezone, e.g. Asia/Kolkata (blank = system local)")
    enable_local_skills: bool | None = Field(
        default=None,
        description="Files/open-app skills. None = on for environment=local, off otherwise",
    )
    workspace_dir: str = Field(default="data/workspace", description="Sandbox folder for file skills")
    app_allowlist: dict[str, str] = Field(
        default_factory=lambda: {"notepad": "notepad", "calculator": "calc", "explorer": "explorer", "vscode": "code"},
        description="name -> executable the open_app skill may launch",
    )
    reminder_poll_seconds: int = Field(default=20, ge=5, description="How often due reminders are checked")
    telegram_bot_token: str = Field(default="", description="Telegram bot token (or paste it in Settings; stored server-side)")
    currency: str = Field(default="INR", description="ISO currency code used by the expense tracker (TAPAN_CURRENCY)")
    public_url: str = Field(default="", description="Public https address of this server (used to register the Telegram webhook)")
    push_enabled: bool = Field(default=True, description="Send Web Push notifications for reminders")
    vapid_private_key: str = Field(default="", description="Optional VAPID private key (base64url, 32 bytes). Blank = generated and stored in the database")
    vapid_subject: str = Field(default="", description="VAPID contact (https URL or mailto:), shared with push services. Blank = this site's URL")

    # ── API security ────────────────────────────────────────────────
    api_token: str = Field(default="", description="Bearer token required by the API when set (required in prod)")
    cors_origins: list[str] = Field(default_factory=list, description="Allowed cross-origin sites (none by default)")
    rate_limit_per_minute: int = Field(default=30, ge=1, description="Chat requests per minute per client")

    # ── Intent classifier ───────────────────────────────────────────
    intent_classifier: str = Field(
        default="hybrid", description="hybrid|semantic|heuristic"
    )
    semantic_intent_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    semantic_intent_threshold: float = Field(default=0.62, ge=0.0, le=1.0)

    # ── NLP ─────────────────────────────────────────────────────────
    spacy_model: str = "en_core_web_sm"

    @property
    def local_skills_enabled(self) -> bool:
        if self.enable_local_skills is not None:
            return self.enable_local_skills
        return self.environment.lower() == "local"

    @classmethod
    def from_env(cls) -> "Settings":
        data = {
            "app_name": os.getenv("TAPAN_APP_NAME", "TAPAN_AI v1"),
            "environment": os.getenv("TAPAN_ENV", "local"),
            "sqlite_path": os.getenv("TAPAN_SQLITE_PATH", "data/tapan_ai_v1.db"),
            "database_url": os.getenv("TAPAN_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
            "chroma_path": os.getenv("TAPAN_CHROMA_PATH", "data/chroma_v1"),
            "llm_provider": os.getenv("TAPAN_LLM_PROVIDER", "openrouter"),
            "ollama_url": os.getenv(
                "TAPAN_OLLAMA_URL", "http://localhost:11434/api/chat"
            ),
            "ollama_model": os.getenv("TAPAN_OLLAMA_MODEL", "qwen3.5:9b"),
            "ollama_timeout": int(os.getenv("TAPAN_OLLAMA_TIMEOUT", "30")),
            "ollama_embed_model": os.getenv(
                "TAPAN_OLLAMA_EMBED_MODEL", "nomic-embed-text"
            ),
            "bitnet_url": os.getenv("TAPAN_BITNET_URL", "http://localhost:8001"),
            "bitnet_model": os.getenv("TAPAN_BITNET_MODEL", "bitnet-7b"),
            "bitnet_timeout": int(os.getenv("TAPAN_BITNET_TIMEOUT", "60")),
            "bitnet_enabled": _env_bool("TAPAN_BITNET_ENABLED", False),
            "bitnet_mode": os.getenv("TAPAN_BITNET_MODE", "auto"),
            "bitnet_cpp_executable": os.getenv("TAPAN_BITNET_CPP_EXECUTABLE", ""),
            "bitnet_cpp_model_path": os.getenv("TAPAN_BITNET_CPP_MODEL_PATH", ""),
            "bitnet_cpp_max_tokens": int(os.getenv("TAPAN_BITNET_CPP_MAX_TOKENS", "256")),
            "bitnet_cpp_threads": int(os.getenv("TAPAN_BITNET_CPP_THREADS", "0")),
            "bitnet_cpp_ctx_size": int(os.getenv("TAPAN_BITNET_CPP_CTX_SIZE", "0")),
            "api_host": os.getenv("TAPAN_API_HOST", "127.0.0.1"),
            "api_port": int(os.getenv("TAPAN_API_PORT") or os.getenv("PORT") or "8000"),
            "log_level": os.getenv("TAPAN_LOG_LEVEL", "INFO"),
            "max_memory_items": int(
                os.getenv("TAPAN_MAX_MEMORY_ITEMS", "8")
            ),
            "stream_chunk_size": int(
                os.getenv("TAPAN_STREAM_CHUNK_SIZE", "18")
            ),
            "intent_classifier": os.getenv("TAPAN_INTENT_CLASSIFIER", "hybrid"),
            "semantic_intent_model": os.getenv(
                "TAPAN_SEMANTIC_INTENT_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            "semantic_intent_threshold": float(
                os.getenv("TAPAN_SEMANTIC_INTENT_THRESHOLD", "0.62")
            ),
            "spacy_model": os.getenv("TAPAN_SPACY_MODEL", "en_core_web_sm"),
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY") or os.getenv("openrouterKey") or "",
            "openrouter_url": os.getenv(
                "TAPAN_OPENROUTER_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            "openrouter_model": os.getenv(
                "TAPAN_OPENROUTER_MODEL", "anthropic/claude-haiku-5.5"
            ),
            "openrouter_fallback_model": os.getenv(
                "TAPAN_OPENROUTER_FALLBACK_MODEL", "deepseek/deepseek-v4.1-flash"
            ),
            "openrouter_timeout": int(os.getenv("TAPAN_OPENROUTER_TIMEOUT", "60")),
            "supermemory_api_key": os.getenv("TAPAN_SUPERMEMORY_API_KEY", ""),
            "omniroute_url": os.getenv("TAPAN_OMNIROUTE_URL", "http://localhost:20128/v1").rstrip("/"),
            "omniroute_api_key": os.getenv("OMNIROUTE_API_KEY", os.getenv("TAPAN_OMNIROUTE_API_KEY", "")),
            "omniroute_model": os.getenv("TAPAN_OMNIROUTE_MODEL", "auto"),
            "omniroute_timeout": int(os.getenv("TAPAN_OMNIROUTE_TIMEOUT", "60")),
            "agent_enabled": _env_bool("TAPAN_AGENT_ENABLED", True),
            "agent_max_steps": int(os.getenv("TAPAN_AGENT_MAX_STEPS", "6")),
            "agent_history_turns": int(os.getenv("TAPAN_AGENT_HISTORY_TURNS", "16")),
            "assistant_name": os.getenv("TAPAN_ASSISTANT_NAME", "Tapan"),
            "user_name": os.getenv("TAPAN_USER_NAME", ""),
            "home_location": os.getenv("TAPAN_HOME_LOCATION", ""),
            "timezone": os.getenv("TAPAN_TIMEZONE", ""),
            "workspace_dir": os.getenv("TAPAN_WORKSPACE_DIR", "data/workspace"),
            "reminder_poll_seconds": int(os.getenv("TAPAN_REMINDER_POLL_SECONDS", "20")),
            "push_enabled": _env_bool("TAPAN_PUSH_ENABLED", True),
            "telegram_bot_token": os.getenv("TAPAN_TELEGRAM_BOT_TOKEN", ""),
            "currency": os.getenv("TAPAN_CURRENCY", "INR").strip().upper()[:3] or "INR",
            "public_url": os.getenv("TAPAN_PUBLIC_URL", "").rstrip("/"),
            "vapid_private_key": os.getenv("TAPAN_VAPID_PRIVATE_KEY", ""),
            "vapid_subject": os.getenv("TAPAN_VAPID_SUBJECT", ""),
            "api_token": os.getenv("TAPAN_API_TOKEN", ""),
            "rate_limit_per_minute": int(os.getenv("TAPAN_RATE_LIMIT_PER_MINUTE", "30")),
            "cors_origins": [o.strip() for o in os.getenv("TAPAN_CORS_ORIGINS", "").split(",") if o.strip()],
        }
        if os.getenv("TAPAN_ENABLE_LOCAL_SKILLS"):
            data["enable_local_skills"] = _env_bool("TAPAN_ENABLE_LOCAL_SKILLS", False)
        apps = os.getenv("TAPAN_APP_ALLOWLIST", "").strip()
        if apps:  # "name=exe,name2=exe2"
            data["app_allowlist"] = dict(
                pair.split("=", 1) for pair in (a.strip() for a in apps.split(",")) if "=" in pair
            )

        # Parse fallback models from comma-separated env var
        fb = os.getenv("TAPAN_OLLAMA_FALLBACK_MODELS", "")
        if fb:
            data["ollama_fallback_models"] = [
                m.strip() for m in fb.split(",") if m.strip()
            ]
        cpp_args = os.getenv("TAPAN_BITNET_CPP_EXTRA_ARGS", "").strip()
        if cpp_args:
            data["bitnet_cpp_extra_args"] = shlex.split(cpp_args)

        return cls(**data)

    def ensure_paths(self) -> None:
        if not self.database_url:
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }
        if hasattr(record, "event"):
            payload["event"] = getattr(record, "event")
        if hasattr(record, "context"):
            payload["context"] = getattr(record, "context")
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_paths()
    configure_logging(settings.log_level)
    return settings
