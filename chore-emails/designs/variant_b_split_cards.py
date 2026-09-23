"""Variant B — modern split soft person cards (coral / sage tints, rounder, friendly)."""

from __future__ import annotations

from datetime import date

from .common import (
    BRANDON,
    FONT,
    KALEAH,
    accent_for,
    email_shell,
    esc,
    full_date_label,
    load_schedule,
)

CANVAS = "#FAFAF9"
SURFACE = "#FFFFFF"
BORDER = "#E7E5E4"
TEXT = "#1C1917"
SECONDARY = "#78716C"
MUTED = "#A8A29E"

# Soft tinted card backgrounds (not cottage oat — contemporary pastels)
CARD_BG = {
    "Brandon": "#FFF5F2",  # coral-tinted
    "Kaleah": "#F0FAF7",   # sage-tinted
}
CARD_BORDER = {
    "Brandon": "#F5D5CC",
    "Kaleah": "#C8E8DE",
}


def _header_block(label: str, date_str: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="margin:0 0 20px 0;">'
        f'<tr><td style="padding:0 4px;">'
        f'<div style="font-family:{FONT};font-size:11px;font-weight:600;'
        f'letter-spacing:0.12em;text-transform:uppercase;color:{MUTED};'
        f'margin:0 0 10px 0;">Week {esc(label)}</div>'
        f'<div style="font-family:{FONT};font-size:24px;font-weight:700;'
        f'color:{TEXT};letter-spacing:-0.03em;line-height:1.2;margin:0 0 6px 0;">'
        f"Today&rsquo;s chores</div>"
        f'<div style="font-family:{FONT};font-size:14px;color:{SECONDARY};'
        f'line-height:1.4;">{esc(date_str)}</div>'
        f"</td></tr></table>"
    )


def _person_card(person: str, chore: str, participants: dict) -> str:
    accent = accent_for(person, participants)
    bg = CARD_BG.get(person, "#F5F5F4")
    border = CARD_BORDER.get(person, BORDER)
    # Soft round pill initial as minimal mark
    initial = esc(person[:1])
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{bg};border:1px solid {border};'
        f'border-radius:16px;margin:0 0 12px 0;">'
        f'<tr><td style="padding:20px 18px;" valign="middle">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
        f"<tr>"
        f'<td width="40" valign="middle" style="padding-right:14px;">'
        f'<div style="width:36px;height:36px;border-radius:18px;background:{accent};'
        f'text-align:center;line-height:36px;font-family:{FONT};font-size:15px;'
        f'font-weight:700;color:#FFFFFF;">{initial}</div>'
        f"</td>"
        f'<td valign="middle">'
        f'<div style="font-family:{FONT};color:{accent};font-size:13px;'
        f'font-weight:700;margin:0 0 4px 0;">{esc(person)}</div>'
        f'<div style="font-family:{FONT};color:{TEXT};font-size:16px;'
        f'font-weight:600;letter-spacing:-0.015em;line-height:1.35;">'
        f"{esc(chore)}</div>"
        f"</td></tr></table>"
        f"</td></tr></table>"
    )


def _footer() -> str:
    return (
        f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};'
        f'text-align:center;padding:8px 8px 0 8px;line-height:1.4;">'
        f"Rotates next week</div>"
    )


def render_daily_html(day_data: dict, schedule: dict | None = None) -> str:
    schedule = schedule or load_schedule()
    participants = schedule["participants"]
    label = day_data["week_label"]
    d = date.fromisoformat(day_data["date"])

    # Outer soft white frame
    cards = "".join(
        _person_card(a["person"], a["chore"], participants)
        for a in day_data["assignments"]
    )
    inner = _header_block(label, full_date_label(d)) + cards

    frame = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{SURFACE};border:1px solid {BORDER};'
        f'border-radius:20px;">'
        f'<tr><td style="padding:26px 20px 18px 20px;">{inner}</td></tr>'
        f"</table>"
    )
    # Tiny dual-dot accent under header area for friendliness (inline in footer zone)
    dual = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'align="center" style="margin:16px auto 0 auto;">'
        f"<tr>"
        f'<td style="width:8px;height:8px;border-radius:4px;background:{BRANDON};'
        f'font-size:0;line-height:0;">&nbsp;</td>'
        f'<td style="width:6px;font-size:0;">&nbsp;</td>'
        f'<td style="width:8px;height:8px;border-radius:4px;background:{KALEAH};'
        f'font-size:0;line-height:0;">&nbsp;</td>'
        f"</tr></table>"
    )
    body = (
        f"<tr><td>{frame}</td></tr>"
        f"<tr><td>{dual}{_footer()}</td></tr>"
    )
    return email_shell(body, canvas=CANVAS, title="Today's Chores")
