# Brandon & Kaleah — Household Chore Emails

Live path on the box: `/home/box/household/chore-emails/`

## What this is

Deterministic Week A/B chore rotation and Warm Kitchen HTML email payloads for Brandon and
Kaleah. **Python never sends mail.** Live delivery is via AgentMail by Household routines
(parent agent / MCP).

## Layout

| Path | Role |
|------|------|
| `household_schedule.json` | Timezone, anchor, chores, colors, recipients |
| `rotation.py` | `monday_of`, `week_label`, `assignments_for_week/day` |
| `send_history.py` + `send_history.json` | Duplicate keys (`weekly:YYYY-MM-DD`, `daily:YYYY-MM-DD`) |
| `warm_kitchen.py` | Email-safe HTML + subjects |
| `icons/*.png` | Monochrome line icons (base64-embedded in HTML) |
| `send_weekly_chore_email.py` | Weekly dry-run CLI + `payload_for_agent()` |
| `send_daily_chore_email.py` | Daily dry-run CLI + `payload_for_agent()` |
| `validate_rotation.py` | Rotation assertion suite (no email) |
| `validate_email_layout.py` | Rendered-HTML assertion suite (no email) |
| `redraw_icons.py` | Regenerates `icons/` from code (needs Pillow) |
| `previews/` | HTML written by dry-runs |
| `.venv/` | Optional Pillow venv, used to recolor icons at render time |

## Dry-run (default)

```bash
cd /home/box/household/chore-emails
python3 send_weekly_chore_email.py --force-date 2026-09-21
python3 send_daily_chore_email.py --force-date 2026-09-18
```

- Prints JSON: `send_key`, `subject`, `html`, `text`, `recipients`, `week_label`, `date_info`,
  `assignments`
- Writes HTML under `previews/`
- **Never sends**
- `--check-only`: exit 0 if would send, 1 if duplicate (or weekend for daily)
- Weekend daily: exit 0 with `{"action":"skip","reason":"weekend"}`
- `--mark-sent`: record success after an external AgentMail/SMTP send (routines call
  `record_success`)
- `--unmark-sent`: forget the key so that period can be sent again — see *Resending* below

## Rotation

- Timezone: `America/Indiana/Indianapolis` only
- Anchor Monday `2026-09-21` = Week **B** (confirmed)
- Week A: Brandon = first chore listed each weekday; Kaleah = second
- Week B: owners swap for each day's pair (bathrooms included)
- Mon–Fri only — no weekend chores, no catch-up / backfill

## Email design

Both emails share one visual language ("Warm Kitchen"): cream oat `#F4EEE2` page, a single
white card with a 20px radius, a `WEEK A` / `WEEK B` pill, a person row made of an outline
accent checkbox + a tinted centered icon well + name/chore, Brandon `#E5654A`, Kaleah
`#2F9F86`, a rotation pill, and the `Grok Team · Household` footer. Every wrapper carries
`color-scheme: light only` plus a `bgcolor` attribute so no client repaints the cream dark.

The weekly chart shows **all five weekdays inside that one card**. Each day is a row of the
card's inner table, so its divider is a hairline running the full card width — visibly
different from the lighter inset rule between the two people of a single day. Day headings are
ALL CAPS with the calendar date on the right (`MONDAY … SEP 21`), and a day with no chores
renders "No chores scheduled" rather than disappearing.

Person rows come from one shared builder with no compact variant, so the weekly cannot drift
into cramped rows while the daily stays roomy. The metrics live in `warm_kitchen.ROW_*`.

### Size budget

`warm_kitchen.HTML_BUDGET_BYTES` (50KB) is the ceiling, checked by `validate_email_layout.py`.
It exists because the first Week B send was ~85KB across five stacked cards; Apple Mail clipped
it and the later weekdays were not in the message at all. Icons are recolored masks encoded at
the exact size the email displays and cached per icon/tint, so each is embedded once at roughly
1KB. Current output: weekly ~35KB, daily ~10KB.

If you add rows or icons, re-run `validate_email_layout.py` and watch the reported byte count.

## Duplicate keys

- Weekly: `weekly:{that week's Monday}`
- Daily: `daily:{YYYY-MM-DD}`

Only successful sends should call `record_sent` / `record_success`.

`send_history.json` is **box-local state**. Copying this directory onto the box will overwrite
it — keep the box's copy unless you mean to reset the dedupe ledger.

## Resending a week

The duplicate guard refuses a key that is already recorded, so re-sending a week whose email
went out broken takes an explicit step:

```bash
python3 send_weekly_chore_email.py --force-date 2026-09-21 --unmark-sent
python3 send_weekly_chore_email.py --force-date 2026-09-21   # fresh payload for AgentMail
```

## Validate

```bash
python3 validate_rotation.py        # rotation math, anchor, no weekend chores
python3 validate_email_layout.py    # rendered HTML: all five days, one card, size budget
```

`validate_email_layout.py` takes `--force-date` to check a specific week.
