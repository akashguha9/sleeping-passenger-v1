# Alpha Evidence Bundle

Advisory-only. One portable, auditable JSON artifact per advisory
verdict: everything a hostile reviewer needs to reproduce or reject the
conclusion.

## Schema

```json
{
  "bundle_id": "EB_<sha256-prefix of content>",
  "created_at": "...",
  "advisory_only": true,
  "signal_name": "...",
  "input_snapshot": {},
  "scores": {
    "opportunity_score": 0,
    "confidence": 0,
    "calibration_adjusted_confidence": 0,
    "evidence_quality_score": 0,
    "probability_source": "calibrated | raw_proxy | neutral_missing | component_supplied",
    "raw_event_probability": null,
    "calibrated_event_probability": null
  },
  "verdict": "...",
  "trap_flags": [],
  "why_not_higher": [],
  "why_not_lower": [],
  "evidence_items": [],
  "filing_lineage": [],
  "prediction_market_lineage": [],
  "narrative_lineage": [],
  "value_chain_lineage": [],
  "replay_lineage": [],
  "calibration_summary": {},
  "autopsy": {},
  "missing_inputs": [],
  "disclaimer": "Advisory-only. Not financial advice. No trade execution."
}
```

## Properties

- **Deterministic IDs**: `bundle_id` is a hash of the bundle content,
  not a UUID — the same inputs with a fixed `created_at` always produce
  the same ID, and any content change changes it. Test fixtures rely on
  this.
- **No environment leakage**: the bundle contains exactly what the
  caller passed plus what the scoring modules computed from it. No env
  reads, no hidden file access (test-enforced with a canary variable).
- **Explicit gaps**: absent sections land in `missing_inputs` instead
  of being silently empty.
- **JSON-roundtrip safe** and free of execution language
  (test-enforced).

## Surfaces

- `src/alpha/evidence_bundle.py` — `build_evidence_bundle(...)`.
- `POST /alpha/evidence-bundle` (strict token gate): accepts the same
  scoring inputs as `/alpha/score` plus a signal name; returns the
  bundle with scores, filing lineage, autopsy, and calibration summary
  computed server-side.
- Dashboard: per-node bundle table in the plumbing v4 panel.
