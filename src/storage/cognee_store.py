"""Cognee integration for advanced graph memory and knowledge graph operations."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CogneeStore:
    """Cognee-based graph memory store with advanced relationship reasoning."""

    def __init__(self, sqlite_store: Any) -> None:
        """Initialize Cognee store with fallback to SQLite graph store."""
        self.sqlite_store = sqlite_store
        self._cognee_available = False
        self._cognee_client: Any = None
        self._initialize_cognee()

    def _initialize_cognee(self) -> None:
        """Try to initialize Cognee, fallback to SQLite if unavailable."""
        try:
            # Try importing Cognee
            from cognee import Cognee
            from cognee.infrastructure.databases.vector import get_vector_engine
            from cognee.infrastructure.databases.graph import get_graph_engine

            self._cognee_client = Cognee()
            self._cognee_available = True
            logger.info("Cognee initialized successfully")
        except ImportError:
            logger.warning(
                "Cognee not available. Install with: pip install cognee. "
                "Falling back to SQLite graph store."
            )
            self._cognee_available = False
        except Exception as e:
            logger.warning("Cognee initialization failed: %s. Using SQLite fallback.", e)
            self._cognee_available = False

    async def add_relationship(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add relationship to graph with Cognee or SQLite fallback."""
        if self._cognee_available and self._cognee_client:
            try:
                await self._cognee_client.add(
                    data=f"{source} {relation} {target}",
                    dataset_id="tapan_ai",
                    metadata=metadata or {},
                )
                # Also create explicit relationship
                await self._cognee_client.primitives.add_relationship(
                    source_node=source,
                    target_node=target,
                    relationship_type=relation,
                    weight=weight,
                )
                return
            except Exception as e:
                logger.warning("Cognee add_relationship failed: %s. Using SQLite fallback.", e)

        # Fallback to SQLite
        from src.storage.graph_store import GraphStore
        graph_store = GraphStore(self.sqlite_store)
        await graph_store.add_relationship(source, target, relation, weight)

    async def find_related(
        self,
        entity: str,
        relation_type: str | None = None,  # Reserved for future filtering
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find related entities using Cognee graph completion or SQLite fallback."""
        if self._cognee_available and self._cognee_client:
            try:
                # Use Cognee's graph completion
                results = await self._cognee_client.search(
                    query=f"entities related to {entity}",
                    dataset_id="tapan_ai",
                    top_k=limit,
                )
                # Transform Cognee results to our format
                relationships = []
                for result in results:
                    relationships.append({
                        "source": entity,
                        "target": result.get("node", ""),
                        "relation": result.get("relationship", "related_to"),
                        "weight": result.get("weight", 1.0),
                        "score": result.get("score", 0.0),
                    })
                return relationships
            except Exception as e:
                logger.warning("Cognee find_related failed: %s. Using SQLite fallback.", e)

        # Fallback to SQLite
        from src.storage.graph_store import GraphStore
        graph_store = GraphStore(self.sqlite_store)
        return await graph_store.find_related(entity, limit)

    async def add_knowledge(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add knowledge to Cognee knowledge graph."""
        if self._cognee_available and self._cognee_client:
            try:
                result = await self._cognee_client.add(
                    data=text,
                    dataset_id="tapan_ai",
                    metadata=metadata or {},
                )
                return str(result.get("id", ""))
            except Exception as e:
                logger.warning("Cognee add_knowledge failed: %s", e)

        return ""

    async def query_graph(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Query Cognee knowledge graph."""
        if self._cognee_available and self._cognee_client:
            try:
                results = await self._cognee_client.search(
                    query=query,
                    dataset_id="tapan_ai",
                    top_k=limit,
                )
                return results
            except Exception as e:
                logger.warning("Cognee query_graph failed: %s", e)

        return []

    @property
    def is_available(self) -> bool:
        """Check if Cognee is available."""
        return self._cognee_available
