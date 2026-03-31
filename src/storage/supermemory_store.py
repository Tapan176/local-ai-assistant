"""Wrapper around the Supermemory SDK for persona, episodic, and semantic memory."""

from __future__ import annotations

import logging
from typing import Any

from supermemory import Supermemory

logger = logging.getLogger(__name__)


class SupermemoryStore:
    """Wrapper around the Supermemory SDK for persona, episodic, and semantic memory."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client: Supermemory | None = None
        if self.api_key:
            try:
                self._client = Supermemory(api_key=self.api_key)
                logger.info("Supermemory client initialized successfully.")
            except Exception as e:
                logger.error("Failed to initialize Supermemory client: %s", e)
        else:
            logger.warning("No Supermemory API key provided. Memory operations will be no-ops.")

    async def add_memory(self, content: str, container_tag: str, metadata: dict[str, Any] | None = None) -> bool:
        """Add a memory to Supermemory using update_memory (upsert)."""
        if not self._client:
            return False

        try:
            self._client.memories.update_memory(
                new_content=content,
                container_tag=container_tag,
                metadata=metadata or {},
            )
            return True
        except Exception as e:
            logger.error("Supermemory add_memory failed: %s", e)
            return False

    async def search_memory(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Search Supermemory."""
        if not self._client:
            return []

        try:
            search_kwargs: dict[str, Any] = {"q": query}
            if filters:
                tag = filters.get("container_tag")
                if tag:
                    search_kwargs["categories_filter"] = [tag]

            response = self._client.search.execute(**search_kwargs)
            return getattr(response, "results", [])
        except Exception as e:
            logger.error("Supermemory search_memory failed: %s", e)
            return []
