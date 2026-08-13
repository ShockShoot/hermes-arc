from __future__ import annotations

from patch_run_agent import (
    _patch_split_turn_context,
    _patch_split_turn_finalizer,
    check_runtime_override_handling,
)
from test_patcher_v019 import V019_TURN_CONTEXT


V020_TURN_FINALIZER = '''            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                platform=getattr(agent, "platform", None) or "",
            )
            for _hook_result in _transform_results:
                if isinstance(_hook_result, str) and _hook_result:
                    _pre_transform_response = final_response
                    final_response = _hook_result
                    _response_transformed = True
                    break  # First non-empty string wins
        except Exception as exc:
            logger.warning("transform_llm_output hook failed: %s", exc)
'''


def test_v020_finalizer_patch_handles_pre_transform_assignment_and_is_idempotent() -> None:
    patched = _patch_split_turn_finalizer(V020_TURN_FINALIZER)

    assert "HERMES_ARC_TRANSFORM_PROVIDER_PATCH" in patched
    assert "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in patched
    assert "_arc_suffix_results" in patched
    assert patched.count("HERMES_ARC_RESPONSE_SUFFIX_PATCH") == 1
    assert _patch_split_turn_finalizer(patched) == patched


def test_check_does_not_mistake_context_signature_stash_for_finalizer_support() -> None:
    context_only = _patch_split_turn_context(V019_TURN_CONTEXT)

    assert "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in context_only
    assert check_runtime_override_handling(context_only)["handles_response_suffix"] is False


def test_requested_provider_restores_even_when_live_runtime_already_matches() -> None:
    patched = _patch_split_turn_context(V019_TURN_CONTEXT)
    conditional_end = patched.index("            agent._fallback_chain")
    restore = patched.index("            agent.requested_provider =")

    assert restore < conditional_end


def test_v225_requested_provider_patch_is_upgraded_in_place() -> None:
    current = _patch_split_turn_context(V019_TURN_CONTEXT)
    current_block = '''                agent.switch_model(_arc_base_runtime.get("model") or getattr(agent, "model", ""), _arc_base_runtime.get("provider") or getattr(agent, "provider", ""), _arc_base_runtime.get("api_key") or getattr(agent, "api_key", ""), _arc_base_runtime.get("base_url") or "", _arc_base_runtime.get("api_mode") or "")
                if isinstance(_arc_primary_snapshot, dict):
                    agent._primary_runtime = _arc_primary_snapshot
            agent.requested_provider = _arc_base_runtime.get("requested_provider") or getattr(agent, "provider", "")
'''
    v225_block = '''                agent.switch_model(_arc_base_runtime.get("model") or getattr(agent, "model", ""), _arc_base_runtime.get("provider") or getattr(agent, "provider", ""), _arc_base_runtime.get("api_key") or getattr(agent, "api_key", ""), _arc_base_runtime.get("base_url") or "", _arc_base_runtime.get("api_mode") or "")
                agent.requested_provider = _arc_base_runtime.get("requested_provider") or getattr(agent, "provider", "")
                if isinstance(_arc_primary_snapshot, dict):
                    agent._primary_runtime = _arc_primary_snapshot
'''
    old_patch = current.replace(current_block, v225_block, 1)

    upgraded = _patch_split_turn_context(old_patch)

    assert old_patch != upgraded
    assert current_block in upgraded
    assert _patch_split_turn_context(upgraded) == upgraded