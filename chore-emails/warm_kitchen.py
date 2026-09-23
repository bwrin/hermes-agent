"""Warm Kitchen chore email renderer — light cream/oat, table layout, inline CSS."""

from __future__ import annotations

import base64
import io
import json
import struct
import sys
import zlib
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

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

# Apple Mail truncates long messages and Gmail clips past ~102KB; a clipped
# weekly chart is what made Week B look like it was missing days. Everything
# this module renders must stay under this, with room to spare.
HTML_BUDGET_BYTES = 50_000

# Person-row metrics — the approved daily language. Weekly reuses this row
# verbatim (no compact variant) so the two emails cannot drift apart.
ROW_PAD_Y = "16px"
ROW_WELL = 52
ROW_ICON = 34
ROW_CHECK = 22
ROW_NAME_SIZE = "13px"
ROW_CHORE_SIZE = "17px"

# Horizontal card padding. The weekly card applies it per day cell instead of
# on the card itself, so day dividers run edge to edge.
CARD_PAD_X = "18px"

# Soft cream Warm Kitchen (not zinc / not dark editorial)
DEFAULT_COLORS = {
    "oat": "#F4EEE2",
    "white": "#FFFFFF",
    "border": "#EFE7DA",
    "rule": "#F0E9DC",
    # Day-to-day divider on the weekly chart. A shade deeper than `rule` so a
    # day break never reads the same as the rule between one day's two people.
    "day_rule": "#E4D9C6",
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


def _week_range_label(monday: date, friday: date, *, sep: str = " – ") -> str:
    """'September 21 – 25', or 'September 28 – October 2' across a month break."""
    if monday.month == friday.month:
        return f"{monday.strftime('%B')} {monday.day}{sep}{friday.day}"
    return (
        f"{monday.strftime('%B')} {monday.day}{sep}"
        f"{friday.strftime('%B')} {friday.day}"
    )


def weekly_subject(week_label: str, monday: date) -> str:
    friday = monday + timedelta(days=4)
    return (
        f"This Week's Chores — Week {week_label} — "
        f"{_week_range_label(monday, friday, sep='–')}"
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


def _pad_png_to_multiple_of_3(png: bytes) -> bytes:
    """Append a tEXt chunk so ``len(png) % 3 == 0``.

    Base64 then needs no ``=`` padding. A trailing ``=`` inside a ``data:``
    URI is the difference that tracked the broken Cat Water icon: in the
    Wed 2026-09-23 message Apple Mail drew its "?" placeholder for the only
    PNG whose URI was padded, and rendered dishes, rotate, and home, which
    were not. The chunk is ancillary and sits just before IEND.
    """
    if len(png) % 3 == 0:
        return png
    iend_at = png.rfind(b"IEND")
    if iend_at < 4:
        raise ValueError("PNG missing IEND")
    need = (3 - (len(png) % 3)) % 3
    prefix = b"Comment\x00"
    extra = (need - (len(prefix) % 3)) % 3
    data = prefix + (b" " * extra)
    if len(data) % 3 != need:
        raise ValueError("tEXt pad length is wrong")
    chunk_type = b"tEXt"
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)
    out = png[: iend_at - 4] + chunk + png[iend_at - 4 :]
    if len(out) % 3 != 0:
        raise ValueError("padded PNG length is not a multiple of 3")
    return out


def _png_bytes_without_base64_padding(icon) -> bytes:
    """Encode ``icon`` so the base64 form contains no ``=`` padding."""

    def dump(*, optimize: bool, level: int | None) -> bytes:
        buf = io.BytesIO()
        kwargs: dict = {"format": "PNG", "optimize": optimize}
        if level is not None:
            kwargs["compress_level"] = level
        icon.save(buf, **kwargs)
        return buf.getvalue()

    primary = dump(optimize=True, level=None)
    if len(primary) % 3 == 0:
        return primary
    for level in range(9, -1, -1):
        raw = dump(optimize=False, level=level)
        if len(raw) % 3 == 0:
            return raw
    return _pad_png_to_multiple_of_3(primary)


@lru_cache(maxsize=128)
def _icon_data_uri(name: str, tint_hex: str, encode_px: int) -> str:
    """Recolor a monochrome icon mask to a person accent, encoded at display size.

    Sources are 128px masks; encoding at the size the email actually renders
    keeps each data URI near 1KB, which is what lets a ten-row weekly chart
    stay far below the Apple Mail / Gmail clipping thresholds. Cached, so an
    icon/tint pair is encoded once per process and every row that needs it
    reuses the identical URI string.

    Transparent pixels are (0, 0, 0, 0). Filling the whole frame with the
    accent and then swapping in the mask left the tint in every clear pixel,
    so a sparse glyph was a solid rectangle to any client that mishandles
    alpha. The file length is forced to a multiple of 3 so the data URI
    never ends in ``=`` — see ``_pad_png_to_multiple_of_3``.
    """
    _ensure_pil()
    from PIL import Image, ImageChops

    path = ICONS_DIR / f"{name}.png"
    if not path.exists():
        path = ICONS_DIR / "home.png"
    alpha = Image.open(path).convert("RGBA").getchannel("A")
    if alpha.width != encode_px or alpha.height != encode_px:
        alpha = alpha.resize((encode_px, encode_px), Image.Resampling.LANCZOS)
    r, g, b = _hex_rgb(tint_hex)
    rgb = Image.new("RGB", alpha.size, (r, g, b))
    # 255 on any ink, 0 on fully clear pixels. Partial alpha keeps a straight
    # (not premultiplied) tint; only a==0 is forced to black.
    ink = alpha.point(lambda a: 0 if a == 0 else 255)
    channels = [ImageChops.multiply(ch, ink) for ch in rgb.split()]
    icon = Image.merge("RGBA", (*channels, alpha))
    raw = _png_bytes_without_base64_padding(icon)
    b64 = base64.b64encode(raw).decode("ascii")
    if "=" in b64 or len(raw) % 3 != 0:
        raise RuntimeError(f"icon {name} data URI still needs base64 padding")
    return f"data:image/png;base64,{b64}"


def _img(name: str, tint: str, width: int, height: int, alt: str = "") -> str:
    src = _icon_data_uri(name, tint, max(width, height))
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


def _outline_checkbox(accent: str, size: int = ROW_CHECK) -> str:
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
    show_rule: bool = False,
) -> str:
    """One checkbox + tinted icon well + name/chore row, identical in both emails."""
    meta = participants.get(person, {})
    accent = meta.get("accent", "#E5654A")
    icon_tint = meta.get("icon_tint", "#FCEDE9")
    top_rule = (
        f"border-top:1px solid {colors['rule']};" if show_rule else ""
    )
    icon_html = _img(icon, accent, ROW_ICON, ROW_ICON, icon)
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="{top_rule}">'
        f"<tr>"
        f'<td width="{ROW_CHECK + 12}" valign="middle" style="padding:{ROW_PAD_Y} 10px '
        f'{ROW_PAD_Y} 0;width:{ROW_CHECK + 12}px;">'
        f"{_outline_checkbox(accent)}"
        f"</td>"
        f'<td width="{ROW_WELL + 12}" valign="middle" style="padding:{ROW_PAD_Y} 12px '
        f'{ROW_PAD_Y} 0;width:{ROW_WELL + 12}px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{ROW_WELL}" height="{ROW_WELL}" style="border-radius:14px;">'
        f'<tr><td bgcolor="{icon_tint}" width="{ROW_WELL}" height="{ROW_WELL}" align="center" '
        f'valign="middle" style="background-color:{icon_tint}!important;width:{ROW_WELL}px;'
        f'height:{ROW_WELL}px;border-radius:14px;text-align:center;">'
        f"{icon_html}</td></tr></table>"
        f"</td>"
        f'<td valign="middle" style="padding:{ROW_PAD_Y} 0;">'
        f'<div style="font-family:{FONT};color:{accent};font-size:{ROW_NAME_SIZE};'
        f'font-weight:700;letter-spacing:0.08em;text-transform:uppercase;'
        f'margin:0 0 3px 0;">{_esc(person)}</div>'
        f'<div style="font-family:{FONT};color:{colors["text"]};font-size:{ROW_CHORE_SIZE};'
        f'font-weight:700;letter-spacing:-0.01em;line-height:1.3;">'
        f"{_esc(chore)}</div>"
        f"</td></tr></table>"
    )


def _day_label(
    day_name: str,
    colors: dict,
    date_label: str = "",
    *,
    color: str | None = None,
) -> str:
    """ALL CAPS day heading; weekly also carries the calendar date on the right."""
    date_cell = ""
    if date_label:
        date_cell = (
            f'<td align="right" valign="bottom" style="font-family:{FONT};font-size:11px;'
            f"font-weight:600;letter-spacing:0.06em;text-transform:uppercase;"
            f'color:{colors["footer_muted"]};padding:0 0 8px 0;">{_esc(date_label)}</td>'
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%"><tr>'
        f'<td align="left" style="font-family:{FONT};font-size:11px;font-weight:600;'
        f"letter-spacing:0.12em;text-transform:uppercase;"
        f'color:{color or colors["muted"]};padding:0 0 8px 0;">{_esc(day_name.upper())}</td>'
        f"{date_cell}"
        f"</tr></table>"
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


def _weekly_day_cell(
    day_name: str,
    d: date,
    rows: list,
    participants: dict,
    colors: dict,
    *,
    first: bool,
    last: bool,
) -> str:
    """One day of the weekly chart: a row of the single card's inner table.

    The divider and the horizontal padding live on this cell rather than on the
    card, so each day break is a hairline running the full card width — visibly
    different from the lighter inset rule between the two people of one day.
    """
    divider = "" if first else f"border-top:1px solid {colors['day_rule']};"
    pad_top = "20px" if first else "18px"
    pad_bottom = "14px" if last else "2px"
    if rows:
        blocks = "".join(
            _person_row(
                a["person"],
                a["chore"],
                a.get("icon", "home"),
                participants,
                colors,
                show_rule=(j > 0),
            )
            for j, a in enumerate(rows)
        )
    else:
        # A day is never dropped silently — an empty one says so.
        blocks = (
            f'<div style="font-family:{FONT};font-size:15px;font-weight:400;'
            f'color:{colors["muted"]};padding:6px 0 14px 0;">No chores scheduled</div>'
        )
    return (
        f'<tr><td style="{divider}'
        f'padding:{pad_top} {CARD_PAD_X} {pad_bottom} {CARD_PAD_X};">'
        f"{_day_label(day_name, colors, _short_month_day(d).upper(), color=colors['secondary'])}"
        f"{blocks}</td></tr>"
    )


def render_weekly_html(week_data: dict, schedule: dict | None = None) -> str:
    """Mon–Fri in ONE card: day sections divided by full-width hairlines.

    Five separate cards made the email both heavy and easy to misread as
    "days are missing" once a client clipped it, so the whole week is one card
    with the same person rows the daily email uses.
    """
    schedule = schedule or _load_schedule()
    participants = schedule["participants"]
    colors = _colors(schedule)
    label = week_data["week_label"]
    monday = date.fromisoformat(week_data["monday"])
    friday = date.fromisoformat(week_data["friday"])

    header = _header_block(
        label,
        "This week's chores",
        _week_range_label(monday, friday),
        colors,
    )

    days = week_data.get("days") or {}
    last_index = len(WEEKDAYS) - 1
    day_cells = "".join(
        _weekly_day_cell(
            day_name,
            monday + timedelta(days=i),
            list(days.get(day_name) or []),
            participants,
            colors,
            first=(i == 0),
            last=(i == last_index),
        )
        for i, day_name in enumerate(WEEKDAYS)
    )
    chart = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%">{day_cells}</table>'
    )
    card = _card(chart, colors, padding="0")

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
    card = _card(
        _day_label(weekday, colors) + blocks,
        colors,
        padding="20px 18px 14px 18px",
    )

    body = (
        f"<tr><td>{header}</td></tr>"
        f"<tr><td>{card}</td></tr>"
        f'<tr><td style="padding:16px 0 0 0;">{_switch_pill(colors)}</td></tr>'
        f"<tr><td>{_brand_footer(colors, kind='daily', thanks=False)}</td></tr>"
    )
    return _shell(body, colors)


def render_weekly_text(week_data: dict) -> str:
    monday = date.fromisoformat(week_data["monday"])
    friday = date.fromisoformat(week_data["friday"])
    days = week_data.get("days") or {}
    lines = [
        f"Week {week_data['week_label']} chores",
        _week_range_label(monday, friday),
        "",
    ]
    # Driven by WEEKDAYS, like the HTML — dict order can never drop a day.
    for i, day_name in enumerate(WEEKDAYS):
        rows = days.get(day_name) or []
        lines.append(f"{day_name.upper()} — {_short_month_day(monday + timedelta(days=i))}")
        for a in rows:
            lines.append(f"  {a['person']}: {a['chore']}")
        if not rows:
            lines.append("  No chores scheduled")
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
