#!/usr/bin/env python3
"""Daily chore reminder email — dry-run by default. Live send via AgentMail MCP (parent)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from rotation import (  # noqa: E402
    assignments_for_day,
    monday_of,
    parse_force_date,
)
from send_history import already_sent, record_success  # noqa: E402
from warm_kitchen import (  # noqa: E402
    daily_subject,
    render_daily_html,
    render_daily_text,
)

SCHEDULE_PATH = BASE_DIR / "household_schedule.json"
PREVIEWS = BASE_DIR / "previews"


def _load_schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def send_key_for(d: date) -> str:
    return f"daily:{d.isoformat()}"


def payload_for_agent(force_date: str | None = None) -> dict:
    """JSON schema the Household routine can load for AgentMail send."""
    d = parse_force_date(force_date)
    schedule = _load_schedule()
    day = assignments_for_day(d, schedule)
    if day is None:
        return {
            "action": "skip",
            "reason": "weekend",
            "date": d.isoformat(),
            "schema": "chore_email_payload_v1",
            "kind": "daily",
        }
    key = send_key_for(d)
    subject = daily_subject(d)
    html = render_daily_html(day, schedule)
    text = render_daily_text(day)
    return {
        "send_key": key,
        "subject": subject,
        "html": html,
        "text": text,
        "recipients": schedule["email"]["recipients"],
        "from": schedule["email"]["from"],
        "inboxId": schedule["email"]["inboxId"],
        "transport": schedule["email"]["transport"],
        "week_label": day["week_label"],
        "date_info": {
            "date": day["date"],
            "weekday": day["weekday"],
            "monday": monday_of(d).isoformat(),
        },
        "assignments": day["assignments"],
        "already_sent": already_sent(key),
        "schema": "chore_email_payload_v1",
        "kind": "daily",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily household chore email (dry-run default)")
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
        help="Exit 0 if would send, 1 if duplicate or weekend skip",
    )
    parser.add_argument(
        "--mark-sent",
        action="store_true",
        help="Record send_key as sent (after external success)",
    )
    parser.add_argument(
        "--payload-only",
        action="store_true",
        help="Print payload_for_agent() JSON only",
    )
    args = parser.parse_args()

    payload = payload_for_agent(args.force_date)

    if payload.get("action") == "skip" and payload.get("reason") == "weekend":
        print(json.dumps(payload))
        # Weekend: exit 0 with skip (per spec)
        if args.check_only:
            return 1  # would not send
        return 0

    key = payload["send_key"]

    if args.check_only:
        if payload.get("already_sent"):
            print(json.dumps({"action": "skip", "reason": "duplicate", "send_key": key}))
            return 1
        print(json.dumps({"action": "would_send", "send_key": key, "subject": payload["subject"]}))
        return 0

    if args.mark_sent:
        record_success(key, {"subject": payload["subject"], "kind": "daily"})
        print(json.dumps({"action": "marked_sent", "send_key": key}))
        return 0

    PREVIEWS.mkdir(parents=True, exist_ok=True)
    preview_path = PREVIEWS / f"daily_{payload['date_info']['date']}_week{payload['week_label']}.html"
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
    _ = args.dry_run
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
