"""Clear Chat RPC scopes its mutation and refuses owners or resumes it cannot reset."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from agent import secret_scope
from hermes_constants import get_hermes_home
from hermes_state import SessionDB
from tui_gateway import launch_profile_policy, server


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    secondary = root / "profiles" / "b"
    secondary.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(server, "_hermes_home", root)
    monkeypatch.setattr(server, "_served_profile_homes", set())
    monkeypatch.setattr(server, "_sessions", {})
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", False)
    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    monkeypatch.setattr(server, "_schedule_agent_build", lambda *args, **kwargs: None)
    events = []
    monkeypatch.setattr(server, "_emit", lambda *args: events.append(args))
    monkeypatch.setattr(server, "_broadcast_global_event", lambda *args: events.append(args))
    homes = {"default": root, "b": secondary}
    dbs = {}
    files = {}
    for name, home in homes.items():
        (home / "config.yaml").write_text("model:\n  default: openai/test-model\nterminal:\n  backend: local\n")
        (home / ".env").write_text(f"PROFILE_CLEAR_TOKEN={name}-secret\n")
        for filename in ("SOUL.md", "memories/MEMORY.md", "skills/custom/SKILL.md", "workspace/notes.txt", "cron/jobs.json"):
            path = home / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"preserve {name} {filename}")
        for path in (home / "config.yaml", home / ".env", *(home / f for f in (
            "SOUL.md", "memories/MEMORY.md", "skills/custom/SKILL.md", "workspace/notes.txt", "cron/jobs.json",
        ))):
            files[path] = path.read_bytes()
        db = dbs[name] = SessionDB(home / "state.db")
        db.create_session("root", source="desktop", model="keep-model", model_config={"provider": "openai"})
        db.append_message("root", "user", f"{name} root history")
        db.end_session("root", "compression")
        db.create_session("tip", source="desktop", parent_session_id="root", model="keep-model")
        db.append_message("tip", "assistant", f"{name} compressed history", _compressed_summary=True)
        db.set_session_title("tip", "Bot Chat")
        db.create_session("side", source="desktop")
        db.append_message("side", "user", f"{name} side history")
    monkeypatch.setattr(server, "_get_db", lambda: dbs["default"])
    try:
        yield homes, dbs, files, events
    finally:
        server._sessions.clear()
        for db in dbs.values():
            db.close()


def _clear(profile):
    return server.handle_request({"id": f"clear-{profile}", "method": "session.clear_bot_chat", "params": {"profile": profile}})


def test_clear_rpc_routes_a_b_a_and_rejects_resume_captured_before_clear(profiles, monkeypatch):
    homes, dbs, files, events = profiles
    scopes = []
    clear = SessionDB.clear_conversation_by_title

    def record_scope(db, *args, **kwargs):
        scopes.append((get_hermes_home(), secret_scope.get_secret("PROFILE_CLEAR_TOKEN")))
        return clear(db, *args, **kwargs)

    monkeypatch.setattr(SessionDB, "clear_conversation_by_title", record_scope)
    previous = {name: 0 for name in homes}
    for name in ("default", "b", "default"):
        other = "b" if name == "default" else "default"
        other_before = dbs[other].get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True)
        result = _clear(name)
        assert "error" not in result, result
        assert result["result"]["conversation_generation"] > previous[name]
        previous[name] = result["result"]["conversation_generation"]
        assert dbs[name].get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []
        assert dbs[other].get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == other_before
        for profile, db in dbs.items():
            assert db.get_session_by_title("Bot Chat")["id"] == "tip"
            assert db.get_session("root")["model"] == "keep-model"
            assert db.get_session_model_config_value("root", "provider") == "openai"
            assert [m["content"] for m in db.get_messages("side")] == [f"{profile} side history"]
    assert scopes == [(homes[name], f"{name}-secret") for name in ("default", "b", "default")]
    assert {path: path.read_bytes() for path in files} == files
    assert os.environ.get("PROFILE_CLEAR_TOKEN") is None
    assert [args[1]["profile"] for args in events if args[0] == "session.conversation_cleared"] == ["default", "b", "default"]

    # Finish a real cold-resume history read, then clear before its live claim.
    # The claim must reject its old generation instead of installing that history.
    dbs["b"].append_message("tip", "user", "captured before clear")
    claim = server._claim_or_reuse_live
    seen = []

    def clear_before_claim(sid, key, record, lease):
        seen.append([m["content"] for m in record["history"]])
        assert "error" not in _clear("b")
        return claim(sid, key, record, lease)

    monkeypatch.setattr(server, "_claim_or_reuse_live", clear_before_claim)
    resumed = server.handle_request({"id": "stale-resume", "method": "session.resume", "params": {
        "session_id": "tip", "profile": "b", "source": "desktop",
    }})
    assert seen == [["captured before clear"]]
    assert resumed["error"]["code"] == 4023
    assert "cleared while resuming" in resumed["error"]["message"]
    assert not server._sessions
    assert dbs["b"].get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []


@pytest.mark.parametrize("blocker", ["hydrating", "settling-turn", "foreign-owner"])
def test_clear_rpc_refuses_unresettable_runtime_across_the_lineage(profiles, blocker):
    homes, dbs, _files, _events = profiles
    db = dbs["b"]
    before = db.get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True)
    child = None
    settling = None
    release_settle = threading.Event()
    if blocker in {"hydrating", "settling-turn"}:
        session = server._sessions["busy"] = {
            "session_key": "tip", "profile_home": str(homes["b"]), "agent": None,
            "history": [], "history_lock": threading.RLock(), "resume_hydrating": blocker == "hydrating",
            "running": False, "source": "desktop",
        }
        if blocker == "settling-turn":
            # The run loop has released running=False but still owns captured
            # steer/goal followups until its worker fully unwinds.
            settling = threading.Thread(target=release_settle.wait)
            session["_run_thread"] = settling
            settling.start()
    else:
        # A separate backend owns the closed compression ancestor, not the
        # canonical tip. Its warm context is beyond this RPC's reset authority.
        child = subprocess.Popen(
            [sys.executable, "-c", '''
import json, sys
from hermes_cli.active_sessions import try_acquire_active_session
lease, error = try_acquire_active_session(session_id="root", surface="desktop", config={}, registry_home=sys.argv[1], track_liveness=True)
print(json.dumps({"acquired": lease is not None, "error": str(error) if error else None}), flush=True)
try:
    sys.stdin.readline()
finally:
    if lease is not None:
        lease.release()
''', str(homes["b"])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    try:
        if child is not None:
            assert json.loads(child.stdout.readline())["acquired"] is True
        result = _clear("b")
        assert result["error"]["code"] == 4023, result
        assert db.get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == before
        assert db.get_conversation_generation("tip") == 0
    finally:
        release_settle.set()
        if settling is not None:
            settling.join(timeout=2)
            assert not settling.is_alive()
        if child is not None:
            try:
                child.communicate(input="\n", timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
            assert child.returncode == 0
        server._sessions.clear()
    assert "error" not in _clear("b")
    assert db.get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []


@pytest.mark.parametrize("route", ["session.resume", "session.activate"])
def test_warm_reattach_refuses_history_cleared_by_another_backend(profiles, route):
    _homes, dbs, _files, _events = profiles
    resumed = server.handle_request({"id": "cold", "method": "session.resume", "params": {
        "session_id": "tip", "profile": "b", "source": "desktop",
    }})
    assert "error" not in resumed, resumed
    live_id = resumed["result"]["session_id"]
    session = server._sessions[live_id]
    assert session["history"]
    old_generation = session["conversation_generation"]
    # A lease-free idle viewer in this process is not reset by another backend.
    cleared = dbs["b"].clear_conversation_by_title("Bot Chat")
    assert cleared["conversation_generation"] > old_generation
    params = ({"session_id": "tip", "profile": "b", "source": "desktop"}
              if route == "session.resume" else {"session_id": live_id})
    result = server.handle_request({"id": "warm", "method": route, "params": params})
    assert result["error"]["code"] == 4023, result
    assert "cleared" in result["error"]["message"].lower()
    assert dbs["b"].get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []


@pytest.mark.parametrize("marker_age", ["legacy", "before-clear", "after-clear"])
def test_cold_resume_only_recovers_interrupted_turns_from_current_conversation(
    profiles, monkeypatch, marker_age,
):
    homes, dbs, _files, _events = profiles
    home, db = homes["b"], dbs["b"]
    scheduled = []
    monkeypatch.setattr(server, "_start_session_work", lambda target, **kwargs: scheduled.append(target) or target)

    def crash_marker():
        session = {"session_key": "tip", "profile_home": str(home), "history_lock": threading.Lock(),
                   "conversation_generation": db.get_conversation_generation("tip")}
        server._record_turn_marker(session, "interrupted request")

    if marker_age != "after-clear":
        crash_marker()
        if marker_age == "legacy":
            path = home / "desktop" / "interrupted_turns.json"
            markers = json.loads(path.read_text())
            markers["tip"].pop("conversation_generation", None)
            path.write_text(json.dumps(markers))
    assert "error" not in _clear("b")
    if marker_age == "after-clear":
        crash_marker()

    resumed = server.handle_request({"id": "recover", "method": "session.resume", "params": {
        "session_id": "tip", "profile": "b", "source": "desktop",
    }})
    assert "error" not in resumed, resumed
    assert bool(scheduled) is (marker_age == "after-clear")
    assert bool(resumed["result"].get("auto_continue")) is (marker_age == "after-clear")
    assert db.get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []
