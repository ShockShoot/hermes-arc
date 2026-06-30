# ARC Signature Flow

Hermes ARC has one source of truth for visible signatures: `signature.py`.

## Builders

- `build_signature(model, topic)` builds the simple routed signature used as a backward-compatible `response_suffix` value.
- `build_final_signature(...)` builds the final visible signature after Hermes has actually produced an answer. This is the preferred path because it can show fallback correctly.

Examples:

```text
- gpt-5.5 [general]
- gemini-3-flash [software_it | routed: ring-2.6-1t]
```

## Current v2.0.1 path

1. `pre_llm_call` classifies the user message and creates `runtime_override`.
2. If the patched Hermes core supports ARC suffix handling, ARC stores structured metadata in:

   ```python
   runtime_override["_arc_signature"] = {
       "topic": display_topic,
       "routed_model": signature_model,
       "routed_provider": routed_provider,
   }
   ```

3. The patched core calls `transform_llm_output(..., _arc_finalize=<metadata>)` after the final responder is known.
4. ARC renders the visible suffix with `build_final_signature(...)`.

This means the signature shown to the user is based on the model that actually answered, not only the model ARC originally routed to.

## Compatibility path

ARC also includes two compatibility paths:

- `runtime_override["response_suffix"]`: for patched cores that can append a plain suffix but do not yet use `_arc_signature` finalize metadata.
- `_LAST_SIGNATURE` + normal `transform_llm_output(response_text, ...)`: for older cores that do not consume runtime suffix metadata.

The plugin chooses exactly one active path per process to avoid duplicate signatures.

## Practical answer

When the core is properly patched, ARC currently uses:

```text
runtime_override._arc_signature → transform_llm_output(_arc_finalize=...) → build_final_signature()
```

`response_suffix` is retained only as a backward-compatible fallback.
