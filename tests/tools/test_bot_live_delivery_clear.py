"""Clear Chat fences delivery admission across real mailbox/SQLite boundaries."""

import json
import subprocess
import sys

import pytest

from hermes_cli.active_sessions import try_acquire_active_session
from hermes_state import SessionDB
from tools import bot_live_delivery as mailbox


def _producer(home, owner, *, probe=False):
    # A nonblocking lock in the child makes mutual exclusion observable without
    # a sleep or a negative timing assertion. All mailbox I/O remains real.
    script = """
import json, os, sys
from tools import bot_live_delivery as mailbox
if sys.argv[3] == 'probe':
    import hermes_cli.active_sessions as leases
    def nonblocking(fh, *, lock):
        if os.name == 'nt':
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK if lock else msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), (fcntl.LOCK_EX | fcntl.LOCK_NB) if lock else fcntl.LOCK_UN)
    leases._flock = nonblocking
try:
    result = mailbox.deliver_to_live_owner(sys.argv[1], json.loads(sys.argv[2]), 'late result', delivery_id='a'*32)
except RuntimeError as exc:
    if 'active session file lock unavailable' not in str(exc):
        raise
    result = {'blocked': True}
print(json.dumps(result))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(home), json.dumps(owner), "probe" if probe else "deliver"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(child.stdout)


def test_clear_guard_serializes_the_first_mailbox_admission(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("chat", source="desktop")
    db.set_session_title("chat", "Bot Chat")
    db.append_message("chat", "user", "old question")
    owner = dict(profile_home=str(tmp_path.resolve()), session_id="chat", lease_id="lease", live_session_id="live")
    try:
        assert not mailbox.has_mailbox(tmp_path)
        with mailbox.pending_delivery_guard(tmp_path, ["chat"]) as pending:
            assert not pending
            result = _producer(tmp_path, owner, probe=True)
            assert result == {"blocked": True}
            db.clear_conversation_by_title("Bot Chat")
        assert mailbox.claim_pending_delivery(tmp_path, owner) is None
        assert db.get_messages("chat") == []
    finally:
        db.close()


@pytest.mark.parametrize("legacy_intent", [False, True])
def test_clear_fences_captured_producer_and_consumer_after_restart(tmp_path, monkeypatch, capsys, legacy_intent):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("chat", source="desktop")
    db.set_session_title("chat", "Bot Chat")
    db.append_message("chat", "user", "old question")
    lease, refusal = try_acquire_active_session(
        session_id="chat", surface="desktop", config={}, registry_home=tmp_path,
        metadata=dict(live_session_id="live", bot_live_delivery_consumer=True),
    )
    assert refusal is None
    try:
        captured = mailbox.find_canonical_live_owner(tmp_path)
        assert captured is not None
        if legacy_intent:
            captured.pop("conversation_generation", None)
        with mailbox.pending_delivery_guard(tmp_path, ["chat"]) as pending:
            assert not pending
            db.clear_conversation_by_title("Bot Chat")
        db.close()
        # A producer whose owner snapshot predates clear runs in a fresh process.
        stale = _producer(tmp_path, captured)
        assert stale["status"] == "cancelled"
        assert stale["reason"] == "conversation_cleared"
        assert _producer(tmp_path, captured) == stale

        # A persisted DM intent must retain that cancellation, never reroute
        # the same old input through a new CLI turn after mailbox refusal.
        from tools import bot_mode_dm
        payload = tmp_path / "old-dm.txt"
        payload.write_text("late DM", encoding="utf-8")
        payload.with_name(payload.name + ".live.json").write_text(json.dumps({
            "owner": captured, "message": "late DM", "delivery_id": "b" * 32,
        }), encoding="utf-8")
        monkeypatch.setattr(bot_mode_dm, "_run_local_turn", lambda *a, **kw: pytest.fail("stale DM rerouted"))
        assert bot_mode_dm._run_delivery(
            ["hermes", "-p", "test-bot"], str(payload), stdin_file=False, profile_home=tmp_path,
        ) == 1
        assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
        monkeypatch.setattr(bot_mode_dm, "_write_dm_file", lambda _content: str(payload))
        monkeypatch.setattr(bot_mode_dm, "_spawn_delivery", lambda *a, **kw: pytest.fail("cancelled DM spawned"))
        acknowledgement = json.loads(bot_mode_dm._start_delivery(
            ["hermes", "-p", "test-bot"], "late DM", "test-bot", stdin_file=False,
            profile_home=tmp_path, task_id=None, agent=None,
        ))
        assert acknowledgement["status"] == "cancelled"
        assert acknowledgement["reason"] == "conversation_cleared"

        current = mailbox.find_canonical_live_owner(tmp_path)
        fresh = mailbox.deliver_to_live_owner(tmp_path, current, "new conversation")
        assert fresh["status"] == "queued"
        assert mailbox.claim_pending_delivery(tmp_path, captured) is None
        claimed = mailbox.claim_pending_delivery(tmp_path, current)
        assert claimed["delivery_id"] == fresh["delivery_id"]
        assert mailbox.claim_pending_delivery(tmp_path, current) is None
    finally:
        lease.release()
        db.close()
