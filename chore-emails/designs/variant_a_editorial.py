"""Variant A — refined spare zinc / editorial list (cool gray, thin accent rules)."""

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

# Cool zinc editorial palette
CANVAS = "#F4F4F5"
SURFACE = "#FFFFFF"
BORDER = "#E4E4E7"
RULE = "#E4E4E7"
TEXT = "#18181B"
SECONDARY = "#71717A"
MUTED = "#A1A1AA"
ACCENT_RULE = "#D4D4D8"


def _meta(text: str) -> str:
    return (
        f'<div style="font-family:{FONT};font-size:10px;font-weight:600;'
        f'letter-spacing:0.16em;text-transform:uppercase;color:{MUTED};'
        f'margin:0 0 14px 0;">{esc(text)}</div>'
    )


def _title(text: str) -> str:
    return (
        f'<div style="font-family:{FONT};font-size:28px;font-weight:700;'
        f'color:{TEXT};letter-spacing:-0.035em;line-height:1.15;'
        f'margin:0 0 8px 0;">{text}</div>'
    )


def _subtitle(text: str) -> str:
    return (
        f'<div style="font-family:{FONT};font-size:14px;font-weight:400;'
        f'color:{SECONDARY};margin:0 0 8px 0;line-height:1.4;">'
        f"{esc(text)}</div>"
    )


def _hairline() -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="margin:20px 0 4px 0;">'
        f'<tr><td style="height:1px;line-height:1px;font-size:0;background:{ACCENT_RULE};">'
        f"&nbsp;</td></tr></table>"
    )


def _person_row(person: str, chore: str, participants: dict, *, show_rule: bool) -> str:
    accent = accent_for(person, participants)
    top = f"border-top:1px solid {RULE};" if show_rule else ""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="{top}">'
        f"<tr>"
        f'<td width="2" style="width:2px;background:{accent};'
        f'font-size:0;line-height:0;">&nbsp;</td>'
        f'<td style="padding:18px 0 18px 16px;" valign="middle">'
        f'<div style="font-family:{FONT};color:{accent};font-size:12px;'
        f'font-weight:600;letter-spacing:0.04em;text-transform:uppercase;'
        f'margin:0 0 4px 0;">{esc(person)}</div>'
        f'<div style="font-family:{FONT};color:{TEXT};font-size:17px;'
        f'font-weight:600;letter-spacing:-0.02em;line-height:1.35;">'
        f"{esc(chore)}</div>"
        f"</td></tr></table>"
    )


def _footer() -> str:
    return (
        f'<div style="font-family:{FONT};font-size:11px;color:{MUTED};'
        f'text-align:center;padding:18px 8px 0 8px;letter-spacing:0.02em;">'
        f"Rotates next week</div>"
    )


def render_daily_html(day_data: dict, schedule: dict | None = None) -> str:
    schedule = schedule or load_schedule()
    participants = schedule["participants"]
    label = day_data["week_label"]
    d = date.fromisoformat(day_data["date"])

    header = (
        f"{_meta(f'Week {label} · Daily')}"
        f"{_title('Today')}"
        f"{_subtitle(full_date_label(d))}"
        f"{_hairline()}"
    )

    blocks = "".join(
        _person_row(
            a["person"],
            a["chore"],
            participants,
            show_rule=(i > 0),
        )
        for i, a in enumerate(day_data["assignments"])
    )

    card = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{SURFACE};border:1px solid {BORDER};'
        f'border-radius:10px;">'
        f'<tr><td style="padding:30px 26px 22px 26px;">{header}{blocks}</td></tr>'
        f"</table>"
    )
    body = f"<tr><td>{card}</td></tr><tr><td>{_footer()}</td></tr>"
    return email_shell(body, canvas=CANVAS, title="Today's Chores")
