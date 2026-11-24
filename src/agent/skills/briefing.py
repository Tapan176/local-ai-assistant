"""Daily briefing: the "good morning, here is your day" skill (also exposed over the API)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.agent import recurrence, timeutil
from src.agent.skill import SkillContext, SkillRegistry, schema
from src.agent import weather


async def build_briefing(ctx: SkillContext) -> dict[str, Any]:
    now = ctx.now()
    today = now.strftime("%Y-%m-%d")
    store, settings = ctx.store, ctx.settings

    reminders = await store.fetchall(
        "SELECT id, title, due_at, recurrence FROM reminders WHERE status='pending' AND due_at IS NOT NULL ORDER BY due_at LIMIT 50"
    )
    overdue, upcoming, later = [], [], []
    for r in reminders:
        r["repeats"] = recurrence.describe(recurrence.Rule.from_json(r.pop("recurrence", None)))
        due = timeutil.as_aware(r["due_at"], settings)
        if due is None:
            continue
        if due <= now:
            overdue.append(r)
        elif due.strftime("%Y-%m-%d") == today:
            upcoming.append(r)
        elif len(later) < 8:  # rows are ordered by due date, so the first few are the soonest
            later.append(r)

    tasks = await store.fetchall(
        "SELECT id, title, due_at, priority FROM tasks WHERE status='open' "
        "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, due_at IS NULL, due_at LIMIT 10"
    )
    events = await store.fetchall(
        "SELECT title, start_at, location FROM calendar_events WHERE substr(start_at, 1, 10) = ? ORDER BY start_at",
        (today,),
    )

    briefing: dict[str, Any] = {
        "now": now.strftime("%A, %d %B %Y, %I:%M %p"),
        "overdue_reminders": overdue,
        "reminders_today": upcoming,
        "upcoming_reminders": later,
        "open_tasks": tasks,
        "events_today": events,
    }
    # Weather is a nice-to-have: it must never slow down or break the briefing, and when it is missing we say why.
    try:
        place = await asyncio.wait_for(weather.home_place(store, settings, ctx.http), timeout=8)
        briefing["home_location"] = weather.label(place) if place else None
        if place:
            briefing["weather"] = await asyncio.wait_for(weather.weather_text(ctx.http, place, days=1), timeout=8)
    except weather.WeatherError as exc:
        briefing["weather_error"] = str(exc)
    except asyncio.TimeoutError:
        briefing["weather_error"] = "The weather service is slow right now."
    briefing.setdefault("home_location", None)
    return briefing


async def daily_briefing(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    return await build_briefing(ctx)


def register(registry: SkillRegistry) -> None:
    registry.add(
        "daily_briefing",
        "Gather the user's day in one call: date/time, overdue and upcoming reminders, open tasks, today's events, "
        "weather. Use for 'good morning', 'what does my day look like', 'brief me', then summarise conversationally.",
        schema(),
        daily_briefing,
    )
