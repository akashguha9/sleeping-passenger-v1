# Mythos → Fable Operational Loop

This is the **operating discipline** for the completed
Mythos → Aggregator → Fable 5 → Capture → Calibration system. The architecture
is done; this document is how you run it safely to accumulate real evidence and
calibrate **only when reality has spoken**.

```
Enable capture → run paper/advisory decisions → append decisions.jsonl
  → check readiness → resolve outcomes weekly
  → calibrate only when enough real labelled records exist
```

## Safety defaults (unchanged)

- **Advisory only. No real-money execution, ever.** Every output carries
  `advisory_status = ADVISORY_ONLY` and `real_money_execution = PROHIBITED`.
- **No writes by default.** Capture is off unless explicitly enabled.
- **No calibration lies.** Unresolved decisions stay `INCONCLUSIVE` and are
  excluded; synthetic fixtures are never eligible; weights are not fitted below
  the evidence threshold.

## Single entry point

```bash
python -m scripts.signal_arbitrage.advisory_runner [action] [flags]
```

Actions (mutually chosen; default action is an advisory run):
`--check-corpus`, `--resolve-outcome`, `--run-calibration`, or (default) an
advisory run. Capture flags: `--capture-decisions`, `--capture-mode write|dry_run`
(default `dry_run`), `--capture-path`, `--strict-capture`. Env equivalents:
`SIGNAL_CAPTURE_DECISIONS`, `SIGNAL_CAPTURE_MODE`, `SIGNAL_CAPTURE_PATH`,
`SIGNAL_CAPTURE_STRICT`.

---

## 1. Daily / paper-advisory run (capture enabled)

A real run supplies observations via `--observations <path.json>` (a JSON list
of Mythos observation dicts produced by your pipeline). `--demo` uses a built-in
cluster forced to `SYNTHETIC_FIXTURE` so demo data can never become
calibration-eligible.

```bash
# Env style
SIGNAL_CAPTURE_DECISIONS=1 \
SIGNAL_CAPTURE_MODE=write \
SIGNAL_CAPTURE_PATH=data/calibration_corpus/decisions.jsonl \
python -m scripts.signal_arbitrage.advisory_runner --observations today_observations.json

# Flag style
python -m scripts.signal_arbitrage.advisory_runner \
  --observations today_observations.json \
  --capture-decisions --capture-mode write \
  --capture-path data/calibration_corpus/decisions.jsonl \
  --run-id 2026-06-13-paper --universe AI --decision-date 1
```

Each decision appends one snapshot (deduped by `decision_id`), with the outcome
left `INCONCLUSIVE` / `OPEN_OR_UNRESOLVED`. Capture failure is non-fatal unless
`--strict-capture` is set.

## 2. Check corpus readiness

```bash
python -m scripts.signal_arbitrage.advisory_runner \
  --check-corpus --capture-path data/calibration_corpus/decisions.jsonl
```

Reports totals (unresolved/resolved/eligible/synthetic), schema versions,
missing fields, first/latest dates, and a status:

```
NO_CORPUS_FOUND
CAPTURE_STARTED_NO_LABELS        (eligible < 10)
PROVISIONAL_DIAGNOSTIC_READY     (10 ≤ eligible < 30)
FIRST_PASS_CALIBRATION_READY     (30 ≤ eligible < 100)
STRONGER_CALIBRATION_READY       (eligible ≥ 100)
```

## 3. Resolve outcomes (weekly)

Default is a dry-run preview; pass `--capture-mode write` to apply. Original
feature snapshots are preserved — only the outcome group is updated and an audit
entry appended.

```bash
python -m scripts.signal_arbitrage.advisory_runner \
  --resolve-outcome \
  --decision-id <DECISION_ID> \
  --realized-return 0.12 \
  --resolved-at 2026-06-13 \
  --capture-mode write \
  --capture-path data/calibration_corpus/decisions.jsonl
```

Outcome derivation (never guessed):

```
engaged (routed) + positive return → WIN
engaged + negative return          → LOSS   (FALSE_POSITIVE if it was ACT_NOW)
avoided/blocked + negative return  → AVOIDED_TRAP
avoided/blocked + positive return  → MISSED_WINNER
unknown return                     → INCONCLUSIVE
```

Re-resolving an already-resolved decision to a different label is **rejected**
unless `--allow-conflict` is passed (the audit trail records every attempt).

## 4. Run calibration

```bash
python -m scripts.signal_arbitrage.advisory_runner \
  --run-calibration --capture-path data/calibration_corpus/decisions.jsonl
```

- Unresolved and `SYNTHETIC_FIXTURE` records are excluded.
- `N_eligible < 10` → `INSUFFICIENT_EVIDENCE` (no metrics, no fitting).
- `10 ≤ N < 30` → `PROVISIONAL_DIAGNOSTIC` (diagnostics only).
- `N ≥ 30` → `FIRST_PASS_CALIBRATION`. `N ≥ 100` → `STRONGER_CALIBRATION_READY`.

## The rule

> **Do not fit weights until at least 30 eligible real labelled records exist.**

---

## Mathematical guardrails (preserved in code)

```
RawMerit       = w1·NarrativeEmergence + w2·SemanticDensity + w3·Vitality
               + w4·TimingEdge + w5·RealityConfirmation + w6·Mispricing
InvestableScore = RawMerit × RealityPurity × (1−SyntheticContamination)
               × TransferGate × RecognitionGate
                 (invariant: InvestableScore ≤ RawMerit)

Corroboration         = max(0, N_distinct_ecologies − 1) / 3
CorroborationAdjusted = Corroboration × DirectionalAgreement × SourceIndependence

CapturedConfidence = min(FableConfidence, MythosConfidenceCap)
                       (invariant: CapturedConfidence ≤ MythosConfidenceCap)

CalibrationEligible = FeatureBearing
  ∧ OutcomeLabel ∈ {WIN, LOSS, AVOIDED_TRAP, FALSE_POSITIVE, FALSE_NEGATIVE, MISSED_WINNER}
  ∧ SourceType ≠ SYNTHETIC_FIXTURE
```

Same-source spam collapses to one ecology (no fake migration); social-only
breadth keeps `RealityPurity = 0` and can never become a Buy.

---

## Final next move (operational, not architectural)

```
1. Enable capture for paper/advisory runs.
2. Collect 30+ resolved eligible records (resolve outcomes weekly).
3. Run first-pass calibration.
4. Only then fit weights — under the invariants above.
```
