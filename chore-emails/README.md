# Brandon & Kaleah — Household Chore Emails

Persistent path: `/home/box/household/chore-emails/`

## What this is

Deterministic Week A/B chore rotation and Warm Kitchen HTML email payloads for Brandon and Kaleah. **Python never sends mail.** Live delivery is via AgentMail by Household routines (parent agent / MCP).

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
| `validate_rotation.py` | Assertion suite (no email) |
| `previews/` | HTML written by dry-runs |
| `.venv/` | Optional Pillow venv used only to generate icons |

## Dry-run (default)

```bash
cd /home/box/household/chore-emails
python3 send_weekly_chore_email.py --force-date 2026-09-14
python3 send_daily_chore_email.py --force-date 2026-09-15
```

- Prints JSON: `send_key`, `subject`, `html`, `text`, `recipients`, `week_label`, `date_info`, `assignments`
- Writes HTML under `previews/`
- **Never sends**
- `--check-only`: exit 0 if would send, 1 if duplicate (or weekend for daily)
- Weekend daily: exit 0 with `{"action":"skip","reason":"weekend"}`
- `--mark-sent`: record success after an external AgentMail/SMTP send (routines call `record_success`)

## Rotation

- Timezone: `America/Indiana/Indianapolis` only
- Anchor Monday `2026-09-21` = Week **B** (confirmed)
- Week A: Brandon = first chore listed each weekday; Kaleah = second
- Week B: owners swap for each day’s pair (bathrooms included)
- Mon–Fri only — no weekend chores, no catch-up / backfill

## Duplicate keys

- Weekly: `weekly:{that week's Monday}`
- Daily: `daily:{YYYY-MM-DD}`

Only successful sends should call `record_sent` / `record_success`.

## Icons

Chore and UI icons are monochrome PNG masks (`icons/*.png`) tinted at send time and embedded as `data:image/png;base64,...`. They are not Unicode emoji.

Apple Mail (the Wed 2026-09-23 daily) drew its broken-image placeholder for **Cat Water & Food** (`bowl`) and rendered Dishes, the rotation arrow, and the footer home mark. Those three URIs needed no base64 `=` padding; `bowl` did. The encoder now keeps every PNG length a multiple of 3 so no data URI is padded, and it stores fully transparent pixels as `(0,0,0,0)` instead of leaving the accent color in the clear pixels. `bowl` is also redrawn heavier so a 34px downsample still has a solid core.

## Validate

```bash
python3 validate_rotation.py
python3 validate_email_layout.py --force-date 2026-09-23
```

`validate_email_layout.py` always checks the week of 2026-09-21 and the daily for 2026-09-23, including that every embedded `data:image/png` decodes as a PNG with non-empty alpha. It does not send mail.

## Copy back to the box

Production reads `/home/box/household/chore-emails/`. Python still never sends; Safehouse / Household sends through AgentMail.

Copy the renderer, the redrawn bowl mask, and the validators. Leave the live send ledger where it is:

```bash
SRC=/path/to/repo/chore-emails
DEST=/home/box/household/chore-emails
install -m 0644 "$SRC/warm_kitchen.py" "$SRC/redraw_icons.py" \
  "$SRC/validate_email_layout.py" "$SRC/README.md" "$DEST/"
install -m 0644 "$SRC/icons/bowl.png" "$DEST/icons/bowl.png"
```

Do **not** copy `send_history.json` over the box file. That ledger (`daily:YYYY-MM-DD`, `weekly:YYYY-MM-DD`) is what stops a second send. Replacing it with this snapshot would let Household deliver days that already went out.

Then dry-run on the box (still no send):

```bash
cd /home/box/household/chore-emails
python3 validate_rotation.py
python3 validate_email_layout.py --force-date 2026-09-23
```
