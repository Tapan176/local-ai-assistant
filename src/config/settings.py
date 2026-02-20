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


class Settings(BaseModel):
    app_name: str = "TAPAN_AI v1"
    environment: str = Field(default="local", description="local|dev|prod")
    sqlite_path: str = "data/tapan_ai_v1.db"
    chroma_path: str = "data/chroma_v1"

    # ── LLM (fully local via Ollama/BitNet) ────────────────────────────────
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "qwen2.5:7b"
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

    # ── Intent classifier ───────────────────────────────────────────
    intent_classifier: str = Field(
        default="hybrid", description="hybrid|semantic|heuristic"
    )
    semantic_intent_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    semantic_intent_threshold: float = Field(default=0.62, ge=0.0, le=1.0)

    # ── NLP ─────────────────────────────────────────────────────────
    spacy_model: str = "en_core_web_sm"

    @classmethod
    def from_env(cls) -> "Settings":
        data = {
            "app_name": os.getenv("TAPAN_APP_NAME", "TAPAN_AI v1"),
            "environment": os.getenv("TAPAN_ENV", "local"),
            "sqlite_path": os.getenv("TAPAN_SQLITE_PATH", "data/tapan_ai_v1.db"),
            "chroma_path": os.getenv("TAPAN_CHROMA_PATH", "data/chroma_v1"),
            "llm_provider": os.getenv("TAPAN_LLM_PROVIDER", "ollama"),
            "ollama_url": os.getenv(
                "TAPAN_OLLAMA_URL", "http://localhost:11434/api/chat"
            ),
            "ollama_model": os.getenv("TAPAN_OLLAMA_MODEL", "qwen2.5:14b"),
            "ollama_timeout": int(os.getenv("TAPAN_OLLAMA_TIMEOUT", "30")),
            "ollama_embed_model": os.getenv(
                "TAPAN_OLLAMA_EMBED_MODEL", "nomic-embed-text"
            ),
            "bitnet_url": os.getenv("TAPAN_BITNET_URL", "http://localhost:8001"),
            "bitnet_model": os.getenv("TAPAN_BITNET_MODEL", "bitnet-7b"),
            "bitnet_timeout": int(os.getenv("TAPAN_BITNET_TIMEOUT", "60")),
            "bitnet_enabled": os.getenv("TAPAN_BITNET_ENABLED", "false").lower() == "true",
            "bitnet_mode": os.getenv("TAPAN_BITNET_MODE", "auto"),
            "bitnet_cpp_executable": os.getenv("TAPAN_BITNET_CPP_EXECUTABLE", ""),
            "bitnet_cpp_model_path": os.getenv("TAPAN_BITNET_CPP_MODEL_PATH", ""),
            "bitnet_cpp_max_tokens": int(os.getenv("TAPAN_BITNET_CPP_MAX_TOKENS", "256")),
            "bitnet_cpp_threads": int(os.getenv("TAPAN_BITNET_CPP_THREADS", "0")),
            "bitnet_cpp_ctx_size": int(os.getenv("TAPAN_BITNET_CPP_CTX_SIZE", "0")),
            "api_host": os.getenv("TAPAN_API_HOST", "127.0.0.1"),
            "api_port": int(os.getenv("TAPAN_API_PORT", "8000")),
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
        }

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
