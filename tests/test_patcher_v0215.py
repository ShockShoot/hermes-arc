"""Compatibility with the extracted hook and output helper in Hermes v0.21.5."""
import ast
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from patch_run_agent import (
    _patch_modern_turn_context, _patch_modern_turn_finalizer,
    apply_split_runtime_patch, resolve_patch_files,
)

HERMES = Path.home() / ".hermes/hermes-agent"


def _helper(source, name, namespace):
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<arc-test>", "exec"), namespace)
    return namespace[name]


def test_current_hermes_route_skip_and_signature(monkeypatch):
    path = HERMES / "agent/turn_context.py"
    fin = HERMES / "agent/turn_finalizer.py"
    if not path.exists() or not fin.exists():
        import pytest
        pytest.skip("Hermes checkout not installed")
    original = path.read_text()
    final_original = fin.read_text()
    routed = _patch_modern_turn_context(original)
    finalized = _patch_modern_turn_finalizer(final_original)
    assert _patch_modern_turn_context(routed) == routed
    assert _patch_modern_turn_finalizer(finalized) == finalized
    compile(routed, str(path), "exec")
    compile(finalized, str(fin), "exec")
    assert set(p.name for p in apply_split_runtime_patch(resolve_patch_files(HERMES / "run_agent.py"))) == {"turn_context.py", "turn_finalizer.py"}

    results = iter([
        [{"runtime_override": {"model": "specialist", "provider": "other", "fallback_chain": [{"model": "fb", "provider": "other"}], "_arc_signature": {"topic": "coding", "routed_model": "specialist", "routed_provider": "other"}}}],
        [{"runtime_override": {"restore_main": True, "user_message": "do work", "_arc_signature": {"topic": "skip", "routed_model": "main", "routed_provider": "main-provider"}}}],
        [{"runtime_override": {"restore_main": True}}],
    ])
    lifecycle = types.ModuleType("hermes_cli.lifecycle")
    def invoke_hook(name, **kw):
        if name == "pre_llm_call":
            assert kw["provider"] == agent.provider
            return next(results)
        if kw.get("_arc_finalize"):
            return ["- " + kw["model"] + " [" + kw["_arc_finalize"]["topic"] + "]"]
        return []
    lifecycle.invoke_hook = invoke_hook
    monkeypatch.setitem(sys.modules, "hermes_cli.lifecycle", lifecycle)
    agent = SimpleNamespace(model="main", provider="main-provider", requested_provider="main-provider",
                            api_key="key", base_url="url", api_mode="mode", session_id="test",
                            _fallback_chain=[{"model": "global", "provider": "main-provider"}],
                            _primary_runtime={"model": "main", "provider": "main-provider"}, platform="")
    def switch_model(model, provider, api_key, base_url, api_mode):
        agent.model, agent.provider = model, provider
        agent._primary_runtime = {"model": model, "provider": provider}
    agent.switch_model = switch_model
    ctx = _helper(routed, "_collect_pre_llm_call_context", {"Any": object, "List": list,
                  "Optional": __import__("typing").Optional, "logger": logging.getLogger("test")})
    messages = [{"role": "user", "content": "please code"}]
    ctx(agent, effective_task_id="", turn_id="1", original_user_message="please code",
        messages=messages, conversation_history=[])
    assert (agent.model, agent.provider) == ("specialist", "other")
    assert [x["model"] for x in agent._fallback_chain] == ["fb", "global"]
    assert agent._primary_runtime == {"model": "main", "provider": "main-provider"}
    assert agent._hermes_arc_signature["topic"] == "coding"
    output = _helper(finalized, "apply_llm_output_transform", {"Any": object, "Tuple": tuple,
                     "Optional": __import__("typing").Optional, "_invoke_hook_safely": lambda *a, **kw: [],
                     "logger": logging.getLogger("test")})
    assert output(agent, "reply", turn_id="1", platform="telegram", logger=logging.getLogger("test"))[0] == "reply\n\n- specialist [coding]"
    assert output(agent, "reply", turn_id="1", platform="telegram", logger=logging.getLogger("test"))[0] == "reply"
    messages = [{"role": "user", "content": "!sd do work"}]
    ctx(agent, effective_task_id="", turn_id="2", original_user_message="!sd do work",
        messages=messages, conversation_history=[])
    assert (agent.model, agent.provider) == ("main", "main-provider")
    assert messages[0]["content"] == "do work"
    assert agent._fallback_chain == [{"model": "global", "provider": "main-provider"}]
    assert output(agent, "done", turn_id="2", platform="telegram", logger=logging.getLogger("test"))[0] == "done\n\n- main [skip]"
    # A user-initiated model switch updates Hermes' primary snapshot. ARC must
    # adopt that main route rather than reverting to its first-turn capture.
    agent.switch_model("new-main", "new-provider", "new-key", "new-url", "new-mode")
    agent._primary_runtime.update(api_key="new-key", base_url="new-url", api_mode="new-mode",
                                  requested_provider="new-provider")
    agent._fallback_chain = [{"model": "new-global", "provider": "new-provider"}]
    ctx(agent, effective_task_id="", turn_id="3", original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}], conversation_history=[])
    assert (agent.model, agent.provider) == ("new-main", "new-provider")
    assert agent._hermes_arc_base_runtime["model"] == "new-main"
    assert agent._fallback_chain == [{"model": "new-global", "provider": "new-provider"}]
