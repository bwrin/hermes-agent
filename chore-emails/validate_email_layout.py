#!/usr/bin/env python3
"""Dry-run assertions for the rendered chore-email HTML. No email.

Guards the failure that produced a bad Week B send: a heavy multi-card weekly
chart that a mail client clipped, so the later days simply were not there.
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import sys
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from rotation import (  # noqa: E402
    assignments_for_day,
    assignments_for_week,
    monday_of,
    parse_force_date,
)
from warm_kitchen import (  # noqa: E402
    HTML_BUDGET_BYTES,
    ICONS_DIR,
    ROW_WELL,
    WEEKDAYS,
    render_daily_html,
    render_weekly_html,
)

# The send Brandon flagged, plus the weekly chart for that week.
PINNED_DAILY = date(2026, 9, 23)
PINNED_WEEK_MONDAY = date(2026, 9, 21)

_DATA_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
_IMG_TAG = re.compile(
    r'<img src="(data:image/png;base64,[A-Za-z0-9+/=]+)"[^>]*alt="([^"]*)"'
)
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
# Emoji blocks. A chore icon that falls back to a Unicode glyph tofus in Mail.
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")
# Every marker that keeps a client from repainting the cream card dark.
_LIGHT_LOCK = (
    '<meta name="color-scheme" content="light only">',
    '<meta name="supported-color-schemes" content="light only">',
    ":root{color-scheme:light only;}",
)
_FOOTER = "Grok Team · Household"
_THANKS = "Thanks for keeping the house running."
_ROTATION_PILL = "Assignments switch next week"
# One white card: the rounded card table is the only place this radius is used.
_CARD_MARKER = "border-radius:20px"


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{extra}")
    return cond


def _shared_checks(kind: str, html: str, week_label: str) -> list[bool]:
    size = len(html.encode("utf-8"))
    results = [
        check(
            f"{kind}: HTML under the clipping budget",
            size < HTML_BUDGET_BYTES,
            f"{size} bytes of {HTML_BUDGET_BYTES}",
        ),
        check(f"{kind}: WEEK {week_label} pill", f"WEEK {week_label}" in html),
        check(f"{kind}: footer reads {_FOOTER}", _FOOTER in html),
        check(f"{kind}: rotation pill", _ROTATION_PILL in html),
    ]
    for marker in _LIGHT_LOCK:
        results.append(
            check(f"{kind}: light-only marker {marker[:34]}…", marker in html)
        )
    uris = _DATA_URI.findall(html)
    results.append(
        check(
            f"{kind}: every embedded icon is a distinct image",
            len(uris) >= 1 and len(uris) == len(set(uris)),
            f"{len(uris)} data URIs, {len(set(uris))} unique",
        )
    )
    results.extend(_png_icon_checks(kind, html))
    return results


def _decoded_icon(uri: str):
    """Return (png_bytes, PIL image) or raise."""
    from PIL import Image

    b64 = uri.split(",", 1)[1]
    raw = base64.b64decode(b64, validate=True)
    im = Image.open(io.BytesIO(raw))
    im.load()
    return b64, raw, im


def _solid_core(uri: str) -> int:
    """Pixels with alpha >= 200. RGB images count as fully solid."""
    _b64, _raw, im = _decoded_icon(uri)
    if "A" not in im.getbands():
        return im.size[0] * im.size[1]
    hist = im.getchannel("A").histogram()
    return sum(hist[200:])


def _png_icon_checks(kind: str, html: str) -> list[bool]:
    """Every embedded icon is a real PNG with ink, and no base64 '=' padding.

    Padding is the Apple Mail failure mode from the 2026-09-23 daily: the
    broken Cat Water icon was the only data URI in that message that ended
    in '='. Dishes, rotate, and home did not, and they rendered.
    """
    tags = _IMG_TAG.findall(html)
    results = [
        check(f"{kind}: icon <img> tags found", len(tags) >= 1, f"{len(tags)}"),
        check(f"{kind}: no Unicode emoji icons", _EMOJI.search(html) is None),
    ]
    cores: dict[str, int] = {}
    for uri, alt in tags:
        label = f"{kind}: {alt or 'icon'}"
        try:
            b64, raw, im = _decoded_icon(uri)
            alpha_max = (
                im.getchannel("A").getextrema()[1] if "A" in im.getbands() else 255
            )
            ok = (
                raw.startswith(_PNG_SIG)
                and "=" not in b64
                and im.size[0] > 0
                and im.size[1] > 0
                and alpha_max > 0
            )
            detail = f"{im.size[0]}x{im.size[1]} {im.mode} alpha_max={alpha_max}"
        except Exception as exc:  # noqa: BLE001 — one line per broken icon
            ok = False
            detail = str(exc)
        results.append(check(f"{label} decodes as a PNG with non-empty alpha", ok, detail))
        if ok:
            cores[alt] = _solid_core(uri)
    if "bowl" in cores and "dishes" in cores:
        results.append(
            check(
                f"{kind}: bowl is at least half as solid as dishes",
                cores["bowl"] >= cores["dishes"] * 0.5,
                f"bowl={cores['bowl']} dishes={cores['dishes']} (alpha>=200 px)",
            )
        )
    return results


def _padding_fallback_check() -> bool:
    """The tEXt pad must keep pixels identical and drop base64 '='.

    Current icons happen to land on a multiple of 3 without the chunk.
    This exercises the fallback with a PNG that does not.
    """
    from PIL import Image

    from warm_kitchen import _pad_png_to_multiple_of_3

    png = b""
    for n in range(2, 40):
        buf = io.BytesIO()
        Image.new("RGBA", (n, 3), (10, 20, 30, 255)).save(buf, format="PNG")
        png = buf.getvalue()
        if len(png) % 3 != 0:
            break
    else:
        return False
    padded = _pad_png_to_multiple_of_3(png)
    b64 = base64.b64encode(padded).decode("ascii")
    before = list(Image.open(io.BytesIO(png)).convert("RGBA").getdata())
    after = list(Image.open(io.BytesIO(padded)).convert("RGBA").getdata())
    return (
        len(padded) % 3 == 0
        and "=" not in b64
        and padded.startswith(_PNG_SIG)
        and b"tEXt" in padded
        and before == after
    )


def _source_mask_checks() -> list[bool]:
    from PIL import Image

    results = []
    masks = sorted(ICONS_DIR.glob("*.png"))
    results.append(check("icon masks present", len(masks) >= 1, f"{len(masks)} files"))
    for path in masks:
        try:
            im = Image.open(path)
            im.load()
            alpha_max = im.getchannel("A").getextrema()[1] if "A" in im.getbands() else 0
            ok = path.stat().st_size > 0 and alpha_max > 0 and im.size == (128, 128)
            detail = f"{im.size[0]}x{im.size[1]} {im.mode} alpha_max={alpha_max}"
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = str(exc)
        results.append(check(f"mask {path.name} is a 128px PNG with ink", ok, detail))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-date", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    # Always cover the reported daily (Wed 2026-09-23) and that week's chart,
    # plus whatever --force-date points at (default: today in Indy time).
    daily_dates = {PINNED_DAILY, parse_force_date(args.force_date)}
    week_mondays = {PINNED_WEEK_MONDAY}
    for d in daily_dates:
        if d.weekday() < 5:
            week_mondays.add(monday_of(d))

    results = _source_mask_checks()
    results.append(
        check(
            "base64-padding fallback keeps the PNG and drops '='",
            _padding_fallback_check(),
        )
    )
    weekly_by_monday: dict[date, str] = {}
    for monday in sorted(week_mondays):
        week = assignments_for_week(monday)
        weekly = render_weekly_html(week)
        weekly_by_monday[monday] = weekly
        label = f"weekly {monday.isoformat()}"
        results.extend(_shared_checks(label, weekly, week["week_label"]))
        for day_name in WEEKDAYS:
            results.append(
                check(
                    f"{label}: {day_name.upper()} section present",
                    day_name.upper() in weekly,
                )
            )
        for weekend in ("SATURDAY", "SUNDAY"):
            results.append(
                check(f"{label}: no {weekend} section", weekend not in weekly.upper())
            )
        results.append(
            check(
                f"{label}: all five days in ONE card",
                weekly.count(_CARD_MARKER) == 1,
                f"{weekly.count(_CARD_MARKER)} card(s)",
            )
        )
        results.append(
            check(
                f"{label}: one row per person per weekday",
                weekly.count("&nbsp;</div>") == 2 * len(WEEKDAYS),
                f"{weekly.count('&nbsp;</div>')} checkbox rows",
            )
        )
        results.append(check(f"{label}: keeps the thanks line", _THANKS in weekly))

    # The weekly chart must reuse the daily person row verbatim, not a
    # cramped variant: the same icon well renders in both. Compared on the
    # pinned week so a --force-date can't skip the reported mail.
    weekly = weekly_by_monday[PINNED_WEEK_MONDAY]
    pinned_day = assignments_for_day(PINNED_DAILY)
    assert pinned_day is not None
    daily_html_by_date: dict[date, str] = {}
    for d in sorted(daily_dates):
        day = assignments_for_day(d)
        if day is None:
            results.append(check(f"daily {d.isoformat()}: weekday", False, "weekend"))
            continue
        daily = render_daily_html(day)
        daily_html_by_date[d] = daily
        label = f"daily {d.isoformat()}"
        results.extend(_shared_checks(label, daily, day["week_label"]))
        results.append(
            check(f"{label}: day heading present", day["weekday"].upper() in daily)
        )
    daily = daily_html_by_date[PINNED_DAILY]
    well = f'width="{ROW_WELL}" height="{ROW_WELL}"'
    daily_per_row = daily.count(well) / len(pinned_day["assignments"])
    weekly_per_row = weekly.count(well) / (2 * len(WEEKDAYS))
    results.append(
        check(
            "weekly person rows match daily person rows",
            daily_per_row > 0 and weekly_per_row == daily_per_row,
            f"icon-well markers per row: daily={daily_per_row}, weekly={weekly_per_row}",
        )
    )
    results.append(
        check(
            "no weekend chores",
            assignments_for_day(PINNED_WEEK_MONDAY + timedelta(days=5)) is None
            and assignments_for_day(PINNED_WEEK_MONDAY + timedelta(days=6)) is None,
        )
    )
    results.append(
        check(
            "pinned daily is Wednesday Cat Water + Dishes",
            "Cat Water" in daily and "Dishes" in daily and "WEDNESDAY" in daily,
        )
    )

    print(f"\nweekly HTML ({PINNED_WEEK_MONDAY.isoformat()}): {len(weekly.encode('utf-8'))} bytes")
    print(f"daily  HTML ({PINNED_DAILY.isoformat()}): {len(daily.encode('utf-8'))} bytes")

    fails = results.count(False)
    if fails:
        print(f"\n{fails} assertion(s) FAILED")
        return 1
    print("\nAll assertions PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
