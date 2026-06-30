from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "topic_detect_skip",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["topic_detect_skip"] = mod
spec.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as tmp:
    home = pathlib.Path(tmp)
    (home / ".hermes").mkdir()
    (home / ".hermes" / "config.yaml").write_text(
        """
topic_detect:
  enabled: true
  routing_mode: keyword
  signature:
    enabled: true
  topics:
    software_it:
      provider: openrouter
      model: inclusionai/ring-2.6-1t:free
""".strip(),
        encoding="utf-8",
    )

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        def fail_classify(messages):
            raise AssertionError("/skipdetect must bypass classifier")

        mod.classify = fail_classify
        mod._CORE_RESPONSE_SUFFIX_SUPPORTED = False

        # Test short /sd prefix
        result = mod._pre_llm_call_impl(
            user_message="/sd แก้พอร์ตในเว็บอ่านนิยาย",
            conversation_history=[],
            model="gpt-5.5",
            provider="openai-codex",
        )

        runtime = result["runtime_override"]
        assert runtime["restore_main"] is True
        assert runtime["user_message"] == "แก้พอร์ตในเว็บอ่านนิยาย"
        assert "model" not in runtime
        assert "provider" not in runtime

        suffix = mod._transform_llm_output(
            "answer",
            model="gpt-5.5",
            provider="openai-codex",
        )
        assert suffix == "answer\n\n- gpt-5.5 [skip]", suffix
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home

# Test prefix stripping for all short and full variants
for pfx in ("/sd", "!sd", "@@sd", "/skipdetect", "!skipdetect", "@@skipdetect"):
    assert mod._strip_skipdetect_prefix(f"{pfx} calculate ROI") == "calculate ROI"
    assert mod._strip_skipdetect_prefix(f"  {pfx}  hello") == "hello"
    assert mod._strip_skipdetect_prefix(f"{pfx}") == ""

assert mod._strip_skipdetect_prefix("ปกติ") is None
assert mod._strip_skipdetect_prefix("/skip") is None
assert mod._strip_skipdetect_prefix("/sdd calculate ROI") is None

print("PASS | skipdetect aliases bypass classifier, restore main, strip prefix, sign [skip]")

def test_skipdetect_smoke() -> None:
    # Module-level assertions above perform the smoke test during import;
    # this wrapper makes the script pytest-collectable too.
    assert True
