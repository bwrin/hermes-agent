"""Rejected hide requests stay rejected after reconnecting across real profile stores."""

from pathlib import Path

from hermes_state import SessionDB
from tui_gateway import server


def _rpc(method, **params):
    reply = server.handle_request({"id": 1, "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def test_visibility_survives_cold_resume_and_profile_switches(tmp_path, monkeypatch):
    launch = tmp_path / ".hermes"
    homes = {"default": launch, "work": launch / "profiles" / "work"}
    for home in homes.values():
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("model:\n  default: test-model\n", encoding="utf-8")
        (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setattr(server, "_hermes_home", launch)
    monkeypatch.setattr(server, "_served_profile_homes", set())
    from agent import secret_scope
    from tui_gateway import launch_profile_policy
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", False)
    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    for name in ("_schedule_agent_build", "_schedule_session_cap_enforcement", "_maybe_schedule_auto_continue"):
        monkeypatch.setattr(server, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_new_session_key", lambda: "same-ordinary-key")
    launch_db = SessionDB(launch / "state.db")
    monkeypatch.setattr(server, "_get_db", lambda: launch_db)
    known = set(server._sessions)
    try:
        for profile, home in homes.items():
            created = _rpc("session.create", profile=profile, source="desktop", hidden=True,
                           title=f"ordinary {profile}")
            runtime = server._sessions[created["session_id"]]
            assert server._ensure_session_db_row(runtime)
            with server._session_db(runtime) as db:
                db.append_message("same-ordinary-key", "user", f"private {profile} transcript")
                db.create_session("same-plumbing-key", source="desktop",
                                  model_config={"room_plumbing": True} if profile == "work" else None)
                db.set_session_title("same-plumbing-key", "Group: room · work" if profile == "work" else "Bot Chat")
                db.append_message("same-plumbing-key", "user", f"plumbing {profile}")
            assert _rpc("session.set_hidden", session_id=created["session_id"], hidden=True)["hidden"] is False
            server._sessions.pop(created["session_id"])

        # Drop the launch handle as well as every runtime: resume must read durable state again.
        launch_db.close()
        launch_db = SessionDB(launch / "state.db")
        for profile in ("default", "work", "default"):
            assert _rpc("session.set_hidden", profile=profile,
                        session_id="same-ordinary-key", hidden=True)["hidden"] is False
            assert _rpc("session.set_hidden", profile=profile,
                        session_id="same-plumbing-key", hidden=True)["hidden"] is True
            resumed = _rpc("session.resume", profile=profile, session_id="same-ordinary-key", source="desktop")
            assert [row["text"] for row in resumed["messages"]] == [f"private {profile} transcript"]
            runtime = server._sessions[resumed["session_id"]]
            assert server._ensure_session_db_row(runtime)
            assert {row["id"] for row in _rpc("session.list", profile=profile)["sessions"]} == {"same-ordinary-key"}
            assert {row["id"] for row in _rpc("session.list", profile=profile, include_hidden=True)["sessions"]} == {
                "same-ordinary-key", "same-plumbing-key"}
            with server._session_db(runtime) as db:
                # A pre-fix hidden ordinary row remains hidden when another hide is refused.
                db._conn.execute("UPDATE sessions SET hidden = 1 WHERE id = ?", ("same-ordinary-key",))
                db._conn.commit()
            for target in ("same-ordinary-key", resumed["session_id"]):
                assert _rpc("session.set_hidden", session_id=target, profile=profile, hidden=True)["hidden"] is True
            assert _rpc("session.set_hidden", session_id=resumed["session_id"], hidden=False)["hidden"] is False
            server._sessions.pop(resumed["session_id"])
    finally:
        for sid in set(server._sessions) - known:
            server._sessions.pop(sid, None)
        launch_db.close()
