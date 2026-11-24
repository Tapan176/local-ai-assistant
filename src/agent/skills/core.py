"""Core personal-productivity skills: time, math, memory, notes, tasks, reminders."""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agent import recurrence, timeutil, workspace
from src.agent.expenses import ExpenseError
from src.agent.skill import SkillContext, SkillRegistry, schema


def _int(value: Any, name: str = "id") -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{name}' must be a number, got {value!r}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── time ────────────────────────────────────────────────────────────
async def get_current_time(ctx: SkillContext, args: dict[str, Any]) -> str:
    tz_name = str(args.get("timezone") or "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            return f"Unknown timezone '{tz_name}'. Use an IANA name like 'Asia/Kolkata' or 'America/New_York'."
    else:
        now = ctx.now()
    return now.strftime("%A, %d %B %Y, %I:%M %p ") + (now.tzname() or "") + f" (ISO: {now.isoformat(timespec='minutes')})"


# ── calculator (AST-based; never uses eval) ─────────────────────────
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log10": math.log10, "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("Exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    raise ValueError("Unsupported expression")


def safe_calculate(expression: str) -> float:
    cleaned = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    if len(cleaned) > 200:
        raise ValueError("Expression too long")
    return _eval_node(ast.parse(cleaned.strip(), mode="eval").body)


async def calculate(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        result = safe_calculate(str(args["expression"]))
    except ZeroDivisionError:
        return "Error: division by zero."
    except Exception as exc:
        return f"Could not evaluate that expression ({exc}). Use numbers, + - * / % ** ( ) and sqrt/round/min/max."
    return str(int(result)) if isinstance(result, float) and result.is_integer() and abs(result) < 1e15 else f"{result:.10g}"


# ── long-term memory ────────────────────────────────────────────────
async def remember(ctx: SkillContext, args: dict[str, Any]) -> str:
    content = str(args["content"]).strip()
    category = str(args.get("category") or "general").strip().lower()[:30]
    existing = await ctx.store.fetchone("SELECT id FROM memories WHERE lower(content) = lower(?)", (content,))
    if existing:
        return f"Already remembered (#{existing['id']})."
    new_id = await ctx.store.execute(
        "INSERT INTO memories (content, category, created_at) VALUES (?, ?, ?)", (content, category, _utc_now())
    )
    return f"Remembered (#{new_id}): {content}"


async def recall(ctx: SkillContext, args: dict[str, Any]) -> Any:
    query = str(args.get("query") or "").strip()
    limit = min(max(_int(args.get("limit", 10), "limit"), 1), 50)
    if not query:
        rows = await ctx.store.fetchall(
            "SELECT id, content, category, created_at FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        )
    else:
        words = [w for w in query.lower().split() if len(w) > 2][:6] or [query.lower()]
        clause = " OR ".join("lower(content) LIKE ?" for _ in words)
        rows = await ctx.store.fetchall(
            f"SELECT id, content, category, created_at FROM memories WHERE {clause} ORDER BY id DESC LIMIT ?",
            tuple(f"%{w}%" for w in words) + (limit,),
        )
    return rows or "Nothing stored matches that."


async def forget(ctx: SkillContext, args: dict[str, Any]) -> str:
    memory_id = _int(args["id"])
    await ctx.store.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return f"Forgot memory #{memory_id}."


# ── conversation history (everything ever said, across all conversations) ──
def _clip(text: str, limit: int = 320) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def search_history(ctx: SkillContext, args: dict[str, Any]) -> Any:
    query = str(args["query"]).strip()
    limit = min(max(_int(args.get("limit", 5), "limit"), 1), 10)
    words = list(dict.fromkeys(w for w in re.findall(r"\w+", query.lower()) if len(w) > 2))[:6] or [query.lower()]
    clause = " OR ".join("(lower(user_text) LIKE ? OR lower(assistant_text) LIKE ?)" for _ in words)
    params: list[Any] = [p for w in words for p in (f"%{w}%", f"%{w}%")]
    where = f"({clause})"
    if args.get("days"):
        cutoff = datetime.now(timezone.utc) - timedelta(days=min(max(_int(args["days"], "days"), 1), 3650))
        where += ' AND "timestamp" >= ?'
        params.append(cutoff.isoformat())
    rows = await ctx.store.fetchall(
        f'SELECT id, session_id, "timestamp" AS ts, user_text, assistant_text FROM episodes WHERE {where} ORDER BY id DESC LIMIT 40',
        tuple(params),
    )

    def score(row: dict[str, Any]) -> int:
        blob = f"{row['user_text']} {row['assistant_text']}".lower()
        return sum(w in blob for w in words)

    best = sorted(rows, key=lambda r: (score(r), r["id"]), reverse=True)[:limit]
    if not best:
        return "Nothing in past conversations matches that."
    return [
        {
            "when": str(r["ts"])[:16].replace("T", " "),
            "conversation": r["session_id"],
            "user": _clip(r["user_text"]),
            "assistant": _clip(r["assistant_text"]),
        }
        for r in sorted(best, key=lambda r: r["id"])  # present chronologically
    ]


# ── notes ───────────────────────────────────────────────────────────
async def add_note(ctx: SkillContext, args: dict[str, Any]) -> str:
    stamp = _utc_now()
    note_id = await ctx.store.execute(
        "INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (str(args.get("title") or "").strip(), str(args["body"]).strip(), str(args.get("tags") or "").strip(), stamp, stamp),
    )
    return f"Saved note #{note_id}."


async def search_notes(ctx: SkillContext, args: dict[str, Any]) -> Any:
    query = str(args.get("query") or "").strip()
    limit = min(max(_int(args.get("limit", 10), "limit"), 1), 50)
    if query:
        pattern = f"%{query.lower()}%"
        rows = await ctx.store.fetchall(
            "SELECT id, title, body, tags, updated_at FROM notes "
            "WHERE lower(title) LIKE ? OR lower(body) LIKE ? OR lower(tags) LIKE ? ORDER BY id DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        )
    else:
        rows = await ctx.store.fetchall(
            "SELECT id, title, body, tags, updated_at FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        )
    return rows or "No notes found."


async def delete_note(ctx: SkillContext, args: dict[str, Any]) -> str:
    note_id = _int(args["id"])
    await ctx.store.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return f"Deleted note #{note_id}."


# ── tasks (to-dos) ──────────────────────────────────────────────────
async def add_task(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        task = await workspace.create_task(
            ctx.store, ctx.settings, title=args["title"], project=args.get("project") or "", priority=args.get("priority") or "normal",
            due=args.get("due"), details=args.get("details") or "", remind=args.get("remind") or "",
        )
    except ExpenseError as exc:
        return str(exc)
    when = f" (due {task['due_date']}{' ' + task['due_time'] if task['due_time'] else ''})" if task["due_date"] else ""
    extra = f" in project {task['project']}" if task["project"] else ""
    note = " I will remind you." if task["remind"] else ""
    return f"Added task #{task['id']}: {task['title']}{extra}{when}.{note}"


async def list_tasks(ctx: SkillContext, args: dict[str, Any]) -> Any:
    status = str(args.get("status") or "open").lower()
    try:
        tasks = await workspace.list_tasks(ctx.store, ctx.settings, status, args.get("project"), args.get("query"), limit=50)
    except ExpenseError as exc:
        return str(exc)
    return [
        {"id": t["id"], "title": t["title"], "project": t["project"] or None, "priority": t["priority"], "due": t["due_at"], "overdue": t["overdue"], "status": t["status"]}
        for t in tasks
    ] or f"No {status} tasks."


async def complete_task(ctx: SkillContext, args: dict[str, Any]) -> str:
    task_id = _int(args["id"])
    try:
        task = await workspace.set_task_done(ctx.store, ctx.settings, task_id, True)
    except ExpenseError:
        return f"No task #{task_id}."
    return f"Completed task #{task_id}: {task['title']}"


async def delete_task(ctx: SkillContext, args: dict[str, Any]) -> str:
    task_id = _int(args["id"])
    try:
        await workspace.delete_task(ctx.store, task_id)
    except ExpenseError:
        return f"No task #{task_id}."
    return f"Deleted task #{task_id}."


# ── reminders (fire proactive notifications via the scheduler) ──────
async def set_reminder(ctx: SkillContext, args: dict[str, Any]) -> str:
    due = timeutil.parse_when(str(args["when"]), ctx.settings)
    if due is None:
        return f"I couldn't understand the time '{args['when']}'. Use an ISO date/time like 2026-12-01T17:00."
    if due <= ctx.now():
        return f"That time ({due:%Y-%m-%d %H:%M}) is in the past. Current time is {ctx.now():%Y-%m-%d %H:%M}."
    try:
        rule = recurrence.build_rule(args.get("repeat"), args.get("every"), args.get("days"), anchor=due)
    except recurrence.RuleError as exc:
        return str(exc)
    reminder_id = await ctx.store.execute(
        "INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES (?, ?, ?, 'pending', ?, ?)",
        (ctx.session_id, str(args["title"]).strip(), due.isoformat(), _utc_now(), rule.to_json() if rule else None),
    )
    repeats = f" (repeats {recurrence.describe(rule)})" if rule else ""
    return f"Reminder #{reminder_id} set for {due:%A %d %B, %I:%M %p}{repeats}: {args['title']}"


MAX_BATCH_REMINDERS = 25


def _slot(title: str, due: datetime) -> tuple[str, str]:
    """Canonical (title, minute-in-UTC) key used to detect duplicate reminders."""
    return title.strip().lower(), due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


async def set_reminders(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any] | str:
    """Create many reminders at once. Each item is validated on its own; valid ones are saved in one transaction."""
    items = args.get("reminders")
    if isinstance(items, str):  # some models send the array as a JSON string
        try:
            items = json.loads(items)
        except ValueError:
            return "'reminders' must be an array of {title, when} objects."
    if not isinstance(items, list) or not items:
        return "Provide a non-empty array of {title, when} objects in 'reminders'."
    if len(items) > MAX_BATCH_REMINDERS:
        return f"Too many reminders in one call (max {MAX_BATCH_REMINDERS}); send them in smaller batches."

    now = ctx.now()
    pending = await ctx.store.fetchall("SELECT title, due_at FROM reminders WHERE status = 'pending' AND due_at IS NOT NULL")
    seen = {
        _slot(r["title"], due)
        for r in pending
        if (due := timeutil.as_aware(r["due_at"], ctx.settings)) is not None
    }

    operations: list[tuple[str, tuple[Any, ...]]] = []
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for position, item in enumerate(items, start=1):
        label = f"#{position}"
        if not isinstance(item, dict):
            skipped.append({"item": label, "reason": "not a {title, when} object"})
            continue
        title = str(item.get("title") or "").strip()
        when = str(item.get("when") or "").strip()
        if not title:
            skipped.append({"item": label, "reason": "missing title"})
            continue
        label = title[:60]
        due = timeutil.parse_when(when, ctx.settings) if when else None
        if due is None:
            skipped.append({"item": label, "reason": f"couldn't understand the time {when!r}" if when else "missing time"})
            continue
        if due <= now:
            skipped.append({"item": label, "reason": f"time {due:%Y-%m-%d %H:%M} is in the past (now is {now:%Y-%m-%d %H:%M})"})
            continue
        slot = _slot(title, due)
        if slot in seen:
            skipped.append({"item": label, "reason": "identical reminder already exists"})
            continue
        try:
            rule = recurrence.build_rule(item.get("repeat"), item.get("every"), item.get("days"), anchor=due)
        except recurrence.RuleError as exc:
            skipped.append({"item": label, "reason": str(exc)})
            continue
        seen.add(slot)
        operations.append(
            (
                "INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES (?, ?, ?, 'pending', ?, ?)",
                (ctx.session_id, title, due.isoformat(), _utc_now(), rule.to_json() if rule else None),
            )
        )
        entry = {"title": title, "due": f"{due:%a %d %b %Y, %I:%M %p}", "due_iso": due.isoformat(timespec="minutes")}
        if rule:
            entry["repeats"] = recurrence.describe(rule)
        created.append(entry)

    if operations:  # all-or-nothing for the valid ones
        ids = await ctx.store.execute_transaction(operations)
        for entry, reminder_id in zip(created, ids):
            entry["id"] = str(reminder_id)

    return {
        "summary": f"{len(created)} reminder(s) set, {len(skipped)} skipped",
        "created": created,
        "skipped": skipped,
    }


async def list_reminders(ctx: SkillContext, args: dict[str, Any]) -> Any:
    status_clause = "" if args.get("include_done") else "WHERE status = 'pending'"
    rows = await ctx.store.fetchall(
        f"SELECT id, title, due_at, status, recurrence FROM reminders {status_clause} ORDER BY due_at IS NULL, due_at LIMIT 50"
    )
    for row in rows:
        row["repeats"] = recurrence.describe(recurrence.Rule.from_json(row.pop("recurrence", None)))
    return rows or "No pending reminders."


async def cancel_reminder(ctx: SkillContext, args: dict[str, Any]) -> str:
    reminder_id = _int(args["id"])
    await ctx.store.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (reminder_id,))
    return f"Cancelled reminder #{reminder_id} (a repeating reminder stops completely)."


def register(registry: SkillRegistry) -> None:
    S = schema
    registry.add(
        "get_current_time",
        "Get the current date and time. ALWAYS use this instead of guessing the date/time.",
        S({"timezone": {"type": "string", "description": "Optional IANA zone, e.g. 'Asia/Tokyo'. Default: user's zone."}}),
        get_current_time,
    )
    registry.add(
        "calculate",
        "Evaluate a math expression exactly (supports + - * / % ** and sqrt, round, min, max, sin, log, pi). Use for any arithmetic.",
        S({"expression": {"type": "string", "description": "e.g. '(1250*0.18)+40'"}}, ["expression"]),
        calculate,
    )
    registry.add(
        "remember",
        "Save a durable fact about the user (preferences, people, goals, routines) so it is recalled in future chats. "
        "Use proactively whenever the user shares something worth remembering.",
        S(
            {
                "content": {"type": "string", "description": "A self-contained fact, e.g. 'Prefers meetings after 11am'"},
                "category": {"type": "string", "description": "profile | preference | person | goal | work | general"},
            },
            ["content"],
        ),
        remember,
    )
    registry.add(
        "recall",
        "Search long-term memory about the user. Empty query lists the most recent memories.",
        S({"query": {"type": "string"}, "limit": {"type": "integer"}}),
        recall,
    )
    registry.add(
        "search_history",
        "Search EVERY past conversation with the user (all sessions, any date) for what was said or decided. Use it "
        "whenever the user refers to something discussed earlier that is not in the recent messages "
        "('what did we decide about…', 'remember when I told you…', 'last week we talked about…'). "
        "Different from recall, which only searches the short facts you chose to save.",
        S(
            {
                "query": {"type": "string", "description": "Keywords to look for"},
                "days": {"type": "integer", "description": "Optional: only the last N days"},
                "limit": {"type": "integer", "description": "Max results (default 5, max 10)"},
            },
            ["query"],
        ),
        search_history,
    )
    registry.add("forget", "Delete a stored memory by id.", S({"id": {"type": "integer"}}, ["id"]), forget)
    registry.add(
        "add_note",
        "Save a note (ideas, snippets, meeting notes, anything to look up later).",
        S(
            {
                "body": {"type": "string"},
                "title": {"type": "string"},
                "tags": {"type": "string", "description": "comma-separated"},
            },
            ["body"],
        ),
        add_note,
    )
    registry.add(
        "search_notes",
        "Search saved notes by text/tag. Empty query lists the newest notes.",
        S({"query": {"type": "string"}, "limit": {"type": "integer"}}),
        search_notes,
    )
    registry.add("delete_note", "Delete a note by id.", S({"id": {"type": "integer"}}, ["id"]), delete_note)
    registry.add(
        "add_task",
        "Add a to-do item. Use set_reminder instead if the user wants to be alerted at a specific time.",
        S(
            {
                "title": {"type": "string"},
                "due": {"type": "string", "description": "Optional ISO date/time or natural phrase. A date alone means by the end of that day."},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                "project": {"type": "string", "description": "Optional project or area, e.g. 'Website redesign'."},
                "details": {"type": "string", "description": "Optional longer description."},
                "remind": {"type": "string", "enum": ["due", "morning", "day_before"], "description": "Optional reminder: at the due time, 9 am that day, or 9 am the day before. Needs `due`."},
            },
            ["title"],
        ),
        add_task,
    )
    registry.add(
        "list_tasks",
        "List to-do items, optionally for one project or matching some text.",
        S({"status": {"type": "string", "enum": ["open", "done", "all"]}, "project": {"type": "string"}, "query": {"type": "string"}}),
        list_tasks,
    )
    registry.add("complete_task", "Mark a task done by id.", S({"id": {"type": "integer"}}, ["id"]), complete_task)
    registry.add("delete_task", "Delete a task by id.", S({"id": {"type": "integer"}}, ["id"]), delete_task)
    registry.add(
        "set_reminder",
        "Schedule ONE reminder; the assistant will proactively notify the user at that time. If the user gives "
        "several reminders, use set_reminders instead. For anything recurring ('every day', 'every Monday', 'on the 1st "
        "of each month', 'every weekday') pass `repeat` ONCE with the FIRST occurrence as `when` — never create one reminder per day.",
        S(
            {
                "title": {"type": "string", "description": "What to remind about"},
                "when": {"type": "string", "description": "ISO-8601 date/time of the FIRST occurrence (preferred) or natural phrase"},
                "repeat": {"type": "string", "enum": ["daily", "weekdays", "weekly", "monthly", "yearly"], "description": "Omit for a one-off"},
                "every": {"type": "integer", "description": "Interval, e.g. 2 with weekly = every other week (default 1)"},
                "days": {"type": "array", "items": {"type": "string"}, "description": "weekly only: weekdays such as ['mon','thu'] (default: the weekday of `when`)"},
            },
            ["title", "when"],
        ),
        set_reminder,
    )
    registry.add(
        "set_reminders",
        "Schedule MANY reminders in one call. Use whenever the user lists two or more reminders (one per line, bullets, "
        "numbered, or in one sentence). Resolve every time to an absolute ISO-8601 date-time using the current date/time "
        "in the system prompt. Valid items are saved even if others are skipped; read 'skipped' and tell the user.",
        S(
            {
                "reminders": {
                    "type": "array",
                    "description": "Every reminder the user asked for",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "What to remind about"},
                            "when": {"type": "string", "description": "ISO-8601 date/time, e.g. 2026-11-24T09:00:00+05:30"},
                            "repeat": {"type": "string", "enum": ["daily", "weekdays", "weekly", "monthly", "yearly"]},
                            "every": {"type": "integer"},
                            "days": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "when"],
                    },
                }
            },
            ["reminders"],
        ),
        set_reminders,
    )
    registry.add(
        "list_reminders",
        "List the user's reminders.",
        S({"include_done": {"type": "boolean"}}),
        list_reminders,
    )
    registry.add("cancel_reminder", "Cancel a reminder by id.", S({"id": {"type": "integer"}}, ["id"]), cancel_reminder)
