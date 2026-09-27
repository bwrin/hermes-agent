"""Cold Clear Chat must retire native context across restarts without touching other profiles."""

from pathlib import Path
from types import SimpleNamespace

from agent import codex_runtime
from agent.transports import codex_app_server_session as session_mod
from hermes_state import SessionDB
from hermes_constants import get_hermes_home
from tui_gateway import server

_session_profile_runtime_scope = server._session_profile_runtime_scope


class _WireClient:
    def __init__(self, **kwargs):
        self.requests = []

    def initialize(self, **kwargs):
        return {}

    def request(self, method, params=None, timeout=None):
        self.requests.append((method, params or {}))
        return {"thread": {"id": (params or {}).get("threadId", "fresh-thread")}}

    def close(self):
        pass


def test_cold_clear_restarts_native_context_in_own_profile_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    homes = [tmp_path / ".hermes", tmp_path / ".hermes" / "profiles" / "second"]
    monkeypatch.setenv("HERMES_HOME", str(homes[0]))
    monkeypatch.setattr(session_mod, "CodexAppServerClient", _WireClient)
    preserved_files = {}
    for index, home in enumerate(homes):
        home.mkdir(parents=True, exist_ok=True)
        for name in ("SOUL.md", "memories/MEMORY.md", "skills/personal/SKILL.md", "workspace/notes.txt", "cron/jobs.json"):
            path = home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"keep profile {index} {name}")
            preserved_files[path] = path.read_bytes()
        with _session_profile_runtime_scope({"profile_home": str(home)}):
            db = SessionDB(get_hermes_home() / "state.db")
            try:
                db.create_session("canonical", source="desktop", model="model-a", model_config={
                    "provider": "openai", "reasoning_config": {"effort": "high"},
                    "codex_thread_id": f"old-thread-{index}", "_usage_anchor": {"base_count": 1},
                    "_proactive_prune_rearm_tokens": 7000,
                })
                db.set_session_title("canonical", "Bot Chat")
                db.append_message("canonical", "user", f"forgotten secret {index}")
                db.create_session("side", source="desktop", model_config={"codex_thread_id": f"side-thread-{index}"})
                db.append_message("side", "user", f"side transcript {index}")
            finally:
                db.close()

    # No live agent is present while clearing. Close and reopen the DB before the first
    # provider request, exactly as a backend restart immediately after a cold clear does.
    generations = {}
    for index in (0, 1, 0):
        with _session_profile_runtime_scope({"profile_home": str(homes[index])}):
            db = SessionDB(get_hermes_home() / "state.db")
            try:
                if index not in generations:
                    assert [m["content"] for m in db.get_messages("canonical")] == [f"forgotten secret {index}"]
                    generations[index] = db.clear_conversation_by_title("Bot Chat")
            finally:
                db.close()
            db = SessionDB(get_hermes_home() / "state.db")
            try:
                history = db.get_messages_as_conversation("canonical", include_ancestors=True, include_compacted=True)
                assert history == []
                agent = SimpleNamespace(
                    _session_db=db, session_id="canonical", session_cwd=str(homes[index]),
                    _codex_session=None, tool_progress_callback=None,
                    _cached_system_prompt="Keep the bot personality", ephemeral_system_prompt=None,
                )
                codex_runtime._ensure_codex_session(agent, history + [{"role": "user", "content": "Start again"}])
                codex_runtime._start_codex_thread(agent)
                requests = agent._codex_session._client.requests
                assert [method for method, _ in requests] == ["thread/start"]
                assert requests[0][1]["developerInstructions"] == "Keep the bot personality"
                codex_runtime._close_codex_session(agent)
                assert db.get_session_by_title("Bot Chat")["id"] == "canonical"
                assert db.get_session("canonical")["model"] == "model-a"
                assert db.get_session_model_config_value("canonical", "reasoning_config") == {"effort": "high"}
                assert db.get_session_model_config_value("canonical", "provider") == "openai"
                for key in ("codex_thread_id", "_usage_anchor", "_proactive_prune_rearm_tokens"):
                    assert db.get_session_model_config_value("canonical", key) is None
                assert db.get_conversation_generation("canonical") == generations[index]["conversation_generation"] > 0
                assert db.get_conversation_generation("side") == 0
                assert [m["content"] for m in db.get_messages("side")] == [f"side transcript {index}"]
                assert db.get_session_model_config_value("side", "codex_thread_id") == f"side-thread-{index}"
            finally:
                db.close()
    assert {path: path.read_bytes() for path in preserved_files} == preserved_files
