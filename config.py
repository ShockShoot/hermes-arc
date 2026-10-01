from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os
import yaml


def hermes_home() -> Path:
    """Resolve the active Hermes profile, including in gateway multiplex mode."""
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except ImportError:  # standalone plugin tests / older Hermes installs
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


@dataclass
class Target:
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    system_prompt: str | None = None
    fallbacks: list["Target"] = field(default_factory=list)


@dataclass
class UpdateCheckConfig:
    enabled: bool
    url: str
    timeout_seconds: float


@dataclass
class TopicDetectConfig:
    enabled: bool
    routing_mode: str

    inertia: int
    min_confidence: float

    default: Target | None
    topics: dict[str, Target]

    semantic_provider: str
    semantic_enabled: bool
    semantic_model: str
    semantic_confidence: float
    semantic_base_url: str
    semantic_api_key: str | None

    signature_enabled: bool

    update_check: UpdateCheckConfig

    agents_file: str | None


def _expand_env(value: Any, *, none_if_unresolved: bool = False) -> Any:
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        if none_if_unresolved and expanded == value and "${" in value:
            return None
        return expanded

    return value


def _target_from_dict(data: dict[str, Any]) -> Target | None:
    provider = data.get("provider")
    model = data.get("model")

    if not provider or not model:
        return None

    fallbacks: list[Target] = []
    raw_fallbacks = data.get("fallbacks", [])
    if isinstance(raw_fallbacks, list):
        for item in raw_fallbacks:
            if isinstance(item, dict):
                fallback = _target_from_dict(item)
                if fallback is not None:
                    fallbacks.append(fallback)

    return Target(
        provider=str(provider),
        model=str(model),
        base_url=_expand_env(data.get("base_url")),
        api_key=_expand_env(data.get("api_key"), none_if_unresolved=True),
        system_prompt=data.get("system_prompt"),
        fallbacks=fallbacks,
    )


def load_config() -> TopicDetectConfig:
    path = hermes_home() / "config.yaml"

    raw = yaml.safe_load(path.read_text()) or {}

    section = raw.get("topic_detect", {})

    semantic = section.get("semantic", {})
    signature = section.get("signature", {})
    update_check = section.get("update_check", {})
    if not isinstance(update_check, dict):
        update_check = {}

    enabled = bool(
        section.get("enabled", True)
    )

    routing_mode = str(
        section.get("routing_mode", "hybrid")
    ).lower()

    inertia = int(
        section.get("inertia", 2)
    )

    min_confidence = float(
        section.get("min_confidence", 0.45)
    )

    semantic_enabled = bool(
        semantic.get("enabled", False)
    )

    semantic_provider = str(
        semantic.get("provider", "openrouter")
    )

    semantic_model = str(
        semantic.get("model", "openrouter/free")
    )

    semantic_confidence = float(
        semantic.get("min_confidence", 0.70)
    )

    semantic_base_url = str(
        semantic.get(
            "base_url",
            "https://openrouter.ai/api/v1",
        )
    )

    semantic_api_key = _expand_env(
        semantic.get(
            "api_key",
            "${OPENROUTER_API_KEY}",
        ),
        none_if_unresolved=True,
    )

    signature_enabled = bool(
        signature.get("enabled", True)
    )

    update_check_enabled = bool(
        update_check.get("enabled", True)
    )
    update_check_url = str(
        update_check.get(
            "url",
            "https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/plugin.yaml",
        )
    )
    update_check_timeout = float(
        update_check.get("timeout_seconds", 2.5)
    )

    agents_file = str(
        section.get(
            "agents_file",
            str(hermes_home() / "plugins" / "topic_detect" / "AGENTS.md"),
        )
    )
    # Older installers wrote a literal default-profile path. Treat that
    # particular value as a default, not a custom cross-profile persona.
    if agents_file == "~/.hermes/plugins/topic_detect/AGENTS.md":
        agents_file = str(hermes_home() / "plugins" / "topic_detect" / "AGENTS.md")

    topics_data = section.get("topics", {})

    return TopicDetectConfig(
        enabled=enabled,
        routing_mode=routing_mode,

        inertia=inertia,
        min_confidence=min_confidence,

        # No topic_detect-specific default model/provider.
        # If no topic target matches, the plugin must not emit a runtime
        # model/provider override; Hermes keeps using the main `model:` config.
        default=None,

        # Topics with no provider/model are intentionally skipped. This lets a
        # category (notably entertainment_media) classify for logging/signature
        # but gracefully fall back to Hermes' main model if no specialist model
        # is configured for that category.
        topics={
            name: target
            for name, value in topics_data.items()
            if isinstance(value, dict)
            for target in [_target_from_dict(value)]
            if target is not None
        },

        semantic_provider=semantic_provider,
        semantic_enabled=semantic_enabled,
        semantic_model=semantic_model,
        semantic_confidence=semantic_confidence,
        semantic_base_url=semantic_base_url,
        semantic_api_key=semantic_api_key,

        signature_enabled=signature_enabled,

        update_check=UpdateCheckConfig(
            enabled=update_check_enabled,
            url=update_check_url,
            timeout_seconds=update_check_timeout,
        ),

        agents_file=agents_file,
    )
