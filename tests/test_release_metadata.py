from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

plugin = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8")) or {}
plugin_version = str(plugin.get("version") or "")
assert re.fullmatch(r"\d+\.\d+\.\d+", plugin_version), plugin_version

pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
assert match, "pyproject.toml must declare project.version"
assert match.group(1) == plugin_version, (
    f"pyproject version {match.group(1)!r} must match plugin.yaml {plugin_version!r}"
)

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
assert f"## {plugin_version} - " in changelog, (
    f"CHANGELOG.md must include an entry for {plugin_version}"
)

print(f"PASS | release metadata is consistent for {plugin_version}")
