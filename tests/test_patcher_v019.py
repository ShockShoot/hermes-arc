from __future__ import annotations

import sys
from types import SimpleNamespace

import patch_run_agent
from patch_run_agent import _patch_split_turn_context

V019_TURN_CONTEXT = '''    # Restore the primary runtime if the previous turn activated fallback.
    agent._restore_primary_runtime()

    # Tell auxiliary_client what the live main provider/model are for this turn
    # after primary restoration has settled the runtime.
    try:
        from agent.auxiliary_client import set_runtime_main
        set_runtime_main(
            getattr(agent, "provider", "") or "",
            getattr(agent, "model", "") or "",
            requested_provider=getattr(agent, "requested_provider", "") or "",
            base_url=getattr(agent, "base_url", "") or "",
            api_key=getattr(agent, "api_key", "") or "",
            api_mode=getattr(agent, "api_mode", "") or "",
            auth_mode=getattr(agent, "auth_mode", "") or "",
        )
    except Exception:
        pass

    # Plugin hook: pre_llm_call (context injected into user message, not system prompt).
    plugin_user_context = ""
    try:
        from hermes_cli.plugins import invoke_hook as _invoke_hook
        _pre_results = _invoke_hook(
            "pre_llm_call",
            session_id=agent.session_id,
            task_id=effective_task_id,
            turn_id=turn_id,
            user_message=original_user_message,
            conversation_history=list(messages),
            is_first_turn=(not bool(conversation_history)),
            model=agent.model,
            platform=getattr(agent, "platform", None) or "",
            sender_id=getattr(agent, "_user_id", None) or "",
        )
        _ctx_parts: list[str] = []
        try:
            from tools.hook_output_spill import (
                get_spill_config as _spill_cfg,
                spill_if_oversized as _spill_if_oversized,
            )
            _spill_config_cached = _spill_cfg()
        except Exception:
            _spill_if_oversized = None
            _spill_config_cached = None
        for r in _pre_results:
            _piece: str = ""
            if isinstance(r, dict) and r.get("context"):
                _piece = str(r["context"])
            elif isinstance(r, str) and r.strip():
                _piece = r
            else:
                continue
            if _spill_if_oversized is not None:
                _piece = _spill_if_oversized(
                    _piece,
                    session_id=agent.session_id,
                    source="plugin hook",
                    config=_spill_config_cached,
                )
            _ctx_parts.append(_piece)
        if _ctx_parts:
            plugin_user_context = "\\n\\n".join(_ctx_parts)
    except Exception as exc:
        logger.warning("pre_llm_call hook failed: %s", exc)

    # api_content sidecar: persist what you send.
    _api_content = compose_user_api_content(
        _turn_user_msg.get("content", ""), ext_prefetch_cache, plugin_user_context
    )
    if _api_content is not None:
        _turn_user_msg["api_content"] = _api_content

    # Crash-resilience persistence must remain after plugin/api_content composition.
    agent._persist_session(messages, conversation_history)
'''


def test_v019_patch_preserves_runtime_identity_and_api_content_safeguards() -> None:
    patched = _patch_split_turn_context(V019_TURN_CONTEXT)

    assert '"requested_provider": getattr(agent, "requested_provider", "")' in patched
    assert "agent.requested_provider = _arc_base_runtime.get(" in patched
    assert patched.index("HERMES_ARC_PATCH: collect runtime_override dicts") < patched.index(
        "compose_user_api_content("
    )
    assert patched.index("compose_user_api_content(") < patched.index(
        "agent._persist_session(messages, conversation_history)"
    )
    assert "auth_mode=getattr(agent, \"auth_mode\", \"\")" in patched
    assert "from tools.hook_output_spill import (" in patched


def test_split_runtime_signature_support_is_detected_in_turn_finalizer(tmp_path, monkeypatch) -> None:
    run_agent = tmp_path / "run_agent.py"
    finalizer = tmp_path / "agent" / "turn_finalizer.py"
    finalizer.parent.mkdir()
    run_agent.write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    finalizer.write_text(
        "# HERMES_ARC_RESPONSE_SUFFIX_PATCH\n_arc_signature = None\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(__file__=str(run_agent)))
    monkeypatch.setattr(patch_run_agent, "RUN_AGENT_PATH", run_agent)

    import __init__ as topic_detect

    monkeypatch.setattr(topic_detect, "_CORE_RESPONSE_SUFFIX_SUPPORTED", None)
    assert topic_detect._core_supports_response_suffix() is True
