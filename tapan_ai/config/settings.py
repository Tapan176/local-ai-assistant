"""Environment-driven settings and structured logging for TAPAN_AI v2."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "TAPAN_AI v2"
    environment: str = Field(default="local", description="local|dev|prod")
    sqlite_path: str = "data/tapan_ai_v2.db"
    chroma_path: str = "data/chroma_v2"
    llm_provider: str = "mock"
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "llama3.1:8b"
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    max_memory_items: int = 8
    stream_chunk_size: int = 18

    @classmethod
    def from_env(cls) -> "Settings":
        data = {
            "app_name": os.getenv("TAPAN_APP_NAME", "TAPAN_AI v2"),
            "environment": os.getenv("TAPAN_ENV", "local"),
            "sqlite_path": os.getenv("TAPAN_SQLITE_PATH", "data/tapan_ai_v2.db"),
            "chroma_path": os.getenv("TAPAN_CHROMA_PATH", "data/chroma_v2"),
            "llm_provider": os.getenv("TAPAN_LLM_PROVIDER", "mock"),
            "ollama_url": os.getenv("TAPAN_OLLAMA_URL", "http://localhost:11434/api/chat"),
            "ollama_model": os.getenv("TAPAN_OLLAMA_MODEL", "llama3.1:8b"),
            "openai_model": os.getenv("TAPAN_OPENAI_MODEL", "gpt-4o-mini"),
            "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
            "api_host": os.getenv("TAPAN_API_HOST", "127.0.0.1"),
            "api_port": int(os.getenv("TAPAN_API_PORT", "8000")),
            "log_level": os.getenv("TAPAN_LOG_LEVEL", "INFO"),
            "max_memory_items": int(os.getenv("TAPAN_MAX_MEMORY_ITEMS", "8")),
            "stream_chunk_size": int(os.getenv("TAPAN_STREAM_CHUNK_SIZE", "18")),
        }
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

