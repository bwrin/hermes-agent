"""Desktop's HTTP list and search retain ordinary chats when a hide is refused."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_state import SessionDB
from hermes_cli.web_routers.sessions import list_router, manage_router, search_router


def test_hide_reply_matches_reopened_list_and_search_in_each_profile(tmp_path, monkeypatch):
    launch = tmp_path / ".hermes"
    homes = {"default": launch, "work": launch / "profiles" / "work"}
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setattr("hermes_state.DEFAULT_DB_PATH", launch / "state.db")
    for profile, home in homes.items():
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("sessions:\n  auto_archive: false\n", encoding="utf-8")
        db = SessionDB(home / "state.db")
        try:
            for key, title in (("ordinary", f"Review {profile}"), ("plumbing", "Agent Inbox")):
                db.create_session(key, source="desktop")
                db.set_session_title(key, title)
                db.append_message(key, "user", f"visibilityneedle {profile} {key}")
        finally:
            db.close()

    app = FastAPI()
    for router in (list_router, search_router, manage_router):
        app.include_router(router)
    for profile in ("default", "work", "default"):
        with TestClient(app) as client:
            ordinary = client.patch("/api/sessions/ordinary", json={"hidden": True, "profile": profile})
            assert ordinary.status_code == 200, ordinary.text
            assert ordinary.json()["hidden"] is False
            plumbing = client.patch("/api/sessions/plumbing", json={"hidden": True, "profile": profile})
            assert plumbing.status_code == 200, plumbing.text
            assert plumbing.json()["hidden"] is True

        # Every HTTP request opens its own reader; use a new client too, as after reconnect.
        with TestClient(app) as client:
            listed = client.get("/api/sessions", params={"profile": profile}).json()["sessions"]
            assert [row["id"] for row in listed] == ["ordinary"]
            assert listed[0]["title"] == f"Review {profile}"
            results = client.get("/api/sessions/search", params={"profile": profile, "q": "visibilityneedle"}).json()["results"]
            ordinary_result = next(row for row in results if row["session_id"] == "ordinary")
            assert ordinary_result["profile"] == profile
            assert f"{profile} ordinary" in ordinary_result["snippet"]
            detail = client.get("/api/sessions/plumbing", params={"profile": profile}).json()
            assert detail["hidden"] == 1


@pytest.mark.parametrize("title,flags", [
    (None, {"hidden": True}),
    ("Agent Inbox", {"hidden": True, "pinned": True}),
], ids=["refused-legacy-hide", "pin-after-hide"])
def test_hide_reply_reports_final_durable_visibility(tmp_path, monkeypatch, title, flags):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("hermes_state.DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB(home / "state.db")
    try:
        db.create_session("legacy", source="desktop")
        db.append_message("legacy", "user", "A conversation whose actual visibility matters")
        if title:
            db.set_session_title("legacy", title)
        else:
            # Pre-fix stores already have these rows; a rejected write does not repair them.
            db._conn.execute("UPDATE sessions SET hidden = 1 WHERE id = ?", ("legacy",))
            db._conn.commit()
    finally:
        db.close()
    app = FastAPI()
    app.include_router(manage_router)
    with TestClient(app) as client:
        patched = client.patch("/api/sessions/legacy", json=flags)
        assert patched.status_code == 200, patched.text
        stored = client.get("/api/sessions/legacy").json()
        assert patched.json()["hidden"] == bool(stored["hidden"])
        if flags.get("pinned"):
            assert stored["pinned"] == 1
            assert stored["hidden"] == 0
