"""Weekly chore-email layout contracts.

The Week B send for 2026-09-21 went out as five stacked cards in ~85KB of HTML;
Apple Mail clipped it and the later weekdays were simply not in the message.
These pin the two properties that prevent a repeat: the whole week renders in
one card, and the payload stays small enough that no client clips it.
"""

import importlib.util
import re
from datetime import date
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "chore-emails"
_DATA_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
# The rounded card table is the only thing in the email using this radius.
_CARD = "border-radius:20px"
# The tinted icon well is the only 14px-radius cell, so this matches the chore
# icon of every person row and nothing else (not the footer or pill icons).
_ROW_ICON = re.compile(
    r'border-radius:14px;text-align:center;"><img src="data:image/png;base64,[^"]+"'
    r' width="(\d+)" height="(\d+)"'
)
# One outline checkbox per person row.
_CHECKBOX = "&nbsp;</div>"
_MONDAY_WEEK_B = date(2026, 9, 21)


def _load(stem: str):
    spec = importlib.util.spec_from_file_location(
        f"chore_emails_{stem}", PACKAGE_DIR / f"{stem}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_weekly_chart_puts_every_weekday_in_one_card():
    rotation = _load("rotation")
    warm_kitchen = _load("warm_kitchen")

    week = rotation.assignments_for_week(_MONDAY_WEEK_B)
    html = warm_kitchen.render_weekly_html(week)

    for day_name in warm_kitchen.WEEKDAYS:
        assert day_name.upper() in html, f"{day_name} missing from the weekly chart"
    assert "SATURDAY" not in html.upper()
    assert "SUNDAY" not in html.upper()
    assert html.count(_CARD) == 1, "the week must render as one card, not one per day"
    assert html.count(_CHECKBOX) == 2 * len(warm_kitchen.WEEKDAYS)
    assert "Grok Team · Household" in html
    assert "Thanks for keeping the house running." in html
    assert "Assignments switch next week" in html
    assert 'content="light only"' in html


def test_weekly_stays_under_budget_and_reuses_the_daily_person_row():
    rotation = _load("rotation")
    warm_kitchen = _load("warm_kitchen")

    week = rotation.assignments_for_week(_MONDAY_WEEK_B)
    weekly = warm_kitchen.render_weekly_html(week)
    day = rotation.assignments_for_day(_MONDAY_WEEK_B)
    daily = warm_kitchen.render_daily_html(day)

    size = len(weekly.encode("utf-8"))
    assert size < warm_kitchen.HTML_BUDGET_BYTES, f"weekly HTML is {size} bytes"

    uris = _DATA_URI.findall(weekly)
    assert uris, "icons should be embedded as data URIs"
    assert len(uris) == len(set(uris)), "an icon/tint pair must be embedded once"

    # A weekly-only "compact" row is what made the chart look cramped next to
    # the approved daily. Both emails must draw the same person row.
    well = f'width="{warm_kitchen.ROW_WELL}" height="{warm_kitchen.ROW_WELL}"'
    per_daily_row = daily.count(well) / len(day["assignments"])
    per_weekly_row = weekly.count(well) / (2 * len(warm_kitchen.WEEKDAYS))
    assert per_daily_row > 0
    assert per_weekly_row == per_daily_row

    daily_icons = set(_ROW_ICON.findall(daily))
    weekly_icons = set(_ROW_ICON.findall(weekly))
    assert daily_icons, "no chore icons found in the daily email"
    assert weekly_icons == daily_icons
