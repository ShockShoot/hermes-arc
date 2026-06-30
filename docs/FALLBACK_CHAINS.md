# Topic Fallback Chains

Hermes ARC v2.1 adds optional per-topic fallback chains.

A fallback chain lets each routed topic try one or more backup models before Hermes falls back to the agent's global main model. This is useful when free models rate-limit, provider endpoints return transient errors, or a specialist model is temporarily unavailable.

## Flow

```text
User message
  → ARC classifies intent/topic
  → ARC requests the topic primary model via runtime_override
  → Hermes tries the primary model
  → if it fails, Hermes tries topic fallback(s) in order
  → if all topic fallbacks fail, Hermes uses the normal global/main fallback path
```

Short form:

```text
primary model → topic fallback 1 → topic fallback 2 → ... → Hermes main/global model
```

## Config shape

Fallbacks are configured under each topic in `topic_detect.topics`.

```yaml
topic_detect:
  topics:
    software_it:
      provider: openrouter
      model: inclusionai/ring-2.6-1t:free
      fallbacks:
        - provider: openrouter
          model: baidu/cobuddy:free
        - provider: openrouter
          model: deepseek/deepseek-v4-flash:free
```

Each fallback entry accepts the same fields as a primary topic target:

```yaml
provider: openrouter
model: baidu/cobuddy:free
base_url: https://openrouter.ai/api/v1
api_key: ${OPENROUTER_API_KEY}
api_mode: openai
```

Only `provider` and `model` are normally required when the provider is already configured globally. Add `base_url`, `api_key`, or `api_mode` when the fallback needs explicit connection settings.

## Behavior

- `fallbacks` is optional. Existing configs without fallback entries keep working.
- Fallback order is deterministic: ARC/Hermes tries entries from top to bottom.
- Topic fallbacks are scoped to the routed topic only; they do not change the global Hermes fallback policy.
- Invalid fallback entries are ignored by the config loader instead of breaking startup.
- The final ARC signature uses the model that actually answered, not only the model ARC requested first.

## Signature examples

Primary succeeds:

```text
ring-2.6-1t [software_it]
```

Topic fallback answers:

```text
cobuddy [software_it | routed: ring-2.6-1t]
```

Global/main fallback answers after the routed path fails:

```text
gpt-5.5 [software_it | routed: ring-2.6-1t]
```

Interpretation:

- Text before the bracket is the final model that answered.
- The bracket topic is the ARC route.
- `routed: ...` is the primary model ARC initially requested for that route.

## Recommended starting chains

These are examples, not hard rules. Adjust them for your own quota, cost, latency, and provider reliability.

| Topic | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| `software_it` | ring-2.6-1t | cobuddy:free | deepseek-v4-flash → owl-alpha |
| `math` | deepseek-v4-flash | owl-alpha | ring-2.6-1t |
| `science` | deepseek-v4-flash | owl-alpha | ring-2.6-1t |
| `business_finance` | deepseek-v4-flash | owl-alpha | ring-2.6-1t |
| `legal_government` | owl-alpha | deepseek-v4-flash | main/global |
| `medicine_healthcare` | deepseek-v4-flash | owl-alpha | ring-2.6-1t |
| `writing_language` | owl-alpha | step-3.5-flash | main/global |
| `entertainment_media` | step-3.5-flash | owl-alpha | main/global |

## Operational tips

- Put cheaper or free models first only if they are reliable enough for the topic.
- Use at least one non-free or high-quota fallback for important production routes.
- Avoid long fallback chains for latency-sensitive chat; every failed model adds delay.
- Prefer provider diversity when possible, for example OpenRouter primary with a direct provider fallback.
- Keep medical/legal fallbacks conservative and strong enough for safety-sensitive explanations.

## Testing locally

Run the fallback config smoke test:

```bash
python tests/test_fallback_config.py
```

Inspect the active runtime patch support:

```bash
python3 ~/.hermes/plugins/topic_detect/patch_run_agent.py --check
python3 ~/.hermes/plugins/topic_detect/patch_run_agent.py --verify
```

Expected patch marker for this feature:

```text
HERMES_ARC_TOPIC_FALLBACK_PATCH
```
