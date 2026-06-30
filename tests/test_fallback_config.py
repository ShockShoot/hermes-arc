from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import load_config  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "topic_detect",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["topic_detect"] = mod
spec.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as tmp:
    home = pathlib.Path(tmp)
    (home / ".hermes").mkdir()
    (home / ".hermes" / "config.yaml").write_text(
        """
topic_detect:
  enabled: true
  topics:
    software_it:
      provider: openrouter
      model: inclusionai/ring-2.6-1t:free
      fallbacks:
        - provider: openrouter
          model: baidu/cobuddy:free
        - provider: openrouter
          model: deepseek/deepseek-v4-flash:free
""".strip(),
        encoding="utf-8",
    )

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        cfg = load_config()
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home

software = cfg.topics["software_it"]
assert software.provider == "openrouter"
assert software.model == "inclusionai/ring-2.6-1t:free"
assert len(software.fallbacks) == 2
assert software.fallbacks[0].provider == "openrouter"
assert software.fallbacks[0].model == "baidu/cobuddy:free"
assert software.fallbacks[1].provider == "openrouter"
assert software.fallbacks[1].model == "deepseek/deepseek-v4-flash:free"

updates = mod._runtime_updates(software)
assert updates["model"] == "inclusionai/ring-2.6-1t:free"
assert updates["provider"] == "openrouter"
assert updates["fallback_chain"] == [
    {"provider": "openrouter", "model": "baidu/cobuddy:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash:free"},
]

software.fallbacks = []
updates_without_topic_fallbacks = mod._runtime_updates(software)
assert updates_without_topic_fallbacks["fallback_chain"] == []

print("PASS | fallback config loads and emits scoped runtime fallback_chain")


def test_fallback_config_smoke() -> None:
    # Module-level assertions above perform the smoke test during import;
    # this wrapper makes the script pytest-collectable too.
    assert True
