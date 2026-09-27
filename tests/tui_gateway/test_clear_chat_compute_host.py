"""An isolated worker must discard its cached conversation at a parent clear."""

import io
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hermes_state import SessionDB
from tui_gateway import server
from tui_gateway.compute_host import ComputeHost


@pytest.mark.parametrize("busy", [False, True])
def test_parent_clear_resets_idle_compute_worker_and_rejects_stale_frames(tmp_path, monkeypatch, busy):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("chat", source="desktop")
    db.set_session_title("chat", "Bot Chat")
    db.append_message("chat", "assistant", "old answer")
    old_history = [{"role": "assistant", "content": "old answer"}]
    provider = SimpleNamespace(close=Mock())
    compressor = SimpleNamespace(on_session_reset=Mock())
    agent = SimpleNamespace(session_id="chat", _session_messages=old_history, _codex_session=provider,
                            context_compressor=compressor)
    worker = dict(agent=agent, session_key="chat", history=list(old_history), history_lock=threading.RLock(),
                  conversation_generation=0, running=busy, history_version=2)
    parent = dict(session_key="chat", history=list(old_history), history_lock=threading.RLock(),
                  conversation_generation=0, history_version=2, profile_home=str(tmp_path), source="desktop", cwd=str(tmp_path))
    sid = "clear-worker"
    monkeypatch.setitem(server._sessions, sid, worker)
    monkeypatch.setattr(server, "_session_auth_user_id", lambda _: None)
    host = ComputeHost(stdout=io.StringIO(), heartbeat_secs=0)
    try:
        old_frame = server._compute_host_turn_frame("old", sid, parent, "old input")
        clear = db.clear_conversation_by_title("Bot Chat")
        parent.update(history=[], conversation_generation=clear["conversation_generation"], history_version=3, _queued_prompt_generation=7)
        frame = server._compute_host_turn_frame("new", sid, parent, "new input")
        if busy:
            with pytest.raises(ValueError, match="running"):
                host._ensure_server_session(server, frame)
            assert worker["history"] == old_history
            provider.close.assert_not_called()
        else:
            assert host._ensure_server_session(server, frame) is worker
            assert worker["history"] == []
            assert agent._session_messages == []
            assert worker["_queued_prompt_generation"] == parent["_queued_prompt_generation"]
            assert agent._codex_session is None
            provider.close.assert_called_once_with()
            compressor.on_session_reset.assert_called_once_with()
            event = server._event_frame("message.complete", sid, {"text": "new answer"})
            assert event["params"]["conversation_generation"] == clear["conversation_generation"]
            with pytest.raises(ValueError, match="older conversation"):
                host._ensure_server_session(server, old_frame)
            assert worker["history"] == []
        assert db.get_messages("chat") == []
    finally:
        host.close()
        db.close()
