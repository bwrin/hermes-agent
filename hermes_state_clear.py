"""Explicit conversation clearing and its durable delivery/replay boundary."""

from __future__ import annotations

from typing import Any, Dict, Optional

from hermes_state_common import _placeholders


class SessionClearMixin:
    """Clear a canonical conversation without replacing its identity."""

    def get_conversation_generation(self, session_id: str) -> int:
        """Durable clear boundary shared by every compression continuation.

        Resolve the root even when a new child did not inherit its metadata. A
        read-only handle on a pre-clear-schema database observes generation zero;
        its next writer open reconciles the column before a clear can commit.
        """
        with self._read_ctx() as conn:
            root_id = self._session_turn_lease_key_on_conn(conn, session_id)
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (root_id,)).fetchone()
            return int(dict(row).get("conversation_generation", 0)) if row is not None else 0

    def _conversation_clear_lineage_on_conn(self, conn, title: str) -> list[str]:
        def _row(session_id: str) -> Optional[Dict[str, Any]]:
            found = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(found) if found is not None else None

        row = conn.execute("SELECT * FROM sessions WHERE title = ?", (title,)).fetchone()
        if row is None:
            return []

        titled = dict(row)
        root = titled
        ancestors = {str(root["id"])}
        while not self._is_explicit_fork_child_row(root, include_reset=True):
            parent_id = root.get("parent_session_id")
            if not parent_id or parent_id in ancestors:
                break
            parent = _row(str(parent_id))
            if parent is None or parent.get("end_reason") != "compression":
                break
            root = parent
            ancestors.add(str(root["id"]))

        lineage = [str(root["id"])]
        seen = set(lineage)
        current = root
        while current.get("end_reason") == "compression":
            children = conn.execute(
                "SELECT * FROM sessions WHERE parent_session_id = ? ORDER BY started_at ASC",
                (current["id"],),
            ).fetchall()
            child = next(
                (dict(candidate) for candidate in children
                 if not self._is_explicit_fork_child_row(dict(candidate), include_reset=True)),
                None,
            )
            if child is None or str(child["id"]) in seen:
                break
            lineage.append(str(child["id"]))
            seen.add(str(child["id"]))
            current = child

        return lineage

    def get_conversation_clear_lineage(self, title: str) -> list[str]:
        """Exact compression spine that an in-place clear would mutate, excluding forks."""
        with self._read_ctx() as conn:
            return self._conversation_clear_lineage_on_conn(conn, title)

    def clear_conversation_by_title(
        self, title: str, *, expected_lineage_ids: list[str] | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Atomically clear one exact titled conversation's compression lineage.

        Session identity and bot settings remain intact.  Destructive admission is
        checked in the same transaction as the delete so an active turn,
        compression, handoff, or undelivered delegation cannot race the clear and
        later repopulate the transcript.
        """
        def _do(conn):
            lineage = self._conversation_clear_lineage_on_conn(conn, title)
            if not lineage:
                return None
            if expected_lineage_ids is not None and lineage != expected_lineage_ids:
                raise RuntimeError("conversation changed while preparing clear; try again")

            for session_id in lineage:
                self._check_transcript_write_guards(
                    conn,
                    session_id,
                    compression_lock_holder=None,
                    reject_active_turn_lease=True,
                    reject_active_compression_lock=True,
                    allow_closed_compression_parent=True,
                )

            placeholders = _placeholders(lineage)
            blocked_handoff = conn.execute(
                f"SELECT 1 FROM sessions WHERE id IN ({placeholders}) "
                "AND handoff_state IN ('pending', 'running') LIMIT 1",
                lineage,
            ).fetchone()
            if blocked_handoff is not None:
                raise RuntimeError("chat has a pending delivery handoff")

            blocked_delegation = conn.execute(
                f"SELECT 1 FROM async_delegations WHERE "
                f"(origin_session IN ({placeholders}) OR origin_session_id IN ({placeholders})) "
                "AND (state IN ('running', 'finalizing') "
                "OR delivery_state NOT IN ('delivered', 'dropped')) LIMIT 1",
                [*lineage, *lineage],
            ).fetchone()
            if blocked_delegation is not None:
                raise RuntimeError("chat has active work or a pending delivery")

            deleted = conn.execute(
                f"DELETE FROM messages WHERE session_id IN ({placeholders})", lineage
            ).rowcount
            generation = 1 + int(conn.execute(
                f"SELECT MAX(conversation_generation) FROM sessions WHERE id IN ({placeholders})",
                lineage,
            ).fetchone()[0])
            for session_id in lineage:
                model_config = self._merge_model_config_json(conn, session_id, {
                    "codex_thread_id": None,
                    "_usage_anchor": None,
                    "_proactive_prune_rearm_tokens": None,
                }, on_missing="raise")
                conn.execute(
                    "UPDATE sessions SET message_count = 0, tool_call_count = 0, "
                    "conversation_generation = ?, model_config = ?, "
                    "compression_failure_cooldown_until = NULL, compression_failure_error = NULL, "
                    "compression_fallback_streak = 0, compression_ineffective_count = 0, "
                    "compression_recovery_deadline = NULL, compression_overload_streak = 0 "
                    "WHERE id = ?",
                    (generation, model_config, session_id),
                )
            self._delete_unreferenced_system_prompts(conn)
            return {
                "root_id": lineage[0],
                "resolved_id": lineage[-1],
                "lineage_ids": lineage,
                "messages_cleared": max(0, int(deleted or 0)),
                "conversation_generation": generation,
            }

        return self._execute_write(_do)

