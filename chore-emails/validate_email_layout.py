#!/usr/bin/env python3
"""Dry-run assertions for the rendered chore-email HTML. No email.

Guards the failure that produced a bad Week B send: a heavy multi-card weekly
chart that a mail client clipped, so the later days simply were not there.
"""

from __future__ import annotations

import argparse
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
    ROW_WELL,
    WEEKDAYS,
    render_daily_html,
    render_weekly_html,
)

_DATA_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
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
            len(uris) == len(set(uris)),
            f"{len(uris)} data URIs, {len(set(uris))} unique",
        )
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-date", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    d = parse_force_date(args.force_date)
    monday = monday_of(d)
    week = assignments_for_week(monday)
    weekly = render_weekly_html(week)
    results = _shared_checks("weekly", weekly, week["week_label"])

    for day_name in WEEKDAYS:
        results.append(
            check(f"weekly: {day_name.upper()} section present", day_name.upper() in weekly)
        )
    for weekend in ("SATURDAY", "SUNDAY"):
        results.append(
            check(f"weekly: no {weekend} section", weekend not in weekly.upper())
        )
    results.append(
        check(
            "weekly: all five days in ONE card",
            weekly.count(_CARD_MARKER) == 1,
            f"{weekly.count(_CARD_MARKER)} card(s)",
        )
    )
    results.append(
        check(
            "weekly: one row per person per weekday",
            weekly.count("&nbsp;</div>") == 2 * len(WEEKDAYS),
            f"{weekly.count('&nbsp;</div>')} checkbox rows",
        )
    )
    results.append(check("weekly: keeps the thanks line", _THANKS in weekly))

    # The weekly chart must reuse the daily person row verbatim, not a
    # cramped variant: the same icon well renders in both.
    weekday = monday if monday.weekday() < 5 else monday_of(monday)
    day = assignments_for_day(weekday)
    assert day is not None
    daily = render_daily_html(day)
    results.extend(_shared_checks("daily", daily, day["week_label"]))
    results.append(
        check("daily: day heading present", day["weekday"].upper() in daily)
    )
    well = f'width="{ROW_WELL}" height="{ROW_WELL}"'
    daily_per_row = daily.count(well) / len(day["assignments"])
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
            assignments_for_day(monday + timedelta(days=5)) is None
            and assignments_for_day(monday + timedelta(days=6)) is None,
        )
    )

    print(f"\nweekly HTML: {len(weekly.encode('utf-8'))} bytes")
    print(f"daily  HTML: {len(daily.encode('utf-8'))} bytes")
    print(f"week of {monday.isoformat()} = Week {week['week_label']}")

    fails = results.count(False)
    if fails:
        print(f"\n{fails} assertion(s) FAILED")
        return 1
    print("\nAll assertions PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
