from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "topic_detect",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["topic_detect"] = mod
spec.loader.exec_module(mod)

suffix = mod._transform_llm_output(
    "",
    model="gpt-5.5",
    provider="openai-codex",
    _arc_finalize={
        "topic": "general",
        "routed_model": "gpt-5.5",
        "routed_provider": "openai-codex",
    },
)
assert suffix == "- gpt-5.5 [general]", suffix

fallback_suffix = mod._transform_llm_output(
    "",
    model="google/gemini-3-flash",
    provider="openrouter",
    _arc_finalize={
        "topic": "software_it",
        "routed_model": "inclusionai/ring-2.6-1t:free",
        "routed_provider": "openrouter",
    },
)
assert fallback_suffix == "- gemini-3-flash [software_it | routed: ring-2.6-1t]", fallback_suffix

skip_suffix = mod._transform_llm_output(
    "",
    model="gpt-5.5",
    provider="openai-codex-oauth",
    _arc_finalize={
        "topic": "general",
        "routed_model": "gpt-5.5",
        "routed_provider": "openai-codex",
        "reason": "skip",
    },
)
assert skip_suffix == "- gpt-5.5 [skip]", skip_suffix

print("PASS | _arc_finalize renders final ARC signature")


def test_signature_finalize_smoke() -> None:
    # Module-level assertions above perform the smoke test during import;
    # this wrapper makes the script pytest-collectable too.
    assert True
