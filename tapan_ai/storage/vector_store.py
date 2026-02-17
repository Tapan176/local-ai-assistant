"""Vector store abstractions (Chroma preferred, in-memory fallback)."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime
from typing import Any, Protocol

from tapan_ai.config.settings import Settings


class BaseVectorStore(Protocol):
    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        ...

    async def query(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        ...


def _hash_embedding(text: str, dim: int = 128) -> list[float]:
    vec = [0.0] * dim
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    if not tokens:
        return vec
    for token in tokens:
        idx = abs(hash(token)) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._docs[doc_id] = {
            "id": doc_id,
            "text": text,
            "metadata": metadata,
            "embedding": _hash_embedding(text),
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def query(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        query_emb = _hash_embedding(text)
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self._docs.values():
            score = _cosine(query_emb, doc["embedding"])
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, doc in scored[:limit]:
            out.append(
                {
                    "id": doc["id"],
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "score": float(score),
                }
            )
        return out


class _HashEmbeddingFn:
    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [_hash_embedding(text) for text in input]


class ChromaVectorStore:
    def __init__(self, persist_path: str, collection_name: str = "tapan_ai_memory") -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=persist_path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=_HashEmbeddingFn(),
        )

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._collection.upsert,
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
        )

    async def query(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(
            self._collection.query,
            query_texts=[text],
            n_results=limit,
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        out: list[dict[str, Any]] = []
        for idx, doc_id in enumerate(ids):
            distance = float(distances[idx]) if idx < len(distances) else 1.0
            out.append(
                {
                    "id": doc_id,
                    "text": docs[idx] if idx < len(docs) else "",
                    "metadata": metas[idx] if idx < len(metas) else {},
                    "score": max(0.0, 1.0 - distance),
                }
            )
        return out


def create_vector_store(settings: Settings) -> BaseVectorStore:
    try:
        return ChromaVectorStore(settings.chroma_path)
    except Exception:
        return InMemoryVectorStore()

