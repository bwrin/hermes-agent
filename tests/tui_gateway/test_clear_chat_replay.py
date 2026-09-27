"""A conversation clear is a replay boundary, not another metadata refresh."""

from tui_gateway import event_replay as replay


def test_clear_replaces_old_replay_without_reusing_sequence_numbers():
    replay.reset_replay_state()

    def emit(sid, kind):
        frame = {"method": "event", "params": {"session_id": sid, "type": kind, "payload": {}}}
        replay._stamp_event(frame)
        return frame["params"]

    try:
        old = emit("bot", "message.complete")
        other = emit("side", "message.complete")
        cleared = emit("bot", "session.conversation_cleared")
        fresh = emit("bot", "message.complete")
        assert replay.events_since("bot", 0) == [cleared, fresh]
        assert replay.is_truncated("bot", 0)
        assert replay.events_since("bot", old["seq"]) == [cleared, fresh]
        assert not replay.is_truncated("bot", old["seq"])
        assert old["seq"] < cleared["seq"] < fresh["seq"]
        assert replay.events_since("side", 0) == [other]
        assert replay.replay_stats()["events"] == 3
    finally:
        replay.reset_replay_state()
