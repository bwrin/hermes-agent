#!/usr/bin/env python3
"""Dry-run assertions for A/B chore rotation. No email."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from rotation import assignments_for_day, assignments_for_week, today_local, week_label  # noqa: E402

# Anchor: 2026-09-21 = Week B → 2026-09-14 = A, 2026-09-28 = A
WEEK_A_MON = date(2026, 9, 14)
WEEK_B_MON = date(2026, 9, 21)


def _find(assignments: list, person: str) -> str:
    for a in assignments:
        if a["person"] == person:
            return a["chore"]
    raise AssertionError(f"no assignment for {person}")


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{extra}")
    return cond


def main() -> int:
    fails = 0

    # Labels
    if not check("Sep 14 2026 is Week A", week_label(WEEK_A_MON) == "A", f"got {week_label(WEEK_A_MON)}"):
        fails += 1
    if not check("Sep 21 2026 is Week B", week_label(WEEK_B_MON) == "B", f"got {week_label(WEEK_B_MON)}"):
        fails += 1
    if not check("Sep 28 2026 is Week A", week_label(date(2026, 9, 28)) == "A"):
        fails += 1

    wa = assignments_for_week(WEEK_A_MON)
    wb = assignments_for_week(WEEK_B_MON)

    # Week A Monday
    a_mon = wa["days"]["Monday"]
    if not check(
        "Week A Monday → Brandon Empty Trash Cans",
        _find(a_mon, "Brandon") == "Empty Trash Cans",
        _find(a_mon, "Brandon"),
    ):
        fails += 1
    if not check(
        "Week A Monday → Kaleah Whites",
        _find(a_mon, "Kaleah") == "Whites",
        _find(a_mon, "Kaleah"),
    ):
        fails += 1

    # Week B Monday
    b_mon = wb["days"]["Monday"]
    if not check(
        "Week B Monday → Brandon Whites",
        _find(b_mon, "Brandon") == "Whites",
        _find(b_mon, "Brandon"),
    ):
        fails += 1
    if not check(
        "Week B Monday → Kaleah Empty Trash Cans",
        _find(b_mon, "Kaleah") == "Empty Trash Cans",
        _find(b_mon, "Kaleah"),
    ):
        fails += 1

    # Week A Tuesday
    a_tue = wa["days"]["Tuesday"]
    if not check(
        "Week A Tuesday → Brandon Upstairs Bathroom",
        _find(a_tue, "Brandon") == "Upstairs Bathroom",
        _find(a_tue, "Brandon"),
    ):
        fails += 1
    if not check(
        "Week A Tuesday → Kaleah Change the Sheets",
        _find(a_tue, "Kaleah") == "Change the Sheets",
        _find(a_tue, "Kaleah"),
    ):
        fails += 1

    # Week B Tuesday
    b_tue = wb["days"]["Tuesday"]
    if not check(
        "Week B Tuesday → Brandon Change the Sheets",
        _find(b_tue, "Brandon") == "Change the Sheets",
        _find(b_tue, "Brandon"),
    ):
        fails += 1
    if not check(
        "Week B Tuesday → Kaleah Upstairs Bathroom",
        _find(b_tue, "Kaleah") == "Upstairs Bathroom",
        _find(b_tue, "Kaleah"),
    ):
        fails += 1

    # Bathroom ownership across Tue (upstairs) + Thu (downstairs)
    a_thu = wa["days"]["Thursday"]
    b_thu = wb["days"]["Thursday"]
    if not check(
        "Week A bathrooms: Brandon upstairs, Kaleah downstairs",
        _find(a_tue, "Brandon") == "Upstairs Bathroom"
        and _find(a_thu, "Kaleah") == "Downstairs Bathroom",
        f"Tue B={_find(a_tue, 'Brandon')}, Thu K={_find(a_thu, 'Kaleah')}",
    ):
        fails += 1
    if not check(
        "Week B bathrooms: Brandon downstairs, Kaleah upstairs",
        _find(b_thu, "Brandon") == "Downstairs Bathroom"
        and _find(b_tue, "Kaleah") == "Upstairs Bathroom",
        f"Thu B={_find(b_thu, 'Brandon')}, Tue K={_find(b_tue, 'Kaleah')}",
    ):
        fails += 1

    # Weekend = None
    sat = assignments_for_day(date(2026, 9, 19))
    if not check("Weekend returns None (no invented chores)", sat is None):
        fails += 1

    today = today_local()
    print(f"\nCurrent local date: {today.isoformat()}")
    print(f"Current week label (America/Indiana/Indianapolis): {week_label(today)}")

    if fails:
        print(f"\n{fails} assertion(s) FAILED")
        return 1
    print("\nAll assertions PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
