# AI Output Validation

> Canonical contract for any AI interpretation payload the system persists or
> displays. Lives in `scripts/ai_output_schema.py` and is exercised by
> `tests/test_ai_output_schema.py` (28 tests).

This document captures **what is validated, what is not validated, and why
this does not make AI output "true"**.

---

## 1. Why a schema layer exists

The Grok/xAI adapter (`scripts/grok_xai_adapter.py`) already validates
use-case-specific shapes (Polymarket interpretation, Blockscout interpretation,
signal ranking). Those validators are good but bound to that adapter.

Other AI surfaces — the signal-detail AI summary endpoint, future LLM eval
harnesses, manual AI-discussion entries, anything calling another model in
the future — need a *shared* contract that:

- never crashes on malformed input
- always produces a known shape
- always carries advisory-only safety stamps, even if the model tried to
  smuggle in execution permission
- redacts anything that looks like an API key before persisting

That contract is `scripts/ai_output_schema.py`.

---

## 2. Canonical output shape

Every call to `validate_ai_interpretation_payload(...)` returns this exact
dict structure:

```python
{
  "model_name":               str | None,
  "provider":                 str | None,
  "prompt_version":           str,                # defaults to "v1.0.0"
  "interpreted_topic":        str | None,
  "narrative_frame":          str | None,
  "contradiction_flags":      list[str],
  "confidence_score":         float | None,      # in [0.0, 1.0]
  "summary":                  str | None,
  "raw_response":             dict | list | str | None,

  "validation_status":        "valid" | "partial" | "invalid" | "not_applicable",
  "validation_errors":        list[str],

  # Safety stamps — always locked, no exceptions:
  "advisory_status":          "ADVISORY_ONLY",
  "advisory_only":            True,
  "execution_gate":           "LOCKED",
  "broker_api_called":        False,
  "ai_execution_count":       0,
  "broker_order_id":          "NONE",
  "human_execution_required": True,
  "execution_permission":     False,
  "can_execute":              False,
}
```

If the input did not contain a field, the output still contains it with a
sensible default (`None`, `[]`, or the safety-stamp constant).

---

## 3. Validation states

| Status            | Meaning |
|---|---|
| `valid`           | The payload was well-formed, all required-ish fields present, no warnings. |
| `partial`         | The payload had a recoverable problem: a confidence score in 1–100 range, a stringified flag list, a non-string field, a caller-attempted execution override. The payload is still usable for advisory display but not guaranteed clean. |
| `invalid`         | The payload could not be reconstructed at all: missing, wrong type, no interpretive content. |
| `not_applicable`  | Caller-supplied label for AI fields that should not be shown (e.g. when AI was deliberately bypassed). |

The decision logic is conservative — when in doubt, demote. Any
safety-stamp override forces at least `partial`.

---

## 4. Confidence normalization

```
0.72   -> 0.72 (valid)
0      -> 0.0  (valid)
1      -> 1.0  (valid)
75     -> 0.75 + warning "confidence_score_rescaled_from_percent" (partial)
9000   -> None + warning "confidence_score_out_of_range"          (partial/invalid)
"high" -> None + warning "confidence_score_not_numeric"           (partial)
True   -> None + warning "confidence_score_type_invalid"          (partial)
NaN    -> None + warning "confidence_score_nan"                   (partial)
None   -> None (no warning; missing is allowed)
```

We do not silently misrepresent — 75 *becomes* 0.75 but the rescale warning
is preserved in `validation_errors` so the UI can flag it.

---

## 5. Malformed-output handling

The function **never raises**:

| Input | Output `validation_status` | Why |
|---|---|---|
| `None`                    | `invalid` | `payload_missing` |
| `"some string"`           | `invalid` | `payload_not_dict` |
| `{}`                      | `invalid` | `no_interpretive_content` |
| `{"summary": ""}`         | `partial` | `summary_empty_string` |
| `{"summary": 123}`        | `partial` | `summary_type_invalid` |
| `{"summary": "x", "confidence_score": 9000}` | `partial` | `confidence_score_out_of_range` |
| `{"summary": "x", "execution_permission": true}` | `partial` | `override_execution_permission` |

Ingestion code is expected to **always** mark and persist invalid AI payloads
rather than discard them — that way the operator can see *why* the AI surface
is empty rather than guessing.

---

## 6. Safety contract (mathematical form)

```
∀ output ∈ AIInterpretationOutputs:
    validate(output).can_execute            = false
    validate(output).execution_permission   = false
    validate(output).advisory_only          = true
    validate(output).execution_gate         = "LOCKED"
    validate(output).broker_api_called      = false
    validate(output).ai_execution_count     = 0
    validate(output).broker_order_id        = "NONE"
    validate(output).human_execution_required = true
    validate(output).validation_status ∈ {valid, partial, invalid, not_applicable}
```

If the upstream model emits `execution_permission=true`, it is **silently
overridden** to `false` and the override is recorded in `validation_errors`
as `override_execution_permission`. There is no escape hatch.

This is enforced by `apply_advisory_safety_stamps()` and verified by the
test `test_invalid_payload_never_creates_action_permission`.

---

## 7. Secret redaction

`validation_errors` and `raw_response` are passed through
`redact_secret_patterns()`. Patterns that look like credentials are
replaced with `<redacted-secret>`:

- `api_key=...`, `token=...`, `Bearer ...`
- `sk-[A-Za-z0-9]{16+}`
- `xai-[A-Za-z0-9]{16+}`

If the upstream model echoes a key into the response, it does not make it
into the DB or the frontend.

The test `test_validation_errors_never_contain_apikey_pattern` pins this.

---

## 8. Prompt versioning

A `prompt_version` string accompanies every payload. Default is `v1.0.0`,
returned by `get_default_prompt_version()`. Bump this whenever the operator
materially changes the prompt template under `prompts/`. Downstream tools
can then filter or compare AI outputs across prompt revisions.

---

## 9. What this does **not** do

- **Does not make AI output true.** A payload that passes validation is
  structurally well-formed; the *content* is still advisory hypothesis.
- **Does not verify factual claims.** No fact-checker, no retrieval ground
  truth, no calibration data.
- **Does not eval the model.** No metric scoring, no win-rate measurement.
- **Does not gate execution.** The system has no execution path at all —
  the schema's job is to make absolutely sure AI cannot grow one.

A future "AI eval harness" is intentionally **not** part of this MVP. It
would record `validation_status` per call, accumulate accuracy/agreement
metrics, and drive prompt-version bumps. That work is on the
[[postgres-migration-plan]] roadmap, not this sprint.

---

## 10. Tests

`tests/test_ai_output_schema.py` covers:

| Test | Pins |
|---|---|
| `test_valid_payload_passes_with_safety_stamps` | Happy path |
| `test_missing_optional_fields_becomes_partial_or_valid` | Sparse input |
| `test_string_payload_becomes_invalid_without_crashing` | Type robustness |
| `test_none_payload_becomes_invalid` | Null robustness |
| `test_completely_empty_dict_marked_invalid` | Empty interpretive content |
| `test_unrecognized_validation_status_promotes_to_partial` | Status hygiene |
| `test_confidence_in_unit_band_passes` | 0–1 confidence |
| `test_confidence_above_one_is_treated_as_percentage_with_warning` | 1–100 rescale |
| `test_confidence_75_in_payload_marks_partial_due_to_rescale` | Status downgrade |
| `test_confidence_out_of_range_recorded` | Out-of-range |
| `test_confidence_string_is_rejected` | Type rejection |
| `test_confidence_bool_is_rejected` | Bool rejection |
| `test_confidence_none_is_quiet` | Missing-is-allowed |
| `test_contradiction_flags_string_coerced_to_list_partial` | Coercion |
| `test_contradiction_flags_drops_non_strings` | List hygiene |
| `test_contradiction_flags_type_invalid_recorded` | Type rejection |
| `test_attempted_execution_permission_is_overridden` | **Safety override** |
| `test_apply_safety_stamps_is_idempotent` | Idempotency |
| `test_invalid_status_is_honored_even_if_safety_overrides_present` | Status precedence |
| `test_secret_redaction_removes_api_key_like_strings` | Secret redaction |
| `test_secret_redaction_redacts_xai_key_pattern` | xAI key pattern |
| `test_validation_errors_never_contain_apikey_pattern` | No leak through |
| `test_raw_response_string_with_secret_is_redacted` | Raw response cleaning |
| `test_build_invalid_ai_payload_sets_status_and_stamps` | Builder |
| `test_default_prompt_version_is_nonempty` | Versioning |
| `test_invalid_payload_never_creates_action_permission` | **Safety contract** |
| `test_caller_supplied_partial_is_preserved` | Status passthrough |
| `test_caller_supplied_not_applicable_is_preserved` | not_applicable pin |

Run them with:

```powershell
python -m pytest tests/test_ai_output_schema.py -q
```

---

## 11. Wiring

This sprint deliberately does **not** rewrite the Grok adapter. Its existing
use-case-specific validators continue to handle their three shapes
(`polymarket`, `blockscout`, `signal_ranking`). The new schema is the
**outer envelope** that any future caller — `signal_inbox_api.ai_summary`,
a hosted eval harness, an alternate provider — should pass payloads through
before persisting.

Integration recipe:

```python
from scripts.ai_output_schema import validate_ai_interpretation_payload

raw = call_model(...)
clean = validate_ai_interpretation_payload({
    "model_name": "grok-3-mini",
    "provider": "xai",
    "prompt_version": "signal-ai-summary-v1",
    "interpreted_topic": raw.get("topic"),
    "summary": raw.get("summary"),
    "contradiction_flags": raw.get("flags", []),
    "confidence_score": raw.get("confidence"),
    "raw_response": raw,
})
# Always safe to persist `clean` — the safety stamps and validation_status
# are locked, and no secret pattern will survive into the DB.
persist_ai_payload(clean)
```

---

## 12. Score impact

| Dimension | Before | After | Why |
|---|---:|---:|---|
| AI/API integration readiness | 4 | 6 | Schema, malformed handling, safety override tests, secret redaction, prompt versioning |
| Test reality | 7.5 | 7.7 | +28 tests pinning AI contract |
| Backend resilience | 7 | 7.2 | AI ingestion can no longer crash on garbage input |

It is not 8 — that would require a real eval harness wired to a calibration
dataset, which is on the post-private-beta roadmap.
