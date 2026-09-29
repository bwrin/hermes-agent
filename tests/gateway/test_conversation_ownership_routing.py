"""Real gateway route/restart contracts for continuation ownership (#124092)."""

import json
from pathlib import Path

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore


def _source(chat):
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat,
        user_id=chat,
        chat_type="dm",
        thread_id="thread-" + chat,
    )


@pytest.fixture
def routing_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.mark.parametrize("marker", ["_branched_from", "_delegate_from", "_reset_from"])
def test_switch_and_restart_move_only_the_resumed_conversation(routing_home, marker):
    """An explicit route switch moves the full compressed fork, never its origin."""
    store = SessionStore(routing_home / "sessions", GatewayConfig())
    try:
        db = store._db
        origin = store.get_or_create_session(_source("origin"))
        db.append_message(origin.session_id, "user", "Independent origin transcript")
        root = "fork-root"
        config = {marker: origin.session_id}
        db.create_session(
            root, source="telegram", parent_session_id=origin.session_id,
            model_config=config, session_key="agent:main:telegram:dm:old-fork",
            chat_id="old-fork", chat_type="dm", user_id="old-fork",
            thread_id="thread-old-fork",
        )
        db.append_message(root, "user", "Earlier fork context")
        db.publish_compression_child(
            parent_session_id=root, child_session_id="fork-tip", source="telegram",
            model_config=config,
            messages=[{"role": "user", "content": "Latest fork context"}],
            require_compression_lease=False,
        )
        # Later independent children must not be mistaken for the active tip.
        independent = []
        for kind, child_source, child_config in (
            ("branch", "telegram", {"_branched_from": root}),
            ("delegate", "telegram", {"_delegate_from": root}),
            ("reset", "telegram", {"_reset_from": root}),
            ("tool", "tool", None),
        ):
            sid = "independent-" + kind
            db.create_session(
                sid, source=child_source, parent_session_id=root,
                model_config=child_config, session_key="independent:" + kind,
                chat_id=kind, user_id=kind, chat_type="dm", thread_id=kind,
            )
            db.append_message(sid, "user", "Independent " + kind)
            independent.append(sid)
        preserved = {
            sid: db.get_session(sid)
            for sid in [origin.session_id, *independent]
        }
        target_source = _source("destination")
        target = store.get_or_create_session(target_source)
        resolved = db.resolve_resume_session_id(root)
        assert resolved == "fork-tip"
        switched = store.switch_session(target.session_key, resolved, preserve_prompt_pin=False)
        assert switched.session_id == "fork-tip"
        for sid in (root, "fork-tip"):
            row = db.get_session(sid)
            assert row["session_key"] == target.session_key
            assert row["chat_id"] == target_source.chat_id
            assert row["thread_id"] == target_source.thread_id
            assert json.loads(row["origin_json"])["chat_id"] == target_source.chat_id
        assert {sid: db.get_session(sid) for sid in preserved} == preserved
        store.close_all_db_handles()

        store = SessionStore(routing_home / "sessions", GatewayConfig())
        restored = store.get_or_create_session(target_source)
        assert restored.session_id == "fork-tip"
        assert restored.origin.chat_id == target_source.chat_id
        assert any(
            row.get("content") == "Latest fork context"
            for row in store.load_transcript(restored.session_id)
        )
        assert {sid: store._db.get_session(sid) for sid in preserved} == preserved
    finally:
        store.close_all_db_handles()


def test_gateway_reset_persists_its_own_route_after_compression(routing_home):
    """The actual reset producer supplies a complete route at the new boundary."""
    store = SessionStore(routing_home / "sessions", GatewayConfig())
    try:
        source = _source("reset-owner")
        entry = store.get_or_create_session(source)
        db = store._db
        db.append_message(entry.session_id, "user", "Before compression")
        db.publish_compression_child(
            parent_session_id=entry.session_id, child_session_id="compressed-tip",
            source="telegram",
            messages=[{"role": "user", "content": "Before reset"}],
            require_compression_lease=False,
        )
        assert store.get_or_create_session(source).session_id == "compressed-tip"
        reset = store.reset_session(entry.session_key)
        row = db.get_session(reset.session_id)
        assert json.loads(row["model_config"])["_reset_from"] == "compressed-tip"
        assert row["session_key"] == entry.session_key
        assert row["chat_id"] == source.chat_id
        assert row["thread_id"] == source.thread_id
        assert json.loads(row["origin_json"])["chat_id"] == source.chat_id
        assert db.get_compression_tip(entry.session_id) == "compressed-tip"
        assert db.get_compression_lineage(reset.session_id) == [reset.session_id]
        db.append_message(reset.session_id, "user", "After reset")
        store.close_all_db_handles()
        store = SessionStore(routing_home / "sessions", GatewayConfig())
        assert store.get_or_create_session(source).session_id == reset.session_id
        assert [row["content"] for row in store.load_transcript(reset.session_id)] == ["After reset"]
    finally:
        store.close_all_db_handles()
