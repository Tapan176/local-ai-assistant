"""Automatic multi-source memory retrieval."""

from __future__ import annotations

from src.models import MemoryContext
from src.storage.supermemory_store import SupermemoryStore

from .episodic_memory import EpisodicMemory
from .persona_memory import PersonaMemory
from .semantic_memory import SemanticMemory


class MemoryRetriever:
    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        persona_memory: PersonaMemory,
        supermemory_store: SupermemoryStore,
        max_items: int = 8,
    ) -> None:
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.persona_memory = persona_memory
        self.supermemory = supermemory_store
        self.max_items = max_items

    async def retrieve(self, session_id: str, user_text: str, entities: list[str]) -> MemoryContext:
        episodic = await self.episodic_memory.recent(session_id, limit=self.max_items)
        semantic = await self.semantic_memory.retrieve(user_text, limit=self.max_items)
        persona = await self.persona_memory.get_profile()

        relations: list[dict] = []
        for entity in entities[:4]:
            results = await self.supermemory.search_memory(
                query=entity, filters={"container_tag": "relationships"}
            )
            for res in results:
                if isinstance(res, dict):
                    relations.append(res)
                else:
                    relations.append({"entity": entity, "info": str(res)})

        return MemoryContext(
            episodic_memories=episodic,
            semantic_memories=semantic,
            persona_profile=persona,
            relationship_graph=relations[:self.max_items],
        )

