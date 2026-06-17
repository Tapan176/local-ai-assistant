"""Wrapper around the Supermemory SDK for persona, episodic, and semantic memory."""

from __future__ import annotations

import logging
import re
from typing import Any

from supermemory import Supermemory

logger = logging.getLogger(__name__)


class SupermemoryStore:
    """Wrapper around the Supermemory SDK for persona, episodic, and semantic memory."""

    # container_tag must be alphanumeric with hyphens and underscores only (max 100 chars)
    _TAG_RE = re.compile(r"[^a-zA-Z0-9_-]")

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

    @classmethod
    def _sanitize_tag(cls, tag: str) -> str:
        """Sanitize container_tag to only allow alphanumeric, hyphens, underscores."""
        return cls._TAG_RE.sub("_", tag)[:100]

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, str | float | bool | list[str]]:
        """Ensure metadata values are only str, float, bool, or list[str] as required by the API."""
        if not metadata:
            return {}
        clean: dict[str, str | float | bool | list[str]] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, float, int, bool)):
                clean[key] = value if not isinstance(value, int) else float(value)
            elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                clean[key] = value
            else:
                # Convert anything else to string
                clean[key] = str(value)
        return clean

    async def add_memory(self, content: str, container_tag: str, metadata: dict[str, Any] | None = None) -> bool:
        """Add a new memory document to Supermemory using client.add()."""
        if not self._client:
            return False

        try:
            safe_tag = self._sanitize_tag(container_tag)
            safe_metadata = self._sanitize_metadata(metadata)
            self._client.add(
                content=content,
                container_tag=safe_tag,
                metadata=safe_metadata,
            )
            return True
        except Exception as e:
            logger.error("Supermemory add_memory failed: %s", e)
            return False

    async def update_memory(
        self, content: str, new_content: str, container_tag: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Update an existing memory in Supermemory by matching original content."""
        if not self._client:
            return False

        try:
            safe_tag = self._sanitize_tag(container_tag)
            safe_metadata = self._sanitize_metadata(metadata)
            self._client.memories.update_memory(
                content=content,
                new_content=new_content,
                container_tag=safe_tag,
                metadata=safe_metadata,
            )
            return True
        except Exception as e:
            logger.error("Supermemory update_memory failed: %s", e)
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
                    safe_tag = self._sanitize_tag(tag)
                    search_kwargs["categories_filter"] = [safe_tag]

            response = self._client.search.execute(**search_kwargs)
            results = getattr(response, "results", [])
            # Normalize results to list of dicts
            out: list[dict[str, Any]] = []
            for item in results:
                if isinstance(item, dict):
                    out.append(item)
                elif hasattr(item, "__dict__"):
                    out.append(vars(item))
                else:
                    out.append({"content": str(item), "score": 1.0})
            return out
        except Exception as e:
            logger.error("Supermemory search_memory failed: %s", e)
            return []
