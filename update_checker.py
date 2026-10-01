from __future__ import annotations

import logging
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .yaml_compat import safe_load
except ImportError:  # direct script/pytest import
    from yaml_compat import safe_load

logger = logging.getLogger("topic_detect")

DEFAULT_UPDATE_URL = (
    "https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/plugin.yaml"
)


@dataclass
class UpdateStatus:
    update_available: bool
    local_version: str
    latest_version: str | None
    url: str
    error: str | None = None


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw in version.strip().lstrip("v").split("."):
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or 0))
    return tuple(parts or [0])


def _is_newer(latest: str, local: str) -> bool:
    latest_parts = _parse_version(latest)
    local_parts = _parse_version(local)
    size = max(len(latest_parts), len(local_parts))
    latest_parts += (0,) * (size - len(latest_parts))
    local_parts += (0,) * (size - len(local_parts))
    return latest_parts > local_parts


def _read_local_version(plugin_yaml_path: str | Path | None = None) -> str:
    if plugin_yaml_path is None:
        plugin_yaml_path = Path(__file__).with_name("plugin.yaml")
    path = Path(plugin_yaml_path).expanduser()
    data = safe_load(path.read_text(encoding="utf-8")) or {}
    return str(data.get("version") or "0.0.0")


def _read_remote_version(url: str, timeout: float = 2.5) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hermes-arc-topic-detect-update-check"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(128_000).decode("utf-8", errors="replace")
    data = safe_load(body) or {}
    return str(data.get("version") or "0.0.0")


def check_for_update(
    *,
    url: str = DEFAULT_UPDATE_URL,
    plugin_yaml_path: str | Path | None = None,
    timeout: float = 2.5,
) -> UpdateStatus:
    local_version = _read_local_version(plugin_yaml_path)
    try:
        latest_version = _read_remote_version(url, timeout=timeout)
    except Exception as exc:
        return UpdateStatus(
            update_available=False,
            local_version=local_version,
            latest_version=None,
            url=url,
            error=str(exc),
        )

    return UpdateStatus(
        update_available=_is_newer(latest_version, local_version),
        local_version=local_version,
        latest_version=latest_version,
        url=url,
    )


def maybe_log_update_notice(cfg: Any) -> UpdateStatus | None:
    """Check once after process restart and log if a newer ARC version exists.

    This intentionally only logs. It does not append user-visible chat text, so
    update checks never spam conversations.
    """

    update_cfg = getattr(cfg, "update_check", None)
    if update_cfg is None or not getattr(update_cfg, "enabled", True):
        return None

    url = getattr(update_cfg, "url", DEFAULT_UPDATE_URL)
    timeout = float(getattr(update_cfg, "timeout_seconds", 2.5))

    status = check_for_update(url=url, timeout=timeout)
    if status.error:
        logger.info(
            "topic_detect: update check skipped local=%s url=%s error=%s",
            status.local_version,
            status.url,
            status.error,
        )
        return status

    if status.update_available:
        logger.warning(
            "topic_detect: update available local=%s latest=%s url=%s; update with: "
            "curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash",
            status.local_version,
            status.latest_version,
            status.url,
        )
    else:
        logger.info(
            "topic_detect: update check ok local=%s latest=%s",
            status.local_version,
            status.latest_version,
        )

    return status
