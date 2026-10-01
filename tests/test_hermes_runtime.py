"""Exercise ARC in the installed Hermes runtime, which may not ship PyYAML."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_doctor_loads_without_pyyaml(tmp_path):
    if shutil.which("hermes") is None:
        pytest.skip("Hermes CLI is not installed")
    target = tmp_path / "topic_detect"
    shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    result = subprocess.run(
        ["hermes", "plugins", "doctor", str(target), "--ci"],
        capture_output=True, text=True, timeout=35,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 hook(s)" in result.stdout
    assert "WARN:" not in result.stdout


def test_installer_check_without_pyyaml_uses_uv(tmp_path):
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").write_text("#!/bin/sh\nexec /usr/bin/python3 -S \"$@\"\n")
    (shim / "curl").write_text("#!/bin/sh\nprintf 'version: 2.3.1\\n'\n")
    for path in shim.iterdir():
        path.chmod(0o755)
    local = tmp_path / "topic_detect"
    local.mkdir()
    (local / "plugin.yaml").write_text("version: 2.3.1\n")
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--check", "--plugin-dir", str(local)],
        env={**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local version : 2.3.1" in result.stdout
