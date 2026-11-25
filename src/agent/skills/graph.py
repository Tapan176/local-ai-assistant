"""Chat skills for the memory graph: remember how people, places and things connect, and look connections up."""

from __future__ import annotations

from typing import Any

from src.agent import graph
from src.agent.expenses import ExpenseError
from src.agent.skill import SkillContext, SkillRegistry, schema


async def link_entities(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        got = await graph.link(ctx.store, args.get("a") or "", args.get("relation") or "", args.get("b") or "",
                               args.get("a_kind"), args.get("b_kind"), args.get("note") or "")
    except ExpenseError as exc:
        return str(exc)
    return f"Remembered: {got['a']} → {got['relation']} → {got['b']}."


async def describe_entity(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        node = await graph.upsert_node(ctx.store, args.get("name") or "", args.get("kind"), args.get("summary") or "")
    except ExpenseError as exc:
        return str(exc)
    return f"Remembered about {node['name']} ({node['kind']}): {node['summary'] or 'no description yet'}."


async def recall_connections(ctx: SkillContext, args: dict[str, Any]) -> Any:
    try:
        return await graph.connections(ctx.store, args.get("name") or "")
    except ExpenseError as exc:
        return str(exc)


async def forget_entity(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        node = await graph.find_node(ctx.store, args.get("name") or "")
        name = await graph.forget_node(ctx.store, int(node["id"]))
    except ExpenseError as exc:
        return str(exc)
    return f"Forgot {name} and everything connected to it."


def register(registry: SkillRegistry) -> None:
    registry.add(
        "link_entities",
        "Remember how two people, places, organisations, projects or things are connected, as a short relation: ('Priya', 'works at', 'Acme'), "
        "('Rahul', 'brother of', 'the user'), ('Atlas', 'reports to', 'Meera'). Use it when the user tells you a lasting fact about someone or something "
        "in their life, not for passing remarks. Say the user as 'the user'. Names are matched ignoring case, so reuse the same spelling.",
        schema({
            "a": {"type": "string"}, "relation": {"type": "string", "description": "Short verb phrase such as 'works at', 'lives in', 'owes', 'mentor of'."},
            "b": {"type": "string"}, "a_kind": {"type": "string", "enum": list(graph.KINDS)}, "b_kind": {"type": "string", "enum": list(graph.KINDS)},
            "note": {"type": "string", "description": "Optional detail about this connection (a date, a condition)."},
        }, ["a", "relation", "b"]),
        link_entities,
    )
    registry.add(
        "describe_entity",
        "Store or update a one-line description of a person, place, organisation, project or thing the user mentions "
        "('Priya: college friend, vegetarian, birthday 12 March'). Use when they tell you something lasting about it that is not a connection.",
        schema({"name": {"type": "string"}, "summary": {"type": "string", "description": "One short line."}, "kind": {"type": "string", "enum": list(graph.KINDS)}}, ["name", "summary"]),
        describe_entity,
    )
    registry.add(
        "recall_connections",
        "Everything stored about one person, place or thing and what it is connected to (two steps out). Use for 'what do you know about …', "
        "'how do I know …', 'who is …'.",
        schema({"name": {"type": "string"}}, ["name"]),
        recall_connections,
    )
    registry.add(
        "forget_entity",
        "Delete a person, place or thing from the memory graph together with its connections. Only when the user asks you to forget it.",
        schema({"name": {"type": "string"}}, ["name"]),
        forget_entity,
    )
