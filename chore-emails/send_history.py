"""Track successful chore-email sends to prevent duplicates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "send_history.json"


def _ensure_file() -> None:
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text('{"sent": {}}\n', encoding="utf-8")


def _read_unlocked(fh) -> dict:
    fh.seek(0)
    raw = fh.read()
    if not raw.strip():
        return {"sent": {}}
    data = json.loads(raw)
    if "sent" not in data:
        data["sent"] = {}
    return data


def already_sent(key: str) -> bool:
    """Return True if this send_key was already recorded as successfully sent."""
    _ensure_file()
    with open(HISTORY_PATH, "r+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            data = _read_unlocked(fh)
            return key in data.get("sent", {})
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def record_sent(key: str, meta: dict | None = None) -> None:
    """Record a successful send. Only call after confirmed delivery."""
    _ensure_file()
    meta = dict(meta or {})
    meta.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
    with open(HISTORY_PATH, "r+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked(fh)
            data.setdefault("sent", {})[key] = meta
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def record_success(send_key: str, meta: dict | None = None) -> None:
    """Alias for routines / agent after MCP send confirms success."""
    record_sent(send_key, meta)


def clear_sent(key: str) -> bool:
    """Drop a send_key so that period can be sent again. Returns True if removed.

    Needed when a delivered email has to be re-sent — a botched layout, a wrong
    recipient — because the duplicate guard would otherwise refuse forever.
    """
    _ensure_file()
    with open(HISTORY_PATH, "r+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked(fh)
            if key not in data.get("sent", {}):
                return False
            del data["sent"][key]
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
            return True
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
