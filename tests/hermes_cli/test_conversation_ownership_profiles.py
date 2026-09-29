"""REST flags and cold RPC resume keep conversation ownership across profiles.

Regression coverage for #124092 / PR #124101. Branches use the actual Desktop
RPC; reset/delegate/tool records use their persisted production markers. Every
compression handoff is published atomically by SessionDB without a provider.
"""

from contextlib import closing
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from hermes_cli.web_routers.sessions import list_router, manage_router
from hermes_state import SessionDB
from tui_gateway import server


def _rpc(method, **params):
    reply = server.handle_request({"id": 1, "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def _compress(db, parent, child, profile):
    config = db.get_session(parent)["model_config"]
    db.publish_compression_child(
        parent_session_id=parent, child_session_id=child, source="desktop",
        model_config=json.loads(config) if config else None,
        messages=[{"role": "user", "content": f"{profile} latest {child}"}],
        profile_name=profile, require_compression_lease=False,
    )


def _snapshot(home):
    with closing(SessionDB(home / "state.db")) as db:
        rows = db._conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()
        return {
            row["id"]: {
                "flags": tuple(db.get_session(row["id"])[key] for key in
                               ("archived", "pinned", "last_read_at")),
                "messages": db.get_messages(row["id"], include_inactive=True),
            }
            for row in rows
        }


@pytest.fixture
def ownership_stores(request, tmp_path, monkeypatch):
    launch = tmp_path / ".hermes"
    homes = {"default": launch, "work": launch / "profiles" / "work"}
    for home in homes.values():
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\nsessions:\n  auto_archive: false\n", encoding="utf-8")
        (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setattr("hermes_state.DEFAULT_DB_PATH", launch / "state.db")
    monkeypatch.setattr(server, "_hermes_home", launch)
    monkeypatch.setattr(server, "_served_profile_homes", set())
    from agent import secret_scope
    from tui_gateway import launch_profile_policy
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", False)
    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    for name in ("_schedule_agent_build", "_schedule_session_cap_enforcement", "_maybe_schedule_auto_continue"):
        monkeypatch.setattr(server, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_new_session_key", lambda: "separate")
    launch_db = SessionDB(launch / "state.db")
    monkeypatch.setattr(server, "_get_db", lambda: launch_db)
    known = set(server._sessions)
    boundary = request.param
    try:
        for profile, home in homes.items():
            with closing(SessionDB(home / "state.db")) as db:
                db.create_session("original", source="desktop", profile_name=profile)
                db.append_message("original", "user", f"{profile} original preserved transcript")
                if boundary == "branch":
                    created = _rpc("session.branch_stored", profile=profile,
                                   parent_session_id="original", source="desktop")
                    assert created["stored_session_id"] == "separate"
                    server._sessions.pop(created["session_id"])
                else:
                    marker = {"reset": "_reset_from", "delegate": "_delegate_from"}.get(boundary)
                    db.create_session(
                        "separate", source="tool" if boundary == "tool" else "desktop",
                        parent_session_id="original", profile_name=profile,
                        model_config={marker: "original"} if marker else None,
                    )
                    db.append_message("separate", "user", f"{profile} {boundary} preserved transcript")
                _compress(db, "original", "original-tip", profile)
                if boundary != "tool":
                    _compress(db, "separate", "separate-tip", profile)
        app = FastAPI()
        app.include_router(list_router)
        app.include_router(manage_router)

        def restart():
            nonlocal launch_db
            for sid in set(server._sessions) - known:
                server._sessions.pop(sid)
            launch_db.close()
            launch_db = SessionDB(launch / "state.db")

        yield homes, app, boundary, restart
    finally:
        for sid in set(server._sessions) - known:
            server._sessions.pop(sid, None)
        launch_db.close()


@pytest.mark.parametrize("ownership_stores", ["branch", "reset", "delegate", "tool"], indirect=True)
@pytest.mark.parametrize("target", ["original", "separate"])
def test_rest_flags_change_only_the_selected_conversation_after_reconnect(ownership_stores, target):
    homes, app, boundary, restart = ownership_stores
    transcripts = {profile: _snapshot(home) for profile, home in homes.items()}
    expected_ids = {target, f"{target}-tip"}
    if target == "separate" and boundary == "tool":
        expected_ids.remove("separate-tip")
    for profile, enabled in (("default", True), ("work", True), ("default", False)):
        restart()
        before = {name: _snapshot(home) for name, home in homes.items()}
        # The same stored IDs intentionally occur in both profiles.
        with TestClient(app) as client:
            response = client.patch(f"/api/sessions/{target}", json={
                "profile": profile, "pinned": enabled, "archived": enabled, "unread": enabled,
            })
            assert response.status_code == 200, response.text
            for flag in ("pinned", "archived", "unread"):
                assert response.json()[flag] is enabled
        after = {name: _snapshot(home) for name, home in homes.items()}
        for name, rows in after.items():
            for sid, state in rows.items():
                assert state["messages"] == transcripts[name][sid]["messages"]
                if name == profile and sid in expected_ids:
                    archived, pinned, read_at = state["flags"]
                    assert bool(archived) is enabled
                    assert bool(pinned) is enabled
                    assert (read_at == 0) is enabled
                else:
                    assert state == before[name][sid]
        with TestClient(app) as client:
            for sid in expected_ids:
                row = client.get(f"/api/sessions/{sid}", params={"profile": profile}).json()
                assert row["profile"] == profile
                assert bool(row["archived"]) is enabled
                assert bool(row["pinned"]) is enabled


@pytest.mark.parametrize("ownership_stores", ["branch", "reset", "delegate"], indirect=True)
def test_rest_history_and_cold_resume_agree_on_each_profiles_latest_segment(ownership_stores):
    homes, app, boundary, restart = ownership_stores
    transcripts = {profile: _snapshot(home) for profile, home in homes.items()}
    for profile in ("default", "work", "default"):
        restart()
        for root in ("original", "separate"):
            tip = f"{root}-tip"
            expected_text = f"{profile} latest {tip}"
            with TestClient(app) as client:
                descendant = client.get(f"/api/sessions/{root}/latest-descendant", params={"profile": profile})
                assert descendant.status_code == 200, descendant.text
                assert descendant.json()["path"] == [root, tip]
                history = client.get(f"/api/sessions/{root}/messages", params={"profile": profile})
                assert history.status_code == 200, history.text
                assert history.json()["session_id"] == tip
                assert [row["content"] for row in history.json()["messages"]] == [expected_text]
                listed = client.get("/api/sessions", params={"profile": profile}).json()["sessions"]
                ids = [row["id"] for row in listed]
                assert ids.count("original-tip") == 1
                assert "original" not in ids
                if boundary != "delegate":
                    assert ids.count("separate-tip") == 1
                    assert "separate" not in ids
            resumed = _rpc("session.resume", session_id=root, profile=profile, source="desktop")
            runtime = server._sessions.pop(resumed["session_id"])
            assert runtime["session_key"] == tip
            with server._session_db(runtime) as db:
                assert Path(db.db_path).resolve() == (homes[profile] / "state.db").resolve()
            texts = [row["text"] for row in resumed["messages"]]
            assert expected_text in texts
            assert all(text.startswith(f"{profile} ") for text in texts)
        for name, home in homes.items():
            for sid, state in _snapshot(home).items():
                assert state["messages"] == transcripts[name][sid]["messages"]
