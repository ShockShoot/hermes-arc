from __future__ import annotations

from patch_run_agent import _patch_split_turn_context


def test_v018_spill_aware_pre_llm_shape_is_patched_without_losing_spill() -> None:
    source = '''    # Plugin hook: pre_llm_call (context injected into user message, not system prompt).
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
            from tools.hook_output_spill import spill_if_oversized as _spill_if_oversized
            _spill_config_cached = object()
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
                _piece = _spill_if_oversized(_piece, config=_spill_config_cached)
            _ctx_parts.append(_piece)
        if _ctx_parts:
            plugin_user_context = "\\n\\n".join(_ctx_parts)
    except Exception as exc:
        logger.warning("pre_llm_call hook failed: %s", exc)
'''

    patched = _patch_split_turn_context(source)

    assert "HERMES_ARC_PATCH: collect runtime_override dicts" in patched
    assert '_arc_ov = r.get("runtime_override")' in patched
    assert "provider=getattr(agent, \"provider\", \"\")" in patched
    assert "HERMES_ARC_TOPIC_FALLBACK_PATCH" in patched
    assert "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in patched
    assert "from tools.hook_output_spill import spill_if_oversized" in patched
    assert "_piece = _spill_if_oversized(_piece, config=_spill_config_cached)" in patched


def test_v018_split_patch_is_idempotent() -> None:
    source = '''    # Plugin hook: pre_llm_call (context injected into user message, not system prompt).
    plugin_user_context = ""
    try:
        _pre_results = _invoke_hook(
            "pre_llm_call",
            model=agent.model,
            platform=getattr(agent, "platform", None) or "",
        )
        _ctx_parts: list[str] = []
        for r in _pre_results:
            _piece: str = ""
            if isinstance(r, dict) and r.get("context"):
                _piece = str(r["context"])
            elif isinstance(r, str) and r.strip():
                _piece = r
            else:
                continue
            _ctx_parts.append(_piece)
        if _ctx_parts:
            plugin_user_context = "\\n\\n".join(_ctx_parts)
    except Exception as exc:
        logger.warning("pre_llm_call hook failed: %s", exc)
'''
    once = _patch_split_turn_context(source)
    assert _patch_split_turn_context(once) == once
