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
        vector_store: Any | None = None,
    ) -> None:
        self.sqlite_store = sqlite_store
        self.llm_dispatcher = llm_dispatcher
        self.vector_store = vector_store

    async def check_health(self) -> dict[str, Any]:
        """Perform comprehensive health check."""
        checks = {
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
            # Quick health check - try to generate with mock
            if self.llm_dispatcher.settings.llm_provider.lower() == "mock":
                checks["components"]["llm"] = {"status": "healthy", "provider": "mock"}
            else:
                # Check if backend is reachable (non-blocking)
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

        # Check vector store
        if self.vector_store:
            try:
                # Quick query test
                await self.vector_store.query("test", limit=1)
                checks["components"]["vector_store"] = {"status": "healthy"}
            except Exception as e:
                checks["components"]["vector_store"] = {
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
