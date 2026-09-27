"""Canonical Bot Chat clearing, bound to the gateway server namespace."""

from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method
_profile_scoped = _registry.profile_scoped


def _bot_chat_clear_block_reason(sid: str, session: dict) -> str:
    if _session_live_status(sid, session) != "idle" or any(
        session.get(key)
        for key in ("queued_prompt", "queued_prompts", "_auto_continue_scheduled", "_kanban_pending")
    ):
        return "chat has active work or a pending delivery"
    if _session_has_active_delegations(sid, session):
        return "chat has active delegated work"
    return ""


@method("session.clear_bot_chat")
def _(rid, params: dict) -> dict:
    """Clear the existing canonical Bot Chat without changing its session identity."""
    from tools.bot_live_delivery import pending_delivery_guard
    from tools.bot_mode_probe import BOT_CHAT_TITLE

    try:
        profile_home = _profile_home(_str_param(params, "profile") or None)
    except Exception as exc:
        return _err(rid, 4007, str(exc))
    home = Path(profile_home) if profile_home is not None else get_hermes_home()

    with _session_resume_lock:
        with _profile_db(params) as db:
            if db is None:
                return _db_unavailable_error(rid, code=5036)
            try:
                row = db.get_session_by_title(BOT_CHAT_TITLE)
                if row is None:
                    return _err(rid, 4007, "Bot Chat not found")
                lineage = db.get_compression_lineage(row["id"])
            except Exception as exc:
                return _err(rid, 5036, f"clear failed: {exc}")

            snapshot, err = _snapshot_sessions(rid)
            if err:
                return err
            live = [
                (sid, session)
                for sid, session in snapshot
                if _live_profile_matches(session, profile_home)
                and _session_lookup_key(session, fallback=sid) in lineage
            ]

            with contextlib.ExitStack() as locks:
                for _sid, session in sorted(live, key=lambda item: item[0]):
                    locks.enter_context(session["history_lock"])
                for sid, session in live:
                    if reason := _bot_chat_clear_block_reason(sid, session):
                        return _err(rid, 4023, f"Cannot clear Bot Chat: {reason}. Finish or stop it, then try again.")

                try:
                    with pending_delivery_guard(home, lineage) as pending:
                        if pending:
                            return _err(
                                rid,
                                4023,
                                "Cannot clear Bot Chat: chat has a pending delivery. Let it finish, then try again.",
                            )
                        cleared = db.clear_conversation_by_title(BOT_CHAT_TITLE)
                except Exception as exc:
                    return _err(rid, 4023, f"Cannot clear Bot Chat: {exc}. Finish or stop it, then try again.")

                if cleared is None:
                    return _err(rid, 4007, "Bot Chat not found")
                for sid, session in live:
                    _clear_active_session_history(session)
                    agent = session.get("agent")
                    info = _session_info(agent, session) if agent is not None else _fallback_session_info(session)
                    _emit("session.info", sid, info)

    _broadcast_global_event("sessions.changed", {})
    return _ok(rid, {
        "cleared": True,
        "messages_cleared": cleared["messages_cleared"],
    })


def register(server) -> None:
    bind_module(globals(), server, skip=("_",))
