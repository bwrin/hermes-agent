"""Shared helpers for daily chore email design variants."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEDULE_PATH = BASE_DIR / "household_schedule.json"

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MAX_W = 420

BRANDON = "#E5654A"
KALEAH = "#2F9F86"


def load_schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def accent_for(person: str, participants: dict) -> str:
    return participants.get(person, {}).get("accent", "#71717A")


def full_date_label(d: date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def render_daily_text(day_data: dict) -> str:
    d = date.fromisoformat(day_data["date"])
    lines = [
        f"Today's chores — Week {day_data['week_label']}",
        full_date_label(d),
        "",
    ]
    for a in day_data["assignments"]:
        lines.append(f"  {a['person']}: {a['chore']}")
    lines.append("")
    lines.append("Rotates next week.")
    return "\n".join(lines)


def email_shell(body_inner: str, *, canvas: str, title: str = "Chores") -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title></head>"
        f'<body style="margin:0;padding:0;background:{canvas};">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{canvas};">'
        f'<tr><td align="center" style="padding:32px 16px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{MAX_W}" style="max-width:{MAX_W}px;width:100%;">'
        f"{body_inner}"
        f"</table></td></tr></table></body></html>"
    )
