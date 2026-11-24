"""Chat skills for the Work notes and the personal-growth journal: the same service the Work and Growth screens use."""

from __future__ import annotations

from typing import Any

from src.agent import workspace
from src.agent.expenses import ExpenseError
from src.agent.skill import SkillContext, SkillRegistry, schema


async def _save(ctx: SkillContext, space: str, args: dict[str, Any]) -> str:
    try:
        note = await workspace.create_note(ctx.store, space=space, kind=args.get("kind"), title=args.get("title") or "", body=args.get("text"), tags=args.get("tags") or "")
    except ExpenseError as exc:
        return str(exc)
    where = "your growth journal" if space == "growth" else "your work notes"
    label = {"rule": "rulebook", "quote": "quotes"}.get(note["kind"], note["kind"])
    return f"Saved to {where} as a {note['kind']} (#{note['id']})." + (" It is in the rulebook." if label == "rulebook" else "")


async def save_growth_note(ctx: SkillContext, args: dict[str, Any]) -> str:
    return await _save(ctx, "growth", args)


async def add_work_note(ctx: SkillContext, args: dict[str, Any]) -> str:
    return await _save(ctx, "work", args)


async def search_notebook(ctx: SkillContext, args: dict[str, Any]) -> Any:
    spaces = [args["space"]] if args.get("space") else list(workspace.SPACES)
    out: list[dict[str, Any]] = []
    try:
        for space in spaces:
            for n in await workspace.list_notes(ctx.store, space, args.get("kind"), args.get("query"), limit=15):
                out.append({"id": n["id"], "space": n["space"], "kind": n["kind"], "title": n["title"] or None, "text": n["body"][:400], "tags": n["tags"]})
    except ExpenseError as exc:
        return str(exc)
    return out or "Nothing in your notebook matches that."


async def daily_principle(ctx: SkillContext, args: dict[str, Any]) -> Any:
    pick = await workspace.todays_pick(ctx.store, ctx.settings)
    if not pick:
        return "Your rulebook, lessons and quotes are empty. Save one first (for example: save this as a rule: …)."
    return {"kind": pick["kind"], "title": pick["title"] or None, "text": pick["body"]}


def register(registry: SkillRegistry) -> None:
    registry.add(
        "save_growth_note",
        "Save something to the user's personal-growth journal: a learning (something they just learned), a lesson (from an experience), "
        "a quote, a thought, or a rule (a personal rule for living, kept in their rulebook). Use when they say 'note this lesson', "
        "'save this quote', 'add a rule: …'. Keep their own wording.",
        schema({
            "kind": {"type": "string", "enum": list(workspace.GROWTH_KINDS)}, "text": {"type": "string", "description": "What to save, in the user's words."},
            "title": {"type": "string", "description": "Optional short title, or the source/author for a quote."}, "tags": {"type": "string", "description": "Optional, comma-separated."},
        }, ["kind", "text"]),
        save_growth_note,
    )
    registry.add(
        "add_work_note",
        "Save a work note, plan, meeting note or idea to the user's Work section. For something to DO use add_task instead.",
        schema({
            "kind": {"type": "string", "enum": list(workspace.WORK_KINDS)}, "text": {"type": "string"},
            "title": {"type": "string"}, "tags": {"type": "string", "description": "Optional, comma-separated."},
        }, ["text"]),
        add_work_note,
    )
    registry.add(
        "search_notebook",
        "Search the user's work notes and growth journal (learnings, lessons, quotes, thoughts, rules) by text or tag. Use for 'what did I learn about …', "
        "'what are my rules about …', 'my notes on the Q3 plan'.",
        schema({
            "query": {"type": "string"}, "space": {"type": "string", "enum": list(workspace.SPACES)},
            "kind": {"type": "string", "description": "Optional kind filter (needs `space`)."},
        }),
        search_notebook,
    )
    registry.add(
        "daily_principle",
        "One rule, quote or lesson from the user's growth journal for today (the same one all day). Use for 'remind me of my rules', 'a thought for today'.",
        schema(),
        daily_principle,
    )
