"""Health check endpoints and monitoring for TAPAN_AI services."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class HealthChecker:
    """Health check service for system components."""

    def __init__(
        self,
        sqlite_store: Any,
        llm_dispatcher: Any,
        supermemory_store: Any | None = None,
    ) -> None:
        self.sqlite_store = sqlite_store
        self.llm_dispatcher = llm_dispatcher
        self.supermemory_store = supermemory_store

    async def check_health(self) -> dict[str, Any]:
        """Perform comprehensive health check."""
        checks: dict[str, Any] = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }

        # Check SQLite
        try:
            await self.sqlite_store.fetchone("SELECT 1")
            checks["components"]["database"] = {"status": "healthy"}
        except Exception as e:
            checks["components"]["database"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            checks["status"] = "degraded"

        # Check LLM backend
        try:
            if self.llm_dispatcher.settings.llm_provider.lower() == "mock":
                checks["components"]["llm"] = {"status": "healthy", "provider": "mock"}
            else:
                checks["components"]["llm"] = {
                    "status": "healthy",
                    "provider": self.llm_dispatcher.settings.llm_provider,
                }
        except Exception as e:
            checks["components"]["llm"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            checks["status"] = "degraded"

        # Check Supermemory
        if self.supermemory_store:
            try:
                await self.supermemory_store.search_memory("health_check_ping")
                checks["components"]["supermemory"] = {"status": "healthy"}
            except Exception as e:
                checks["components"]["supermemory"] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                checks["status"] = "degraded"

        return checks

    async def check_readiness(self) -> dict[str, bool]:
        """Check if system is ready to accept requests."""
        readiness = {
            "database": False,
            "llm": False,
        }

        try:
            await self.sqlite_store.fetchone("SELECT 1")
            readiness["database"] = True
        except Exception:
            pass

        try:
            # LLM is ready if dispatcher is initialized
            readiness["llm"] = self.llm_dispatcher is not None
        except Exception:
            pass

        return readiness
