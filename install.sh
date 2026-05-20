#!/usr/bin/env bash
# Hermes ARC (Adaptive Routing Core) — One-Click Install
# Internal plugin name: topic_detect
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash -s -- --check
#   curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash -s -- --patch-runtime
#   bash install.sh [--check|--update] [--plugin-dir PATH] [--run-agent-path PATH] [--no-restart] [--patch-runtime|--no-patch-runtime]

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
REPO_RAW="https://raw.githubusercontent.com/ShockShoot/hermes-arc/main"
HERMES_HOME_DEFAULT="${HERMES_HOME:-${HOME}/.hermes}"
PLUGIN_DIR="${HERMES_HOME_DEFAULT}/plugins/topic_detect"
PLUGIN_DIR_EXPLICIT=false
RESTART=true
PATCH_RUNTIME="auto" # auto | prompt | yes | no
RUN_AGENT_PATH=""
CONFIGURE=true
CONFIG_PATH="${HERMES_HOME_DEFAULT}/config.yaml"
CONFIG_PATH_EXPLICIT=false
CHECK_ONLY=false
UPDATE_REQUESTED=false

# ── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --update) UPDATE_REQUESTED=true; shift ;;
    --plugin-dir) PLUGIN_DIR="$2"; PLUGIN_DIR_EXPLICIT=true; shift 2 ;;
    --run-agent-path) RUN_AGENT_PATH="$2"; shift 2 ;;
    --config-path) CONFIG_PATH="$2"; CONFIG_PATH_EXPLICIT=true; shift 2 ;;
    --no-config) CONFIGURE=false; shift ;;
    --no-restart) RESTART=false; shift ;;
    --patch-runtime) PATCH_RUNTIME="yes"; shift ;;
    --no-patch-runtime) PATCH_RUNTIME="no"; shift ;;
    -h|--help)
      echo "Usage: bash install.sh [--check|--update] [--plugin-dir PATH] [--config-path PATH] [--run-agent-path PATH] [--no-config] [--no-restart] [--patch-runtime|--no-patch-runtime]"
      echo ""
      echo "Update options:"
      echo "  --check              Compare local ARC version with latest GitHub version and exit"
      echo "  --update             Explicitly run install/update flow (same as default, clearer for users)"
      echo ""
      echo "Config options:"
      echo "  --config-path PATH    Target Hermes config.yaml (default: ~/.hermes/config.yaml)"
      echo "  --no-config           Do not modify config.yaml"
      echo ""
      echo "Runtime patch options:"
      echo "  --run-agent-path PATH Target a specific Hermes run_agent.py when multiple installs exist"
      echo "  --patch-runtime       Patch Hermes run_agent.py automatically if ARC support is missing"
      echo "  --no-patch-runtime    Never patch Hermes core runtime"
      echo "  default               Auto-patch when exactly one Hermes runtime is found; prompt only when needed"
      exit 0
      ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

get_yaml_version() {
  local path_or_url="$1"
  if [[ "$path_or_url" == http://* || "$path_or_url" == https://* ]]; then
    curl -fsSL "$path_or_url" 2>/dev/null | python3 -c 'import sys,yaml; print((yaml.safe_load(sys.stdin.read()) or {}).get("version","0.0.0"))'
  elif [[ -f "$path_or_url" ]]; then
    python3 -c 'import sys,yaml,pathlib; print((yaml.safe_load(pathlib.Path(sys.argv[1]).read_text()) or {}).get("version","0.0.0"))' "$path_or_url"
  else
    echo "0.0.0"
  fi
}

version_gt() {
  python3 - "$1" "$2" <<'PY'
import sys
def parse(v):
    out=[]
    for part in v.strip().lstrip('v').split('.'):
        digits=''
        for ch in part:
            if ch.isdigit(): digits += ch
            else: break
        out.append(int(digits or 0))
    return out or [0]
a,b=parse(sys.argv[1]),parse(sys.argv[2])
n=max(len(a),len(b))
a += [0]*(n-len(a)); b += [0]*(n-len(b))
raise SystemExit(0 if a>b else 1)
PY
}


select_runtime_with_arrows() {
  local count="${#RUN_AGENT_CANDIDATES[@]}"
  local selected=0
  local key rest i prefix

  if [[ "${count}" -le 0 || ! -r /dev/tty || ! -w /dev/tty ]]; then
    return 1
  fi

  printf "\nSelect Hermes runtime to check/patch\n" > /dev/tty
  printf "Use ↑/↓ (or k/j), Enter to select, q/Esc to skip.\n" > /dev/tty

  # Hide cursor while drawing the small menu. Always show it again before exit.
  printf '\033[?25l' > /dev/tty

  render_runtime_menu() {
    for i in "${!RUN_AGENT_CANDIDATES[@]}"; do
      if (( i == selected )); then
        prefix="❯"
      else
        prefix=" "
      fi
      printf '\r\033[2K  %s %d) %s\n' "${prefix}" "$((i + 1))" "${RUN_AGENT_CANDIDATES[$i]}" > /dev/tty
    done
  }

  render_runtime_menu

  while IFS= read -rsn1 key < /dev/tty; do
    case "${key}" in
      $'\x1b')
        # Escape alone skips; escape sequence [A/[B handles arrow keys.
        if IFS= read -rsn2 -t 0.05 rest < /dev/tty; then
          case "${rest}" in
            '[A') selected=$(( (selected - 1 + count) % count )) ;;
            '[B') selected=$(( (selected + 1) % count )) ;;
            *) printf '\033[?25h' > /dev/tty; return 1 ;;
          esac
        else
          printf '\033[?25h' > /dev/tty
          return 1
        fi
        ;;
      $'\n'|$'\r')
        printf '\033[?25h' > /dev/tty
        printf "\n" > /dev/tty
        echo "${selected}"
        return 0
        ;;
      q|Q)
        printf '\033[?25h' > /dev/tty
        printf "\n" > /dev/tty
        return 1
        ;;
      k|K)
        selected=$(( (selected - 1 + count) % count ))
        ;;
      j|J)
        selected=$(( (selected + 1) % count ))
        ;;
      '')
        ;;
      *)
        # Number shortcuts remain available for keyboard-only shells.
        if [[ "${key}" =~ ^[1-9]$ ]] && (( key >= 1 && key <= count )); then
          selected=$((key - 1))
          printf '\033[?25h' > /dev/tty
          printf "\n" > /dev/tty
          echo "${selected}"
          return 0
        fi
        ;;
    esac
    printf '\033[%dA' "${count}" > /dev/tty
    render_runtime_menu
  done

  printf '\033[?25h' > /dev/tty
  return 1
}

if [[ "${CHECK_ONLY}" == true ]]; then
  if ! command -v python3 &>/dev/null; then echo "❌ python3 not found"; exit 1; fi
  if [[ "${PLUGIN_DIR_EXPLICIT}" != true ]] && command -v hermes &>/dev/null; then
    HERMES_CONFIG_DISCOVERED="$(hermes config path 2>/dev/null | awk '/config\.yaml$/ {print; exit}' || true)"
    if [[ -n "${HERMES_CONFIG_DISCOVERED}" ]]; then
      PLUGIN_DIR="$(dirname "${HERMES_CONFIG_DISCOVERED}")/plugins/topic_detect"
    fi
  fi
  if ! python3 - <<'PY' >/dev/null 2>&1
import yaml
PY
  then echo "❌ PyYAML is required for --check"; exit 1; fi
  LOCAL_VERSION="$(get_yaml_version "${PLUGIN_DIR}/plugin.yaml")"
  LATEST_VERSION="$(get_yaml_version "${REPO_RAW}/plugin.yaml" || echo "0.0.0")"
  echo "Local version : ${LOCAL_VERSION}"
  echo "Latest version: ${LATEST_VERSION}"
  if version_gt "${LATEST_VERSION}" "${LOCAL_VERSION}"; then
    echo "Update available: yes"
    echo "Run:"
    echo "  curl -fsSL ${REPO_RAW}/install.sh | bash -s -- --update"
    exit 0
  fi
  echo "Update available: no"
  exit 0
fi

if [[ "${UPDATE_REQUESTED}" == true ]]; then
  echo "Update mode: installing latest ARC files from ${REPO_RAW}"
  echo ""
fi

# ── Pre-flight checks ───────────────────────────────────────────────────────
if ! command -v hermes &>/dev/null; then
  echo "❌ Hermes CLI not found. Install hermes-agent first:"
  echo "   curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Hermes ARC requires Python 3."
  exit 1
fi

# Prefer the active Hermes config/home over the shell user's HOME. This matters
# for pip/uv installs, root shells, systemd gateways, and custom HERMES_HOME.
if [[ "${CONFIG_PATH_EXPLICIT}" != true || "${PLUGIN_DIR_EXPLICIT}" != true ]]; then
  HERMES_CONFIG_DISCOVERED="$(hermes config path 2>/dev/null | awk '/config\.yaml$/ {print; exit}' || true)"
  if [[ -n "${HERMES_CONFIG_DISCOVERED}" ]]; then
    HERMES_HOME_DISCOVERED="$(dirname "${HERMES_CONFIG_DISCOVERED}")"
    if [[ "${CONFIG_PATH_EXPLICIT}" != true ]]; then
      CONFIG_PATH="${HERMES_CONFIG_DISCOVERED}"
    fi
    if [[ "${PLUGIN_DIR_EXPLICIT}" != true ]]; then
      PLUGIN_DIR="${HERMES_HOME_DISCOVERED}/plugins/topic_detect"
    fi
  fi
fi

echo ""
echo "🧊 Hermes ARC (Adaptive Routing Core) — Installer"
echo "   Plugin name : topic_detect"
echo "   Target dir  : ${PLUGIN_DIR}"
echo "   Config path : ${CONFIG_PATH}"
echo ""

# ── Create plugin directory ─────────────────────────────────────────────────
mkdir -p "${PLUGIN_DIR}"
echo "✅ Plugin directory ready: ${PLUGIN_DIR}"

# ── Source files to install ─────────────────────────────────────────────────
FILES=(
  __init__.py
  state.py
  classifier.py
  semantic.py
  config.py
  agent_loader.py
  signature.py
  patch_run_agent.py
  AGENTS.md
  plugin.yaml
  pyproject.toml
  update_checker.py
  README.md
  README_TH.md
  CHANGELOG.md
  docs/SIGNATURE_FLOW.md
  docs/REPO_LAYOUT.md
  docs/FALLBACK_CHAINS.md
  docs/V2_REWRITE_PLAN.md
  docs/V3_SMART_ROUTER.md
  tests/test_fallback_config.py
  tests/test_release_metadata.py
  tests/test_signature_finalize.py
  tests/test_skipdetect.py
  tests/test_v2_classifier.py
)

# ── Download or copy ────────────────────────────────────────────────────────
if [[ "${REPO_RAW}" == *"<USERNAME>"* ]]; then
  echo ""
  echo "⚠️  REPO_RAW contains <USERNAME>/<REPO> placeholder."
  echo "    Copying from local plugin directory instead..."
  echo ""

  LOCAL_SRC="${HOME}/.hermes/plugins/topic_detect"
  for f in "${FILES[@]}"; do
    mkdir -p "$(dirname "${PLUGIN_DIR}/${f}")"
    if [[ -f "${LOCAL_SRC}/${f}" ]]; then
      if [[ "${LOCAL_SRC}/${f}" -ef "${PLUGIN_DIR}/${f}" ]]; then
        echo "  ✅ ${f} (already in place)"
      else
        cp -f "${LOCAL_SRC}/${f}" "${PLUGIN_DIR}/${f}"
        echo "  ✅ ${f}"
      fi
    else
      echo "  ⚠️  ${f} not found in ${LOCAL_SRC} — skipped"
    fi
  done
else
  echo "Downloading from: ${REPO_RAW}"
  for f in "${FILES[@]}"; do
    mkdir -p "$(dirname "${PLUGIN_DIR}/${f}")"
    if curl -fsSL "${REPO_RAW}/${f}" -o "${PLUGIN_DIR}/${f}"; then
      echo "  ✅ ${f}"
    else
      echo "  ❌ Failed to download ${f}"
      exit 1
    fi
  done
fi

echo ""

# ── Syntax check ────────────────────────────────────────────────────────────
echo "🔍 Running Python syntax check..."
if python3 -m compileall "${PLUGIN_DIR}" -q 2>/dev/null; then
  echo "   ✅ All Python files compile OK"
else
  echo "   ❌ Syntax error detected! Aborting."
  exit 1
fi
echo ""

# ── Optional Hermes runtime compatibility patch ─────────────────────────────
PATCHER="${PLUGIN_DIR}/patch_run_agent.py"
if [[ -f "${PATCHER}" ]]; then
  echo "🔎 Locating Hermes run_agent.py..."

  if [[ -z "${RUN_AGENT_PATH}" ]]; then
    mapfile -t RUN_AGENT_CANDIDATES < <(python3 "${PATCHER}" --list 2>/dev/null || true)

    if [[ ${#RUN_AGENT_CANDIDATES[@]} -eq 0 ]]; then
      echo "⚠️  No Hermes run_agent.py found. Runtime compatibility check skipped."
      echo "   If Hermes is installed in a custom location, re-run with:"
      echo "   bash install.sh --run-agent-path /path/to/run_agent.py"
      echo ""
      RUN_AGENT_PATH=""
    elif [[ ${#RUN_AGENT_CANDIDATES[@]} -eq 1 ]]; then
      RUN_AGENT_PATH="${RUN_AGENT_CANDIDATES[0]}"
      echo "   ✅ Found: ${RUN_AGENT_PATH}"
    else
      echo "   ⚠️  Multiple Hermes runtimes found:"
      for i in "${!RUN_AGENT_CANDIDATES[@]}"; do
        printf "     %d) %s\n" "$((i + 1))" "${RUN_AGENT_CANDIDATES[$i]}"
      done

      if [[ -r /dev/tty && -w /dev/tty ]]; then
        if SELECTED_RUNTIME_INDEX="$(select_runtime_with_arrows)"; then
          RUN_AGENT_PATH="${RUN_AGENT_CANDIDATES[${SELECTED_RUNTIME_INDEX}]}"
          echo "   ✅ Selected: ${RUN_AGENT_PATH}"
        else
          echo "   Runtime selection skipped."
          RUN_AGENT_PATH=""
        fi
      else
        echo "   Non-interactive install cannot choose safely — runtime patch skipped."
        echo "   Re-run with --run-agent-path /path/to/run_agent.py"
        RUN_AGENT_PATH=""
      fi
    fi
  else
    echo "   Using explicit target: ${RUN_AGENT_PATH}"
  fi

  if [[ -n "${RUN_AGENT_PATH}" ]]; then
    echo "🔎 Checking Hermes runtime compatibility..."
    CHECK_OUTPUT="$(python3 "${PATCHER}" --check --path "${RUN_AGENT_PATH}" 2>&1 || true)"
    echo "${CHECK_OUTPUT}"

    if echo "${CHECK_OUTPUT}" | grep -Eq "All checks passed|fully compatible|no patch needed"; then
      echo "✅ Runtime already supports Hermes ARC overrides"
    else
      echo "⚠️  Hermes runtime may need ARC compatibility patching."
      echo "   Target: ${RUN_AGENT_PATH}"
      echo "   The patcher creates a timestamped backup before changing run_agent.py."
      echo "   If you have custom run_agent.py edits, review carefully or choose --no-patch-runtime."

      SHOULD_PATCH="no"
      case "${PATCH_RUNTIME}" in
        yes)
          SHOULD_PATCH="yes"
          ;;
        no)
          SHOULD_PATCH="no"
          ;;
        auto)
          SHOULD_PATCH="yes"
          echo "   Auto-patching because a single Hermes runtime was selected."
          ;;
        prompt)
          if [[ -r /dev/tty && -w /dev/tty ]]; then
            printf "Patch this Hermes runtime now? [y/N]: " > /dev/tty
            read -r REPLY < /dev/tty || REPLY=""
            # Accept answers that accidentally include composing characters from IMEs,
            # e.g. Thai keyboard input like "ัy".
            case "${REPLY}" in
              *y*|*Y*) SHOULD_PATCH="yes" ;;
              *) SHOULD_PATCH="no" ;;
            esac
          else
            echo "   Non-interactive prompt mode detected — skipping runtime patch."
            echo "   To force patching safely, include target path:"
            echo "   curl -fsSL ${REPO_RAW}/install.sh | bash -s -- --patch-runtime --run-agent-path ${RUN_AGENT_PATH}"
          fi
          ;;
      esac

      if [[ "${SHOULD_PATCH}" == "yes" ]]; then
        echo "🩹 Applying Hermes ARC runtime compatibility patch..."
        python3 "${PATCHER}" --patch --verify --path "${RUN_AGENT_PATH}"
      else
        echo "ℹ️  Runtime patch skipped. You can run later:"
        echo "   python3 ${PATCHER} --patch --verify --path ${RUN_AGENT_PATH}"
      fi
    fi
    echo ""
  fi
fi

# ── Ensure Hermes config.yaml has required ARC config ────────────────────────
if [[ "${CONFIGURE}" == true ]]; then
  echo "🧩 Ensuring Hermes config has topic_detect settings..."
  mkdir -p "$(dirname "${CONFIG_PATH}")"

  python3 - "${CONFIG_PATH}" <<'PY'
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path
import os

try:
    import yaml
except Exception as exc:
    print(f"❌ PyYAML is required to update config.yaml: {exc}")
    sys.exit(1)

path = Path(sys.argv[1]).expanduser()
backup = None
if path.exists():
    backup = path.with_suffix(path.suffix + ".arc-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    raw = yaml.safe_load(path.read_text()) or {}
else:
    raw = {}

if not isinstance(raw, dict):
    print("❌ config.yaml root must be a mapping/object")
    sys.exit(1)

changed = False

def ensure(key, value, obj=raw):
    global changed
    if key not in obj or obj[key] is None:
        obj[key] = value
        changed = True
    return obj[key]

plugins = raw.get("plugins")
if plugins is None:
    raw["plugins"] = {"enabled": ["topic_detect"]}
    changed = True
elif isinstance(plugins, dict):
    enabled = plugins.get("enabled")
    if enabled is None:
        plugins["enabled"] = ["topic_detect"]
        changed = True
    elif isinstance(enabled, list):
        if "topic_detect" not in enabled:
            enabled.append("topic_detect")
            changed = True
    else:
        print("⚠️  config.yaml plugins.enabled is not a list; leaving it unchanged.")
        print("   Run manually after install: hermes plugins enable topic_detect")
elif isinstance(plugins, list):
    # Older ARC installer versions wrote plugins as a plain list. Current Hermes
    # expects plugins.enabled, so migrate the legacy shape without dropping values.
    enabled = list(plugins)
    if "topic_detect" not in enabled:
        enabled.append("topic_detect")
    raw["plugins"] = {"enabled": enabled}
    changed = True
else:
    print("⚠️  config.yaml 'plugins' has an unsupported shape; leaving it unchanged.")
    print("   Run manually after install: hermes plugins enable topic_detect")

section = raw.get("topic_detect")
if section is None:
    section = {}
    raw["topic_detect"] = section
    changed = True
elif not isinstance(section, dict):
    print("❌ config.yaml 'topic_detect' must be a mapping/object. Please fix manually.")
    sys.exit(1)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_KEY = "${OPENROUTER_API_KEY}"

def env_key_available(name: str) -> bool:
    if os.environ.get(name):
        return True
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return False
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == name and v.strip().strip('"').strip("'"):
            return True
    return False

OPENROUTER_KEY_AVAILABLE = env_key_available(OPENROUTER_KEY_ENV)

def target(model: str) -> dict:
    data = {
        "provider": "openrouter",
        "model": model,
        "base_url": OPENROUTER_BASE,
    }
    if OPENROUTER_KEY_AVAILABLE:
        data["api_key"] = OPENROUTER_KEY
    return data

ensure("enabled", True, section)
ensure("routing_mode", "hybrid", section)
ensure("inertia", 2, section)
ensure("min_confidence", 0.45, section)
ensure("agents_file", "~/.hermes/plugins/topic_detect/AGENTS.md", section)

semantic = section.get("semantic")
if semantic is None:
    semantic = {}
    section["semantic"] = semantic
    changed = True
elif not isinstance(semantic, dict):
    print("❌ topic_detect.semantic must be a mapping/object. Please fix manually.")
    sys.exit(1)
ensure("enabled", True, semantic)
ensure("provider", "openrouter", semantic)
ensure("model", "baidu/cobuddy:free", semantic)
ensure("min_confidence", 0.70, semantic)
ensure("base_url", OPENROUTER_BASE, semantic)
if OPENROUTER_KEY_AVAILABLE:
    ensure("api_key", OPENROUTER_KEY, semantic)
elif isinstance(semantic.get("api_key"), str) and semantic["api_key"].startswith("${") and semantic["api_key"].endswith("}"):
    del semantic["api_key"]
    changed = True
    print("   🧹 Removed unresolved api_key from topic_detect.semantic")

signature = section.get("signature")
if signature is None:
    signature = {}
    section["signature"] = signature
    changed = True
elif not isinstance(signature, dict):
    print("❌ topic_detect.signature must be a mapping/object. Please fix manually.")
    sys.exit(1)
ensure("enabled", True, signature)

update_check = section.get("update_check")
if update_check is None:
    update_check = {}
    section["update_check"] = update_check
    changed = True
elif not isinstance(update_check, dict):
    print("❌ topic_detect.update_check must be a mapping/object. Please fix manually.")
    sys.exit(1)
ensure("enabled", True, update_check)
ensure("url", "https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/plugin.yaml", update_check)
ensure("timeout_seconds", 2.5, update_check)

topics = section.get("topics")
if topics is None:
    topics = {}
    section["topics"] = topics
    changed = True
elif not isinstance(topics, dict):
    print("❌ topic_detect.topics must be a mapping/object. Please fix manually.")
    sys.exit(1)

# ── Migration: remove stale fields ──────────────────────────────────────
# Remove topic_detect.default — ARC no longer uses a plugin-level default
# model/provider. If present, it overrides the user's main Hermes model
# on every turn, which is almost never what anyone wants.
if "default" in section:
    del section["default"]
    changed = True
    print("   🧹 Removed stale topic_detect.default (no longer needed)")

nemotron = "nvidia/nemotron-3-super-120b-a12b:free"
owl = "openrouter/owl-alpha"
gpt_oss = "openai/gpt-oss-120b:free"
required_topics = {
    "software_it": nemotron,
    "math": owl,
    "science": owl,
    "business_finance": owl,
    "legal_government": owl,
    "medicine_healthcare": owl,
    "writing_language": gpt_oss,
    "entertainment_media": owl,
}

# Older ARC versions shipped 12 topics. When a user installs the new 8-topic
# version over an existing install, a pure additive merge leaves dead categories
# in config.yaml forever. Migrate obvious old categories into their new Arena-
# aligned names only when the new category is absent, then always remove the old
# key. The old `science` key is intentionally kept because it is still a valid
# current topic.
legacy_topic_renames = {
    "programming": "software_it",
    "technology": "software_it",
    "finance": "business_finance",
    "marketing": "business_finance",
    "legal": "legal_government",
    "health": "medicine_healthcare",
    "academia": "science",
    "translation": "writing_language",
    "seo": "writing_language",
    "roleplay": "entertainment_media",
    "trivia": "entertainment_media",
}
for old_name, new_name in legacy_topic_renames.items():
    if old_name not in topics:
        continue
    old_value = topics.pop(old_name)
    changed = True
    if new_name not in topics and isinstance(old_value, dict):
        topics[new_name] = old_value
        print(f"   🔁 Migrated legacy topics.{old_name} -> topics.{new_name}")
    else:
        print(f"   🧹 Removed legacy topics.{old_name}")

# Remove any remaining unknown legacy/default ARC-generated categories while
# preserving genuinely custom user topics. These names are known from the old
# 12-topic installer, so this is intentionally not a broad allowlist wipe.
legacy_topic_names = {
    "programming",
    "finance",
    "academia",
    "health",
    "legal",
    "seo",
    "translation",
    "technology",
    "marketing",
    "roleplay",
    "trivia",
}
for old_name in legacy_topic_names:
    if old_name in topics:
        del topics[old_name]
        changed = True
        print(f"   🧹 Removed legacy topics.{old_name}")

# Remove unresolved ${ENV} api_key placeholders from topic targets.
# ARC's config.py now ignores them, but cleaning up avoids confusion.
for tname, tval in list(topics.items()):
    if isinstance(tval, dict):
        tkey = tval.get("api_key")
        if isinstance(tkey, str) and tkey.startswith("${") and tkey.endswith("}"):
            # Only remove if the env var is actually unset.
            env_var = tkey[2:-1].split(":")[0]
            if not env_key_available(env_var):
                del tval["api_key"]
                changed = True
                print(f"   🧹 Removed unresolved api_key from topics.{tname}")

for name, model in required_topics.items():
    current = topics.get(name)
    if current is None:
        topics[name] = target(model)
        changed = True
    elif isinstance(current, dict):
        # Preserve user choices. If provider/model are intentionally missing or
        # empty, keep that topic as a graceful fallback-to-main route.
        if current.get("provider") and current.get("model"):
            for k, v in target(model).items():
                if k not in current or current[k] is None:
                    current[k] = v
                    changed = True
    else:
        print(f"❌ topic_detect.topics.{name} must be a mapping/object. Please fix manually.")
        sys.exit(1)

if changed:
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"   ✅ Updated {path}")
    if backup:
        print(f"   🛟 Backup: {backup}")
else:
    print(f"   ✅ {path} already has required ARC config")
PY
  echo ""
else
  echo "ℹ️  Config update skipped (--no-config)"
  echo ""
fi

# ── Verify .env exists ─────────────────────────────────────────────────────
ENV_FILE="${HOME}/.hermes/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "⚠️  No .env found at ${ENV_FILE}"
  echo "   Create one with your API keys:"
  echo "   echo 'OPENROUTER_API_KEY=<your-openrouter-key>' > ${ENV_FILE}"
  echo ""
fi

# ── Enable plugin ───────────────────────────────────────────────────────────
echo "🔧 Enabling plugin..."
hermes plugins enable topic_detect 2>&1 || true
echo ""

# ── Restart ─────────────────────────────────────────────────────────────────
if [[ "${RESTART}" == true ]]; then
  echo "🔄 Restarting Hermes gateway..."
  hermes gateway restart 2>&1 || true
  echo ""
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo "─────────────────────────────────────────────"
echo "✅ Hermes ARC installed successfully!"
echo ""
echo "Next steps:"
echo "  1. Set OPENROUTER_API_KEY in ~/.hermes/.env"
echo "  2. Restart/relaunch Hermes if it was running"
echo "  3. Run: hermes logs | grep topic_detect"
echo ""
echo "Docs: ${PLUGIN_DIR}/README.md"
echo "─────────────────────────────────────────────"
