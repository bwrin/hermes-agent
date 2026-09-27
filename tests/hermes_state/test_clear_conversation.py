"""Invariant coverage for the explicit canonical-chat clear (#110229)."""

import os

import pytest

from hermes_state import SessionDB
from hermes_state_errors import SessionTurnLeaseLostError


def test_clear_conversation_keeps_named_lineage_and_fences_active_work(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("root", source="desktop", model="model-a", model_config={"provider": "test"})
    db.set_session_title("root", "Bot Chat")
    db.append_message("root", "user", "before compression")
    db.end_session("root", "compression")
    db.create_session("tip", source="desktop", parent_session_id="root", model="model-a")
    db.append_message("tip", "assistant", "summary and current tail", _compressed_summary=True)
    assert db.set_session_title("tip", "Bot Chat")
    db.create_session("other", source="desktop")
    db.append_message("other", "user", "keep me")

    holder = f"pid={os.getpid()}:turn=active"
    assert db.try_acquire_session_turn_lease("tip", holder, ttl_seconds=30)
    with pytest.raises(SessionTurnLeaseLostError):
        db.clear_conversation_by_title("Bot Chat")
    db.release_session_turn_lease("tip", holder)

    cleared = db.clear_conversation_by_title("Bot Chat")

    assert cleared == {
        "root_id": "root",
        "resolved_id": "tip",
        "lineage_ids": ["root", "tip"],
        "messages_cleared": 2,
        "conversation_generation": db.get_conversation_generation("tip"),
    }
    assert cleared["conversation_generation"] > 0
    assert db.get_session_by_title("Bot Chat")["id"] == "tip"
    assert db.get_compression_tip("root") == "tip"
    assert db.get_session("root")["model_config"] == '{"provider": "test"}'
    assert db.get_messages_as_conversation("tip", include_ancestors=True, include_compacted=True) == []
    assert [message["content"] for message in db.get_messages("other")] == ["keep me"]


def test_clear_boundary_is_atomic_and_follows_compression_but_not_forks(tmp_path):
    import json
    import sqlite3

    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("root", source="desktop", model_config={"codex_thread_id": "old-native", "provider": "openai"})
        # Existing read-only owners can inspect an old database before the writer
        # has reconciled the new column; the first clear requires its writer open.
        db._execute_write(lambda conn: conn.execute("ALTER TABLE sessions DROP COLUMN conversation_generation"))
        db.close()
        db = SessionDB(tmp_path / "state.db", read_only=True)
        assert db.get_conversation_generation("root") == 0
        db.close()
        db = SessionDB(tmp_path / "state.db")
        assert db.get_conversation_generation("root") == 0
        db.append_message("root", "user", "old root")
        db.end_session("root", "compression")
        for sid, marker in (("branch", "_branched_from"), ("delegate", "_delegate_from"), ("reset", "_reset_from")):
            db.create_session(sid, source="desktop", parent_session_id="root", model_config={marker: "root"})
            db.append_message(sid, "user", f"keep {sid}")
        db.create_session("tip", source="desktop", parent_session_id="root", model_config={"codex_thread_id": "old-native"})
        db.append_message("tip", "assistant", "old summary", _compressed_summary=True)
        db.set_session_title("tip", "Bot Chat")
        db.set_compression_ineffective_count("tip", 3)
        db.set_compression_recovery_deadline("tip", 123456789.0)
        db.record_compression_failure_cooldown("tip", 9999999999.0, "old context overflow")
        before = {sid: db.get_session(sid) for sid in ("root", "tip")}
        db._execute_write(lambda conn: conn.execute(
            "CREATE TRIGGER refuse_clear BEFORE UPDATE OF conversation_generation ON sessions "
            "BEGIN SELECT RAISE(ABORT, 'generation update refused'); END"))
        with pytest.raises(sqlite3.IntegrityError, match="generation update refused"):
            db.clear_conversation_by_title("Bot Chat")
        assert {sid: db.get_session(sid) for sid in before} == before
        assert db.message_count("root") == db.message_count("tip") == 1
        db._execute_write(lambda conn: conn.execute("DROP TRIGGER refuse_clear"))

        result = db.clear_conversation_by_title("Bot Chat")
        assert result["lineage_ids"] == ["root", "tip"]
        assert db.get_conversation_generation("root") == db.get_conversation_generation("tip") == result["conversation_generation"]
        for sid in result["lineage_ids"]:
            assert db.get_session_model_config_value(sid, "codex_thread_id") is None
            assert db.get_compression_ineffective_count(sid) == 0
            assert db.get_compression_recovery_deadline(sid) == 0
            assert db.get_compression_failure_cooldown(sid) is None
        for sid in ("branch", "delegate", "reset"):
            assert [m["content"] for m in db.get_messages(sid)] == [f"keep {sid}"]
            assert db.get_conversation_generation(sid) == 0

        # Compression callers construct fresh model_config; settings writes replace it.
        # Neither operation may resurrect pre-clear delivery authority.
        db.publish_compression_child(
            parent_session_id="tip", child_session_id="new-tip", source="desktop",
            model_config={"provider": "openai"}, messages=[{"role": "user", "content": "new conversation"}],
            require_compression_lease=False,
        )
        db.update_session_meta("new-tip", json.dumps({"provider": "openai", "reasoning_config": {"effort": "low"}}))
        assert db.get_conversation_generation("new-tip") == result["conversation_generation"]
        db.set_session_title("new-tip", "Bot Chat")
        again = db.clear_conversation_by_title("Bot Chat")
        assert again["conversation_generation"] > result["conversation_generation"]
        assert all(db.get_conversation_generation(sid) == again["conversation_generation"] for sid in again["lineage_ids"])
    finally:
        db.close()


def test_clear_lineage_follows_canonical_fork_and_refuses_changed_preflight(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("original", source="desktop")
        db.append_message("original", "user", "original conversation")
        db.end_session("original", "compression")
        db.create_session("fork", source="desktop", parent_session_id="original", model_config={"_branched_from": "original"})
        db.append_message("fork", "user", "fork conversation")
        db.set_session_title("fork", "Bot Chat")
        before_compression = db.get_conversation_clear_lineage("Bot Chat")
        assert before_compression == ["fork"]
        db.publish_compression_child(
            parent_session_id="fork", child_session_id="fork-tip", source="desktop",
            messages=[{"role": "assistant", "content": "fork summary"}],
            model_config={"_branched_from": "original"}, require_compression_lease=False,
        )
        lineage = db.get_conversation_clear_lineage("Bot Chat")
        assert lineage == ["fork", "fork-tip"]
        with pytest.raises(RuntimeError, match="conversation changed"):
            db.clear_conversation_by_title("Bot Chat", expected_lineage_ids=before_compression)
        assert db.message_count("fork") == db.message_count("fork-tip") == 1
        holder = f"pid={os.getpid()}:turn=active-fork"
        assert db.try_acquire_session_turn_lease("fork-tip", holder, ttl_seconds=30)
        with pytest.raises(SessionTurnLeaseLostError):
            db.clear_conversation_by_title("Bot Chat", expected_lineage_ids=lineage)
        db.release_session_turn_lease("fork-tip", holder)
        cleared = db.clear_conversation_by_title("Bot Chat", expected_lineage_ids=lineage)
        assert cleared["lineage_ids"] == lineage
        assert [m["content"] for m in db.get_messages("original")] == ["original conversation"]
        assert db.get_conversation_generation("original") == 0
        assert db.get_conversation_generation("fork-tip") == cleared["conversation_generation"] > 0
    finally:
        db.close()
