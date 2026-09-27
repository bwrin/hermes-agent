"""Session visibility RPC and shared lazy-create hide authorization.

Bodies bind to the server namespace through ``method_ctx`` like other RPC siblings.
"""

from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method


def _live_hide_authorized(session: dict) -> bool:
    """``session_hide_authorized`` for a live record whose row (and queued title) may not exist yet."""
    from hermes_state_sessions import session_hide_authorized
    return session_hide_authorized(title=session.get("pending_title"), source=session.get("source"),
                                   room_plumbing=bool(session.get("room_plumbing")))


@method("session.set_hidden")
def _(rid, params: dict) -> dict:
    """Set/clear ``hidden`` (leaves the default list, stays resumable by its owner) on a session + lineage:
    LIVE runtime id first (unpersisted drafts via ``pending_hidden``), then a stored id/key in the profile db."""
    hidden = is_truthy_value(params.get("hidden", True))
    # Quiet live lookup: a stored id that is not in memory is this method's expected second tier, not a
    # rejection — _sess_nowait would log "session-scoped RPC rejected … not in memory" for a request that is
    # then fulfilled from the profile db, burying the real stale-runtime-id signal under sweep noise.
    session = _sessions.get(str(params.get("session_id") or ""))
    with (_profile_db(params, writer=True) if session is None else _session_db(session)) as db:
        if db is None:
            return _db_unavailable_error(rid, code=5007)
        try:
            # The store refuses to hide a non-plumbing row; ``hidden`` in the reply is what took effect.
            if session is not None:
                key = session["session_key"]
                applied = db.set_session_hidden(key, hidden)
                if not applied and db.get_session(key) is None:
                    # No row yet: _ensure_session_db_row is born hidden — only if the draft is plumbing.
                    session["pending_hidden"] = applied = hidden and _live_hide_authorized(session)
            else:
                # ``resolve_session_id`` follows key/title aliases like the REST pin/archive path.
                target = _str_param(params, "session_id")
                if not (key := db.resolve_session_id(target) if hasattr(db, "resolve_session_id") else target):
                    return _err(rid, 4001, "session not found")
                applied = db.set_session_hidden(key, hidden)
            return _ok(rid, {"hidden": bool(hidden and applied), "session_key": key})
        except Exception as e:
            return _err(rid, 5007, str(e))


def register(server) -> None:
    """Rebind this module's handlers onto the server namespace."""
    bind_module(globals(), server, skip=("_",))
