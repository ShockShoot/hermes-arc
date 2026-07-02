# Changelog

## 2.2.3 - 2026-07-02

### Verified
- Checked Hermes Agent v0.18.0 upstream `2068754d`; the split-runtime patch targets (`agent/conversation_loop.py`, `agent/turn_context.py`, and `agent/turn_finalizer.py`) already pass all ARC compatibility checks: runtime override collection, `switch_model()` routing, response suffix/signature finalization, provider-aware transform hooks, topic fallback chains, and skipdetect message rewrite.

### Changed
- Release metadata refreshed so ARC update checks report the latest verified Hermes compatibility window after the July 2026 Hermes update.

## 2.2.2 - 2026-06-30

### Fixed
- Refreshed installer default routing away from stale/unavailable defaults (`nemotron-3`, `gpt-oss`, and paid `qwen3.6-plus`) to the current free/known-good ARC chain: `ring-2.6-1t`, `cobuddy`, `deepseek-v4-flash`, `owl-alpha`, and `step-3.5-flash` by topic.
- New installs now seed topic-scoped fallback chains instead of only a primary model, while preserving existing user-customized topic routes.
- Smoke tests are now also pytest-collectable, so `python -m pytest tests` catches regressions instead of exiting with “no tests collected”.

### Verified
- Checked Hermes Agent v0.17.0 upstream `b6045170`; active runtime already has all ARC markers (`runtime_override`, fallback-chain, skipdetect rewrite, provider transform, structured signature) and needs no additional patch.

## 2.2.1 - 2026-06-22

### Verified
- Re-applied ARC compatibility patches to Hermes Agent v0.17.0 (`agent/turn_context.py` and `agent/turn_finalizer.py`) after the latest Hermes update and verified all runtime override, fallback-chain, skipdetect, provider transform, and structured signature markers pass.

### Changed
- Release metadata refreshed so ARC update checks report the latest verified Hermes compatibility window.

## 2.2.0 - 2026-06-12

### Fixed
- `patch_run_agent.py` now supports Hermes v0.16 split-runtime layout where `pre_llm_call` lives in `agent/turn_context.py` and final response transforms live in `agent/turn_finalizer.py`.
- Runtime override routing, topic-scoped fallback chains, skipdetect message rewrites, and structured ARC signatures are restored after the latest Hermes update.
- Explicit `--path .../agent/conversation_loop.py` is now accepted instead of being rejected as “not a valid run_agent.py”.

### Verified
- Re-applied ARC compatibility patches to Hermes Agent v0.16.0 and verified all ARC markers pass across `conversation_loop.py`, `turn_context.py`, and `turn_finalizer.py`.

## 2.1.9 - 2026-05-29

### Verified
- Re-applied ARC compatibility patches to Hermes Agent v0.15.1 (`agent/conversation_loop.py`) after an upstream update and verified all runtime override, fallback-chain, skipdetect, and signature markers pass.

### Changed
- Release metadata refreshed so update checks and GitHub releases report the latest verified Hermes compatibility window.

## 2.1.8 - 2026-05-19

### Fixed
- `patch_run_agent.py` now supports Hermes v0.14+ where the main conversation loop moved from `run_agent.py` into `agent/conversation_loop.py`. Passing `--path .../run_agent.py` still works; the patcher detects and targets the real loop module automatically.
- ARC runtime overrides, provider-aware signature rendering, topic fallback chains, system-prompt context injection, and skipdetect message rewrites are restored on the refactored Hermes core after an update.

### Verified
- Re-applied ARC compatibility patches to Hermes Agent v0.14.0 (`agent/conversation_loop.py`) and verified all ARC markers pass.

## 2.1.7 - 2026-05-17

### Fixed
- Release metadata is now consistent across `plugin.yaml`, `pyproject.toml`, and `CHANGELOG.md` so installers, update checks, package metadata, and GitHub releases report the same ARC version.
- Added a release metadata smoke test and wired it into CI to prevent future version drift.

### Verified
- Confirmed the v2.1.x patcher can apply cleanly to the latest checked Hermes `origin/main` `run_agent.py` and verify all ARC compatibility markers: runtime overrides, final signature rendering, provider-aware transform hooks, topic fallback chains, and skipdetect message rewrite.

## 2.1.6 - 2026-05-16

### Added
- Interactive arrow-key runtime selector for the plain `curl -fsSL .../install.sh | bash` installer flow when multiple Hermes `run_agent.py` candidates are found. Use ↑/↓ or k/j, Enter to select, q/Esc to skip.

## 2.1.5 - 2026-05-16

### Fixed
- Plain `curl -fsSL .../install.sh | bash` installs/updates ARC and automatically re-applies the runtime patch when exactly one Hermes `run_agent.py` is discovered, which makes the normal install command safe to run after `hermes update`.
- Installer compatibility detection now recognizes the current patcher success output (`All checks passed`) instead of prompting on already-patched runtimes.
- Non-interactive installs still skip patching when multiple Hermes runtimes are discovered; pass `--run-agent-path` to choose explicitly.

## 2.1.4 - 2026-05-13

### Fixed
- Installer/runtime discovery now resolves the active Hermes config home and finds `run_agent.py` across source checkouts, pip/uv installs, importable runtimes, and running Hermes gateway processes instead of relying only on `$HOME` static paths.

## 2.1.3 - 2026-05-13

### Added
- Short skip aliases `/sd`, `!sd`, and `@@sd` for faster one-turn ARC bypass while keeping `/skipdetect`, `!skipdetect`, and `@@skipdetect` as full-form aliases.

## 2.1.2 - 2026-05-13

### Fixed
- Avoid duplicate ARC signatures on patched Hermes cores by emitting only the structured `_arc_signature` runtime metadata and no longer also setting `response_suffix` for the same turn.
- Preserve the legacy `transform_llm_output` compatibility path for older Hermes cores that do not consume structured `_arc_signature` metadata.

## 2.1.1 - 2026-05-12

### Added
- `/skipdetect <message>` command prefix to bypass ARC classification/routing for one turn, restore the main Hermes model, strip the prefix before the LLM call, and show `[skip]` in the final signature.
- Patcher verification for `HERMES_ARC_SKIPDETECT_PATCH`, which lets patched Hermes runtimes rewrite the current-turn user message from plugin metadata.
- Smoke test covering `/skipdetect` bypass behavior and signature rendering.

### Fixed
- Topic fallback chains are now explicitly scoped per turn: routed topics always emit `fallback_chain` (possibly empty), global fallback chains are preserved, and stale topic fallbacks cannot leak into later turns.

## 2.1.0 - 2026-05-12

### Added
- Optional per-topic `fallbacks` arrays in `topic_detect.topics`. ARC now emits a `runtime_override.fallback_chain` so a routed topic can try specialist fallbacks before Hermes falls back to the global/main runtime.
- `patch_run_agent.py` verification for `HERMES_ARC_TOPIC_FALLBACK_PATCH`, which teaches patched cores to apply topic-scoped fallback chains.
- Smoke test covering fallback config parsing and runtime override emission.

### Changed
- Runtime switch logs now include fallback count for easier diagnosis.

## 2.0.1 - 2026-05-12

### Fixed
- Render ARC signatures from the structured `_arc_signature` finalize path so patched Hermes cores show the final responder correctly in Telegram and CLI output.
- Make `patch_run_agent.py` repair partially patched Hermes runtimes instead of exiting early when only some ARC markers already exist.

### Changed
- Cleaned repository layout by moving development smoke tests under `tests/`, adding focused docs under `docs/`, and adding CI smoke checks while keeping runtime plugin files flat for installer compatibility.
- Installer now downloads `docs/` references and creates nested directories before writing files.
- Documented the current signature source of truth: `runtime_override._arc_signature → transform_llm_output(_arc_finalize=...) → build_final_signature()`.

## 2.0.0 - 2026-05-12

### Breaking
- Reframed ARC classification from topic-first to intent/action-first routing. The 8 topic names and config schema are unchanged, but route decisions now prioritize what the user is trying to do over what subject words appear in the prompt.

### Added
- Extensible action detection registry for `technical`, `analytical`, and `creative` actions, with room for future categories such as tool-use, research, multimodal, and agentic actions.
- Absolute `TECHNICAL_ACTION` override: prompts asking to modify, fix, run, configure, debug, build, implement, test, refactor, or operate technical artifacts route to `software_it` even when the subject mentions writing, finance, law, healthcare, or media.
- Action/subject routing tables for creative and analytical prompts.
- Debug metadata on keyword classification results: `action_detected`, `action_score`, `subject_detected`, `final_route_reason`, plus matched action/subject details in logs.
- `test_v2_classifier.py` smoke matrix covering technical override, creative routing, analytical routing, and safe `none` cases.

### Changed
- Semantic classifier prompt now explicitly classifies intent, not merely topic, and includes five rules: technical action overrides everything; classify action not subject; content subject alone is not enough; use subject as tiebreaker only when action is unclear; `none` is safe.
- Keyword classifier now normalizes text with Unicode NFKC and whitespace compaction before scoring.
- Creative article writing stays `writing_language` even when the article subject is finance; report/contract deliverables keep domain-specific routes.

### Preserved
- `config.yaml` structure, the 8 topic names, signature format, fallback behavior, inertia state logic, and installer behavior remain compatible with v1.2.x.

## 1.2.0 - 2026-05-12

### Breaking
- Full rewrite of core compatibility patch to match Hermes Agent v0.13+ plugin hook architecture. After 62 upstream commits refactored `pre_llm_call` (now returns context-only, no `runtime_override` dict) and removed `response_suffix` / `plugin_system_prompt` mechanisms entirely, v1.1.x patches are incompatible.

### Added
- `switch_model()` integration: runtime model/provider routing now uses Hermes' native `switch_model()` method instead of direct attribute mutation. This preserves provider-specific `api_mode`, OAuth credentials, headers, context-compressor metadata, and client rebuild logic.
- `provider=self.provider` injection into `transform_llm_output` hook — enables signature builder to detect fallback (final model differs from routed model).
- `_arc_signature` dict in `runtime_override` — structured routing metadata (`topic`, `routed_model`, `routed_provider`) carried into post-loop for final-render.
- System prompt override injected as part of `_ctx_parts` into user message, preserving prompt cache prefix stability.

### Changed
- `patch_run_agent.py` completely rewritten for v1.2.0:
  - Patch 1A: `_runtime_override` dict init before `pre_llm_call`
  - Patch 1B: collect `runtime_override` from hook results
  - Patch 1C: apply routing via `switch_model()` (with `resolve_provider_client` + `determine_api_mode`)
  - Patch 2: inject `provider=self.provider` into `transform_llm_output` hook
  - Patch 3: `_arc_signature` suffix render (fallback-aware)
  - Patch 4: system prompt capture as `_ctx_parts` member
- Plugin `__init__.py` unchanged — structurally compatible with v1.2.0 patch (sends `runtime_override` dict, reads `provider` from kwargs)
- Config topic models updated:
  - `software_it` → `nvidia/nemotron-3-super-120b-a12b:free`
  - `math` → `inclusionai/ring-2.6-1t:free`
  - `science` → `nvidia/nemotron-3-super-120b-a12b:free`
  - `business_finance` → `openai/gpt-oss-120b:free`
  - `legal_government` → `openai/gpt-oss-120b:free`
  - `medicine_healthcare` → `openrouter/owl-alpha`
  - `writing_language` → `google/gemma-4-31b-it:free`
  - `entertainment_media` → empty (falls back to main model)

### Deprecated
- PR #23898 (`_plugin_system_prompt` scope fix) — upstream removed the entire mechanism; v1.2.0 uses a different approach that doesn't require patching `_handle_max_iterations()`.

## 1.1.8 - 2026-05-12

### Fixed
- Signatures now identify the model that actually produced the final answer after Hermes fallback. When ARC routes to one model but the API call rate-limits/fails and Hermes switches to fallback, the suffix renders the final responder first and preserves the routed model as context, e.g. `- owl-alpha [software_it | routed: gemma-4-31b]`.
- The legacy `transform_llm_output` compatibility path also rebuilds signatures from the final model when available.

## 1.1.7 - 2026-05-11

### Fixed
- `patch_run_agent.py` no longer injects code referencing `_plugin_system_prompt` as a local variable inside `_handle_max_iterations()`. That variable only exists in `run_conversation()` scope and caused a `NameError` at runtime when max iterations was reached with a plugin system_prompt override. The patcher now adds `plugin_system_prompt: str = ""` as a parameter to `_handle_max_iterations`, uses the parameter in the injected code, and passes `_plugin_system_prompt` from the call site. Matches the fix in NousResearch/hermes-agent PR #23898.

## 1.1.6 - 2026-05-11

### Fixed
- Installer no longer prints `Removed unresolved api_key` and then re-adds the same `${OPENROUTER_API_KEY}` placeholder to topic targets. It now treats `OPENROUTER_API_KEY` in `~/.hermes/.env` as resolvable, and only omits/removes the placeholder when the key is unavailable from both the process environment and `.env`.

## 1.1.5 - 2026-05-11

### Fixed
- Restore visible topic signatures on patched Hermes cores by placing `response_suffix` inside `runtime_override`, where the ARC core patch reads it. Keeps the legacy `transform_llm_output` fallback for older cores without duplicating signatures.

## 1.1.4 - 2026-05-11

### Fixed
- Avoid duplicate topic signature suffixes when running on Hermes core builds that consume `runtime_override.response_suffix`; ARC now chooses either the core suffix path or the legacy `transform_llm_output` path, never both.

## 1.1.3 - 2026-05-11

### Fixed
- Installer now migrates/removes legacy 12-topic config keys when updating to the 8-topic Arena-aligned taxonomy, preventing stale topics from accumulating in `topic_detect.topics`.
- Legacy topic values are preserved when they can be safely moved into a new topic that does not already exist; custom non-legacy topics are left untouched.

## 1.1.2 - 2026-05-11

### Changed
- Polished README/README_TH positioning for Hermes ARC as a practical reference implementation for topic-aware runtime model routing.
- Added upstream Hermes issue links, clean smart-router architecture direction, roadmap, and current recommended model mapping examples.

## 1.1.1 - 2026-05-11

### Changed
- Signature display now renders internal `none`/empty fallback topics as `general`, e.g. `- gpt-5.5 [general]`, while keeping internal routing logic as `none`.

## 1.1.0 - 2026-05-11

### Added
- Runtime update notice: after Hermes restarts, ARC checks once whether a newer `plugin.yaml` version exists on GitHub and logs an update notice without spamming chat responses.
- `install.sh --check` to compare local vs latest GitHub version.
- `install.sh --update` as an explicit update alias for normal install/update flow.
- `topic_detect.update_check` config support.

### Changed
- Reworked taxonomy to 8 Arena.ai-aligned primary topics: `software_it`, `math`, `science`, `business_finance`, `legal_government`, `medicine_healthcare`, `writing_language`, `entertainment_media`.
- Removed the `general` topic; unclear prompts return `none` and use Hermes' main model.
- Tuned bilingual EN/TH keyword routing to be conservative and high-signal only.
- Removed ambiguous broad keywords such as `app`, `review`, `policy`, `market`, `terms`, `story`, generic `เขียน`, and generic `สุขภาพ`.
- English keyword matching now uses token boundaries instead of raw substring matching.
- Topics with missing/empty `provider` or `model` are skipped and gracefully fall back to Hermes' main model.

### Notes
- `entertainment_media` is intentionally optional; leave it without a model if your main model handles movie/game/sports/media prompts well.
- `writing_language` remains broad by design. If routing complaints appear later, split creative writing and translation first.
- Arena Expert/Hard/Instruction/Multi-Turn/Longer Query/language boards remain future modifiers, not primary routes.
