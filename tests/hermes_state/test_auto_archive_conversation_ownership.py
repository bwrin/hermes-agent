"""Reactivating an idle branch preserves the original conversation's archive choice."""

from contextlib import closing
import json
import time

import pytest

from hermes_state import SessionDB


def _compress(db, parent, child):
    config = db.get_session(parent)["model_config"]
    db.publish_compression_child(
        parent_session_id=parent, child_session_id=child, source="desktop",
        model_config=json.loads(config) if config else None,
        messages=[{"role": "user", "content": f"Preserved context for {child}"}],
        require_compression_lease=False,
    )


def _flags(db, ids):
    return {sid: tuple(db.get_session(sid)[key] for key in ("archived", "auto_archived"))
            for sid in ids}


@pytest.mark.parametrize("reactivate", ["reopen", "compress"])
@pytest.mark.parametrize("original_manual", [False, True])
def test_reactivating_idle_branch_preserves_original_archive_after_reopen(
    tmp_path, monkeypatch, reactivate, original_manual,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    path = tmp_path / "state.db"
    original = ("original", "original-tip")
    branch = ("branch", "branch-tip")
    with closing(SessionDB(path)) as db:
        db.create_session("original", source="desktop")
        db.append_message("original", "user", "Original transcript")
        db.create_session("branch", source="desktop", parent_session_id="original",
                          model_config={"_branched_from": "original"})
        db.append_message("branch", "user", "Independent branch transcript")
        _compress(db, "original", "original-tip")
        _compress(db, "branch", "branch-tip")
        # Exercise the actual idle sweep, then persist across a database reopen.
        later = time.time() + 60
        monkeypatch.setattr("hermes_state_maintenance.time.time", lambda: later)
        assert db.archive_stale_sessions(0) == 2
        assert _flags(db, (*original, *branch)) == {
            sid: (1, 1) for sid in (*original, *branch)}
        if original_manual:
            assert db.set_session_archived("original-tip", True)
        before_original = _flags(db, original)
        messages = {sid: db.get_messages(sid) for sid in (*original, *branch)}

    with closing(SessionDB(path)) as db:
        if reactivate == "reopen":
            db.reopen_session("branch-tip")
            live = "branch-tip"
        else:
            _compress(db, "branch-tip", "branch-live")
            live = "branch-live"
        assert _flags(db, (*branch, live)) == {sid: (0, 0) for sid in (*branch, live)}
        assert _flags(db, original) == before_original
        for sid, transcript in messages.items():
            assert db.get_messages(sid) == transcript
        listed = {row["id"] for row in db.list_sessions_rich(
            limit=20, min_message_count=1, include_archived=False,
            order_by_last_active=True, compact_rows=True)}
        assert live in listed
        assert not listed.intersection(original)
