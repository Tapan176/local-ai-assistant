"""Automatic multi-source memory retrieval."""

from __future__ import annotations

from src.models import MemoryContext
from src.storage.graph_store import GraphStore

from .episodic_memory import EpisodicMemory
from .persona_memory import PersonaMemory
from .semantic_memory import SemanticMemory


class MemoryRetriever:
    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        persona_memory: PersonaMemory,
        graph_store: GraphStore,
        max_items: int = 8,
    ) -> None:
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.persona_memory = persona_memory
        self.graph_store = graph_store
        self.max_items = max_items

    async def retrieve(self, session_id: str, user_text: str, entities: list[str]) -> MemoryContext:
        episodic = await self.episodic_memory.recent(session_id, limit=self.max_items)
        semantic = await self.semantic_memory.retrieve(user_text, limit=self.max_items)
        persona = await self.persona_memory.get_profile()

        relations: list[dict] = []
        for entity in entities[:4]:
            relations.extend(await self.graph_store.find_related(entity, limit=3))

        return MemoryContext(
            episodic_memories=episodic,
            semantic_memories=semantic,
            persona_profile=persona,
            relationship_graph=relations,
        )

