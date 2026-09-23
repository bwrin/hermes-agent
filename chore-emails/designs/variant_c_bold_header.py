"""Variant C — bold modern: near-black header band + clean white body list (app-like)."""

from __future__ import annotations

from datetime import date

from .common import (
    FONT,
    accent_for,
    email_shell,
    esc,
    full_date_label,
    load_schedule,
)

CANVAS = "#EDEDED"
HEADER_BG = "#111111"
SURFACE = "#FFFFFF"
BORDER = "#E5E5E5"
RULE = "#EFEFEF"
TEXT = "#111111"
SECONDARY = "#6B6B6B"
MUTED = "#9CA3AF"
ON_HEADER = "#FFFFFF"
ON_HEADER_MUTED = "#A3A3A3"


def _header_band(label: str, date_str: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{HEADER_BG};border-radius:14px 14px 0 0;">'
        f'<tr><td style="padding:28px 24px 26px 24px;">'
        f'<div style="font-family:{FONT};font-size:11px;font-weight:600;'
        f'letter-spacing:0.14em;text-transform:uppercase;color:{ON_HEADER_MUTED};'
        f'margin:0 0 12px 0;">Week {esc(label)}</div>'
        f'<div style="font-family:{FONT};font-size:26px;font-weight:800;'
        f'color:{ON_HEADER};letter-spacing:-0.04em;line-height:1.15;'
        f'margin:0 0 8px 0;">Today</div>'
        f'<div style="font-family:{FONT};font-size:14px;font-weight:400;'
        f'color:{ON_HEADER_MUTED};line-height:1.4;">{esc(date_str)}</div>'
        f"</td></tr></table>"
    )


def _person_row(person: str, chore: str, participants: dict, *, show_rule: bool) -> str:
    accent = accent_for(person, participants)
    top = f"border-top:1px solid {RULE};" if show_rule else ""
    # High-contrast app list: colored name chip + bold chore
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="{top}">'
        f'<tr><td style="padding:18px 0;" valign="middle">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
        f"<tr>"
        f'<td width="10" valign="top" style="padding-top:6px;">'
        f'<div style="width:8px;height:8px;border-radius:4px;background:{accent};'
        f'font-size:0;line-height:0;">&nbsp;</div>'
        f"</td>"
        f'<td style="padding-left:12px;" valign="middle">'
        f'<div style="font-family:{FONT};color:{accent};font-size:12px;'
        f'font-weight:700;letter-spacing:0.02em;margin:0 0 5px 0;">'
        f"{esc(person)}</div>"
        f'<div style="font-family:{FONT};color:{TEXT};font-size:17px;'
        f'font-weight:700;letter-spacing:-0.02em;line-height:1.3;">'
        f"{esc(chore)}</div>"
        f"</td></tr></table>"
        f"</td></tr></table>"
    )


def _body_list(assignments: list, participants: dict) -> str:
    rows = "".join(
        _person_row(
            a["person"],
            a["chore"],
            participants,
            show_rule=(i > 0),
        )
        for i, a in enumerate(assignments)
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{SURFACE};'
        f'border-radius:0 0 14px 14px;border:1px solid {BORDER};'
        f'border-top:none;">'
        f'<tr><td style="padding:8px 24px 20px 24px;">{rows}</td></tr>'
        f"</table>"
    )


def _footer() -> str:
    return (
        f'<div style="font-family:{FONT};font-size:11px;color:{MUTED};'
        f'text-align:center;padding:18px 8px 0 8px;letter-spacing:0.04em;'
        f'text-transform:uppercase;">Rotates next week</div>'
    )


def render_daily_html(day_data: dict, schedule: dict | None = None) -> str:
    schedule = schedule or load_schedule()
    participants = schedule["participants"]
    label = day_data["week_label"]
    d = date.fromisoformat(day_data["date"])

    card = (
        _header_band(label, full_date_label(d))
        + _body_list(day_data["assignments"], participants)
    )
    body = f"<tr><td>{card}</td></tr><tr><td>{_footer()}</td></tr>"
    return email_shell(body, canvas=CANVAS, title="Today's Chores")
