"""Retained replay follows a durable conversation even after runtime teardown."""

import pytest

from hermes_state import SessionDB
from tui_gateway import event_replay as replay


@pytest.mark.parametrize("local_clear", [False, True])
def test_clear_invalidates_retired_replay_and_fences_old_frames(tmp_path, local_clear):
    replay.reset_replay_state()
    homes = [tmp_path / name for name in ("a", "b")]
    stores = [SessionDB(home / "state.db") for home in homes]
    frames = []
    for index, (db, home) in enumerate(zip(stores, homes)):
        db.create_session("chat", source="desktop")
        db.set_session_title("chat", "Bot Chat")
        db.append_message("chat", "assistant", f"old answer {index}")
        frame = {"method": "event", "params": {
            "type": "message.complete", "session_id": f"retired-{index}",
            "conversation_generation": 0, "payload": {"text": f"old answer {index}"},
        }}
        replay._stamp_event(frame, owner=(str(home), "chat"))
        frames.append(frame)
    try:
        cursor = replay.latest_seq("retired-0")
        cleared = stores[0].clear_conversation_by_title("Bot Chat")
        payload = {"stored_session_id": "chat", "session_ids": ["chat"],
                   "conversation_generation": cleared["conversation_generation"], "profile": "default"}
        if local_clear:
            replay.clear_conversation_replay(homes[0], ["chat"], payload)
        snapshot = replay.replay_snapshot("retired-0", 0)
        events = snapshot["events"]
        assert snapshot["conversation_generation"] == cleared["conversation_generation"]
        assert snapshot["count"] == len(events)
        assert not any(event["type"] == "message.complete" for event in events)
        if local_clear:
            assert events[-1]["type"] == "session.conversation_cleared"
            assert replay.events_since("retired-0", cursor) == events
        else:
            assert replay.is_truncated("retired-0", cursor)
        # A frame constructed before clear and stamped afterward stays fenced.
        replay._stamp_event(frames[0], owner=(str(homes[0]), "chat"))
        assert not any(event["type"] == "message.complete" for event in replay.events_since("retired-0", 0))
        assert replay.events_since("retired-1", 0)[0]["payload"]["text"] == "old answer 1"
        assert not replay.is_truncated("retired-1", 0)
    finally:
        for db in stores:
            db.close()
        replay.reset_replay_state()
