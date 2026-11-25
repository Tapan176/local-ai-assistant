"""Authenticated REST routes for the memory graph (view and clean up what the assistant has remembered)."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.agent import expenses, graph
from src.config.settings import Settings


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str = Field(max_length=200)
    relation: str = Field(max_length=100)
    b: str = Field(max_length=200)
    note: str = Field(default="", max_length=400)


def register(app: FastAPI, *, runtime: Any, settings: Settings, require_auth: Callable, limiter: Any) -> None:
    store = runtime.sqlite_store
    auth = [Depends(require_auth)]

    async def guarded(coro: Any) -> Any:
        try:
            return await coro
        except expenses.ExpenseError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    @app.get("/api/graph", dependencies=auth)
    async def graph_overview(q: str = Query(default="", max_length=80)) -> dict[str, Any]:
        return await guarded(graph.overview(store, q))

    @app.post("/api/graph/links", dependencies=auth)
    async def graph_link(body: LinkIn) -> dict[str, Any]:
        return await guarded(graph.link(store, body.a, body.relation, body.b, note=body.note))

    @app.delete("/api/graph/nodes/{node_id}", dependencies=auth)
    async def graph_forget_node(node_id: int) -> dict[str, Any]:
        return {"ok": True, "name": await guarded(graph.forget_node(store, node_id))}

    @app.delete("/api/graph/edges/{edge_id}", dependencies=auth)
    async def graph_forget_edge(edge_id: int) -> dict[str, bool]:
        await guarded(graph.forget_edge(store, edge_id))
        return {"ok": True}
