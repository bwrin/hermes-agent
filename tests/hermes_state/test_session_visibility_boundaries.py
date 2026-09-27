"""Visibility changes belong to one conversation, including compression, not its forks."""

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def _chat(db, session_id, *, parent=None, marker=None, source="desktop", title=None):
    db.create_session(
        session_id, source=source, parent_session_id=parent,
        model_config={marker: parent} if marker else {},
    )
    if title:
        assert db.set_session_title(session_id, title)
    db.append_message(session_id, "user", f"History for {session_id}")


@pytest.mark.parametrize("fork_marker", ["_branched_from", "_reset_from"])
@pytest.mark.parametrize("title", ["Bot Chat", "Agent Inbox", "Group: room-1"])
def test_hiding_plumbing_parent_preserves_separate_desktop_forks(db, fork_marker, title):
    _chat(db, "plumbing", title=title)
    db.end_session("plumbing", "compression")
    _chat(db, "continuation", parent="plumbing")
    _chat(db, "ordinary-fork", parent="plumbing", marker=fork_marker, title="Weekly review")
    assert "ordinary-fork" in {row["id"] for row in db.list_sessions_rich()}

    assert db.set_session_hidden("plumbing", True)

    assert db.get_session("plumbing")["hidden"] == 1
    assert db.get_session("continuation")["hidden"] == 1
    assert db.get_session("ordinary-fork")["hidden"] == 0
    assert "ordinary-fork" in {
        row["id"] for row in db.list_sessions_rich(search_query="Weekly review")
    }


@pytest.mark.parametrize("fork_marker,source,title", [
    ("_branched_from", "desktop", "Bot Chat"),
    ("_reset_from", "desktop", "Group: room-1"),
    ("_delegate_from", "tool", None),
])
def test_hiding_plumbing_fork_preserves_ordinary_ancestor(db, fork_marker, source, title):
    _chat(db, "ordinary", title="Weekly review")
    db.end_session("ordinary", "compression")
    _chat(db, "ordinary-tip", parent="ordinary")
    _chat(db, "plumbing-fork", parent="ordinary", marker=fork_marker, source=source, title=title)

    assert db.set_session_hidden("plumbing-fork", True)

    assert db.get_session("plumbing-fork")["hidden"] == 1
    assert db.get_session("ordinary")["hidden"] == 0
    assert db.get_session("ordinary-tip")["hidden"] == 0
    assert "ordinary-tip" in {
        row["id"] for row in db.list_sessions_rich(search_query="Weekly review")
    }


def test_hide_rechecks_plumbing_authority_when_the_writer_is_acquired(db, tmp_path, monkeypatch):
    """A rename completed by another client while our hide waits cannot authorize hiding the new title."""
    _chat(db, "renamed", title="Agent Inbox")
    other_client = SessionDB(tmp_path / "state.db")
    execute_write = db._execute_write

    def acquire_after_rename(*args, **kwargs):
        assert other_client.set_session_title("renamed", "Weekly review")
        return execute_write(*args, **kwargs)

    monkeypatch.setattr(db, "_execute_write", acquire_after_rename)
    try:
        assert db.set_session_hidden("renamed", True) is False
        assert other_client.get_session("renamed")["hidden"] == 0
        assert "renamed" in {
            row["id"] for row in other_client.list_sessions_rich(search_query="Weekly review")
        }
    finally:
        other_client.close()
