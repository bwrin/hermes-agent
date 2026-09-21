"""Warm Kitchen chore email renderer — light cream/oat, table layout, inline CSS."""

from __future__ import annotations

import base64
import io
import json
import sys
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_PATH = BASE_DIR / "household_schedule.json"
ICONS_DIR = BASE_DIR / "icons"

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
MAX_W = 420

# Soft cream Warm Kitchen (not zinc / not dark editorial)
DEFAULT_COLORS = {
    "oat": "#F4EEE2",
    "white": "#FFFFFF",
    "border": "#EFE7DA",
    "rule": "#F0E9DC",
    "text": "#2C2620",
    "secondary": "#5A4F42",
    "muted": "#8A7C6B",
    "footer_muted": "#A4967F",
    "pill_bg": "#EFE4D2",
    "pill_accent": "#A8785A",
}


def _load_schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _colors(schedule: dict) -> dict:
    c = dict(DEFAULT_COLORS)
    c.update(schedule.get("colors") or {})
    return c


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _short_month_day(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def weekly_subject(week_label: str, monday: date) -> str:
    friday = monday + timedelta(days=4)
    return (
        f"This Week's Chores — Week {week_label} — "
        f"{_short_month_day(monday)}–{_short_month_day(friday)}"
    )


def daily_subject(d: date) -> str:
    return f"Today's Chores — {d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _ensure_pil():
    try:
        from PIL import Image  # noqa: F401
        return
    except ImportError:
        venv_site = BASE_DIR / ".venv" / "lib"
        if venv_site.exists():
            for p in venv_site.glob("python*/site-packages"):
                sp = str(p)
                if sp not in sys.path:
                    sys.path.insert(0, sp)
        from PIL import Image  # noqa: F401


@lru_cache(maxsize=128)
def _icon_data_uri(name: str, tint_hex: str, encode_px: int | None = None) -> str:
    """Load monochrome icon mask, recolor, optionally downscale for email size."""
    _ensure_pil()
    from PIL import Image

    path = ICONS_DIR / f"{name}.png"
    if not path.exists():
        path = ICONS_DIR / "home.png"
    im = Image.open(path).convert("RGBA")
    r, g, b = _hex_rgb(tint_hex)
    pixels = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            pr, pg, pb, pa = pixels[x, y]
            if pa == 0:
                continue
            # Treat near-opaque dark mask as tint; preserve anti-alias alpha
            pixels[x, y] = (r, g, b, pa)
    if encode_px and (w != encode_px or h != encode_px):
        # 2× display size keeps retina sharp while shrinking base64 a lot vs 128px
        im = im.resize((encode_px, encode_px), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _img(name: str, tint: str, width: int, height: int, alt: str = "") -> str:
    # Encode at CSS display size (sources are 128px; downscale keeps HTML small for Apple Mail)
    encode_px = max(width, height)
    src = _icon_data_uri(name, tint, encode_px)
    return (
        f'<img src="{src}" width="{width}" height="{height}" '
        f'alt="{_esc(alt or name)}" style="display:inline-block;margin:0;vertical-align:middle;border:0;outline:none;" />'
    )


def _week_pill(label: str, colors: dict) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td bgcolor="{colors["pill_bg"]}" style="background-color:{colors["pill_bg"]}!important;'
        f'border-radius:999px;padding:6px 12px;">'
        f'<span style="font-family:{FONT};font-size:11px;font-weight:700;'
        f"letter-spacing:0.08em;text-transform:uppercase;"
        f"color:{colors['pill_accent']};\">WEEK {_esc(label)}</span>"
        f"</td></tr></table>"
    )


def _header_block(
    week_label: str,
    title: str,
    subtitle: str,
    colors: dict,
) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%">'
        f'<tr><td style="padding:0 0 14px 0;">{_week_pill(week_label, colors)}</td></tr>'
        f'<tr><td style="font-family:{FONT};font-size:28px;font-weight:700;'
        f"color:{colors['text']};letter-spacing:-0.02em;line-height:1.2;"
        f'padding:0 0 6px 0;">{_esc(title)}</td></tr>'
        f'<tr><td style="font-family:{FONT};font-size:14px;font-weight:400;'
        f"color:{colors['muted']};line-height:1.4;padding:0 0 22px 0;\">"
        f"{_esc(subtitle)}</td></tr>"
        f"</table>"
    )


def _outline_checkbox(accent: str, size: int = 22) -> str:
    """Empty circular outline in person accent — CSS only, email-safe."""
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f"border:2px solid {accent};background:#FFFFFF;background-color:#FFFFFF!important;"
        f'box-sizing:border-box;">&nbsp;</div>'
    )


def _person_row(
    person: str,
    chore: str,
    icon: str,
    participants: dict,
    colors: dict,
    *,
    compact: bool = False,
    show_rule: bool = False,
    icon_px: int | None = None,
    well: int | None = None,
) -> str:
    meta = participants.get(person, {})
    accent = meta.get("accent", "#E5654A")
    icon_tint = meta.get("icon_tint", "#FCEDE9")
    pad_y = "12px" if compact else "16px"
    if well is None:
        well = 44 if compact else 52
    if icon_px is None:
        icon_px = 28 if compact else 34
    check = 20 if compact else 22
    name_sz = "12px" if compact else "13px"
    chore_sz = "15px" if compact else "17px"
    top_rule = (
        f"border-top:1px solid {colors['rule']};" if show_rule else ""
    )
    icon_html = _img(icon, accent, icon_px, icon_px, icon)
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="{top_rule}">'
        f"<tr>"
        f'<td width="{check + 12}" valign="middle" style="padding:{pad_y} 10px '
        f'{pad_y} 0;width:{check + 12}px;">'
        f"{_outline_checkbox(accent, check)}"
        f"</td>"
        f'<td width="{well + 12}" valign="middle" style="padding:{pad_y} 12px '
        f'{pad_y} 0;width:{well + 12}px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{well}" height="{well}" style="border-radius:14px;">'
        f'<tr><td bgcolor="{icon_tint}" width="{well}" height="{well}" align="center" '
        f'valign="middle" style="background-color:{icon_tint}!important;width:{well}px;'
        f'height:{well}px;border-radius:14px;text-align:center;">'
        f"{icon_html}</td></tr></table>"
        f"</td>"
        f'<td valign="middle" style="padding:{pad_y} 0;">'
        f'<div style="font-family:{FONT};color:{accent};font-size:{name_sz};'
        f'font-weight:700;letter-spacing:0.08em;text-transform:uppercase;'
        f'margin:0 0 3px 0;">{_esc(person)}</div>'
        f'<div style="font-family:{FONT};color:{colors["text"]};font-size:{chore_sz};'
        f'font-weight:700;letter-spacing:-0.01em;line-height:1.3;">'
        f"{_esc(chore)}</div>"
        f"</td></tr></table>"
    )


def _card(inner: str, colors: dict, padding: str = "22px 20px") -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" bgcolor="{colors["white"]}" style="background-color:{colors["white"]}!important;'
        f'border:1px solid {colors["border"]};border-radius:20px;">'
        f'<tr><td bgcolor="{colors["white"]}" style="background-color:{colors["white"]}!important;'
        f'padding:{padding};">{inner}</td></tr></table>'
    )


def _switch_pill(colors: dict) -> str:
    rotate = _img("rotate", colors["pill_accent"], 14, 14, "rotate")
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%"><tr><td align="center" style="padding:4px 0 0 0;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td bgcolor="{colors["pill_bg"]}" style="background-color:{colors["pill_bg"]}!important;'
        f'border-radius:999px;padding:10px 18px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td valign="middle" style="padding:0 8px 0 0;">{rotate}</td>'
        f'<td valign="middle" style="font-family:{FONT};font-size:12px;'
        f'font-weight:600;color:{colors["pill_accent"]};">'
        f"Assignments switch next week</td></tr></table>"
        f"</td></tr></table></td></tr></table>"
    )


def _brand_footer(colors: dict, *, kind: str, thanks: bool) -> str:
    home = _img("home", colors["footer_muted"], 12, 12, "home")
    # Brand footer label
    label = "Grok Team · Household"
    thanks_row = ""
    if thanks:
        thanks_row = (
            f'<tr><td align="center" style="font-family:{FONT};font-size:13px;'
            f'color:{colors["muted"]};padding:14px 8px 8px 8px;">'
            f"Thanks for keeping the house running.</td></tr>"
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%">'
        f"{thanks_row}"
        f'<tr><td align="center" style="padding:{"6px" if thanks else "16px"} 8px 0 8px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td valign="middle" style="padding:0 6px 0 0;">{home}</td>'
        f'<td valign="middle" style="font-family:{FONT};font-size:11px;'
        f'color:{colors["footer_muted"]};">{_esc(label)}</td>'
        f"</tr></table></td></tr></table>"
    )


def _shell(body_inner: str, colors: dict) -> str:
    oat = colors["oat"]
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<meta name="supported-color-schemes" content="light only">'
        '<style type="text/css">:root{color-scheme:light only;}'
        f'html,body{{background-color:{oat}!important;}}</style>'
        "<title>Chores</title></head>"
        f'<body bgcolor="{oat}" style="margin:0;padding:0;background-color:{oat}!important;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" bgcolor="{oat}" style="background-color:{oat}!important;">'
        f'<tr><td bgcolor="{oat}" align="center" style="padding:32px 16px;'
        f'background-color:{oat}!important;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{MAX_W}" bgcolor="{oat}" style="max-width:{MAX_W}px;width:100%;'
        f'background-color:{oat}!important;">'
        f"{body_inner}"
        f"</table></td></tr></table></body></html>"
    )


def render_weekly_html(week_data: dict, schedule: dict | None = None) -> str:
    """One-card weekly chart matching daily Warm Kitchen language (clipping-safe)."""
    schedule = schedule or _load_schedule()
    participants = schedule["participants"]
    colors = _colors(schedule)
    label = week_data["week_label"]
    monday = date.fromisoformat(week_data["monday"])
    friday = date.fromisoformat(week_data["friday"])

    header = _header_block(
        label,
        "This week's chores",
        f"{_short_month_day(monday)} – {_short_month_day(friday)}",
        colors,
    )

    day_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    days = week_data.get("days") or {}
    sections: list[str] = []
    for i, day_name in enumerate(day_names):
        rows = days.get(day_name) or []
        # Hairline between days (not before Monday)
        day_top = ""
        if i > 0:
            day_top = (
                f"border-top:1px solid {colors['rule']};"
                f"padding-top:14px;margin-top:2px;"
            )
        day_hdr = (
            f'<div style="font-family:{FONT};font-size:11px;font-weight:600;'
            f'letter-spacing:0.12em;text-transform:uppercase;'
            f'color:{colors["muted"]};padding:0 0 8px 0;">'
            f"{_esc(day_name.upper())}</div>"
        )
        # Full-size row language (not compact) — slightly smaller icons for clipping budget
        blocks = "".join(
            _person_row(
                a["person"],
                a["chore"],
                a.get("icon", "home"),
                participants,
                colors,
                compact=False,
                show_rule=(j > 0),
                icon_px=28,
                well=52,  # keep well size so icons stay centered like daily
            )
            for j, a in enumerate(rows)
        )
        sections.append(f'<div style="{day_top}">{day_hdr}{blocks}</div>')

    card = _card("".join(sections), colors, padding="20px 18px 14px 18px")

    body = (
        f"<tr><td>{header}</td></tr>"
        f"<tr><td>{card}</td></tr>"
        f'<tr><td style="padding:16px 0 0 0;">{_switch_pill(colors)}</td></tr>'
        f"<tr><td>{_brand_footer(colors, kind='weekly', thanks=True)}</td></tr>"
    )
    return _shell(body, colors)


def render_daily_html(day_data: dict, schedule: dict | None = None) -> str:
    schedule = schedule or _load_schedule()
    participants = schedule["participants"]
    colors = _colors(schedule)
    label = day_data["week_label"]
    d = date.fromisoformat(day_data["date"])
    full = f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"
    weekday = day_data.get("weekday") or d.strftime("%A")

    header = _header_block(label, "Today's chores", full, colors)

    day_hdr = (
        f'<div style="font-family:{FONT};font-size:11px;font-weight:600;'
        f'letter-spacing:0.12em;text-transform:uppercase;'
        f'color:{colors["muted"]};padding:0 0 8px 0;">'
        f"{_esc(weekday.upper())}</div>"
    )
    blocks = "".join(
        _person_row(
            a["person"],
            a["chore"],
            a.get("icon", "home"),
            participants,
            colors,
            show_rule=(i > 0),
        )
        for i, a in enumerate(day_data["assignments"])
    )
    card = _card(day_hdr + blocks, colors, padding="20px 18px 14px 18px")

    body = (
        f"<tr><td>{header}</td></tr>"
        f"<tr><td>{card}</td></tr>"
        f'<tr><td style="padding:16px 0 0 0;">{_switch_pill(colors)}</td></tr>'
        f"<tr><td>{_brand_footer(colors, kind='daily', thanks=False)}</td></tr>"
    )
    return _shell(body, colors)


def render_weekly_text(week_data: dict) -> str:
    lines = [
        f"Week {week_data['week_label']} chores",
        f"{week_data['monday']} – {week_data['friday']}",
        "",
    ]
    for day, rows in week_data["days"].items():
        lines.append(day)
        for a in rows:
            lines.append(f"  {a['person']}: {a['chore']}")
        lines.append("")
    lines.append("Assignments switch next week.")
    lines.append("Thanks for keeping the house running.")
    lines.append("Grok Team · Household")
    return "\n".join(lines)


def render_daily_text(day_data: dict) -> str:
    d = date.fromisoformat(day_data["date"])
    lines = [
        f"Today's chores — Week {day_data['week_label']}",
        f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}",
        "",
    ]
    for a in day_data["assignments"]:
        lines.append(f"  {a['person']}: {a['chore']}")
    lines.append("")
    lines.append("Assignments switch next week.")
    lines.append("Grok Team · Household")
    return "\n".join(lines)
