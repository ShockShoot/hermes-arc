"""Routing and signatures must not cross independent Hermes sessions/profiles."""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_active_profile_config_and_persona(tmp_path, monkeypatch):
    from config import load_config
    from agent_loader import get_agent_prompt

    profile = tmp_path / "profile"
    (profile / "plugins/topic_detect").mkdir(parents=True)
    (profile / "config.yaml").write_text('topic_detect:\n  enabled: false\n  agents_file: ~/.hermes/plugins/topic_detect/AGENTS.md\n')
    (profile / "plugins/topic_detect/AGENTS.md").write_text("# software_it\nProfile-specific persona\n")
    monkeypatch.setenv("HERMES_HOME", str(profile))
    assert load_config().enabled is False
    assert load_config().agents_file == str(profile / "plugins/topic_detect/AGENTS.md")
    assert get_agent_prompt("software_it") == "Profile-specific persona"


def test_sessions_have_independent_inertia_and_legacy_signatures(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.yaml").write_text('''topic_detect:
  enabled: true
  routing_mode: keyword
  signature:
    enabled: true
  topics:
    software_it:
      provider: openrouter
      model: specialist
''')
    monkeypatch.setenv("HERMES_HOME", str(profile))
    plugin = load_plugin("topic_detect_isolation")
    monkeypatch.setattr(plugin, "_CORE_RESPONSE_SUFFIX_SUPPORTED", False)
    a = plugin._pre_llm_call_impl(user_message="fix code", conversation_history=[],
                                  session_id="A", model="main", provider="main-provider")
    b = plugin._pre_llm_call_impl(user_message="thanks", conversation_history=[],
                                  session_id="B", model="main", provider="main-provider")
    assert a["runtime_override"]["model"] == "specialist"
    assert b["runtime_override"]["restore_main"] is True
    # Historical technical intent must not hijack an ordinary new turn.
    plain = plugin._pre_llm_call_impl(user_message="hi", conversation_history=[
        {"role": "user", "content": "fix code"}], session_id="C",
        model="main", provider="main-provider")
    assert plain["runtime_override"]["restore_main"] is True
    assert plugin._extract_messages({"user_message": [{"type": "text", "text": "fix code"}, {"type": "image_url", "image_url": "image"}]}) == ["fix code"]
    assert plugin._transform_llm_output("response B", session_id="B", model="main", provider="main-provider") == "response B\n\n- main [general]"
    assert plugin._transform_llm_output("response A", session_id="A", model="specialist", provider="openrouter") == "response A\n\n- specialist [software_it]"
    other = tmp_path / "other-profile"
    other.mkdir()
    (other / "config.yaml").write_text((profile / "config.yaml").read_text())
    monkeypatch.setenv("HERMES_HOME", str(other))
    assert plugin._transform_llm_output("unrelated", session_id="C", model="main", provider="main-provider") is None


def test_installer_config_uses_selected_profile(tmp_path, monkeypatch):
    import os
    import yaml

    profile = tmp_path / "profile"
    profile.mkdir()
    plugin_dir = profile / "plugins/topic_detect"
    plugin_dir.mkdir(parents=True)
    config_path = profile / "config.yaml"
    config_path.write_text('topic_detect:\n  agents_file: ~/.hermes/plugins/topic_detect/AGENTS.md\n')
    script = (ROOT / "install.sh").read_text()
    syntax = subprocess.run(["bash", "-n", str(ROOT / "install.sh")], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    assert 'if [[ "${CONFIG_PATH_EXPLICIT}" == true && "${PLUGIN_DIR_EXPLICIT}" != true ]]; then\n  PLUGIN_DIR="$(dirname "${CONFIG_PATH}")/plugins/topic_detect"' in script
    start = '  python3 - "${CONFIG_PATH}" "${PLUGIN_DIR}" <<\'PY\'\n'
    code = script.split(start, 1)[1].split("\nPY\n", 1)[0]
    env = dict(os.environ, HERMES_HOME=str(profile))
    env.pop("OPENROUTER_API_KEY", None)
    proc = subprocess.run([sys.executable, "-c", code, str(config_path), str(plugin_dir)],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    installed = yaml.safe_load(config_path.read_text())
    assert installed["topic_detect"]["agents_file"] == str(plugin_dir / "AGENTS.md")
    assert "api_key" not in installed["topic_detect"]["semantic"]


def test_semantic_reason_is_not_logged(tmp_path, monkeypatch, caplog):
    from types import SimpleNamespace

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.yaml").write_text('''topic_detect:
  enabled: true
  routing_mode: semantic
  semantic:
    enabled: true
    api_key: fake
''')
    monkeypatch.setenv("HERMES_HOME", str(profile))
    plugin = load_plugin("topic_detect_reasonlog")
    secret = "private-text-echoed-by-classifier"
    monkeypatch.setattr(plugin, "semantic_classify", lambda *a, **kw: SimpleNamespace(
        topic="none", confidence=0.0, reason=secret))
    monkeypatch.setattr(plugin, "_CORE_RESPONSE_SUFFIX_SUPPORTED", False)
    with caplog.at_level(logging.INFO, logger="topic_detect"):
        plugin._pre_llm_call_impl(user_message="hello", conversation_history=[],
                                  session_id="reason", model="main", provider="main-provider")
    assert secret not in caplog.text


def test_runtime_log_does_not_expose_api_key(tmp_path, monkeypatch, caplog):
    profile = tmp_path / "profile"
    profile.mkdir()
    secret = "not-a-real-secret-for-test"
    (profile / "config.yaml").write_text(f'''topic_detect:
  enabled: true
  routing_mode: keyword
  topics:
    software_it:
      provider: openrouter
      model: specialist
      api_key: {secret}
''')
    monkeypatch.setenv("HERMES_HOME", str(profile))
    plugin = load_plugin("topic_detect_logtest")
    monkeypatch.setattr(plugin, "_CORE_RESPONSE_SUFFIX_SUPPORTED", False)
    with caplog.at_level(logging.INFO, logger="topic_detect"):
        plugin._pre_llm_call_impl(user_message="fix code", conversation_history=[],
                                  session_id="log", model="main", provider="main-provider")
    assert secret not in caplog.text
