"""Independent user-flow reproductions for #124092 / PR #124101.

Research only: invoke real branch/archive/resume RPC handlers and SQLite
compression publication; suppress provider construction and background cleanup.
"""

import json
from pathlib import Path

import pytest

from hermes_state import SessionDB
from tui_gateway import server


def _rpc(method, **params):
    reply = server.handle_request({"id": 1, "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


@pytest.fixture
def chat_store(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  default: test-model\n", encoding="utf-8")
    (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(server, "_hermes_home", home)
    for name in ("_schedule_agent_build", "_schedule_session_cap_enforcement", "_maybe_schedule_auto_continue"):
        monkeypatch.setattr(server, name, lambda *args, **kwargs: None)
    db = SessionDB(home / "state.db")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    before = set(server._sessions)
    try:
        db.create_session("original", source="desktop")
        db.append_message("original", "user", "Original conversation evidence")
        branch = _rpc("session.branch_stored", parent_session_id="original", source="desktop")
        key = branch["stored_session_id"]
        server._sessions.pop(branch["session_id"])
        assert json.loads(db.get_session(key)["model_config"])["_branched_from"] == "original"
        yield db, key
    finally:
        for sid in set(server._sessions) - before:
            server._sessions.pop(sid, None)
        db.close()


def _compress(db, parent, child, model_config=None):
    db.publish_compression_child(
        parent_session_id=parent, child_session_id=child, source="desktop",
        messages=[{"role": "user", "content": "Latest preserved context"}],
        model_config=model_config, require_compression_lease=False,
    )


def test_archiving_branch_keeps_compressed_original_in_picker(chat_store):
    db, branch = chat_store
    _compress(db, "original", "original-tip")
    result = _rpc("session.archive", session_id=branch, archived=True)
    assert result["archived"] is True
    assert db.get_session(branch)["archived"] == 1
    assert db.get_session("original")["archived"] == 0
    assert db.get_session("original-tip")["archived"] == 0
    assert "original-tip" in {row["id"] for row in _rpc("session.list")["sessions"]}


def test_cold_resume_of_compressed_branch_reaches_latest_context(chat_store):
    db, branch = chat_store
    _compress(db, branch, "branch-tip", json.loads(db.get_session(branch)["model_config"]))
    resumed = _rpc("session.resume", session_id=branch, source="desktop")
    assert server._sessions[resumed["session_id"]]["session_key"] == "branch-tip"
    assert any(row.get("text") == "Latest preserved context" for row in resumed["messages"])
