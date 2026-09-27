"""A foreign cold runtime cannot revive a cleared transcript on its first turn."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from hermes_cli.active_sessions import active_session_registry_snapshot
from hermes_state import SessionDB
from tui_gateway import server


@pytest.mark.parametrize("automatic", [False, True])
def test_foreign_clear_refuses_stale_unleased_runtime_before_turn(tmp_path, monkeypatch, automatic):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("chat", source="desktop")
    db.set_session_title("chat", "Bot Chat")
    db.append_message("chat", "user", "old question")
    session = server._deferred_session_record(
        "chat", cols=80, cwd=str(tmp_path), history=[{"role": "user", "content": "old question"}],
        lease=None, source="desktop", profile_home=tmp_path,
    )
    session["agent"] = SimpleNamespace()
    session["agent_ready"].set()
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))
    script = """
import json, sys
from pathlib import Path
from hermes_state import SessionDB
from hermes_cli.active_sessions import active_session_liveness_guard
from tools.bot_live_delivery import pending_delivery_guard
home = sys.argv[1]
db = SessionDB(Path(home) / 'state.db')
with active_session_liveness_guard(['chat'], registry_home=home) as active:
    assert not active
    with pending_delivery_guard(home, ['chat']) as pending:
        assert not pending
        print(json.dumps(db.clear_conversation_by_title('Bot Chat')))
db.close()
"""
    try:
        cleared = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                                 capture_output=True, text=True, timeout=30)
        assert cleared.returncode == 0, cleared.stderr
        generation = json.loads(cleared.stdout)["conversation_generation"]
        if automatic:
            assert server._admit_prompt_turn("old-runtime", session, "late wake-up", [], None, None, None) is None
            assert emitted and "Reopen" in emitted[-1][2]["message"]
        else:
            assert "Reopen" in server._ensure_active_session_slot("old-runtime", session)
        assert session.get("active_session_lease") is None
        assert active_session_registry_snapshot(registry_home=tmp_path) == []
        assert db.get_messages("chat") == []
        # A newly hydrated runtime of the same durable identity may still work.
        session.update(history=[], conversation_generation=generation)
        assert server._ensure_active_session_slot("new-runtime", session) is None
    finally:
        if lease := session.get("active_session_lease"):
            lease.release()
        db.close()


@pytest.mark.parametrize("existing_store", [False, True])
def test_generation_check_preserves_no_store_chats_but_refuses_unreadable_existing_state(
    tmp_path, monkeypatch, existing_store,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(server, "_hermes_home", tmp_path)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    if existing_store:
        db = SessionDB(tmp_path / "state.db")
        db.create_session("chat", source="desktop")
        db.set_session_title("chat", "Bot Chat")
        db.clear_conversation_by_title("Bot Chat")
        db.close()
    session = server._deferred_session_record(
        "chat", cols=80, cwd=str(tmp_path), history=[{"role": "user", "content": "in-memory question"}],
        lease=None, source="desktop",
    )
    try:
        refusal = server._ensure_active_session_slot("memory-runtime", session)
        if existing_store:
            assert refusal and "verify" in refusal
            assert session.get("active_session_lease") is None
        else:
            assert refusal is None
            assert session["active_session_lease"] is not None
        assert (tmp_path / "state.db").exists() is existing_store
    finally:
        if lease := session.get("active_session_lease"):
            lease.release()
