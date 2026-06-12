#!/usr/bin/env python3
"""
Hermes ARC v1.2.0 — run_agent.py compatibility checker & patcher

Checks whether run_agent.py properly handles runtime_override from
pre_llm_call hooks, provider in transform_llm_output, and response
suffix rendering. Optionally applies a compatibility patch if needed.

Usage:
    python3 patch_run_agent.py --check     # Check only
    python3 patch_run_agent.py --patch     # Check and patch if needed
    python3 patch_run_agent.py --verify    # Verify patch applied correctly
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RUN_AGENT_PATH = Path("/usr/local/lib/hermes-agent/run_agent.py")
BACKUP_SUFFIX = ".backup"


def _safe_resolve(path: Path) -> Path | None:
    """Resolve a path without throwing for broken symlinks or unreadable parents."""
    try:
        return path.expanduser().resolve()
    except OSError:
        return None


def _hermes_home_candidates() -> list[Path]:
    """Return likely Hermes homes, preferring the active `hermes config path`."""
    homes: list[Path] = []

    def add_home(path: str | Path | None) -> None:
        if not path:
            return
        resolved = _safe_resolve(Path(path))
        if resolved and resolved not in homes:
            homes.append(resolved)

    add_home(os.environ.get("HERMES_HOME"))

    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        try:
            proc = subprocess.run(
                [hermes_bin, "config", "path"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
            for line in proc.stdout.splitlines():
                candidate = line.strip()
                if candidate.endswith("config.yaml"):
                    add_home(Path(candidate).expanduser().parent)
        except (OSError, subprocess.SubprocessError):
            pass

    add_home(Path.home() / ".hermes")
    return homes


def _read_shebang_interpreter(script: Path) -> Path | None:
    """Best-effort interpreter extraction from an executable wrapper script."""
    try:
        with script.open("rb") as fh:
            first = fh.readline(512).decode(errors="ignore").strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None

    parts = first[2:].strip().split()
    if not parts:
        return None
    if Path(parts[0]).name == "env":
        # Handles common wrappers: #!/usr/bin/env python3, env -S python3 -u
        rest = parts[1:]
        if rest[:1] == ["-S"]:
            rest = rest[1:]
        if rest:
            found = shutil.which(rest[0])
            return Path(found) if found else None
        return None
    return Path(parts[0])


def _probe_imported_run_agent(python_exe: Path | str | None) -> Path | None:
    """Ask a Python interpreter where its importable run_agent module lives."""
    if not python_exe:
        return None
    exe = str(python_exe)
    code = (
        "import inspect, pathlib, sys\n"
        "try:\n"
        "    import run_agent\n"
        "    print(pathlib.Path(inspect.getfile(run_agent)).resolve())\n"
        "except Exception:\n"
        "    sys.exit(1)\n"
    )
    try:
        proc = subprocess.run(
            [exe, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    first = proc.stdout.splitlines()[0].strip() if proc.stdout.splitlines() else ""
    return Path(first) if first else None


def _process_runtime_candidates() -> list[Path]:
    """Inspect running Hermes processes for cwd/executable-adjacent run_agent.py files."""
    paths: list[Path] = []
    proc_root = Path("/proc")
    if not proc_root.exists():
        return paths

    for pid_dir in proc_root.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            cmdline = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if "hermes" not in cmdline.lower():
            continue

        cwd = _safe_resolve(pid_dir / "cwd")
        if cwd:
            paths.append(cwd / "run_agent.py")
            paths.append(cwd / "hermes-agent" / "run_agent.py")

        exe = _safe_resolve(pid_dir / "exe")
        if exe:
            paths.append(exe.parent / "run_agent.py")
            paths.append(exe.parent.parent / "run_agent.py")
            imported = _probe_imported_run_agent(exe)
            if imported:
                paths.append(imported)
    return paths


def _looks_like_hermes_run_agent(path: Path) -> bool:
    """Return True if path appears to be Hermes Agent's core run_agent.py."""
    try:
        if not path.is_file() or path.name != "run_agent.py":
            return False
        text = path.read_text(errors="ignore")[:250_000]
    except OSError:
        return False
    markers = ("class AIAgent", "pre_llm_call", "run_conversation")
    return sum(marker in text for marker in markers) >= 2


def find_run_agent_candidates() -> list[Path]:
    """Locate likely Hermes run_agent.py files across source, pip/uv, and service layouts."""
    candidates: list[Path] = []

    def add(path: str | Path | None) -> None:
        if not path:
            return
        resolved = _safe_resolve(Path(path))
        if resolved and resolved not in candidates and _looks_like_hermes_run_agent(resolved):
            candidates.append(resolved)

    # Explicit environment override for scripts/services.
    add(os.environ.get("HERMES_RUN_AGENT_PATH"))

    # Static/common source-checkout locations.
    known = [
        RUN_AGENT_PATH,
        Path.cwd() / "run_agent.py",
        Path.home() / ".hermes/hermes-agent/run_agent.py",
        Path.home() / ".hermes/hermes_agent/run_agent.py",
        Path.home() / "hermes-agent/run_agent.py",
    ]
    for home in _hermes_home_candidates():
        known.extend([
            home / "hermes-agent/run_agent.py",
            home / "hermes_agent/run_agent.py",
        ])
    for path in known:
        add(path)

    # The active `hermes` wrapper is the best signal for pip/uv installs.
    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        exe = _safe_resolve(Path(hermes_bin))
        if exe:
            for parent in [exe.parent, *exe.parents]:
                add(parent / "run_agent.py")
                add(parent.parent / "run_agent.py")

            shebang_python = _read_shebang_interpreter(exe)
            add(_probe_imported_run_agent(shebang_python))

    # Also probe the interpreter running the patcher; this covers `python -m pip`
    # editable installs where `hermes` and the patcher share the same venv.
    add(_probe_imported_run_agent(sys.executable))
    add(_probe_imported_run_agent(shutil.which("python3")))

    # If a gateway/CLI is already running, inspect its process context.
    for path in _process_runtime_candidates():
        add(path)

    # Last resort: bounded filesystem searches in common install roots.
    roots = [
        Path("/usr/local/lib"),
        Path("/usr/local/share"),
        Path("/opt"),
        Path.home() / ".hermes",
        Path.home() / ".local",
    ]
    for home in _hermes_home_candidates():
        roots.append(home)
    for root in roots:
        resolved_root = _safe_resolve(root)
        if not resolved_root or not resolved_root.exists():
            continue
        try:
            for path in resolved_root.rglob("run_agent.py"):
                add(path)
        except (OSError, PermissionError):
            continue

    return sorted(candidates, key=lambda p: str(p))


def choose_run_agent_path(explicit_path: str | None = None, interactive: bool = True) -> Path:
    """Choose a run_agent.py path, prompting when multiple candidates exist."""
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not _looks_like_hermes_runtime_file(path):
            print(f"❌ Not a valid Hermes runtime file: {path}")
            sys.exit(1)
        return path

    candidates = find_run_agent_candidates()
    if not candidates:
        print("❌ No Hermes run_agent.py candidates found.")
        print("   Pass --path /path/to/run_agent.py if Hermes is installed in a custom location.")
        sys.exit(1)

    if len(candidates) == 1:
        return candidates[0]

    print("⚠️  Multiple Hermes run_agent.py candidates found:")
    for i, path in enumerate(candidates, 1):
        print(f"  {i}. {path}")

    if interactive and sys.stdin.isatty():
        while True:
            choice = input(f"Select target [1-{len(candidates)}] or q to abort: ").strip().lower()
            if choice in {"q", "quit", "abort"}:
                sys.exit(1)
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1]

    print("❌ Ambiguous runtime target in non-interactive mode.")
    print("   Re-run with --path /path/to/run_agent.py")
    sys.exit(1)


def resolve_patch_target(path: Path) -> Path:
    """Return the file that owns the conversation loop for this Hermes runtime.

    Hermes v0.14+ moved ``run_conversation`` out of ``run_agent.py`` into
    ``agent/conversation_loop.py`` while keeping ``run_agent.py`` as a thin
    forwarder. Keep the public CLI contract accepting ``--path run_agent.py``
    but patch/check the module that actually contains plugin hooks.
    """
    if path.name == "run_agent.py":
        modular = path.parent / "agent" / "conversation_loop.py"
        if modular.exists():
            try:
                text = modular.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if "pre_llm_call" in text and "def run_conversation" in text:
                return modular
    return path


def check_runtime_override_handling(content: str) -> dict:
    """Check if run_agent.py handles runtime_override from pre_llm_call hooks."""
    results = {}

    results["has_pre_llm_call_hook"] = "pre_llm_call" in content
    results["has_transform_llm_output_hook"] = "transform_llm_output" in content
    results["reads_runtime_override"] = "_runtime_override" in content and "runtime_override" in content
    results["uses_switch_model_runtime"] = bool(
        "switch_model(" in content
        and "_hermes_arc_base_runtime" in content
        and ("_arc_resolve_provider_client" in content or "runtime override switch failed" in content)
    )
    results["handles_response_suffix"] = bool(
        "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in content
        and "_arc_signature" in content
    )
    results["sends_provider_in_transform_hook"] = bool(
        re.search(r'transform_llm_output.*provider\s*=\s*(?:self|agent)\.provider', content, re.DOTALL)
    )
    results["supports_topic_fallback_chain"] = "HERMES_ARC_TOPIC_FALLBACK_PATCH" in content
    results["supports_skipdetect_message_rewrite"] = "HERMES_ARC_SKIPDETECT_PATCH" in content

    return results


def needs_patch(results: dict) -> bool:
    """Determine if patching is needed."""
    required = [
        "has_pre_llm_call_hook",
        "has_transform_llm_output_hook",
        "reads_runtime_override",
        "uses_switch_model_runtime",
        "handles_response_suffix",
        "sends_provider_in_transform_hook",
        "supports_topic_fallback_chain",
        "supports_skipdetect_message_rewrite",
    ]
    return not all(results.get(k, False) for k in required)


def apply_patch(path: Path, content: str) -> str:
    """
    Apply compatibility patch to run_agent.py v1.2.0.

    Three patch sections:
    1. HERMES_ARC_PATCH: runtime_override support (collect + apply via switch_model)
    2. HERMES_ARC_RESPONSE_SUFFIX_PATCH: render _arc_signature in final response
    3. transform_llm_output provider injection
    """
    new_content = content

    is_modular_loop = "def run_conversation(\n    agent," in new_content or "agent.conversation_loop" in new_content
    if is_modular_loop:
        if "_runtime_override = {}" not in new_content:
            init_old = '    _plugin_user_context = ""\n    try:\n'
            init_new = (
                '    _plugin_user_context = ""\n'
                '    # HERMES_ARC_PATCH: runtime_override support\n'
                '    _runtime_override = {}\n'
                '    _plugin_system_prompt = ""  # HERMES_ARC_SYSTEM_PROMPT_PATCH\n'
                '    try:\n'
            )
            if init_old in new_content:
                new_content = new_content.replace(init_old, init_new, 1)
            else:
                print("⚠️  Could not locate modular pre_llm_call initialization — init patch skipped")

        if '_arc_ov = r.get("runtime_override")' not in new_content:
            loop_old = (
                '        for r in _pre_results:\n'
                '            if isinstance(r, dict) and r.get("context"):\n'
                '                _ctx_parts.append(str(r["context"]))\n'
                '            elif isinstance(r, str) and r.strip():\n'
                '                _ctx_parts.append(r)\n'
                '        if _ctx_parts:\n'
                '            _plugin_user_context = "\\n\\n".join(_ctx_parts)\n'
            )
            loop_new = (
                '        for r in _pre_results:\n'
                '            if isinstance(r, dict):\n'
                '                if r.get("context"):\n'
                '                    _ctx_parts.append(str(r["context"]))\n'
                '                _arc_ov = r.get("runtime_override")\n'
                '                if isinstance(_arc_ov, dict):\n'
                '                    _runtime_override.update(_arc_ov)\n'
                '            elif isinstance(r, str) and r.strip():\n'
                '                _ctx_parts.append(r)\n'
                '        # HERMES_ARC_SYSTEM_PROMPT_PATCH: capture system prompt override\n'
                '        _arc_sys = _runtime_override.get("system_prompt")\n'
                '        if _arc_sys:\n'
                '            _plugin_system_prompt = str(_arc_sys)\n'
                '            _ctx_parts.append(_plugin_system_prompt)\n'
                '        if _ctx_parts:\n'
                '            _plugin_user_context = "\\n\\n".join(_ctx_parts)\n'
            )
            if loop_old in new_content:
                new_content = new_content.replace(loop_old, loop_new, 1)
            else:
                print("⚠️  Could not locate modular pre_llm_call result loop — collect patch skipped")

        if "_arc_resolve_provider_client" not in new_content:
            ctx_old = '        if _ctx_parts:\n            _plugin_user_context = "\\n\\n".join(_ctx_parts)\n'
            runtime_block = '''        if _ctx_parts:
            _plugin_user_context = "\\n\\n".join(_ctx_parts)

        # HERMES_ARC_SKIPDETECT_PATCH: allow router plugins to rewrite the
        # current turn user message after inspecting a command prefix.
        _arc_user_message = _runtime_override.get("user_message")
        if isinstance(_arc_user_message, str):
            user_message = _arc_user_message
            original_user_message = _arc_user_message
            try:
                user_msg["content"] = _arc_user_message
                agent._persist_user_message_override = _arc_user_message
            except Exception:
                pass

        # HERMES_ARC_PATCH: apply runtime routing overrides from plugins.
        # Use Hermes' own switch_model() instead of mutating attributes
        # directly — preserves provider-specific api_mode, OAuth, headers,
        # context-compressor metadata, and client rebuild logic.
        if isinstance(_runtime_override, dict) and _runtime_override:
            _arc_restore_main = bool(_runtime_override.get("restore_main"))
            _arc_model = _runtime_override.get("model")
            _arc_provider = _runtime_override.get("provider")
            _arc_base_url = _runtime_override.get("base_url")
            _arc_api_key = _runtime_override.get("api_key")
            _arc_api_mode = _runtime_override.get("api_mode")

            if not hasattr(agent, "_hermes_arc_base_runtime"):
                agent._hermes_arc_base_runtime = {
                    "model": getattr(agent, "model", ""),
                    "provider": getattr(agent, "provider", ""),
                    "base_url": getattr(agent, "base_url", ""),
                    "api_key": getattr(agent, "api_key", ""),
                    "api_mode": getattr(agent, "api_mode", ""),
                    "fallback_chain": list(getattr(agent, "_fallback_chain", []) or []),
                }

            if _arc_restore_main:
                _arc_base = getattr(agent, "_hermes_arc_base_runtime", None) or {}
                _base_model = _arc_base.get("model")
                _base_provider = _arc_base.get("provider")
                if _base_model and _base_provider:
                    if hasattr(agent, "switch_model"):
                        agent.switch_model(
                            _base_model,
                            _base_provider,
                            api_key=_arc_base.get("api_key", ""),
                            base_url=_arc_base.get("base_url", ""),
                            api_mode=_arc_base.get("api_mode", ""),
                        )
                    else:
                        agent.model = str(_base_model)
                        agent.provider = str(_base_provider)
                        if _arc_base.get("base_url"):
                            agent.base_url = str(_arc_base.get("base_url")).rstrip("/")
                        if _arc_base.get("api_key"):
                            agent.api_key = str(_arc_base.get("api_key"))
                    _base_fallback_chain = [
                        f for f in (_arc_base.get("fallback_chain") or [])
                        if isinstance(f, dict) and f.get("provider") and f.get("model")
                    ]
                    agent._fallback_chain = list(_base_fallback_chain)
                    agent._fallback_model = agent._fallback_chain[0] if agent._fallback_chain else None
                    agent._fallback_index = 0
                    agent._fallback_activated = False
                    logger.info(
                        "hermes-arc: restored main runtime provider=%s model=%s fallbacks=%d",
                        getattr(agent, "provider", ""),
                        getattr(agent, "model", ""),
                        len(agent._fallback_chain),
                    )
            elif _arc_model or _arc_provider or _arc_base_url or _arc_api_key:
                _target_provider = str(_arc_provider or getattr(agent, "provider", "") or "auto")
                _target_model = str(_arc_model or getattr(agent, "model", ""))
                _resolved_model = _target_model
                _resolved_api_key = str(_arc_api_key or "")
                _resolved_base_url = str(_arc_base_url or "")
                _resolved_api_mode = str(_arc_api_mode or "")

                try:
                    from agent.auxiliary_client import resolve_provider_client as _arc_resolve_provider_client
                    _arc_client, _arc_client_model = _arc_resolve_provider_client(
                        _target_provider,
                        model=_target_model,
                        raw_codex=True,
                        explicit_base_url=_resolved_base_url or None,
                        explicit_api_key=_resolved_api_key or None,
                        api_mode=_resolved_api_mode or None,
                        main_runtime=getattr(agent, "_primary_runtime", None),
                    )
                    if _arc_client is not None:
                        _resolved_model = str(_arc_client_model or _target_model)
                        _resolved_api_key = str(getattr(_arc_client, "api_key", "") or _resolved_api_key)
                        _resolved_base_url = str(getattr(_arc_client, "base_url", "") or _resolved_base_url).rstrip("/")
                except Exception as _arc_resolve_error:
                    logger.debug("hermes-arc: provider resolution skipped: %s", _arc_resolve_error)

                if not _resolved_api_mode:
                    try:
                        from hermes_cli.providers import determine_api_mode as _arc_determine_api_mode
                        _resolved_api_mode = _arc_determine_api_mode(_target_provider, _resolved_base_url)
                    except Exception:
                        _resolved_api_mode = getattr(agent, "api_mode", "")

                if hasattr(agent, "switch_model"):
                    agent.switch_model(
                        _resolved_model,
                        _target_provider,
                        api_key=_resolved_api_key,
                        base_url=_resolved_base_url,
                        api_mode=_resolved_api_mode,
                    )
                else:
                    agent.model = str(_resolved_model)
                    agent.provider = str(_target_provider)
                    if _resolved_base_url:
                        agent.base_url = _resolved_base_url
                    if _resolved_api_key:
                        agent.api_key = _resolved_api_key

                # HERMES_ARC_TOPIC_FALLBACK_PATCH: optional topic-scoped
                # fallback chain supplied by topic_detect runtime_override.
                _arc_fb_chain_raw = _runtime_override.get("fallback_chain")
                if isinstance(_arc_fb_chain_raw, list):
                    _arc_topic_fb_chain = [
                        f for f in _arc_fb_chain_raw
                        if isinstance(f, dict) and f.get("provider") and f.get("model")
                    ]
                    _arc_base = getattr(agent, "_hermes_arc_base_runtime", None) or {}
                    _arc_global_fb_chain = [
                        f for f in (_arc_base.get("fallback_chain") or [])
                        if isinstance(f, dict) and f.get("provider") and f.get("model")
                    ]
                    agent._fallback_chain = list(_arc_topic_fb_chain) + list(_arc_global_fb_chain)
                    agent._fallback_model = agent._fallback_chain[0] if agent._fallback_chain else None
                    agent._fallback_index = 0
                    agent._fallback_activated = False
                    logger.info(
                        "hermes-arc: topic fallback chain loaded topic_entries=%d global_entries=%d total=%d",
                        len(_arc_topic_fb_chain),
                        len(_arc_global_fb_chain),
                        len(agent._fallback_chain),
                    )

                logger.info(
                    "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",
                    getattr(agent, "provider", ""),
                    getattr(agent, "model", ""),
                    getattr(agent, "api_mode", ""),
                )
'''
            if ctx_old in new_content:
                new_content = new_content.replace(ctx_old, runtime_block, 1)
            else:
                print("⚠️  Could not locate modular context assembly — runtime patch skipped")

        if "HERMES_ARC_TRANSFORM_PROVIDER_PATCH" not in new_content:
            old_hook = '''            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                platform=getattr(agent, "platform", None) or "",
            )'''
            new_hook = '''            # HERMES_ARC_TRANSFORM_PROVIDER_PATCH: add provider for signature rebuild
            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                provider=agent.provider,
                platform=getattr(agent, "platform", None) or "",
            )'''
            if old_hook in new_content:
                new_content = new_content.replace(old_hook, new_hook, 1)
            else:
                print("⚠️  Could not locate modular transform_llm_output hook call — provider patch skipped")

        if "_arc_signature" not in new_content:
            suffix_marker = '    # Plugin hook: post_llm_call'
            suffix_block = '''    # HERMES_ARC_RESPONSE_SUFFIX_PATCH: render ARC signature from
    # _runtime_override (structured _arc_signature dict) and the final
    # model/provider after any fallback occurred.
    if final_response and not interrupted:
        try:
            _arc_sig = (_runtime_override or {}).get("_arc_signature")
            if isinstance(_arc_sig, dict):
                try:
                    from hermes_cli.plugins import invoke_hook as _arc_inv
                    _arc_final_sig_results = _arc_inv(
                        "transform_llm_output",
                        response_text="",
                        session_id=agent.session_id or "",
                        model=agent.model,
                        provider=agent.provider,
                        platform=getattr(agent, "platform", None) or "",
                        _arc_finalize=_arc_sig,
                    )
                    for _arc_hr in _arc_final_sig_results:
                        if isinstance(_arc_hr, str) and _arc_hr:
                            final_response = final_response.rstrip() + "\\n\\n" + _arc_hr
                            break
                except Exception:
                    _routed = _arc_sig.get("routed_model", "")
                    _routed_p = _arc_sig.get("routed_provider", "")
                    _final_m = agent.model or ""
                    _final_p = agent.provider or ""
                    _topic = _arc_sig.get("topic", "")
                    _short = lambda m: m.split("/")[-1] if "/" in m else m
                    if _short(_final_m) == _short(_routed) and _final_p == _routed_p:
                        _arc_suffix = f"- {_short(_final_m)} [{_topic}]"
                    else:
                        _arc_suffix = f"- {_short(_final_m)} [{_topic} | routed: {_short(_routed)}]"
                    if _arc_suffix:
                        final_response = final_response.rstrip() + "\\n\\n" + _arc_suffix
        except Exception:
            logger.debug("hermes-arc: response suffix render failed")

'''
            if suffix_marker in new_content:
                new_content = new_content.replace(suffix_marker, suffix_block + suffix_marker, 1)
            else:
                print("⚠️  Could not locate modular post_llm_call hook boundary — suffix patch skipped")

        return new_content

    # ─── Patch 1A: Add _runtime_override init before pre_llm_call block ───
    # Run each sub-patch independently so partially patched cores can be repaired.
    if "_runtime_override = {}" not in new_content:
        init_old = '        _plugin_user_context = ""\n        try:\n'
        init_new = (
            '        _plugin_user_context = ""\n'
            '        # HERMES_ARC_PATCH: runtime_override support\n'
            '        _runtime_override = {}\n'
            '        try:\n'
        )
        if init_old not in new_content:
            print("⚠️  Could not locate pre_llm_call initialization — init patch skipped")
        else:
            new_content = new_content.replace(init_old, init_new, 1)

    # ─── Patch 1B: Collect runtime_override from pre_llm_call results ───
    if '_arc_ov = r.get("runtime_override")' not in new_content:
        loop_old = (
            '            for r in _pre_results:\n'
            '                if isinstance(r, dict) and r.get("context"):\n'
            '                    _ctx_parts.append(str(r["context"]))\n'
            '                elif isinstance(r, str) and r.strip():\n'
            '                    _ctx_parts.append(r)\n'
        )
        loop_new = (
            '            for r in _pre_results:\n'
            '                if isinstance(r, dict):\n'
            '                    if r.get("context"):\n'
            '                        _ctx_parts.append(str(r["context"]))\n'
            '                    _arc_ov = r.get("runtime_override")\n'
            '                    if isinstance(_arc_ov, dict):\n'
            '                        _runtime_override.update(_arc_ov)\n'
            '                elif isinstance(r, str) and r.strip():\n'
            '                    _ctx_parts.append(r)\n'
        )
        if loop_old not in new_content:
            print("⚠️  Could not locate pre_llm_call result loop — collect patch skipped")
        else:
            new_content = new_content.replace(loop_old, loop_new, 1)

    # ─── Patch 1C: Apply runtime overrides after context assembly ───
    if "_arc_resolve_provider_client" not in new_content:
        ctx_old = (
            '            if _ctx_parts:\n'
            '                _plugin_user_context = "\\n\\n".join(_ctx_parts)\n'
        )
        runtime_block = '''            if _ctx_parts:
                _plugin_user_context = "\\n\\n".join(_ctx_parts)

            # HERMES_ARC_SKIPDETECT_PATCH: allow router plugins to rewrite the
            # current turn user message after inspecting a command prefix.
            _arc_user_message = _runtime_override.get("user_message")
            if isinstance(_arc_user_message, str):
                user_message = _arc_user_message
                original_user_message = _arc_user_message
                try:
                    user_msg["content"] = _arc_user_message
                    self._persist_user_message_override = _arc_user_message
                except Exception:
                    pass

            # HERMES_ARC_PATCH: apply runtime routing overrides from plugins.
            # Use Hermes' own switch_model() instead of mutating attributes
            # directly — preserves provider-specific api_mode, OAuth, headers,
            # context-compressor metadata, and client rebuild logic.
            if isinstance(_runtime_override, dict) and _runtime_override:
                _arc_restore_main = bool(_runtime_override.get("restore_main"))
                _arc_model = _runtime_override.get("model")
                _arc_provider = _runtime_override.get("provider")
                _arc_base_url = _runtime_override.get("base_url")
                _arc_api_key = _runtime_override.get("api_key")
                _arc_api_mode = _runtime_override.get("api_mode")

                if not hasattr(self, "_hermes_arc_base_runtime"):
                    self._hermes_arc_base_runtime = {
                        "model": getattr(self, "model", ""),
                        "provider": getattr(self, "provider", ""),
                        "base_url": getattr(self, "base_url", ""),
                        "api_key": getattr(self, "api_key", ""),
                        "api_mode": getattr(self, "api_mode", ""),
                        "fallback_chain": list(getattr(self, "_fallback_chain", []) or []),
                    }

                if _arc_restore_main:
                    _arc_base = getattr(self, "_hermes_arc_base_runtime", None) or {}
                    _base_model = _arc_base.get("model")
                    _base_provider = _arc_base.get("provider")
                    if _base_model and _base_provider:
                        if hasattr(self, "switch_model"):
                            self.switch_model(
                                _base_model,
                                _base_provider,
                                api_key=_arc_base.get("api_key", ""),
                                base_url=_arc_base.get("base_url", ""),
                                api_mode=_arc_base.get("api_mode", ""),
                            )
                        else:
                            self.model = str(_base_model)
                            self.provider = str(_base_provider)
                            if _arc_base.get("base_url"):
                                self.base_url = str(_arc_base.get("base_url")).rstrip("/")
                            if _arc_base.get("api_key"):
                                self.api_key = str(_arc_base.get("api_key"))
                        _base_fallback_chain = [
                            f for f in (_arc_base.get("fallback_chain") or [])
                            if isinstance(f, dict) and f.get("provider") and f.get("model")
                        ]
                        self._fallback_chain = list(_base_fallback_chain)
                        self._fallback_model = self._fallback_chain[0] if self._fallback_chain else None
                        self._fallback_index = 0
                        self._fallback_activated = False
                        logger.info(
                            "hermes-arc: restored main runtime provider=%s model=%s fallbacks=%d",
                            getattr(self, "provider", ""),
                            getattr(self, "model", ""),
                            len(self._fallback_chain),
                        )
                elif _arc_model or _arc_provider or _arc_base_url or _arc_api_key:
                    _target_provider = str(_arc_provider or getattr(self, "provider", "") or "auto")
                    _target_model = str(_arc_model or getattr(self, "model", ""))
                    _resolved_model = _target_model
                    _resolved_api_key = str(_arc_api_key or "")
                    _resolved_base_url = str(_arc_base_url or "")
                    _resolved_api_mode = str(_arc_api_mode or "")

                    try:
                        from agent.auxiliary_client import resolve_provider_client as _arc_resolve_provider_client
                        _arc_client, _arc_client_model = _arc_resolve_provider_client(
                            _target_provider,
                            model=_target_model,
                            raw_codex=True,
                            explicit_base_url=_resolved_base_url or None,
                            explicit_api_key=_resolved_api_key or None,
                            api_mode=_resolved_api_mode or None,
                            main_runtime=getattr(self, "_primary_runtime", None),
                        )
                        if _arc_client is not None:
                            _resolved_model = str(_arc_client_model or _target_model)
                            _resolved_api_key = str(getattr(_arc_client, "api_key", "") or _resolved_api_key)
                            _resolved_base_url = str(getattr(_arc_client, "base_url", "") or _resolved_base_url).rstrip("/")
                    except Exception as _arc_resolve_error:
                        logger.debug("hermes-arc: provider resolution skipped: %s", _arc_resolve_error)

                    if not _resolved_api_mode:
                        try:
                            from hermes_cli.providers import determine_api_mode as _arc_determine_api_mode
                            _resolved_api_mode = _arc_determine_api_mode(_target_provider, _resolved_base_url)
                        except Exception:
                            _resolved_api_mode = getattr(self, "api_mode", "")

                    if hasattr(self, "switch_model"):
                        self.switch_model(
                            _resolved_model,
                            _target_provider,
                            api_key=_resolved_api_key,
                            base_url=_resolved_base_url,
                            api_mode=_resolved_api_mode,
                        )
                    else:
                        self.model = str(_resolved_model)
                        self.provider = str(_target_provider)
                        if _resolved_base_url:
                            self.base_url = _resolved_base_url
                        if _resolved_api_key:
                            self.api_key = _resolved_api_key

                    logger.info(
                        "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",
                        getattr(self, "provider", ""),
                        getattr(self, "model", ""),
                        getattr(self, "api_mode", ""),
                    )
'''
        if ctx_old not in new_content:
            print("⚠️  Could not locate context assembly — patch skipped")
            return content
        new_content = new_content.replace(ctx_old, runtime_block, 1)

    # ─── Patch 1D: /skipdetect user-message rewrite ───
    if "HERMES_ARC_SKIPDETECT_PATCH" not in new_content:
        skip_old = '''            if _ctx_parts:
                _plugin_user_context = "\\n\\n".join(_ctx_parts)

            # HERMES_ARC_PATCH: apply runtime routing overrides from plugins.
'''
        skip_new = '''            if _ctx_parts:
                _plugin_user_context = "\\n\\n".join(_ctx_parts)

            # HERMES_ARC_SKIPDETECT_PATCH: allow router plugins to rewrite the
            # current turn user message after inspecting a command prefix.
            _arc_user_message = _runtime_override.get("user_message")
            if isinstance(_arc_user_message, str):
                user_message = _arc_user_message
                original_user_message = _arc_user_message
                try:
                    user_msg["content"] = _arc_user_message
                    self._persist_user_message_override = _arc_user_message
                except Exception:
                    pass

            # HERMES_ARC_PATCH: apply runtime routing overrides from plugins.
'''
        if skip_old in new_content:
            new_content = new_content.replace(skip_old, skip_new, 1)
        else:
            print("⚠️  Could not locate context assembly — /skipdetect patch skipped")

    # ─── Patch 2: Add provider to transform_llm_output hook call ───
    if "HERMES_ARC_TRANSFORM_PROVIDER_PATCH" not in new_content:
        # Find the transform_llm_output invoke_hook call and add provider=self.provider
        old_hook = '''                _transform_results = _invoke_hook(
                    "transform_llm_output",
                    response_text=final_response,
                    session_id=self.session_id or "",
                    model=self.model,
                    platform=getattr(self, "platform", None) or "",
                )'''
        new_hook = '''                # HERMES_ARC_TRANSFORM_PROVIDER_PATCH: add provider for signature rebuild
                _transform_results = _invoke_hook(
                    "transform_llm_output",
                    response_text=final_response,
                    session_id=self.session_id or "",
                    model=self.model,
                    provider=self.provider,
                    platform=getattr(self, "platform", None) or "",
                )'''
        if old_hook in new_content:
            new_content = new_content.replace(old_hook, new_hook, 1)
        else:
            print("⚠️  Could not locate transform_llm_output hook call — provider patch skipped")

    # ─── Patch 3: Response suffix rendering (signature append) ───
    if "_arc_signature" not in new_content:
        # Insert before post_llm_call. Older patcher versions required the exact
        # transform warning line immediately before this marker; newer Hermes
        # cores may change spacing/comments, so anchor on the stable next hook.
        suffix_marker = '        # Plugin hook: post_llm_call'
        suffix_block = '''        # HERMES_ARC_RESPONSE_SUFFIX_PATCH: render ARC signature from
        # _runtime_override (structured _arc_signature dict) and the final
        # model/provider after any fallback occurred.
        if final_response and not interrupted:
            try:
                _arc_sig = (_runtime_override or {}).get("_arc_signature")
                if isinstance(_arc_sig, dict):
                    try:
                        from hermes_cli.plugins import invoke_hook as _arc_inv
                        _arc_final_sig_results = _arc_inv(
                            "transform_llm_output",
                            response_text="",
                            session_id=self.session_id or "",
                            model=self.model,
                            provider=self.provider,
                            platform=getattr(self, "platform", None) or "",
                            _arc_finalize=_arc_sig,
                        )
                        for _arc_hr in _arc_final_sig_results:
                            if isinstance(_arc_hr, str) and _arc_hr:
                                final_response = final_response.rstrip() + "\\n\\n" + _arc_hr
                                break
                    except Exception:
                        _routed = _arc_sig.get("routed_model", "")
                        _routed_p = _arc_sig.get("routed_provider", "")
                        _final_m = self.model or ""
                        _final_p = self.provider or ""
                        _topic = _arc_sig.get("topic", "")
                        _short = lambda m: m.split("/")[-1] if "/" in m else m
                        if _short(_final_m) == _short(_routed) and _final_p == _routed_p:
                            _arc_suffix = f"- {_short(_final_m)} [{_topic}]"
                        else:
                            _arc_suffix = f"- {_short(_final_m)} [{_topic} | routed: {_short(_routed)}]"
                        if _arc_suffix:
                            final_response = final_response.rstrip() + "\\n\\n" + _arc_suffix
            except Exception:
                logger.debug("hermes-arc: response suffix render failed")

'''
        if suffix_marker in new_content:
            new_content = new_content.replace(suffix_marker, suffix_block + suffix_marker, 1)
        else:
            print("⚠️  Could not locate post_llm_call hook boundary — suffix patch skipped")

    # ─── Patch 5: topic-scoped fallback chains ───
    if "HERMES_ARC_TOPIC_FALLBACK_PATCH" not in new_content:
        modern_old = '''            self.switch_model(new_model, new_provider, api_key=api_key, base_url=base_url, api_mode=api_mode)
            # ``switch_model`` deliberately prunes fallback entries for
'''
        modern_new = '''            self.switch_model(new_model, new_provider, api_key=api_key, base_url=base_url, api_mode=api_mode)
            # HERMES_ARC_TOPIC_FALLBACK_PATCH: allow router plugins to scope
            # the fallback chain for this runtime override before falling back
            # to the agent's global chain.
            _override_fallback_chain = runtime_override.get("fallback_chain")
            if isinstance(_override_fallback_chain, list):
                _topic_fallback_chain = [
                    f for f in _override_fallback_chain
                    if isinstance(f, dict) and f.get("provider") and f.get("model")
                ]
                fallback_chain = list(_topic_fallback_chain) + list(fallback_chain)
                fallback_model = fallback_chain[0] if fallback_chain else None
                fallback_index = 0
            # ``switch_model`` deliberately prunes fallback entries for
'''
        legacy_old = '''                    logger.info(
                        "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",
'''
        legacy_new = '''                    # HERMES_ARC_TOPIC_FALLBACK_PATCH: optional topic-scoped
                    # fallback chain supplied by topic_detect runtime_override.
                    _arc_fb_chain_raw = _runtime_override.get("fallback_chain")
                    if isinstance(_arc_fb_chain_raw, list):
                        _arc_topic_fb_chain = [
                            f for f in _arc_fb_chain_raw
                            if isinstance(f, dict) and f.get("provider") and f.get("model")
                        ]
                        _arc_base = getattr(self, "_hermes_arc_base_runtime", None) or {}
                        _arc_global_fb_chain = [
                            f for f in (_arc_base.get("fallback_chain") or [])
                            if isinstance(f, dict) and f.get("provider") and f.get("model")
                        ]
                        self._fallback_chain = list(_arc_topic_fb_chain) + list(_arc_global_fb_chain)
                        self._fallback_model = self._fallback_chain[0] if self._fallback_chain else None
                        self._fallback_index = 0
                        self._fallback_activated = False
                        logger.info(
                            "hermes-arc: topic fallback chain loaded topic_entries=%d global_entries=%d total=%d",
                            len(_arc_topic_fb_chain),
                            len(_arc_global_fb_chain),
                            len(self._fallback_chain),
                        )

                    logger.info(
                        "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",
'''
        if modern_old in new_content:
            new_content = new_content.replace(modern_old, modern_new, 1)
        elif legacy_old in new_content:
            new_content = new_content.replace(legacy_old, legacy_new, 1)
        else:
            print("⚠️  Could not locate runtime override apply block — topic fallback patch skipped")

    # ─── Patch 4: system_prompt support (pre_llm_call → inject before context assembly) ───
    if "HERMES_ARC_SYSTEM_PROMPT_PATCH" not in new_content:
        # Add _plugin_system_prompt init alongside _runtime_override
        old_runtime_init = (
            '        # HERMES_ARC_PATCH: runtime_override support\n'
            '        _runtime_override = {}\n'
        )
        new_runtime_init = (
            '        # HERMES_ARC_PATCH: runtime_override support\n'
            '        _runtime_override = {}\n'
            '        _plugin_system_prompt = ""\n'
        )
        if old_runtime_init in new_content:
            new_content = new_content.replace(old_runtime_init, new_runtime_init, 1)

        # We need to inject system_prompt capture right after the runtime block
        # Find the end of the runtime block and inject system_prompt handling
        inject_point = '                    logger.info(\n                        "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",\n                        getattr(self, "provider", ""),\n                        getattr(self, "model", ""),\n                        getattr(self, "api_mode", ""),\n                    )\n'
        if inject_point in new_content:
            after_inject = '''                    logger.info(
                        "hermes-arc: runtime_override applied provider=%s model=%s api_mode=%s",
                        getattr(self, "provider", ""),
                        getattr(self, "model", ""),
                        getattr(self, "api_mode", ""),
                    )

                # HERMES_ARC_SYSTEM_PROMPT_PATCH: capture system prompt override
                _arc_sys = _runtime_override.get("system_prompt")
                if _arc_sys:
                    _plugin_system_prompt = str(_arc_sys)
                    _ctx_parts.append(_plugin_system_prompt)
'''
            new_content = new_content.replace(inject_point, after_inject, 1)
        else:
            print("⚠️  Could not locate runtime override log line — system prompt patch skipped")

    return new_content


def verify_patch(content: str) -> dict:
    """Verify all ARC patches are correctly applied."""
    checks = {}

    checks["HERMES_ARC_PATCH marker"] = "HERMES_ARC_PATCH: runtime_override support" in content
    checks["_runtime_override init"] = "_runtime_override = {}" in content
    checks["runtime_override collect"] = '_arc_ov = r.get("runtime_override")' in content
    checks["switch_model call"] = (
        "switch_model(" in content
        and ("_arc_resolve_provider_client" in content or "runtime override switch failed" in content)
    )
    checks["_hermes_arc_base_runtime"] = "_hermes_arc_base_runtime" in content
    checks["HERMES_ARC_RESPONSE_SUFFIX_PATCH"] = "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in content
    checks["_arc_signature"] = "_arc_signature" in content
    checks["HERMES_ARC_TRANSFORM_PROVIDER_PATCH"] = "HERMES_ARC_TRANSFORM_PROVIDER_PATCH" in content
    checks["provider=self.provider in transform hook"] = bool(
        re.search(r'transform_llm_output[\s\S]{0,240}provider\s*=\s*(?:self|agent)\.provider', content)
    )
    checks["HERMES_ARC_SYSTEM_PROMPT_PATCH"] = "HERMES_ARC_SYSTEM_PROMPT_PATCH" in content
    checks["HERMES_ARC_TOPIC_FALLBACK_PATCH"] = "HERMES_ARC_TOPIC_FALLBACK_PATCH" in content
    checks["HERMES_ARC_SKIPDETECT_PATCH"] = "HERMES_ARC_SKIPDETECT_PATCH" in content

    return checks



# HERMES ARC v2.2 split-runtime support (Hermes v0.16+)
def _looks_like_hermes_conversation_loop(path: Path) -> bool:
    try:
        return path.is_file() and path.name == "conversation_loop.py" and "def run_conversation" in path.read_text(encoding="utf-8", errors="ignore")[:250_000]
    except OSError:
        return False

def _looks_like_hermes_turn_context(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:120_000]
        return path.is_file() and path.name == "turn_context.py" and "def build_turn_context" in text and "pre_llm_call" in text
    except OSError:
        return False

def _looks_like_hermes_turn_finalizer(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:120_000]
        return path.is_file() and path.name == "turn_finalizer.py" and "def finalize_turn" in text and "transform_llm_output" in text
    except OSError:
        return False

def _looks_like_hermes_runtime_file(path: Path) -> bool:
    return _looks_like_hermes_run_agent(path) or _looks_like_hermes_conversation_loop(path) or _looks_like_hermes_turn_context(path) or _looks_like_hermes_turn_finalizer(path)

def resolve_patch_files(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    if path.name == "run_agent.py":
        base = path.parent / "agent"
    elif path.name in {"conversation_loop.py", "turn_context.py", "turn_finalizer.py"}:
        base = path.parent
    else:
        return [path]
    loop, ctx, fin = base / "conversation_loop.py", base / "turn_context.py", base / "turn_finalizer.py"
    if _looks_like_hermes_conversation_loop(loop):
        files = [loop]
        if _looks_like_hermes_turn_context(ctx): files.append(ctx)
        if _looks_like_hermes_turn_finalizer(fin): files.append(fin)
        return files
    return [path]

def _combined_runtime_text(files: list[Path]) -> str:
    return "\n\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files if p.exists())

def _patch_split_turn_context(text: str) -> str:
    new = text
    start_old = '''    # Restore the primary runtime if the previous turn activated fallback.
    agent._restore_primary_runtime()
'''
    start_new = '''    # Restore the primary runtime if the previous turn activated fallback.
    agent._restore_primary_runtime()

    # HERMES_ARC_PATCH: runtime_override support for Hermes' split turn prologue.
    _arc_base_runtime = getattr(agent, "_hermes_arc_base_runtime", None)
    if isinstance(_arc_base_runtime, dict) and _arc_base_runtime:
        try:
            if (getattr(agent, "model", "") != _arc_base_runtime.get("model")
                    or getattr(agent, "provider", "") != _arc_base_runtime.get("provider")
                    or getattr(agent, "base_url", "") != _arc_base_runtime.get("base_url")
                    or getattr(agent, "api_mode", "") != _arc_base_runtime.get("api_mode")):
                _arc_primary_snapshot = getattr(agent, "_primary_runtime", None)
                agent.switch_model(_arc_base_runtime.get("model") or getattr(agent, "model", ""), _arc_base_runtime.get("provider") or getattr(agent, "provider", ""), _arc_base_runtime.get("api_key") or getattr(agent, "api_key", ""), _arc_base_runtime.get("base_url") or "", _arc_base_runtime.get("api_mode") or "")
                if isinstance(_arc_primary_snapshot, dict):
                    agent._primary_runtime = _arc_primary_snapshot
            agent._fallback_chain = list(_arc_base_runtime.get("fallback_chain") or [])
            agent._fallback_index = 0
            agent._fallback_activated = False
        except Exception as _arc_restore_exc:
            logger.warning("HERMES_ARC_PATCH: failed to restore base runtime: %s", _arc_restore_exc)
'''
    if "HERMES_ARC_PATCH: runtime_override support for Hermes' split turn prologue" not in new and start_old in new:
        new = new.replace(start_old, start_new, 1)
    hook_old = '''    # Plugin hook: pre_llm_call (context injected into user message, not system prompt).
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
        for r in _pre_results:
            if isinstance(r, dict) and r.get("context"):
                _ctx_parts.append(str(r["context"]))
            elif isinstance(r, str) and r.strip():
                _ctx_parts.append(r)
        if _ctx_parts:
            plugin_user_context = "\\n\\n".join(_ctx_parts)
    except Exception as exc:
        logger.warning("pre_llm_call hook failed: %s", exc)
'''
    hook_new = '''    # Plugin hook: pre_llm_call (context injected into user message, not system prompt).
    plugin_user_context = ""
    # HERMES_ARC_PATCH: collect runtime_override dicts returned by router plugins.
    _runtime_override = {}
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
            provider=getattr(agent, "provider", ""),
            base_url=getattr(agent, "base_url", ""),
            api_mode=getattr(agent, "api_mode", ""),
            platform=getattr(agent, "platform", None) or "",
            sender_id=getattr(agent, "_user_id", None) or "",
        )
        _ctx_parts: list[str] = []
        for r in _pre_results:
            if isinstance(r, dict):
                if r.get("context"):
                    _ctx_parts.append(str(r["context"]))
                _arc_ov = r.get("runtime_override")
                if isinstance(_arc_ov, dict):
                    _runtime_override.update(_arc_ov)
            elif isinstance(r, str) and r.strip():
                _ctx_parts.append(r)
        _arc_sys = _runtime_override.get("system_prompt")
        if _arc_sys:
            _ctx_parts.append(str(_arc_sys))  # HERMES_ARC_SYSTEM_PROMPT_PATCH
        _arc_user_message = _runtime_override.get("user_message")
        if isinstance(_arc_user_message, str):
            user_message = _arc_user_message
            original_user_message = _arc_user_message
            try:
                messages[current_turn_user_idx]["content"] = _arc_user_message
                agent._persist_user_message_override = _arc_user_message
            except Exception:
                pass  # HERMES_ARC_SKIPDETECT_PATCH
        if isinstance(_runtime_override, dict) and _runtime_override:
            if not hasattr(agent, "_hermes_arc_base_runtime"):
                agent._hermes_arc_base_runtime = {"model": getattr(agent, "model", ""), "provider": getattr(agent, "provider", ""), "base_url": getattr(agent, "base_url", ""), "api_key": getattr(agent, "api_key", ""), "api_mode": getattr(agent, "api_mode", ""), "fallback_chain": list(getattr(agent, "_fallback_chain", []) or [])}
            _arc_model = _runtime_override.get("model") or getattr(agent, "model", "")
            _arc_provider = _runtime_override.get("provider") or getattr(agent, "provider", "")
            if _arc_model or _arc_provider:
                try:
                    _arc_primary_snapshot = getattr(agent, "_primary_runtime", None)
                    agent.switch_model(_arc_model, _arc_provider, _runtime_override.get("api_key") or getattr(agent, "api_key", ""), _runtime_override.get("base_url") or "", _runtime_override.get("api_mode") or "")
                    if isinstance(_arc_primary_snapshot, dict):
                        agent._primary_runtime = _arc_primary_snapshot
                except Exception as _arc_switch_exc:
                    logger.warning("HERMES_ARC_PATCH: runtime override switch failed: %s", _arc_switch_exc)
            if "fallback_chain" in _runtime_override:
                _arc_chain = _runtime_override.get("fallback_chain")
                agent._fallback_chain = list(_arc_chain) if isinstance(_arc_chain, list) else []  # HERMES_ARC_TOPIC_FALLBACK_PATCH
                agent._fallback_index = 0
                agent._fallback_activated = False
            _arc_signature = _runtime_override.get("_arc_signature")
            agent._hermes_arc_signature = dict(_arc_signature) if isinstance(_arc_signature, dict) else None  # HERMES_ARC_RESPONSE_SUFFIX_PATCH
        if _ctx_parts:
            plugin_user_context = "\\n\\n".join(_ctx_parts)
    except Exception as exc:
        logger.warning("pre_llm_call hook failed: %s", exc)
'''
    if "HERMES_ARC_PATCH: collect runtime_override dicts" not in new and hook_old in new:
        new = new.replace(hook_old, hook_new, 1)
    return new

def _patch_split_turn_finalizer(text: str) -> str:
    new = text
    transform_old = '''            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                platform=getattr(agent, "platform", None) or "",
            )
'''
    transform_new = '''            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                provider=agent.provider,  # HERMES_ARC_TRANSFORM_PROVIDER_PATCH
                base_url=agent.base_url,
                api_mode=agent.api_mode,
                platform=getattr(agent, "platform", None) or "",
            )
'''
    if "HERMES_ARC_TRANSFORM_PROVIDER_PATCH" not in new and transform_old in new:
        new = new.replace(transform_old, transform_new, 1)
    suffix_old = '''            for _hook_result in _transform_results:
                if isinstance(_hook_result, str) and _hook_result:
                    final_response = _hook_result
                    _response_transformed = True
                    break  # First non-empty string wins
'''
    suffix_new = '''            for _hook_result in _transform_results:
                if isinstance(_hook_result, str) and _hook_result:
                    final_response = _hook_result
                    _response_transformed = True
                    break  # First non-empty string wins
            # HERMES_ARC_RESPONSE_SUFFIX_PATCH: render structured ARC signature exactly once.
            _arc_signature = getattr(agent, "_hermes_arc_signature", None)
            if isinstance(_arc_signature, dict):
                _arc_suffix_results = _invoke_hook("transform_llm_output", response_text="", session_id=agent.session_id or "", model=agent.model, provider=agent.provider, base_url=agent.base_url, api_mode=agent.api_mode, platform=getattr(agent, "platform", None) or "", _arc_finalize=_arc_signature)
                for _arc_suffix in _arc_suffix_results:
                    if isinstance(_arc_suffix, str) and _arc_suffix.strip():
                        final_response = final_response.rstrip() + "\\n\\n" + _arc_suffix.strip()
                        _response_transformed = True
                        break
                agent._hermes_arc_signature = None
'''
    if "HERMES_ARC_RESPONSE_SUFFIX_PATCH" not in new and suffix_old in new:
        new = new.replace(suffix_old, suffix_new, 1)
    return new

def apply_split_runtime_patch(files: list[Path]) -> dict[Path, str]:
    changed = {}
    for f in files:
        old = f.read_text(encoding="utf-8", errors="ignore")
        new = _patch_split_turn_context(old) if f.name == "turn_context.py" else (_patch_split_turn_finalizer(old) if f.name == "turn_finalizer.py" else old)
        if new != old:
            changed[f] = new
    return changed

def verify_patch_files(files: list[Path]) -> dict:
    return verify_patch(_combined_runtime_text(files))

def main():
    parser = argparse.ArgumentParser(description="Hermes ARC run_agent.py patcher")
    parser.add_argument("--check", action="store_true", help="Check only")
    parser.add_argument("--patch", action="store_true", help="Check and patch if needed")
    parser.add_argument("--verify", action="store_true", help="Verify patch applied")
    parser.add_argument("--list", action="store_true", help="List discovered Hermes run_agent.py candidates")
    parser.add_argument("--path", type=str, help="Explicit path to run_agent.py")
    args = parser.parse_args()

    if args.list:
        for candidate in find_run_agent_candidates():
            print(candidate)
        return

    if not any([args.check, args.patch, args.verify]):
        parser.print_help()
        sys.exit(1)

    path = choose_run_agent_path(args.path)
    patch_files = resolve_patch_files(path)
    if len(patch_files) > 1 or patch_files[0] != path:
        print("ℹ️  Hermes runtime patch targets:")
        for _file in patch_files:
            print(f"   - {_file}")
    content = _combined_runtime_text(patch_files)

    if args.check:
        results = check_runtime_override_handling(content)
        print("🔍 Hermes ARC compatibility check:")
        for key, val in results.items():
            status = "✅" if val else "❌"
            print(f"  {status} {key}")
        if needs_patch(results):
            print("\n⚠️  Patch needed. Run: python3 patch_run_agent.py --patch")
        else:
            print("\n✅ All checks passed — no patch needed.")

    if args.patch:
        changes = apply_split_runtime_patch(patch_files) if any(p.name in {"turn_context.py", "turn_finalizer.py"} for p in patch_files) else {}
        if not changes and len(patch_files) == 1:
            patch_path = patch_files[0]
            original = patch_path.read_text(encoding="utf-8", errors="ignore")
            patched = apply_patch(patch_path, original)
            if patched != original:
                changes[patch_path] = patched
        if not changes:
            print("✅ Already patched or patch could not be applied — no changes made.")
        else:
            for patch_path, new_content in changes.items():
                backup = patch_path.with_suffix(patch_path.suffix + BACKUP_SUFFIX)
                if not backup.exists():
                    shutil.copy2(patch_path, backup)
                    print(f"📦 Backup created: {backup}")
                patch_path.write_text(new_content, encoding="utf-8")
                print(f"✅ Patch applied: {patch_path}")
            content = _combined_runtime_text(patch_files)

    if args.verify:
        checks = verify_patch_files(patch_files)
        print("🔍 Hermes ARC patch verification:")
        all_ok = True
        for key, val in checks.items():
            status = "✅" if val else "❌"
            print(f"  {status} {key}")
            if not val:
                all_ok = False
        if all_ok:
            print("\n✅ All patches verified successfully.")
        else:
            print("\n❌ Some patches missing or incomplete.")



if __name__ == "__main__":
    main()
