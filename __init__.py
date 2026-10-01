from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

try:
    from .agent_loader import get_agent_prompt
    from .classifier import classify
    from .config import hermes_home, load_config
    from .semantic import semantic_classify
    from .signature import build_final_signature, build_signature
    from .state import TopicState
    from .update_checker import maybe_log_update_notice
except ImportError:  # pragma: no cover - direct script/pytest import fallback
    from agent_loader import get_agent_prompt
    from classifier import classify
    from config import hermes_home, load_config
    from semantic import semantic_classify
    from signature import build_final_signature, build_signature
    from state import TopicState
    from update_checker import maybe_log_update_notice

logger = logging.getLogger("topic_detect")

_STATE_LOCK = threading.RLock()
_TOPIC_STATES: OrderedDict[str, TopicState] = OrderedDict()
_LEGACY_SIGNATURES: OrderedDict[str, dict[str, Any] | str] = OrderedDict()
_MAX_SESSIONS = 256
_UPDATE_NOTICE_CHECKED = False
_CORE_RESPONSE_SUFFIX_SUPPORTED: bool | None = None


def _session_key(kwargs: dict[str, Any]) -> str:
    identity = kwargs.get("session_id") or kwargs.get("task_id") or kwargs.get("turn_id") or "unknown"
    return f"{hermes_home()}:{identity}"


def _remember_signature(key: str, signature: dict[str, Any] | str | None) -> None:
    with _STATE_LOCK:
        _LEGACY_SIGNATURES.pop(key, None)
        if signature:
            _LEGACY_SIGNATURES[key] = signature
            if len(_LEGACY_SIGNATURES) > _MAX_SESSIONS:
                _LEGACY_SIGNATURES.popitem(last=False)



def _extract_messages(kwargs: dict[str, Any]) -> list[str]:
    """Route only the current intent, not an earlier turn with another task."""
    content = kwargs.get("user_message")
    if isinstance(content, list):
        text = " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
    elif isinstance(content, str):
        text = content.strip()
    else:
        text = ""
    return [text] if text else []


def _strip_skipdetect_prefix(message: str | None) -> str | None:
    text = str(message or "")
    stripped = text.lstrip()

    commands = ("/sd", "!sd", "@@sd", "/skipdetect", "!skipdetect", "@@skipdetect")
    for command in commands:
        if stripped == command:
            return ""
        if stripped.startswith(f"{command} "):
            remainder = stripped[len(command):].lstrip()
            return remainder if remainder else ""

    return None


def _target_runtime_dict(target) -> dict[str, Any]:
    data: dict[str, Any] = {
        "model": target.model,
        "provider": target.provider,
    }

    if target.base_url:
        data["base_url"] = target.base_url

    if target.api_key:
        data["api_key"] = target.api_key

    return data


def _runtime_updates(target) -> dict[str, Any]:
    updates = _target_runtime_dict(target)

    if target.system_prompt:
        updates["system_prompt"] = target.system_prompt

    # Always send fallback_chain for routed topics, even when empty.
    # This keeps topic-scoped fallback state turn-scoped and prevents a
    # previous topic's fallback chain from leaking into the next route.
    updates["fallback_chain"] = [
        _target_runtime_dict(fallback)
        for fallback in getattr(target, "fallbacks", [])
    ]

    return updates


def _core_supports_response_suffix() -> bool:
    """Return True when Hermes core consumes runtime_override.response_suffix.

    Hermes ARC used transform_llm_output as a compatibility path before the
    core runtime_override patch learned to append response_suffix directly.
    If both paths run, signatures are duplicated. Detect the patched core
    once and choose exactly one signature path per process.
    """

    global _CORE_RESPONSE_SUFFIX_SUPPORTED

    if _CORE_RESPONSE_SUFFIX_SUPPORTED is not None:
        return _CORE_RESPONSE_SUFFIX_SUPPORTED

    try:
        import run_agent  # type: ignore

        run_agent_path = Path(getattr(run_agent, "__file__", ""))
        if not run_agent_path.exists():
            _CORE_RESPONSE_SUFFIX_SUPPORTED = False
            return False

        runtime_files = [
            run_agent_path,
            run_agent_path.parent / "agent" / "conversation_loop.py",
            run_agent_path.parent / "agent" / "turn_finalizer.py",
        ]
        source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in runtime_files
            if path.is_file()
        )
        _CORE_RESPONSE_SUFFIX_SUPPORTED = "HERMES_ARC_RESPONSE_SUFFIX_PATCH" in source
    except Exception as exc:
        logger.debug("topic_detect: response_suffix support detection failed: %s", exc)
        _CORE_RESPONSE_SUFFIX_SUPPORTED = False

    return bool(_CORE_RESPONSE_SUFFIX_SUPPORTED)


def _pre_llm_call(**kwargs):
    logger.info(
        "topic_detect: pre_llm_call fired kwargs=%s",
        list(kwargs.keys()),
    )

    try:
        return _pre_llm_call_impl(**kwargs)

    except Exception:
        logger.exception(
            "topic_detect: pre_llm_call crashed"
        )
        return None


def _pre_llm_call_impl(**kwargs):
    global _UPDATE_NOTICE_CHECKED

    key = _session_key(kwargs)
    cfg = load_config()

    if not cfg.enabled:
        _remember_signature(key, None)
        with _STATE_LOCK:
            _TOPIC_STATES.pop(key, None)
        logger.info("topic_detect: disabled")
        return None

    if not _UPDATE_NOTICE_CHECKED:
        _UPDATE_NOTICE_CHECKED = True
        maybe_log_update_notice(cfg)

    messages = _extract_messages(kwargs)
    logger.debug("topic_detect: considering %d messages", len(messages))

    skip_message = _strip_skipdetect_prefix(kwargs.get("user_message"))
    if skip_message is not None:
        logger.info("topic_detect: skipdetect requested; bypassing classification and routing")
        with _STATE_LOCK:
            _TOPIC_STATES.pop(key, None)
        updates: dict[str, Any] = {
            "restore_main": True,
            "user_message": skip_message,
        }
        signature_model = str(kwargs.get("model") or "default")
        signature = build_signature(signature_model, "skip", reason="skip")

        if cfg.signature_enabled and _core_supports_response_suffix():
            updates["_arc_signature"] = {
                "topic": "skip",
                "routed_model": signature_model,
                "routed_provider": str(kwargs.get("provider") or ""),
                "reason": "skip",
            }
            _remember_signature(key, None)
        elif cfg.signature_enabled:
            _remember_signature(key, {
                "topic": "skip",
                "routed_model": signature_model,
                "routed_provider": str(kwargs.get("provider") or ""),
                "reason": "skip",
            })
        else:
            _remember_signature(key, None)

        return {"runtime_override": updates}

    result = classify(messages)

    routing_mode = cfg.routing_mode

    source = "keyword"

    if routing_mode == "semantic":
        result.topic = "none"
        result.confidence = 0.0
        result.scores = {}

    if routing_mode in ("semantic", "hybrid"):
        should_use_semantic = (
            cfg.semantic_enabled
            and (
                routing_mode == "semantic"
                or result.confidence < cfg.semantic_confidence
            )
        )

        if should_use_semantic:
            semantic = semantic_classify(
                messages,
                provider=cfg.semantic_provider,
                model=cfg.semantic_model,
                api_key=cfg.semantic_api_key,
                base_url=cfg.semantic_base_url,
            )

            logger.info(
                "topic_detect: semantic topic=%s conf=%.2f status=%s",
                semantic.topic,
                semantic.confidence,
                "ok" if semantic.confidence > 0 else "unavailable",
            )

            if semantic.confidence <= 0:
                logger.info(
                    "topic_detect: semantic failed, fallback to keyword"
                )

            if (
                routing_mode == "semantic"
                or semantic.confidence > result.confidence
            ):
                result.topic = semantic.topic
                result.confidence = semantic.confidence
                source = "semantic"

    with _STATE_LOCK:
        state = _TOPIC_STATES.pop(key, None) or TopicState()
        topic, should_switch, reason = state.decide(
            result.topic, result.confidence,
            inertia=cfg.inertia, min_conf=cfg.min_confidence,
        )
        _TOPIC_STATES[key] = state
        if len(_TOPIC_STATES) > _MAX_SESSIONS:
            _TOPIC_STATES.popitem(last=False)
        candidate = state.candidate_topic

    logger.info(
        "topic_detect: source=%s raw=%s conf=%.2f final=%s switch=%s reason=%s action=%s action_score=%.2f subject=%s route_reason=%s scores=%s debug=%s",
        source,
        result.topic,
        result.confidence,
        topic,
        should_switch,
        reason,
        getattr(result, "action_detected", "none"),
        getattr(result, "action_score", 0.0),
        getattr(result, "subject_detected", "none"),
        getattr(result, "final_route_reason", ""),
        {
            k: round(v, 2)
            for k, v in result.scores.items()
            if v > 0
        },
        getattr(result, "debug", {}),
    )

    target = None

    if (
        topic
        and topic != "none"
        and topic in cfg.topics
    ):
        target = cfg.topics[topic]

    agent_prompt = get_agent_prompt(
        topic,
        cfg.agents_file,
    )

    if agent_prompt and target:
        target.system_prompt = agent_prompt

        logger.info(
            "topic_detect: agent prompt loaded topic=%s chars=%s",
            topic,
            len(agent_prompt),
        )

    updates = _runtime_updates(target) if target else {"restore_main": True}
    if target:
        logger.info("topic_detect: route provider=%s model=%s fallbacks=%d",
                    target.provider, target.model, len(target.fallbacks))
    else:
        logger.info("topic_detect: no specialist route; main runtime retained")

    display_topic = topic

    if (
        candidate
        and candidate != topic
    ):
        display_topic = f"{topic} → {candidate}"

    signature_model = target.model if target else str(kwargs.get("model") or "default")

    signature = build_signature(
        signature_model,
        display_topic,
    )

    logger.info(
        "topic_detect: signature=%s",
        signature,
    )

    logger.debug("topic_detect: runtime override keys=%s", list(updates))

    if cfg.signature_enabled and _core_supports_response_suffix():
        # Patched Hermes cores read _arc_signature from runtime_override
        # and render the signature themselves via transform_llm_output(_arc_finalize=...)
        # after any fallback has resolved. Do NOT set response_suffix here —
        # that would cause a double signature (hook appends once, core appends again).
        updates = dict(updates)
        updates["_arc_signature"] = {
            "topic": display_topic,
            "routed_model": signature_model,
            "routed_provider": target.provider if target else str(kwargs.get("provider") or ""),
        }
        _remember_signature(key, None)
    elif cfg.signature_enabled:
        # Older cores use the normal transform hook rather than structured
        # finalization. Keep one signature per session, not per process.
        _remember_signature(key, {
            "topic": display_topic,
            "routed_model": signature_model,
            "routed_provider": target.provider if target else str(kwargs.get("provider") or ""),
        })
    else:
        _remember_signature(key, None)

    return {
        "runtime_override": updates,
    }

def register(ctx):
    logger.info("topic_detect: loaded")

    ctx.register_hook(
        "pre_llm_call",
        _pre_llm_call,
    )

    ctx.register_hook(
        "transform_llm_output",
        _transform_llm_output,
    )


def _transform_llm_output(response_text: str, **kwargs) -> str | None:
    """Render or append the ARC signature suffix.

    Legacy cores call this hook with the final response and use
    _LAST_SIGNATURE. Patched cores call it a second way with
    _arc_finalize metadata and an empty response_text so the core can append
    exactly one final-model-aware suffix itself.
    """
    finalize = kwargs.get("_arc_finalize")
    if isinstance(finalize, dict):
        return build_final_signature(
            routed_model=finalize.get("routed_model"),
            final_model=kwargs.get("model"),
            topic=finalize.get("topic"),
            routed_provider=finalize.get("routed_provider"),
            final_provider=kwargs.get("provider"),
            reason=finalize.get("reason"),
        )

    key = _session_key(kwargs)
    with _STATE_LOCK:
        sig = _LEGACY_SIGNATURES.pop(key, None)

    if isinstance(sig, dict):
        return f"{response_text}\n\n{build_final_signature(routed_model=sig.get('routed_model'), final_model=kwargs.get('model'), topic=sig.get('topic'), routed_provider=sig.get('routed_provider'), final_provider=kwargs.get('provider'), reason=sig.get('reason'))}"

    if sig:
        return f"{response_text}\n\n{sig}"

    return None
