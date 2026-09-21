#!/usr/bin/env python3
"""Weekly chore chart email — dry-run by default. Live send via AgentMail MCP (parent)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from rotation import (  # noqa: E402
    assignments_for_week,
    monday_of,
    parse_force_date,
    week_label,
)
from send_history import already_sent, clear_sent, record_success  # noqa: E402
from warm_kitchen import (  # noqa: E402
    render_weekly_html,
    render_weekly_text,
    weekly_subject,
)

SCHEDULE_PATH = BASE_DIR / "household_schedule.json"
PREVIEWS = BASE_DIR / "previews"


def _load_schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def send_key_for(monday: date) -> str:
    return f"weekly:{monday.isoformat()}"


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def _ensure_five_weekdays(week: dict) -> dict:
    """Guarantee week_data['days'] has Mon–Fri keys (ordered) for the renderer."""
    days_in = week.get("days") or {}
    days = {name: list(days_in.get(name) or []) for name in _WEEKDAYS}
    out = dict(week)
    out["days"] = days
    return out


def payload_for_agent(force_date: str | None = None) -> dict:
    """JSON schema the Household routine can load for AgentMail send."""
    d = parse_force_date(force_date)
    monday = monday_of(d)
    schedule = _load_schedule()
    week = _ensure_five_weekdays(assignments_for_week(monday, schedule))
    key = send_key_for(monday)
    subject = weekly_subject(week["week_label"], monday)
    html = render_weekly_html(week, schedule)
    text = render_weekly_text(week)
    return {
        "send_key": key,
        "subject": subject,
        "html": html,
        "text": text,
        "recipients": schedule["email"]["recipients"],
        "from": schedule["email"]["from"],
        "inboxId": schedule["email"]["inboxId"],
        "transport": schedule["email"]["transport"],
        "week_label": week["week_label"],
        "date_info": {
            "monday": week["monday"],
            "friday": week["friday"],
            "force_date": d.isoformat(),
        },
        "assignments": week["days"],
        "already_sent": already_sent(key),
        "schema": "chore_email_payload_v1",
        "kind": "weekly",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly household chore email (dry-run default)")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print payload JSON and write HTML preview; never send (default: true)",
    )
    parser.add_argument("--force-date", type=str, default=None, help="YYYY-MM-DD for validation")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Exit 0 if would send, 1 if duplicate",
    )
    parser.add_argument(
        "--mark-sent",
        action="store_true",
        help="Record send_key as sent (after external SMTP/AgentMail success)",
    )
    parser.add_argument(
        "--unmark-sent",
        action="store_true",
        help="Forget send_key so this week can be re-sent (e.g. resending a fixed layout)",
    )
    parser.add_argument(
        "--payload-only",
        action="store_true",
        help="Print payload_for_agent() JSON only",
    )
    args = parser.parse_args()

    payload = payload_for_agent(args.force_date)
    key = payload["send_key"]

    if args.unmark_sent:
        removed = clear_sent(key)
        print(json.dumps({"action": "unmarked_sent", "send_key": key, "removed": removed}))
        return 0

    if args.check_only:
        if payload["already_sent"]:
            print(json.dumps({"action": "skip", "reason": "duplicate", "send_key": key}))
            return 1
        print(json.dumps({"action": "would_send", "send_key": key, "subject": payload["subject"]}))
        return 0

    if args.mark_sent:
        record_success(key, {"subject": payload["subject"], "kind": "weekly"})
        print(json.dumps({"action": "marked_sent", "send_key": key}))
        return 0

    # Always dry-run path for Python — no live AgentMail send implemented
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    preview_path = PREVIEWS / f"weekly_{payload['date_info']['monday']}_week{payload['week_label']}.html"
    preview_path.write_text(payload["html"], encoding="utf-8")

    out = {
        "action": "dry_run",
        "send_key": payload["send_key"],
        "subject": payload["subject"],
        "html": payload["html"],
        "text": payload["text"],
        "recipients": payload["recipients"],
        "week_label": payload["week_label"],
        "date_info": payload["date_info"],
        "assignments": payload["assignments"],
        "preview_path": str(preview_path),
        "already_sent": payload["already_sent"],
        "note": "No email sent. Parent agent sends via AgentMail MCP after loading this payload.",
    }
    if args.payload_only:
        print(json.dumps(payload_for_agent(args.force_date), indent=2))
    else:
        print(json.dumps(out, indent=2))
    # dry-run never sends
    _ = args.dry_run
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
