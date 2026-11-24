"""Recurrence arithmetic: DST, month ends, leap days, weekends, long gaps, validation and wording."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.agent import recurrence as rec
from src.agent.recurrence import Rule, RuleError, build_rule, describe, latest_and_next, next_after, step

KOL = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def at(y, mo, d, h=9, mi=0, tz=KOL):
    return datetime(y, mo, d, h, mi, tzinfo=tz)


# ── validation ──────────────────────────────────────────────────────
@pytest.mark.parametrize("value", [None, "", "none", "once", "No", "never", False])
def test_no_repeat_means_one_off(value):
    assert build_rule(value) is None


@pytest.mark.parametrize("spoken,canonical", [("day", "daily"), ("Daily", "daily"), ("everyday", "daily"), ("weekday", "weekdays"), ("workdays", "weekdays"),
                                              ("week", "weekly"), ("MONTHLY", "monthly"), ("annually", "yearly")])
def test_common_spellings_are_accepted(spoken, canonical):
    assert build_rule(spoken, anchor=at(2026, 11, 24)).repeat == canonical


@pytest.mark.parametrize("repeat,every,days,message", [
    ("hourly", 1, None, "Unsupported repeat"), ("daily", 0, None, "between 1"), ("daily", -2, None, "between 1"), ("daily", 9999, None, "between 1"),
    ("daily", "abc", None, "whole number"), ("weekdays", 2, None, "cannot be combined"), ("daily", 1, ["mon"], "only applies to weekly"),
    ("weekly", 1, ["blursday"], "weekday"), ("weekly", 1, [9], "out of range"),
])
def test_bad_rules_are_rejected_with_a_message(repeat, every, days, message):
    with pytest.raises(RuleError, match=message):
        build_rule(repeat, every, days, anchor=at(2026, 11, 24))


def test_weekly_days_accept_names_numbers_and_strings():
    anchor = at(2026, 11, 24)                                              # a Tuesday
    assert build_rule("weekly", 1, ["Mon", "thursday"]).days == (0, 3)
    assert build_rule("weekly", 1, "mon, wed fri").days == (0, 2, 4)
    assert build_rule("weekly", 1, [6, "0"]).days == (0, 6)
    assert build_rule("weekly", 1, None, anchor=anchor).days == (1,)         # no days given: the weekday of the first occurrence


def test_rules_survive_a_json_round_trip_and_garbage_is_ignored():
    rule = build_rule("monthly", 2, None, anchor=at(2026, 1, 31))
    assert Rule.from_json(rule.to_json()) == rule and rule.day == 31
    for junk in (None, "", "not json", "{}", '{"repeat": 5, "every": "x"}', "[1,2]"):
        assert Rule.from_json(junk) is None


# ── daily / weekdays ────────────────────────────────────────────────
def test_daily_and_every_n_days():
    due = at(2026, 11, 24)
    assert step(Rule("daily"), due, KOL) == at(2026, 11, 25)
    assert step(Rule("daily", 3), due, KOL) == at(2026, 11, 27)
    assert step(Rule("daily"), at(2026, 12, 31), KOL) == at(2027, 1, 1)


def test_weekdays_skip_the_weekend():
    friday = at(2026, 11, 27)
    assert friday.weekday() == 4
    assert step(Rule("weekdays"), friday, KOL) == at(2026, 11, 30)          # Monday
    assert step(Rule("weekdays"), at(2026, 11, 24), KOL) == at(2026, 11, 25)


def test_daylight_saving_never_shifts_the_hour():
    before = at(2026, 3, 7, 9, 0, NY)                                         # the day before US clocks spring forward
    nxt = step(Rule("daily"), before, NY)
    assert nxt.hour == 9 and nxt.date().isoformat() == "2026-03-08" and nxt.utcoffset() != before.utcoffset()
    fall = at(2026, 10, 31, 9, 0, NY)
    assert step(Rule("daily"), fall, NY).hour == 9 and step(Rule("daily"), step(Rule("daily"), fall, NY), NY).hour == 9


def test_a_wall_clock_time_that_does_not_exist_is_still_a_valid_instant():
    gap = at(2026, 3, 7, 2, 30, NY)                                           # 02:30 does not exist on 2026-03-08 in New York
    nxt = step(Rule("daily"), gap, NY)
    assert nxt.date().isoformat() == "2026-03-08" and nxt > gap


# ── weekly ──────────────────────────────────────────────────────────
def test_weekly_on_several_days_walks_through_the_week():
    rule = build_rule("weekly", 1, ["mon", "thu"])
    cur = at(2026, 11, 23)                                                     # Monday
    seen = []
    for _ in range(4):
        cur = step(rule, cur, KOL)
        seen.append((cur.strftime("%a"), cur.day))
    assert seen == [("Thu", 26), ("Mon", 30), ("Thu", 3), ("Mon", 7)]


def test_every_other_week_keeps_its_rhythm():
    anchor = at(2026, 11, 24)                                                  # Tue: weeks of Nov 23 and Dec 7, Dec 21 …
    rule = build_rule("weekly", 2, ["tue"], anchor=anchor)
    cur, got = anchor, []
    for _ in range(3):
        cur = step(rule, cur, KOL, anchor)
        got.append(cur.date().isoformat())
    assert got == ["2026-12-08", "2026-12-22", "2027-01-05"]


def test_every_other_week_with_two_days_stays_in_the_right_weeks():
    anchor = at(2026, 11, 23)                                                  # Monday of an "on" week
    rule = build_rule("weekly", 2, ["mon", "wed"], anchor=anchor)
    cur, got = anchor, []
    for _ in range(4):
        cur = step(rule, cur, KOL, anchor)
        got.append(cur.strftime("%b%d"))
    assert got == ["Nov25", "Dec07", "Dec09", "Dec21"]


# ── monthly / yearly ────────────────────────────────────────────────
def test_monthly_on_the_31st_clamps_without_drifting():
    rule = build_rule("monthly", 1, None, anchor=at(2026, 1, 31))
    cur, got = at(2026, 1, 31), []
    for _ in range(5):
        cur = step(rule, cur, KOL)
        got.append(cur.date().isoformat())
    assert got == ["2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"]     # March is the 31st again, not the 28th


def test_monthly_leap_year_and_every_n_months_and_year_wrap():
    rule = build_rule("monthly", 1, None, anchor=at(2028, 1, 30))
    assert step(rule, at(2028, 1, 30), KOL).date().isoformat() == "2028-02-29"
    quarterly = build_rule("monthly", 3, None, anchor=at(2026, 11, 15))
    assert step(quarterly, at(2026, 11, 15), KOL).date().isoformat() == "2027-02-15"


def test_yearly_including_a_leap_day():
    rule = build_rule("yearly", 1, None, anchor=at(2028, 2, 29))
    cur, got = at(2028, 2, 29), []
    for _ in range(4):
        cur = step(rule, cur, KOL)
        got.append(cur.date().isoformat())
    assert got == ["2029-02-28", "2030-02-28", "2031-02-28", "2032-02-29"]                   # the leap day returns in a leap year


# ── catching up after downtime ──────────────────────────────────────
def test_a_long_outage_fires_once_and_schedules_the_future():
    rule = Rule("daily")
    due, now = at(2026, 11, 1), at(2026, 11, 24, 10, 0)
    latest, nxt = latest_and_next(rule, due, now, KOL)
    assert latest == at(2026, 11, 24) and nxt == at(2026, 11, 25)                              # one notification for the latest missed day
    assert next_after(rule, due, now, KOL) == nxt


def test_an_occurrence_exactly_at_now_counts_as_due_and_the_next_is_strictly_later():
    rule = Rule("daily")
    latest, nxt = latest_and_next(rule, at(2026, 11, 24), at(2026, 11, 24), KOL)
    assert latest == at(2026, 11, 24) and nxt == at(2026, 11, 25) and nxt > at(2026, 11, 24)


def test_years_of_downtime_are_computed_quickly():
    start = time.perf_counter()
    latest, nxt = latest_and_next(Rule("daily"), at(2016, 1, 1), at(2026, 11, 24, 10), KOL)
    assert latest == at(2026, 11, 24) and time.perf_counter() - start < 2.0


def test_next_after_is_always_in_the_future_for_every_rule_kind():
    now = at(2026, 11, 24, 12, 30)
    anchor = at(2026, 6, 15)
    rules = [Rule("daily"), Rule("daily", 5), Rule("weekdays"), build_rule("weekly", 1, ["mon", "fri"], anchor=anchor),
             build_rule("weekly", 3, ["sun"], anchor=anchor), build_rule("monthly", 1, None, anchor=at(2026, 6, 31 - 1)),
             build_rule("monthly", 2, None, anchor=anchor), build_rule("yearly", 1, None, anchor=anchor)]
    for rule in rules:
        due = at(2026, 6, 15)
        nxt = next_after(rule, due, now, KOL, anchor)
        assert nxt > now and nxt.hour == 9 and nxt.minute == 0, rule


# ── wording ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("rule,text", [
    (None, None), (Rule("daily"), "every day"), (Rule("daily", 3), "every 3 days"), (Rule("weekdays"), "every weekday"),
    (Rule("weekly", 1, (0, 3)), "every week on Mon, Thu"), (Rule("weekly", 2, (1,)), "every 2 weeks on Tue"),
    (Rule("monthly", 1, (), 1), "every month on the 1st"), (Rule("monthly", 1, (), 22), "every month on the 22nd"),
    (Rule("monthly", 2, (), 3), "every 2 months on the 3rd"), (Rule("monthly", 1, (), 11), "every month on the 11th"),
    (Rule("yearly"), "every year"), (Rule("yearly", 2), "every 2 years"),
])
def test_descriptions(rule, text):
    assert describe(rule) == text


def test_dst_is_respected_for_fixed_offset_input_as_stored_in_the_database():
    """The DB stores ISO strings with a fixed offset ('-05:00'), not a zone. Naive `+ timedelta` on those would drift an hour."""
    stored = datetime.fromisoformat("2026-03-07T09:00:00-05:00")              # what ReminderTool/skills persist
    assert stored.tzinfo is not NY and stored.utcoffset() == timedelta(hours=-5)
    nxt = step(Rule("daily"), stored, NY)
    assert nxt.hour == 9 and nxt.utcoffset() == timedelta(hours=-4)           # 09:00 EDT, not 10:00
    weekly = step(build_rule("weekly", 1, ["sun"]), datetime.fromisoformat("2026-03-01T09:00:00-05:00"), NY)
    assert weekly.hour == 9 and weekly.date().isoformat() == "2026-03-08"
    assert latest_and_next(Rule("daily"), stored, datetime(2026, 3, 10, 12, tzinfo=NY), NY)[0].hour == 9
