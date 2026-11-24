"""Vector store abstractions with real Ollama embeddings (local, zero-cost)."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class BaseVectorStore(Protocol):
    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        ...

    async def query(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        ...


# ── Embedding functions ─────────────────────────────────────────────


def _hash_embedding(text: str, dim: int = 128) -> list[float]:
    """Bag-of-words hash embedding — last-resort fallback."""
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


class OllamaEmbeddingFn:
    """Compute embeddings using a local Ollama model (e.g. nomic-embed-text).

    Falls back to hash embeddings if Ollama is unreachable.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.name = f"ollama-{model}"  # ChromaDB embedding_function protocol
        self.base_url = base_url.rstrip("/")
        self._available: bool | None = None

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Blocking call — run via asyncio.to_thread."""
        results: list[list[float]] = []
        for text in texts:
            try:
                resp = httpx.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=15.0,
                )
                resp.raise_for_status()
                embedding = resp.json().get("embedding")
                if embedding:
                    results.append(embedding)
                    self._available = True
                    continue
            except Exception:
                self._available = False
            results.append(_hash_embedding(text))
        return results

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_sync, texts)

    # ChromaDB embedding_function protocol
    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self._embed_sync(input)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── In-memory store (uses Ollama embeddings when available) ─────────


class InMemoryVectorStore:
    def __init__(self, embed_fn: OllamaEmbeddingFn | None = None) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._embed_fn = embed_fn

    async def _get_embedding(self, text: str) -> list[float]:
        if self._embed_fn is not None:
            results = await self._embed_fn.embed([text])
            return results[0]
        return _hash_embedding(text)

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        emb = await self._get_embedding(text)
        self._docs[doc_id] = {
            "id": doc_id,
            "text": text,
            "metadata": metadata,
            "embedding": emb,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def query(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        query_emb = await self._get_embedding(text)
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


# ── ChromaDB store (uses Ollama embeddings) ─────────────────────────


class ChromaVectorStore:
    def __init__(
        self,
        persist_path: str,
        collection_name: str = "tapan_ai_memory",
        embed_fn: OllamaEmbeddingFn | None = None,
    ) -> None:
        import chromadb

        self._embed_fn = embed_fn
        self._client = chromadb.PersistentClient(path=persist_path)

        # Use Ollama embeddings or fall back to hash
        chroma_ef = embed_fn if embed_fn is not None else _HashEmbeddingFnCompat()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=chroma_ef,
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


class _HashEmbeddingFnCompat:
    """Fallback ChromaDB embedding function using hash embeddings."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [_hash_embedding(text) for text in input]


# ── Factory ─────────────────────────────────────────────────────────


def create_vector_store(settings: Settings) -> BaseVectorStore:
    """Create best available vector store: Chroma+Ollama → InMemory+Ollama → InMemory+hash."""
    embed_fn = OllamaEmbeddingFn(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_url.replace("/api/chat", ""),
    )
    try:
        store = ChromaVectorStore(settings.chroma_path, embed_fn=embed_fn)
        logger.info("Vector store: ChromaDB + Ollama embeddings (%s)", settings.ollama_embed_model)
        return store
    except Exception as exc:
        logger.warning("ChromaDB unavailable (%s), using in-memory store", exc)
        return InMemoryVectorStore(embed_fn=embed_fn)
