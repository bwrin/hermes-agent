"""Deterministic A/B chore rotation for America/Indiana/Indianapolis."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_PATH = BASE_DIR / "household_schedule.json"
TZ = ZoneInfo("America/Indiana/Indianapolis")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def _load_schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def today_local() -> date:
    return datetime.now(TZ).date()


def monday_of(d: date) -> date:
    """Return the Monday of the week containing d (Mon=0)."""
    return d - timedelta(days=d.weekday())


def week_label(d: date, schedule: dict | None = None) -> str:
    """Return 'A' or 'B' for the week containing d, from the confirmed anchor."""
    schedule = schedule or _load_schedule()
    anchor = schedule["rotation_anchor"]
    anchor_monday = date.fromisoformat(anchor["monday"])
    anchor_week = anchor["week"]
    this_monday = monday_of(d)
    weeks_since = (this_monday - anchor_monday).days // 7
    if weeks_since % 2 == 0:
        return anchor_week
    return "B" if anchor_week == "A" else "A"


def assignments_for_week(monday: date, schedule: dict | None = None) -> dict:
    """
    Return Mon–Fri assignments for the week starting at monday.
    Week A: Brandon = first chore listed, Kaleah = second.
    Week B: swap owners (Brandon gets second, Kaleah gets first).
    Rows always ordered Brandon then Kaleah for email layout.
    """
    schedule = schedule or _load_schedule()
    if monday.weekday() != 0:
        monday = monday_of(monday)
    label = week_label(monday, schedule)
    chores = schedule["weekday_chores"]
    icons = schedule["chore_icons"]
    days: dict = {}
    for day_name in _WEEKDAYS:
        chore_pair = chores[day_name]
        if label == "A":
            brandon_chore, kaleah_chore = chore_pair[0], chore_pair[1]
        else:
            brandon_chore, kaleah_chore = chore_pair[1], chore_pair[0]
        days[day_name] = [
            {
                "person": "Brandon",
                "chore": brandon_chore,
                "icon": icons.get(brandon_chore, "home"),
            },
            {
                "person": "Kaleah",
                "chore": kaleah_chore,
                "icon": icons.get(kaleah_chore, "home"),
            },
        ]
    return {
        "week_label": label,
        "monday": monday.isoformat(),
        "friday": (monday + timedelta(days=4)).isoformat(),
        "days": days,
    }


def assignments_for_day(d: date, schedule: dict | None = None) -> dict | None:
    """Today's two assignments, or None on weekend. Never invents weekend chores."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return None
    schedule = schedule or _load_schedule()
    week = assignments_for_week(monday_of(d), schedule)
    day_name = d.strftime("%A")
    return {
        "week_label": week["week_label"],
        "date": d.isoformat(),
        "weekday": day_name,
        "assignments": week["days"][day_name],
    }


def parse_force_date(s: str | None) -> date:
    if not s:
        return today_local()
    return date.fromisoformat(s)
