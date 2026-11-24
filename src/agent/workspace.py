"""Work and personal growth: tasks with projects, due dates and reminders; notes and plans; a journal of learnings, lessons,
quotes and thoughts; and a rulebook of personal rules.

It reuses the ``tasks`` and ``notes`` tables the chat skills already use (new columns only), so a task added in chat, on the Today
panel or on the Work screen is the same task, and finishing it anywhere cancels its reminder.

* A due date without a time means "by the end of that day": it is stored as 23:59 local time and is not overdue until it is over.
* A task may carry one reminder (at the due time, at 9 am that morning, or at 9 am the day before). It always follows the task:
  moving the date moves the reminder, finishing or deleting the task cancels it.
* Notes belong to a *space* (``work`` or ``growth``) and have a *kind* that depends on it.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from src.agent import timeutil
from src.agent.expenses import ExpenseError, NotFound, clean_text, reminder_ops
from src.config.settings import Settings

PRIORITIES = ("high", "normal", "low")
REMIND_CHOICES = ("", "due", "morning", "day_before")
WORK_KINDS = ("note", "plan", "meeting", "idea")
GROWTH_KINDS = ("learning", "lesson", "quote", "thought", "rule")
SPACES = {"work": WORK_KINDS, "growth": GROWTH_KINDS}
MAX_TASKS = 5000
MAX_NOTES = 5000
MAX_BODY = 8000
MAX_TAGS = 8
_UNSET: Any = object()
_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tz(settings: Settings):
    return timeutil.get_tz(settings)


# ── tasks ──────────────────────────────────────────────────────────────
def _due_iso(settings: Settings, due: Any) -> str | None:
    """'2026-12-05' -> end of that day, local; a date and time or a phrase ('tomorrow 5pm') -> that moment. Empty -> no due date."""
    if due is None or str(due).strip() == "":
        return None
    raw = str(due).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            when = datetime.combine(date.fromisoformat(raw), time(23, 59), tzinfo=_tz(settings))
        except ValueError:
            raise ExpenseError("The due date must be a real date like 2026-12-05.") from None
    else:
        when = timeutil.parse_when(raw, settings)
        if when is None:
            raise ExpenseError("I couldn't understand that due date. Use a date like 2026-12-05, or a date and time like 2026-12-05T17:00.")
    if when.year < 2000 or when.year > 2200:
        raise ExpenseError("That due date is out of range.")
    return when.isoformat()


def _has_time(when: datetime) -> bool:
    return not (when.hour == 23 and when.minute == 59)


def _priority(value: Any) -> str:
    text = str(value or "normal").strip().lower()
    if text not in PRIORITIES:
        raise ExpenseError(f"The priority must be one of: {', '.join(PRIORITIES)}.")
    return text


def _remind_choice(value: Any) -> str:
    text = "" if value in (None, "none") else str(value).strip().lower()
    if text not in REMIND_CHOICES:
        raise ExpenseError("The reminder must be: none, at the due time, the morning of the due date, or the day before.")
    return text


def _shape_task(row: dict[str, Any], settings: Settings) -> dict[str, Any]:
    now = timeutil.now(settings)
    due = timeutil.as_aware(row["due_at"], settings)
    open_ = row["status"] == "open"
    local_due = due.astimezone(now.tzinfo) if due else None
    return {
        "id": row["id"], "title": row["title"], "project": row.get("project") or "", "priority": row["priority"], "status": row["status"],
        "due_at": row["due_at"], "due_date": local_due.date().isoformat() if local_due else None,
        "due_time": local_due.strftime("%H:%M") if local_due and _has_time(local_due) else None,
        "overdue": bool(open_ and due and due < now), "due_today": bool(open_ and local_due and local_due.date() == now.date()),
        "details": row.get("details") or "", "remind": row.get("remind") or "", "completed_at": row["completed_at"],
    }


async def _task_row(store: Any, task_id: int) -> dict[str, Any]:
    row = await store.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not row:
        raise NotFound("That task no longer exists.")
    return row


async def get_task(store: Any, settings: Settings, task_id: int) -> dict[str, Any]:
    return _shape_task(await _task_row(store, task_id), settings)


def _like(text: str) -> str:
    """A LIKE pattern for 'contains', with the user's % and _ taken literally (used with ESCAPE '\\')."""
    return "%" + text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def list_tasks(store: Any, settings: Settings, status: str = "open", project: Any = None, q: Any = None, limit: int = 400) -> list[dict[str, Any]]:
    status = str(status or "open").lower()
    if status not in ("open", "done", "all"):
        raise ExpenseError("The status must be open, done or all.")
    where, params = [], []
    if status != "all":
        where.append("status = ?"); params.append(status)
    if project not in (None, ""):
        where.append("lower(project) = ?"); params.append(str(project).strip().lower())
    if q not in (None, ""):
        pattern = _like(str(q).strip()[:100])
        where.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(details) LIKE ? ESCAPE '\\' OR lower(project) LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern, pattern])
    rows = await store.fetchall(f"SELECT * FROM tasks {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY id DESC LIMIT ?", (*params, max(1, min(int(limit), 1000))))
    tasks = [_shape_task(r, settings) for r in rows]
    if status == "done":
        return sorted(tasks, key=lambda t: t["completed_at"] or "", reverse=True)
    return sorted(tasks, key=lambda t: (t["status"] != "open", _PRIORITY_RANK[t["priority"]] if t["status"] == "open" else 0, t["due_at"] is None, t["due_at"] or "", -t["id"]))


async def work_overview(store: Any, settings: Settings) -> dict[str, Any]:
    rows = await store.fetchall("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (MAX_TASKS,))
    tasks = [_shape_task(r, settings) for r in rows]
    open_ = [t for t in tasks if t["status"] == "open"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    projects: dict[str, dict[str, Any]] = {}
    for t in open_:
        if t["project"]:
            p = projects.setdefault(t["project"].lower(), {"name": t["project"], "open": 0, "overdue": 0})
            p["open"] += 1
            p["overdue"] += 1 if t["overdue"] else 0
    for t in tasks:
        if t["project"] and t["project"].lower() not in projects:
            projects[t["project"].lower()] = {"name": t["project"], "open": 0, "overdue": 0}
    return {
        "open": len(open_), "overdue": sum(1 for t in open_ if t["overdue"]), "due_today": sum(1 for t in open_ if t["due_today"]),
        "high": sum(1 for t in open_ if t["priority"] == "high"), "no_date": sum(1 for t in open_ if not t["due_at"]),
        "done_7d": sum(1 for t in tasks if t["status"] == "done" and (t["completed_at"] or "") >= week_ago),
        "projects": sorted(projects.values(), key=lambda p: (-p["open"], p["name"].lower())),
    }


async def create_task(store: Any, settings: Settings, *, title: Any, project: Any = "", priority: Any = "normal", due: Any = None,
                      details: Any = "", remind: Any = "") -> dict[str, Any]:
    title = clean_text(title, "task", limit=200, required=True)
    due_at = _due_iso(settings, due)
    choice = _remind_choice(remind)
    if choice and not due_at:
        raise ExpenseError("A reminder needs a due date. Add one, or turn the reminder off.")
    if (await store.fetchone("SELECT COUNT(*) AS n FROM tasks"))["n"] >= MAX_TASKS:
        raise ExpenseError("You have a lot of tasks. Delete finished ones first.")
    task_id = await store.execute(
        "INSERT INTO tasks (title, due_at, priority, status, created_at, project, details, remind) VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
        (title, due_at, _priority(priority), _now_iso(), clean_text(project, "project", limit=60), _body(details, 2000), choice),
    )
    await sync_task_reminder(store, settings, task_id)
    return await get_task(store, settings, task_id)


async def update_task(store: Any, settings: Settings, task_id: int, *, title: Any = _UNSET, project: Any = _UNSET, priority: Any = _UNSET,
                      due: Any = _UNSET, details: Any = _UNSET, remind: Any = _UNSET) -> dict[str, Any]:
    row = await _task_row(store, task_id)
    sets: list[str] = []
    params: list[Any] = []
    if title is not _UNSET:
        sets.append("title = ?"); params.append(clean_text(title, "task", limit=200, required=True))
    if project is not _UNSET:
        sets.append("project = ?"); params.append(clean_text(project, "project", limit=60))
    if priority is not _UNSET:
        sets.append("priority = ?"); params.append(_priority(priority))
    new_due = row["due_at"]
    if due is not _UNSET:
        new_due = _due_iso(settings, due)
        sets.append("due_at = ?"); params.append(new_due)
    choice = _remind_choice(remind) if remind is not _UNSET else (row.get("remind") or "")
    if due is not _UNSET and not new_due:
        choice = ""                                           # no date, no reminder
    if choice and not new_due:
        raise ExpenseError("A reminder needs a due date. Add one, or turn the reminder off.")
    if choice != (row.get("remind") or ""):
        sets.append("remind = ?"); params.append(choice)
    if details is not _UNSET:
        sets.append("details = ?"); params.append(_body(details, 2000))
    if sets:
        await store.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", (*params, task_id))
        await sync_task_reminder(store, settings, task_id)
    return await get_task(store, settings, task_id)


async def set_task_done(store: Any, settings: Settings, task_id: int, done: bool = True) -> dict[str, Any]:
    row = await _task_row(store, task_id)
    if done and row["status"] != "done":
        await store.execute("UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", (_now_iso(), task_id))
    elif not done and row["status"] == "done":
        await store.execute("UPDATE tasks SET status = 'open', completed_at = NULL WHERE id = ?", (task_id,))
    await sync_task_reminder(store, settings, task_id)
    return await get_task(store, settings, task_id)


async def delete_task(store: Any, task_id: int) -> None:
    row = await _task_row(store, task_id)
    if row.get("reminder_id"):
        await store.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (row["reminder_id"],))
    await store.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


async def sync_task_reminder(store: Any, settings: Settings, task_id: int) -> None:
    """One reminder per task, always matching its due date and choice; gone when the task is done, undated or deleted."""
    row = await store.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not row:
        return
    want: tuple[str, str] | None = None
    choice = row.get("remind") or ""
    due = timeutil.as_aware(row["due_at"], settings) if row["due_at"] else None
    if row["status"] == "open" and choice and due:
        tz = _tz(settings)
        local = due.astimezone(tz)
        morning = datetime.combine(local.date(), time(9, 0), tzinfo=tz)
        fire = {"due": local if _has_time(local) else morning, "morning": morning, "day_before": morning - timedelta(days=1)}[choice]
        if fire > timeutil.now(settings):
            tail = " (due tomorrow)" if choice == "day_before" else ""
            label = f"Task · {row['title']}" + (f" · {row['project']}" if row.get("project") else "") + tail
            want = (fire.isoformat(), label[:200])
    current = await store.fetchone("SELECT id, title, due_at, status FROM reminders WHERE id = ?", (row["reminder_id"],)) if row.get("reminder_id") else None
    ops = reminder_ops("tasks", task_id, current, want, "work", bool(row.get("reminder_id")))
    if ops:
        await store.execute_transaction(ops)


# ── notes: work notes/plans and the growth journal ─────────────────────
def _body(value: Any, limit: int) -> str:
    text = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > limit:
        raise ExpenseError(f"That is too long (max {limit} characters).")
    return text


def _tags(value: Any) -> str:
    raw = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    seen: list[str] = []
    for item in raw:
        tag = re.sub(r"\s+", "-", str(item).strip().lower().lstrip("#"))
        if not tag:
            continue
        if len(tag) > 24:
            raise ExpenseError("A tag can be at most 24 characters.")
        if tag not in seen:
            seen.append(tag)
    if len(seen) > MAX_TAGS:
        raise ExpenseError(f"Use at most {MAX_TAGS} tags.")
    return ",".join(seen)


def _space_kind(space: Any, kind: Any) -> tuple[str, str]:
    space = str(space or "").strip().lower()
    if space not in SPACES:
        raise ExpenseError(f"The space must be one of: {', '.join(SPACES)}.")
    kind = str(kind or SPACES[space][0]).strip().lower()
    if kind not in SPACES[space]:
        raise ExpenseError(f"For {space} the kind must be one of: {', '.join(SPACES[space])}.")
    return space, kind


def _shape_note(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "space": r["space"], "kind": r["kind"], "title": r["title"], "body": r["body"],
            "tags": [t for t in (r["tags"] or "").split(",") if t], "pinned": bool(r["pinned"]), "created_at": r["created_at"], "updated_at": r["updated_at"]}


async def _note_row(store: Any, note_id: int) -> dict[str, Any]:
    row = await store.fetchone("SELECT * FROM notes WHERE id = ?", (note_id,))
    if not row:
        raise NotFound("That note no longer exists.")
    return row


async def get_note(store: Any, note_id: int) -> dict[str, Any]:
    return _shape_note(await _note_row(store, note_id))


async def list_notes(store: Any, space: str, kind: Any = None, q: Any = None, tag: Any = None, pinned: Any = None, limit: int = 300) -> list[dict[str, Any]]:
    space, _ = _space_kind(space, None)
    where, params = ["space = ?"], [space]
    if kind not in (None, ""):
        where.append("kind = ?"); params.append(_space_kind(space, kind)[1])
    if tag not in (None, ""):
        escaped = _tags(tag).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(',' || tags || ',') LIKE ? ESCAPE '\\'"); params.append(f"%,{escaped},%")
    if pinned is True:
        where.append("pinned = 1")
    if q not in (None, ""):
        pattern = _like(str(q).strip()[:100])
        where.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(body) LIKE ? ESCAPE '\\' OR lower(tags) LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern, pattern])
    order = "pinned DESC, id ASC" if kind == "rule" else "pinned DESC, id DESC"            # a rulebook keeps its order; a journal is newest first
    rows = await store.fetchall(f"SELECT * FROM notes WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", (*params, max(1, min(int(limit), 1000))))
    return [_shape_note(r) for r in rows]


async def create_note(store: Any, *, space: Any, kind: Any = None, title: Any = "", body: Any, tags: Any = "", pinned: Any = False) -> dict[str, Any]:
    space, kind = _space_kind(space, kind)
    text = _body(body, MAX_BODY)
    if not text:
        raise ExpenseError("Write something first.")
    if (await store.fetchone("SELECT COUNT(*) AS n FROM notes"))["n"] >= MAX_NOTES:
        raise ExpenseError("You have a lot of notes. Delete old ones first.")
    now = _now_iso()
    note_id = await store.execute(
        "INSERT INTO notes (title, body, tags, created_at, updated_at, space, kind, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (clean_text(title, "title", limit=160), text, _tags(tags), now, now, space, kind, 1 if pinned else 0),
    )
    return await get_note(store, note_id)


async def update_note(store: Any, note_id: int, *, kind: Any = _UNSET, title: Any = _UNSET, body: Any = _UNSET, tags: Any = _UNSET, pinned: Any = _UNSET) -> dict[str, Any]:
    row = await _note_row(store, note_id)
    if row["space"] not in SPACES:
        raise ExpenseError("That note belongs to chat and is edited there.")
    sets: list[str] = []
    params: list[Any] = []
    if kind is not _UNSET:
        sets.append("kind = ?"); params.append(_space_kind(row["space"], kind)[1])
    if title is not _UNSET:
        sets.append("title = ?"); params.append(clean_text(title, "title", limit=160))
    if body is not _UNSET:
        text = _body(body, MAX_BODY)
        if not text:
            raise ExpenseError("Write something first.")
        sets.append("body = ?"); params.append(text)
    if tags is not _UNSET:
        sets.append("tags = ?"); params.append(_tags(tags))
    if pinned is not _UNSET:
        sets.append("pinned = ?"); params.append(1 if pinned else 0)
    if sets:
        await store.execute(f"UPDATE notes SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*params, _now_iso(), note_id))
    return await get_note(store, note_id)


async def delete_note(store: Any, note_id: int) -> None:
    await _note_row(store, note_id)
    await store.execute("DELETE FROM notes WHERE id = ?", (note_id,))


# ── growth ─────────────────────────────────────────────────────────────
async def growth_overview(store: Any, settings: Settings) -> dict[str, Any]:
    rows = await store.fetchall("SELECT kind, tags FROM notes WHERE space = 'growth'")
    counts = {k: 0 for k in GROWTH_KINDS}
    tags: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        for t in (r["tags"] or "").split(","):
            if t:
                tags[t] = tags.get(t, 0) + 1
    return {"kinds": list(GROWTH_KINDS), "counts": counts, "total": len(rows),
            "tags": [{"tag": t, "count": n} for t, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:30]],
            "pick": await todays_pick(store, settings)}


async def todays_pick(store: Any, settings: Settings) -> dict[str, Any] | None:
    """One rule, quote or lesson to read today. Stable for the whole day, different tomorrow; pinned ones are preferred."""
    rows = await store.fetchall("SELECT * FROM notes WHERE space = 'growth' AND kind IN ('rule', 'quote', 'lesson') ORDER BY id")
    if not rows:
        return None
    pinned = [r for r in rows if r["pinned"]]
    pool = pinned or rows
    return _shape_note(pool[timeutil.now(settings).date().toordinal() % len(pool)])
