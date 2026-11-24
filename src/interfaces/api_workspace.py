"""Authenticated REST routes for the Work and Growth screens. Every route needs the access token."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.agent import expenses, workspace
from src.config.settings import Settings


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskIn(_Body):
    title: str = Field(max_length=400)
    project: str = Field(default="", max_length=200)
    priority: str = Field(default="normal", max_length=10)
    due: str | None = Field(default=None, max_length=60)
    details: str = Field(default="", max_length=4000)
    remind: str = Field(default="", max_length=20)


class TaskPatch(_Body):
    title: str | None = Field(default=None, max_length=400)
    project: str | None = Field(default=None, max_length=200)
    priority: str | None = Field(default=None, max_length=10)
    due: str | None = Field(default=None, max_length=60)             # null / empty clears the due date
    details: str | None = Field(default=None, max_length=4000)
    remind: str | None = Field(default=None, max_length=20)


class DoneIn(_Body):
    done: bool = True


class NoteIn(_Body):
    space: str = Field(max_length=10)
    kind: str | None = Field(default=None, max_length=20)
    title: str = Field(default="", max_length=400)
    body: str = Field(max_length=20000)
    tags: str = Field(default="", max_length=400)
    pinned: bool = False


class NotePatch(_Body):
    kind: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=400)
    body: str | None = Field(default=None, max_length=20000)
    tags: str | None = Field(default=None, max_length=400)
    pinned: bool | None = None


def register(app: FastAPI, *, runtime: Any, settings: Settings, require_auth: Callable, limiter: Any) -> None:
    store = runtime.sqlite_store
    auth = [Depends(require_auth)]

    async def guarded(coro: Any) -> Any:
        try:
            return await coro
        except expenses.ExpenseError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    def provided(body: _Body, *names: str) -> dict[str, Any]:
        return {n: getattr(body, n) for n in names if n in body.model_fields_set}

    # ── work: tasks, projects, notes and plans in one round trip ───
    @app.get("/api/work", dependencies=auth)
    async def work(status: str = "open", project: str | None = None, q: str | None = None) -> dict[str, Any]:
        return {
            "tasks": await guarded(workspace.list_tasks(store, settings, status, project, q)),
            "overview": await guarded(workspace.work_overview(store, settings)),
            "notes": await guarded(workspace.list_notes(store, "work")),
            "priorities": list(workspace.PRIORITIES), "kinds": list(workspace.WORK_KINDS), "today": workspace.timeutil.now(settings).date().isoformat(),
        }

    @app.post("/api/work/tasks", dependencies=auth)
    async def task_add(body: TaskIn) -> dict[str, Any]:
        return await guarded(workspace.create_task(store, settings, title=body.title, project=body.project, priority=body.priority, due=body.due,
                                                    details=body.details, remind=body.remind))

    @app.patch("/api/work/tasks/{task_id}", dependencies=auth)
    async def task_edit(task_id: int, body: TaskPatch) -> dict[str, Any]:
        fields = provided(body, "title", "project", "priority", "due", "details", "remind")
        for required in ("title", "project", "priority", "details", "remind"):
            if required in fields and fields[required] is None:
                raise HTTPException(status_code=400, detail=f"The {required} cannot be empty.")
        return await guarded(workspace.update_task(store, settings, task_id, **fields))

    @app.post("/api/work/tasks/{task_id}/done", dependencies=auth)
    async def task_done(task_id: int, body: DoneIn | None = None) -> dict[str, Any]:
        return await guarded(workspace.set_task_done(store, settings, task_id, (body or DoneIn()).done))

    @app.delete("/api/work/tasks/{task_id}", dependencies=auth)
    async def task_remove(task_id: int) -> dict[str, bool]:
        await guarded(workspace.delete_task(store, task_id))
        return {"ok": True}

    # ── notes (work) and the growth journal share one set of routes ─
    @app.get("/api/notebook", dependencies=auth)
    async def notes_list(space: str, kind: str | None = None, q: str | None = None, tag: str | None = None, pinned: bool | None = None) -> dict[str, Any]:
        return {"notes": await guarded(workspace.list_notes(store, space, kind, q, tag, pinned)), "kinds": list(workspace.SPACES.get(space, ()))}

    @app.post("/api/notebook", dependencies=auth)
    async def note_add(body: NoteIn) -> dict[str, Any]:
        return await guarded(workspace.create_note(store, space=body.space, kind=body.kind, title=body.title, body=body.body, tags=body.tags, pinned=body.pinned))

    @app.patch("/api/notebook/{note_id}", dependencies=auth)
    async def note_edit(note_id: int, body: NotePatch) -> dict[str, Any]:
        fields = provided(body, "kind", "title", "body", "tags", "pinned")
        if any(v is None for v in fields.values()):
            raise HTTPException(status_code=400, detail="Send a value for each field you change.")
        return await guarded(workspace.update_note(store, note_id, **fields))

    @app.delete("/api/notebook/{note_id}", dependencies=auth)
    async def note_remove(note_id: int) -> dict[str, bool]:
        await guarded(workspace.delete_note(store, note_id))
        return {"ok": True}

    # ── growth: the journal's overview and today's reminder ────────
    @app.get("/api/growth", dependencies=auth)
    async def growth() -> dict[str, Any]:
        return {**await guarded(workspace.growth_overview(store, settings)), "notes": await guarded(workspace.list_notes(store, "growth"))}
