"""A REST page started before Clear must keep its old generation after Clear."""

import asyncio
import json
import threading

import pytest
from fastapi import HTTPException

from hermes_state import SessionDB
from hermes_cli.web_routers import sessions
import hermes_state_timeline


@pytest.mark.parametrize("route", ["messages", "around", "timeline"])
def test_delayed_rest_history_keeps_snapshot_generation(tmp_path, monkeypatch, route):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.create_session("bot", source="desktop")
    db.set_session_title("bot", "Bot Chat")
    row_id = db.append_message("bot", "user", "before the clear")
    monkeypatch.setattr(sessions, "_open_session_db_for_profile",
                        lambda profile, read_only: SessionDB(path, read_only=read_only))
    monkeypatch.setattr(sessions, "_serving_profile", lambda profile: "default")
    monkeypatch.setattr(sessions, "_history_profile_home", lambda profile: tmp_path)
    entered, release = threading.Event(), threading.Event()
    target, name = ((hermes_state_timeline, "get_session_timeline") if route == "timeline"
                    else (sessions, "_project_for_display"))
    original = getattr(target, name)

    def delay_result(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10), "clear never released the captured page"
        return result

    monkeypatch.setattr(target, name, delay_result)

    async def request():
        if route == "messages":
            return await sessions.get_session_messages("bot", limit=20, offset=0, order="oldest", include_compacted=False)
        if route == "around":
            return await sessions.get_session_messages_around("bot", row_id=row_id, limit=20)
        return await sessions.get_session_timeline("bot", limit=20, after_row_id=0)

    async def exercise():
        pending = asyncio.create_task(request())
        try:
            assert await asyncio.to_thread(entered.wait, 10), "page did not reach the response boundary"
            assert db.clear_conversation_by_title("Bot Chat")["conversation_generation"] == 1
        finally:
            release.set()
        stale = await pending
        assert stale["conversation_generation"] == 0
        assert "before the clear" in json.dumps(stale)
        if route == "around":
            with pytest.raises(HTTPException) as exc:
                await request()
            assert exc.value.status_code == 404
        else:
            fresh = await request()
            assert fresh["conversation_generation"] == 1
            assert "before the clear" not in json.dumps(fresh)

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        db.close()
