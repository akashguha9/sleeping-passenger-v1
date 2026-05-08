# Claude → Codex Hackathon Fix Plan — pipeline-v5.7-core

> Companion to `AUDIT_BRUTAL_MVP_ASSESSMENT.md`.
> Implementation contract for Codex. Do not soften. Do not embellish.
> This is not financial advice. This is not an execution product.
> This document does not grant decision-readiness to anything.

---

## 0. Current Reality Check

```text
Current overall score: 4.8 / 10
Current deployability: NO  (1.4 / 10)
Current decision-readiness: NO
Current showcase-readiness: PARTIAL (5.6–5.9 / 10)
Current scientific validity: 2.7 / 10  (no external falsification loop)
Current engineering validity: 4.1–5.0 / 10 (modular but sprawling, weak spine)
Main blocker: There is no canonical truth -> evidence -> validation -> veto -> action-permission -> decision spine. Many guards, many scores, many reports — none of them bind the final action recommendation in a typed, testable way.
Most dangerous illusion: Internal coherence (707 passing tests, deterministic seeded outputs, polished health summaries) is being treated as if it were external validity. It is not.
Fastest path to 6/10: Add typed contracts spine + canonical action-permission contract + honest health report (Patches 1, 4, 5).
Fastest path to 7/10: Add canonical evidence ledger + canonical decision ledger + position reconciliation states + calibration honesty layer (Patches 2, 3, 6, 8).
Fastest path to 8/10: Real replay-ready external truth interface + state machine hardening + integration tests against archived/labeled cases (Patches 7, 9, 10).
What must NOT be claimed yet:
  - "decision-ready"
  - "validated alpha"
  - "predictive"
  - "calibrated"
  - "deployable"
  - "live"
  - "investment-grade"
  - "tradeable"
```

Verified prerequisites (this run):

```text
python -m compileall scripts tests       -> exit 0
python -m pytest tests -q                 -> 707 passed in 9.10s
python scripts/pipeline_health_report.py --summary --no-write
    -> system_readiness_state=DO_NOT_DEPLOY
    -> can_deploy_capital=false
    -> policy_state=RESTRICTED
    -> position_integrity_state=DIVERGED
    -> truth_origin=seeded
    -> external_signal_count=0
    -> contextual_interpretation_enabled=false
    -> signal_surface_logic=DIABLO_CHAOS_SURFACE_VETO
    -> board_control_safety=GLOBAL_CLEARANCE_BLOCKED
    -> pre_execution_scan=UNKNOWN_PRE_EXECUTION_STATE
```

Codex: this is the baseline. You are not allowed to make the system look stronger. You are required to make it harder for the system to lie.

---

## 1. Audit-Derived Diagnosis

| Audit finding | Why it matters | Files implicated | Type | Severity /10 | Fix priority |
| ------------- | -------------- | ---------------- | ---- | -----------: | ------------ |
| No external truth spine; `truth_origin=seeded`, `external_signal_count=0` | Internal scores cannot be called validated without external truth | `scripts/pipeline_health_report.py`, `scripts/runtime_common.py`, `scripts/external_adapters/*`, `scripts/market_data_adapter.py` | TRUTH | 10 | P0 |
| No canonical action-decision spine | Many guards exist but `action_engine.py` does not consume most of them | `scripts/action_engine.py`, `scripts/run_diagnostics_pipeline.py`, `scripts/signal_surface_engine.py`, `scripts/board_control_safety_layer.py`, `scripts/pre_execution_scan_engine.py`, `scripts/extreme_state/*` | ARCHITECTURE | 10 | P0 |
| Seeded runtime treated as if it were meaningful evidence | Risk of false confidence and self-deception | `scripts/runtime_common.py`, `scripts/pipeline_health_report.py` | TRUTH | 9 | P0 |
| Validation is heuristic self-consistency, not outcome validation | "Validated" status without predictive power | `scripts/signal_refinery.py`, `scripts/signal_conversion_monitor.py` | VALIDATION | 9 | P0 |
| Position divergence is reported but not reconciled | DIVERGED is surfaced but downstream action does not bind on it | `scripts/position_truth_resolver.py`, `scripts/paper_reconciliation.py`, `scripts/position_conflict_detector.py` | POSITION_TRUTH | 9 | P0 |
| Veto/chaos/board/pre-exec/policy not consolidated into one action-permission contract | Guards become advisory captions, not binding control | `scripts/signal_surface_engine.py`, `scripts/board_control_safety_layer.py`, `scripts/pre_execution_scan_engine.py`, `scripts/extreme_state_logic.py`, `scripts/action_engine.py` | RISK | 9 | P0 |
| Paper trading not market-realistic (default fill `100.0`) | Artificially flattering execution / PnL | `scripts/paper_execution.py`, `scripts/paper_reconciliation.py`, `scripts/paper_trade_retirement.py`, `scripts/yahoo_market_data_adapter.py` | PAPER_TRADING | 8 | P1 |
| State machine fragmented across modules (MIURA/HURACAN/DIABLO/etc. have different triggers per file) | Cross-module state ambiguity | `scripts/signal_surface_engine.py`, `scripts/contextual_interpretation_engine.py`, `scripts/extreme_state/*`, `scripts/pre_execution_scan_engine.py`, `scripts/board_control_safety_layer.py` | STATE_MACHINE | 8 | P1 |
| Scoring thresholds without empirical backing | Arbitrary cutoffs masquerade as calibration | `config/thresholds.yaml`, `scripts/signal_refinery.py`, `scripts/structural_design_engine.py`, `scripts/extreme_state_logic.py` | VALIDATION | 8 | P1 |
| `pipeline_health_report.py` is 4996 lines, surfaces many states, hides causal winner | Too much summary breadth weakens interpretability | `scripts/pipeline_health_report.py` | REPORTING | 7 | P1 |
| Contextual interpretation disabled but reports do not always downgrade confidence | Hidden uncertainty in summaries | `scripts/contextual_interpretation_engine.py`, `scripts/contextual_interpretation/*`, `scripts/pipeline_health_report.py` | REPORTING | 7 | P1 |
| 192 Python scripts, 29 separate `clamp01` defs, vendored `tribev2` | Maintenance and naming sprawl | `scripts/*` | ARCHITECTURE | 6 | P2 |
| README has encoding issues / overstates plumbing relative to truth | Showcase risk and audit risk | `README.md` | DOCS | 6 | P2 |
| Tests are deterministic snapshot heavy, weak on adversarial / replay invariants | Old tests can pass while system is unsafe | `tests/*` | TESTING | 7 | P1 |
| External evidence routing exists but is not wired to canonical decisions | Architecture overstates operational reality | `scripts/core/external_evidence_router.py`, `scripts/external_adapters/*` | TRUTH | 7 | P1 |
| Public-facing repo could read as overbuilt theater | Investor / employer credibility risk | `README.md`, `docs/*` | PRODUCT | 6 | P2 |
| Filesystem hygiene: leftover `tests/_tmp_runtime`, generated fixture debris | CI cleanliness | `tests/_tmp_runtime/*`, `tests/.pytest_tmp/*` | CONFIG | 4 | P3 |
| No outcome labels, false-positive accounting, or naive benchmarks | Refusal can look safe while still being useless | repo-wide | VALIDATION | 9 | P0 |

---

## 2. Hackathon Objective

```text
Turn the MVP from a metaphor-rich diagnostic prototype into a structurally honest research MVP with:
1. one evidence ledger,
2. one decision ledger,
3. one action-permission contract,
4. explicit truth-origin handling,
5. hard no-capital boundaries,
6. stronger state-machine contracts,
7. position reconciliation states,
8. calibration placeholders that refuse false precision,
9. replay-ready data interfaces,
10. tests that prevent fake confidence.
```

What "fixed" means for this hackathon:

```text
Fixed does not mean profitable.
Fixed does not mean deployable.
Fixed does not mean externally validated.
Fixed means the system can no longer pretend seeded/internal signals are external truth, can no longer bypass vetoes, can no longer report decision-readiness without reconciliation, and can no longer hide uncertainty behind pretty reports.
```

What this hackathon explicitly does NOT do:

- Does not introduce live market data.
- Does not introduce live execution.
- Does not introduce real calibration curves.
- Does not introduce broker reconciliation.
- Does not promote any score from heuristic to predictive.
- Does not unlock capital deployment.

---

## 3. Non-Negotiable Design Doctrine

Codex must enforce, in code and in tests:

```text
Policy veto > External truth absence > Position divergence > Chaos veto > Risk guards > Validation gates > Contextual interpretation > Signal strength > Report aesthetics
```

Hard rules:

```text
No external truth        => no decision-ready claim.
Seeded data              => demo/simulation only; never counts as external truth.
Position divergence      => block capital permission, period.
Contextual interpretation disabled => downgrade report confidence in every summary that consumes it.
Chaos veto               => quarantine unless explicitly overridden by policy-approved test/demo mode.
Any score without calibration must be labeled UNCALIBRATED_HEURISTIC.
Any threshold without empirical backing must be labeled ARBITRARY_THRESHOLD.
Reports must expose uncertainty before they expose confidence.
A guard that does not change downstream action is not a guard. It is a caption. Captions are forbidden.
```

A test must fail if any of the following are observable in any code path produced by this hackathon:

- Seeded/demo evidence increments `external_signal_count`.
- A "decision-ready" or "deployable" claim is emitted while `truth_origin in {SEED, DEMO}` or `external_signal_count == 0`.
- An action permission allows capital while `position_integrity_state in {DIVERGED, UNKNOWN, MISSING_SOURCE, STALE_SOURCE, QUANTITY_MISMATCH, PRICE_MISMATCH}`.
- A health summary fails to surface an active chaos / policy / position veto as a `veto_reason` in the canonical action permission.

---

## 4. Target Architecture After Fixes

```text
Data / Demo / Replay Inputs
    ↓
Truth Origin Classifier
    ↓
Evidence Ledger
    ↓
Signal Normalization Layer
    ↓
Contextual Interpretation Layer
    ↓
Validation + Durability Layer
    ↓
State Machine / Archetype Classifier
    ↓
Risk + Chaos + Policy Veto Layer
    ↓
Position Truth + Reconciliation Layer
    ↓
Action Permission Contract
    ↓
Decision Ledger
    ↓
Health Report / CLI / Audit Output
```

Layer specs:

### 4.1 Truth Origin Classifier
- Purpose: classify every evidence record as SEED / DEMO / REPLAY / LIVE_EXTERNAL / MANUAL / UNKNOWN.
- Likely files: new `scripts/truth_origin.py` or extension to `scripts/runtime_common.py:build_truth_context`.
- Required dataclasses/enums: `TruthOrigin`.
- Tests: seeded inputs never escalate to LIVE_EXTERNAL; UNKNOWN never silently becomes LIVE_EXTERNAL.
- Failure if missing: external truth illusion, current state.

### 4.2 Evidence Ledger
- Purpose: single typed sink for all signal/evidence inputs with origin and confidence.
- Likely files: new `scripts/evidence_ledger.py`.
- Required: `EvidenceItem`, `EvidenceLedger`, `EvidenceSummary`.
- Tests: counts by origin; rejection of unsourced LIVE_EXTERNAL; deterministic summary.
- Failure if missing: no shared truth view.

### 4.3 Signal Normalization Layer
- Purpose: convert ledger evidence into the existing per-signal row shape used by `runtime_common.normalize_per_signal_rows`.
- Likely files: `scripts/signal_refinery.py`, `scripts/runtime_common.py`.
- Required: pass-through that preserves `truth_origin` per row.
- Tests: round-trip preserves origin, never upgrades it.
- Failure if missing: origin laundering.

### 4.4 Contextual Interpretation Layer
- Purpose: existing `contextual_interpretation_engine.py`, but downstream consumers must read its `enabled` flag and downgrade confidence when false.
- Likely files: `scripts/contextual_interpretation_engine.py`, `scripts/pipeline_health_report.py`.
- Tests: when disabled, summary explicitly carries `confidence_downgraded=true`.
- Failure if missing: hidden uncertainty.

### 4.5 Validation + Durability Layer
- Purpose: apply existing durability/validation logic but tag each record with `ValidationStatus`.
- Likely files: `scripts/signal_refinery.py`, new `scripts/calibration_status.py`.
- Required: explicit `UNVALIDATED` default; no `CALIBRATED` without sample metadata.
- Tests: missing samples => not CALIBRATED.
- Failure if missing: validation theatre.

### 4.6 State Machine / Archetype Classifier
- Purpose: one ontology of MIURA/MURCIELAGO/AVENTADOR/GALLARDO/ISLERO/DIABLO/HURACAN/COLLAPSE/JAIL/PROBE/CONFIRM/DEPLOY/CHAOS/VETO with an explicit forbidden-transition matrix.
- Likely files: new `scripts/state_machine_contracts.py`; consumed by `scripts/signal_surface_engine.py`, `scripts/board_control_safety_layer.py`, `scripts/pre_execution_scan_engine.py`, `scripts/extreme_state_logic.py`, `scripts/contextual_interpretation_engine.py`.
- Tests: forbidden transitions raise; DIABLO blocks capital; DEPLOY requires reconciliation + truth.
- Failure if missing: cross-module ambiguity.

### 4.7 Risk + Chaos + Policy Veto Layer
- Purpose: typed `VetoReason` set, fed to one resolver.
- Likely files: existing veto modules; new `scripts/action_permission.py`.
- Failure if missing: advisory theater.

### 4.8 Position Truth + Reconciliation Layer
- Purpose: extend `scripts/position_truth_resolver.py` with reconciliation states.
- Likely files: `scripts/position_truth_resolver.py`, `scripts/paper_reconciliation.py`.
- Tests: UNKNOWN != CLEAN; DIVERGED forces capital block.
- Failure if missing: misstated exposure.

### 4.9 Action Permission Contract
- Purpose: single function `resolve_action_permission(...)` consumed by `action_engine.py` and `pipeline_health_report.py`.
- Likely files: new `scripts/action_permission.py`.
- Failure if missing: scattered guards = none.

### 4.10 Decision Ledger
- Purpose: append-only record of final decisions with veto chain and evidence snapshot id.
- Likely files: new `scripts/decision_ledger.py`. JSONL artifact under `runtime/`.
- Failure if missing: unauditable decisions.

### 4.11 Health Report / CLI / Audit Output
- Purpose: brutally honest summary surfacing canonical permission and veto chain first.
- Likely files: `scripts/pipeline_health_report.py`.
- Failure if missing: pretty reports, missing truth.

---

## 5. Patch Sequence for Codex

Implement patches in order. Stop after each major patch if the suite or health summary breaks.

---

### Patch 1 — Create canonical contracts spine

**Objective**: introduce typed enums and dataclasses that every later patch will consume.

**Files to inspect first**:
- `scripts/runtime_common.py` (truth context, source mode, deployment permissions)
- `scripts/action_engine.py`
- `scripts/position_truth_resolver.py`

**Files likely to edit**: none yet (additive).

**New files**:
```text
scripts/runtime_contracts.py
tests/test_runtime_contracts.py
```

**Implementation instructions**:

Create `scripts/runtime_contracts.py` with:

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

class TruthOrigin(str, Enum):
    SEED = "SEED"
    DEMO = "DEMO"
    REPLAY = "REPLAY"
    LIVE_EXTERNAL = "LIVE_EXTERNAL"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"

class SystemMode(str, Enum):
    DEMO = "DEMO"
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE_BLOCKED = "LIVE_BLOCKED"

class ValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    INTERNALLY_CONSISTENT = "INTERNALLY_CONSISTENT"
    EXTERNALLY_CHECKED = "EXTERNALLY_CHECKED"
    CALIBRATED = "CALIBRATED"
    FAILED = "FAILED"

class PositionIntegrityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CLEAN = "CLEAN"
    WARNING = "WARNING"
    DIVERGED = "DIVERGED"
    RECONCILED = "RECONCILED"

class PolicyState(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"

class ActionPermission(str, Enum):
    ALLOW_DEMO_ONLY = "ALLOW_DEMO_ONLY"
    ALLOW_RESEARCH_ONLY = "ALLOW_RESEARCH_ONLY"
    ALLOW_PAPER_ONLY = "ALLOW_PAPER_ONLY"
    BLOCK_CAPITAL = "BLOCK_CAPITAL"
    BLOCK_ALL = "BLOCK_ALL"

class VetoReason(str, Enum):
    NO_EXTERNAL_TRUTH = "NO_EXTERNAL_TRUTH"
    POSITION_DIVERGED = "POSITION_DIVERGED"
    CHAOS_VETO = "CHAOS_VETO"
    POLICY_RESTRICTED = "POLICY_RESTRICTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CALIBRATION_MISSING = "CALIBRATION_MISSING"
    CONTEXTUAL_INTERPRETATION_DISABLED = "CONTEXTUAL_INTERPRETATION_DISABLED"
    UNKNOWN_STATE = "UNKNOWN_STATE"

@dataclass(frozen=True)
class EvidenceItem:
    source: str
    origin: TruthOrigin
    timestamp: str
    confidence: float
    validation: ValidationStatus
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["origin"] = self.origin.value
        d["validation"] = self.validation.value
        return d

@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    evidence_snapshot_id: str
    system_mode: SystemMode
    action_permission: ActionPermission
    veto_reasons: tuple[VetoReason, ...]
    position_integrity_state: PositionIntegrityState
    policy_state: PolicyState
    explanation: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "system_mode": self.system_mode.value,
            "action_permission": self.action_permission.value,
            "veto_reasons": [v.value for v in self.veto_reasons],
            "position_integrity_state": self.position_integrity_state.value,
            "policy_state": self.policy_state.value,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }
```

**Tests** (`tests/test_runtime_contracts.py`):
- Every enum exposes the required values listed above.
- `EvidenceItem.to_dict` and `DecisionRecord.to_dict` round-trip via `json.dumps`/`json.loads`.
- `TruthOrigin.SEED.value == "SEED"`, etc. (catch typos).

**Acceptance**:
- `python -m compileall scripts tests` exit 0.
- `python -m pytest tests -q` -> 707 + new tests, all passing.
- No existing module imports from this file yet.

**Do not break**: any existing import path or string used in JSON artifacts.

---

### Patch 2 — Build canonical evidence ledger

**Objective**: one typed evidence sink with explicit origin counts.

**Files to inspect first**:
- `scripts/runtime_common.py:build_truth_context`, `_external_observation_state`
- `scripts/external_data_runtime_sync.py`
- `scripts/external_observation_lane.py`
- `scripts/core/external_evidence_router.py`

**New files**:
```text
scripts/evidence_ledger.py
tests/test_evidence_ledger.py
```

**Implementation**:

`EvidenceLedger` must:
- Append `EvidenceItem` records.
- Compute `summary()` returning a dict with `counts_by_origin`, `external_signal_count`, `seeded_signal_count`, `validation_breakdown`, `latest_timestamp`, `has_external_truth`.
- Reject `LIVE_EXTERNAL` without a non-empty `source` and `timestamp` (raise `ValueError` or downgrade to `UNKNOWN` with explicit reason — pick one and document).
- `external_signal_count` must count only `LIVE_EXTERNAL`, plus `REPLAY` records whose payload contains an `outcome_label` field. Nothing else.
- `seeded_signal_count` includes `SEED` and `DEMO`.

**Tests**:
- Seeded evidence does not increment `external_signal_count`.
- Demo evidence does not increment `external_signal_count`.
- Replay evidence without `outcome_label` does not count as externally checked.
- Replay evidence with `outcome_label` does count.
- `LIVE_EXTERNAL` without source raises or downgrades and is recorded as such.
- `summary()` is deterministic across two equal call sequences.

**Acceptance**:
- Optional: `pipeline_health_report.py` reads `EvidenceLedger.summary()` if available. If still wired only via the existing truth context, document that the ledger is consumed in Patch 5.

**Do not break**: existing `truth_origin=seeded` behavior or `external_signal_count=0` semantics.

---

### Patch 3 — Build canonical decision ledger

**Objective**: append-only typed log of every final decision.

**Files to inspect first**:
- `scripts/action_engine.py`
- `scripts/runtime_common.py:append_jsonl`, `write_runtime_artifact`
- `scripts/operator_override_ledger.py` (existing append-only pattern)

**New files**:
```text
scripts/decision_ledger.py
tests/test_decision_ledger.py
```

**Implementation**:
- `DecisionLedger.record(record: DecisionRecord) -> None`
- Default JSONL path under `runtime/decision_ledger.jsonl`. Tests use an in-memory mode (pass `path=None`).
- `record()` must hash the evidence snapshot id and refuse to record if missing.
- `summary()` returns the latest record + counts by `action_permission` and `veto_reasons`.

**Hard rules**:
- No final report may emit `decision_ready=true` without a `DecisionRecord` whose `action_permission` is `ALLOW_PAPER_ONLY` and whose `veto_reasons` is empty AND `position_integrity_state == RECONCILED` AND `truth_origin` per evidence snapshot is `LIVE_EXTERNAL` or `REPLAY` with outcome labels. (This combination is currently impossible. Good.)
- Every `BLOCK_CAPITAL` record must populate `veto_reasons`. Empty `veto_reasons` with `BLOCK_CAPITAL` is a contract violation.

**Tests**:
- `DecisionRecord` serializes/deserializes round-trip.
- `BLOCK_CAPITAL` with empty `veto_reasons` raises.
- Missing evidence snapshot id raises.
- Seeded truth origin produces `ALLOW_DEMO_ONLY` or `ALLOW_RESEARCH_ONLY`, never `ALLOW_PAPER_ONLY`.
- Position divergence forces `BLOCK_CAPITAL`.

---

### Patch 4 — Consolidate action permission contract

**Objective**: one resolver that consumes every veto source and produces one typed permission.

**Files to inspect first**:
- `scripts/action_engine.py`
- `scripts/execution_governance.py`
- `scripts/signal_surface_engine.py`
- `scripts/pre_execution_scan_engine.py`
- `scripts/board_control_safety_layer.py`
- `scripts/extreme_state_logic.py`
- `scripts/position_truth_resolver.py`

**New files**:
```text
scripts/action_permission.py
tests/test_action_permission_contract.py
```

**Implementation**:

```python
def resolve_action_permission(
    *,
    evidence_summary: dict,        # from EvidenceLedger.summary()
    policy_state: PolicyState,
    chaos_veto_active: bool,
    chaos_severity: str,           # "NONE" | "SOFT" | "HARD"
    validation_status: ValidationStatus,
    position_integrity_state: PositionIntegrityState,
    contextual_interpretation_enabled: bool,
    calibration_state: str,        # "CALIBRATED" | "UNCALIBRATED_HEURISTIC" | "INSUFFICIENT_SAMPLES"
    system_mode: SystemMode,
) -> dict:
    ...
```

Returned dict (typed contract):

```python
{
  "action_permission": ActionPermission,
  "veto_reasons": list[VetoReason],
  "warnings": list[str],
  "explanation": str,
  "allowed_use": list[str],   # e.g. ["demo", "research_diagnostics"]
  "forbidden_use": list[str], # e.g. ["capital_deployment", "investment_advice", "automated_execution"]
}
```

Resolution rules (must be implemented exactly):

```text
if evidence_summary["has_external_truth"] is False or evidence_summary["external_signal_count"] == 0:
    add VetoReason.NO_EXTERNAL_TRUTH
    permission = ALLOW_DEMO_ONLY if system_mode == DEMO else ALLOW_RESEARCH_ONLY

if position_integrity_state in {DIVERGED, UNKNOWN}:
    add VetoReason.POSITION_DIVERGED
    permission = downgrade_to(BLOCK_CAPITAL)

if chaos_veto_active:
    add VetoReason.CHAOS_VETO
    if chaos_severity == "HARD":
        permission = BLOCK_ALL
    else:
        permission = downgrade_to(BLOCK_CAPITAL)

if policy_state == PolicyState.RESTRICTED:
    add VetoReason.POLICY_RESTRICTED
    permission = downgrade_to(BLOCK_CAPITAL)
if policy_state == PolicyState.BLOCKED:
    permission = BLOCK_ALL

if validation_status in {UNVALIDATED, FAILED}:
    add VetoReason.VALIDATION_FAILED
    permission = downgrade_to(BLOCK_CAPITAL)

if calibration_state != "CALIBRATED":
    add VetoReason.CALIBRATION_MISSING
    # does not block demo/research, but blocks any decision-ready claim

if contextual_interpretation_enabled is False:
    add VetoReason.CONTEXTUAL_INTERPRETATION_DISABLED
    # warning only; downgrades confidence in summaries
```

Where `downgrade_to` keeps the strictest of the current and new permission (BLOCK_ALL > BLOCK_CAPITAL > ALLOW_PAPER_ONLY > ALLOW_RESEARCH_ONLY > ALLOW_DEMO_ONLY).

**Tests**:
- No external truth -> `NO_EXTERNAL_TRUTH` + permission != `ALLOW_PAPER_ONLY`.
- Position diverged -> `POSITION_DIVERGED` + `BLOCK_CAPITAL` or stricter.
- Chaos HARD -> `BLOCK_ALL`.
- Multiple vetoes preserve all reasons (none swallowed).
- Identical inputs produce identical outputs (deterministic).
- `forbidden_use` always includes `"capital_deployment"` and `"investment_advice"` while truth is seeded.

**Acceptance**:
- `pipeline_health_report.py` consumes `resolve_action_permission` and surfaces `canonical_action_permission`.
- Existing tests still pass.
- No scattered readiness flag (`can_deploy_capital`, `policy_state`, `position_integrity_state`) contradicts canonical permission.

---

### Patch 5 — Make health report brutally honest

**Files to edit**: `scripts/pipeline_health_report.py`.

**Required additions to summary** (key=value lines, deterministic order):

```text
canonical_action_permission=...
veto_reasons=[...]
truth_origin_breakdown=seed=N,demo=N,replay=N,live_external=N
evidence_ledger_status=ok|degraded
decision_ledger_status=ok|empty|degraded
calibration_status=UNCALIBRATED_HEURISTIC|INSUFFICIENT_SAMPLES|CALIBRATED
external_truth_status=ABSENT|REPLAY_ONLY|LIVE
allowed_use=[...]
forbidden_use=[...]
```

Mandatory invariants:
- `system_readiness_state=DO_NOT_DEPLOY` while any veto reason is present.
- `can_deploy_capital=false` while `action_permission != ALLOW_PAPER_ONLY`.
- `forbidden_use` always contains `capital_deployment`, `investment_advice`, `automated_execution` until the impossible-for-this-hackathon decision-ready combination holds.
- If `contextual_interpretation_enabled=false`, summary must include a top-of-output line `confidence_downgraded=true`.

**Tests** (`tests/test_health_report_honesty.py`):
- Summary in seeded mode contains explicit `forbidden_use=...capital_deployment...`.
- `external_signal_count=0` => summary contains `NO_EXTERNAL_TRUTH` in `veto_reasons`.
- `position_integrity_state=DIVERGED` => `POSITION_DIVERGED` in `veto_reasons`.
- `--summary --no-write` is stable: two consecutive runs produce identical bytes (modulo timestamp lines that must be excluded from the equality assertion).

**Do not break**:
- `python scripts/pipeline_health_report.py --summary --no-write` must keep working.
- Existing keys consumed by other modules (search for `system_readiness_state`, `can_deploy_capital`, `policy_state`, `position_integrity_state` across the repo) must still appear.

---

### Patch 6 — Position truth reconciliation states

**Files to inspect first**:
- `scripts/position_truth_resolver.py`
- `scripts/paper_reconciliation.py`
- `scripts/position_conflict_detector.py`
- `scripts/temporal_position_engine.py`

**Files likely to edit**:
- `scripts/position_truth_resolver.py` (extend, do not replace)
- `scripts/runtime_contracts.py` (already defines enum)

**Required states**:

```text
UNKNOWN
MATCHED
MISSING_SOURCE
STALE_SOURCE
QUANTITY_MISMATCH
PRICE_MISMATCH
DIVERGED
RECONCILED
```

**Required behavior**:
- `DIVERGED`, `UNKNOWN`, `MISSING_SOURCE`, `STALE_SOURCE`, `QUANTITY_MISMATCH`, `PRICE_MISMATCH` => `BLOCK_CAPITAL` via the action permission contract.
- `MATCHED` allows progression only if `truth_origin in {LIVE_EXTERNAL, REPLAY+labels}`.
- `RECONCILED` requires explicit `reconciliation_evidence: list[EvidenceItem]` with at least one `LIVE_EXTERNAL` or labeled `REPLAY` record.

Add output fields:
- `position_reconciliation_status`
- `position_divergence_reason`
- `position_resolution_recommendation`
- `position_capital_permission_impact`

**Tests** (`tests/test_position_reconciliation_contract.py`):
- UNKNOWN never passes as CLEAN.
- DIVERGED forces capital block.
- STALE_SOURCE creates warning + capital block.
- MATCHED + seeded truth -> still capital block via `NO_EXTERNAL_TRUTH`.
- RECONCILED without `reconciliation_evidence` raises.

---

### Patch 7 — State machine hardening

**Files to inspect first**:
- `scripts/signal_surface_engine.py`
- `scripts/board_control_safety_layer.py`
- `scripts/pre_execution_scan_engine.py`
- `scripts/extreme_state_logic.py`
- `scripts/contextual_interpretation_engine.py`
- `scripts/archetype_registry.py`
- `scripts/state_classifier.py`

**New files**:
```text
scripts/state_machine_contracts.py
tests/test_state_machine_contracts.py
```

**Required**:
- One `Archetype` enum: MIURA, MURCIELAGO, AVENTADOR, GALLARDO, ISLERO, DIABLO, HURACAN, COLLAPSE, JAIL, PROBE, CONFIRM, DEPLOY, CHAOS, VETO.
- One `Transition` dataclass: `from_state`, `to_state`, `reason`, `confidence`, `reversible`, `timestamp`.
- `forbidden_transitions: frozenset[tuple[Archetype, Archetype]]` covering at minimum:
  - MIURA -> GALLARDO without CONFIRM.
  - MIURA -> DEPLOY without CONFIRM and PROBE.
  - DIABLO -> DEPLOY (always forbidden).
  - JAIL -> DEPLOY (always forbidden).
  - HURACAN -> DEPLOY without CONFIRM (validation floor).
  - ISLERO must reroute through PROBE (force reclassification).
- `validate_transition(prev, next, evidence)` returns `(ok: bool, reason: str)` and `apply_transition(...)` records to a `transition_log` artifact.

**Required runtime semantics**:
- `DIABLO` must always raise a `CHAOS_VETO` `VetoReason`.
- `JAIL` must block new-risk deployment.
- `DEPLOY` must require `truth_origin in {LIVE_EXTERNAL, REPLAY+labels}` AND `position_integrity_state == RECONCILED` AND no active veto.

**Tests**:
- Forbidden transitions fail with explicit reason.
- DIABLO -> CHAOS_VETO is enforced in `resolve_action_permission`.
- HURACAN without CONFIRM cannot fast-track.
- ISLERO forces reclassification.
- Transition log entries serialize.
- A transition without `reason` is rejected.

**Do not break**:
- Existing string state labels emitted in JSON artifacts. Map enum -> string to keep snapshots stable.

---

### Patch 8 — Calibration honesty layer

**Files to inspect first**:
- `scripts/signal_refinery.py`
- `scripts/structural_design_engine.py`
- `scripts/extreme_state_logic.py`
- `scripts/composite_edge_score.py`
- `config/thresholds.yaml`

**New files**:
```text
scripts/calibration_status.py
tests/test_calibration_status.py
```

**Implementation**:
- `CalibrationStatus` strings: `CALIBRATED`, `UNCALIBRATED_HEURISTIC`, `INSUFFICIENT_SAMPLES`, `DEMO_ONLY`, `REQUIRES_EXTERNAL_LABELS`.
- `tag_score(name, value, *, sample_count, has_outcome_labels) -> dict`:
  - Without labels => `UNCALIBRATED_HEURISTIC` (or `REQUIRES_EXTERNAL_LABELS` if labels are explicitly required).
  - sample_count < N (configurable, default 30) => `INSUFFICIENT_SAMPLES`.
  - SEED/DEMO origin => `DEMO_ONLY`.
- `tag_threshold(name, value, *, provenance: str | None)` => `ARBITRARY_THRESHOLD` if `provenance is None or empty`.

**Required usage**:
- Health report shows calibration status next to each headline score (`structural_design_pressure_score`, `composite_edge_score`, `truth_metrics.candidate_survival_rate`, etc.).
- No `CALIBRATED` status anywhere in this hackathon's output. If you see `CALIBRATED`, that is a bug.

**Tests**:
- Missing labels => `UNCALIBRATED_HEURISTIC`.
- Threshold without provenance => `ARBITRARY_THRESHOLD`.
- Sample-count gating works.
- Demo/seed evidence => `DEMO_ONLY`.

---

### Patch 9 — Replay-ready external truth interface

**Files to inspect first**:
- `scripts/external_adapters/*`
- `scripts/external_data_runtime_sync.py`
- `scripts/external_observation_lane.py`
- `scripts/core/external_evidence_router.py`
- `scripts/market_data_adapter.py`

**New files**:
```text
scripts/truth_sources.py
tests/test_truth_sources.py
```

**Required**:

```python
class TruthSource(Protocol):
    name: str
    origin: TruthOrigin
    def fetch(self, *, since: str | None = None) -> list[TruthRecord]: ...

class TruthRecord:
    source: str
    origin: TruthOrigin
    timestamp: str
    payload: dict
    outcome_label: OutcomeLabel | None

class OutcomeLabel:
    label: str            # e.g. "RESOLVED_YES" / "RESOLVED_NO" / "UNRESOLVED"
    resolved_at: str
    resolution_source: str

class SeedTruthSource(TruthSource):  # origin=SEED, never produces outcome_label
class ReplayTruthSource(TruthSource): # origin=REPLAY, requires timestamps, may carry outcome_label
class ExternalTruthSourceStub(TruthSource): # origin=UNKNOWN, fetch() returns [] and a warning "NOT_CONFIGURED"
```

**Hard rules**:
- `SeedTruthSource` may never emit a non-None `outcome_label`.
- `ReplayTruthSource` without labels can be stored but cannot be counted as externally checked.
- `ExternalTruthSourceStub` must always declare `NOT_CONFIGURED` and never invent records.

**Tests**:
- Seed source classified as SEED.
- Replay source without labels cannot validate outcomes.
- Replay source with labels can produce externally checkable records.
- External stub returns empty + `NOT_CONFIGURED` flag.

---

### Patch 10 — Testing upgrade without weakening old tests

**Required new test files** (some may already be created above):

```text
tests/test_runtime_contracts.py
tests/test_evidence_ledger.py
tests/test_decision_ledger.py
tests/test_action_permission_contract.py
tests/test_position_reconciliation_contract.py
tests/test_state_machine_contracts.py
tests/test_calibration_status.py
tests/test_truth_sources.py
tests/test_health_report_honesty.py
```

**Test categories that must be added**:
- Seeded/demo truth honesty (no laundering of origin).
- No-external-truth blocking via canonical permission.
- Position divergence blocking.
- Chaos veto blocking.
- Calibration missing => warning or block depending on mode.
- Forbidden state transitions.
- Decision ledger serialization (JSONL round-trip).
- Evidence ledger summary determinism.
- Health summary consistency: action permission ↔ veto reasons ↔ readiness.
- No contradiction tests: if `veto_reasons` is non-empty, `system_readiness_state == DO_NOT_DEPLOY` and `can_deploy_capital == false`.

**Hard rules for test code**:
- Do not weaken existing assertions.
- Do not add `pytest.skip` to make a previously failing test pass.
- Do not snapshot pretty strings as the only assertion. Test behavior and contracts.

**Acceptance**:
- All 707 prior tests still pass.
- New tests pass.
- `pytest -q` shows >= 707 + N (where N = new tests).

---

### Patch 11 — Documentation honesty upgrade

**Files to edit**: `README.md` (preserve existing wording where it is already careful).

**Required additions** (top of README, before any feature list):

```text
> Status: research / demo MVP. NOT financial advice. NOT deployable.
> Truth origin: seeded. External signal count: 0.
> Capital deployment: blocked by canonical action permission contract.
> Decision-readiness: NOT CLAIMED.
```

**Required new section: "How to read the health report"**:
- Explain `canonical_action_permission`, `veto_reasons`, `truth_origin_breakdown`, `calibration_status`, `external_truth_status`, `allowed_use`, `forbidden_use`.
- Explain why "DO_NOT_DEPLOY" is the correct state and what would have to change for it to move.

**Required new section: "What is real vs not real"**:
- Real: typed contracts spine, action permission contract, deterministic diagnostics, paper-only refusal posture.
- Not real: live market data, broker reconciliation, calibrated probabilities, validated alpha, predictive scoring.

**Forbidden language**:
- "decision-ready", "validated alpha", "production-ready", "deployable", "tradeable", "predictive", "calibrated" — unless backed by data this hackathon does not produce.

**Acceptance**:
- A first-time GitHub visitor cannot mistake this for an investment product after reading the first 30 lines of README.
- Audit and fix plan are linked at the bottom.

---

## 6. Codex Execution Prompt

Paste the block below into Codex after Claude finishes:

```text
Read CLAUDE_CODEX_HACKATHON_FIX_PLAN.md from the repo root. Implement Patches 1 through 11 in order. Do not skip patches. Do not reorder. Do not silently weaken any existing test. After each major patch, run:

    python -m compileall scripts tests
    python -m pytest tests -q
    python scripts/pipeline_health_report.py --summary --no-write

If any of the three commands fail, STOP. Print the failing command, the exact error, your hypothesis for the cause, and the file/line you intend to change. Do not proceed to the next patch until the previous patch is green.

Hard rules during implementation:
1. Preserve all 707 existing tests as passing.
2. Do not invent live external data. Do not invent calibration. Do not invent broker reconciliation.
3. Do not introduce any new claim of "decision-ready", "validated alpha", "production-ready", "deployable", "tradeable", "predictive", or "calibrated".
4. Seeded/demo evidence must never increment external_signal_count.
5. Position divergence must always block capital permission.
6. Every BLOCK_CAPITAL emitted must carry at least one VetoReason.
7. The health report must keep system_readiness_state=DO_NOT_DEPLOY while any veto reason is present.
8. Update README.md per Patch 11 — honestly.

When all 11 patches pass, produce a final implementation summary with:
- patches completed
- new files created
- files modified
- new tests added (count)
- pytest summary line
- the full output of `python scripts/pipeline_health_report.py --summary --no-write`
- any patch you could not finish, and why

Then commit and push:

    git status
    git add .
    git commit -m "feat: add canonical truth decision and action permission spine"
    git push origin "$(git branch --show-current)"

PowerShell fallback if needed:

    git push origin $(git branch --show-current)

Do not open a pull request unless explicitly asked.
```

---

## 7. Segmented Target Scores After Hackathon

Targets are realistic, not fantasy. External truth, calibration, and broker reconciliation are out of scope for this hackathon, so deployability stays low.

| Segment | Current score | After Patch target | 30-day target | Notes |
| ------- | ------------: | -----------------: | ------------: | ----- |
| Core architecture | 5.0 | 6.5 | 7.5 | Spine + action contract + decision ledger |
| Evidence/truth spine | 2.5 | 6.0 | 7.5 | Patches 2, 9 |
| Decision spine | 2.5 | 6.5 | 7.5 | Patches 3, 4 |
| External truth honesty | 2.0 | 6.0 | 7.0 | Honesty up; live data still absent |
| Data ingestion readiness | 4.2 | 5.0 | 6.5 | Patch 9 stub + replay scaffolding |
| Validation quality | 4.0 | 5.0 | 6.5 | Heuristic still, but tagged |
| Calibration honesty | 2.8 | 5.5 | 6.5 | Patch 8 — labels, no fakes |
| State machine clarity | 4.8 | 6.5 | 7.5 | Patch 7 |
| Archetype operational value | 4.2 | 5.5 | 6.5 | Linked to permission, not metaphor |
| Risk/veto enforcement | 5.7 | 7.0 | 7.5 | Patch 4 |
| Position truth/reconciliation | 3.4 | 6.0 | 7.0 | Patch 6 |
| Paper-trading realism | 3.0 | 3.5 | 5.0 | Out of scope this hackathon |
| Health report honesty | 6.0 | 7.5 | 8.0 | Patch 5 |
| Test quality | 5.8 | 7.0 | 7.5 | Patch 10 |
| Documentation quality | 6.2 | 7.0 | 7.5 | Patch 11 |
| Scientific validity | 2.7 | 3.5 | 5.0 | Honest, not validated |
| Showcase credibility | 5.9 | 7.0 | 7.5 | Less theater, more honesty |
| Decision-readiness | 0.0 | 0.0 | 0.0 | Explicitly not claimed |
| Deployability | 1.4 | 1.6 | 2.5 | Stays low intentionally |
| Overall MVP | 4.8 | 5.8–6.4 | 6.8–7.2 | Realistic |

---

## 8. Definition of Done

```text
1. All old tests pass.
2. New safety/contract tests pass.
3. Health report exposes canonical action permission.
4. Seeded/demo truth cannot be counted as external truth.
5. Position divergence blocks capital permission.
6. Chaos/policy vetoes flow into one action permission contract.
7. Decision ledger records final decision state.
8. Evidence ledger records truth-origin counts.
9. Calibration status is visible for important scores.
10. README/docs explain limitations honestly.
11. No report claims decision-readiness without truth, calibration, and reconciliation.
12. `python scripts/pipeline_health_report.py --summary --no-write` gives a coherent, non-contradictory output.
```

---

## 9. Red-Team Checks Codex Must Run Mentally

Codex must answer each of the following after implementation. Acceptable answers: `fixed`, `partially fixed`, or `not fixed and documented`.

1. Can seeded data still accidentally look like external truth?
2. Can a report still imply decision-readiness while `external_signal_count=0`?
3. Can position divergence be reported but ignored by final action permission?
4. Can DIABLO/CHAOS be shown while action remains permissive?
5. Can an uncalibrated score look like a calibrated forecast?
6. Can `contextual_interpretation_enabled=false` be hidden in the summary?
7. Can a state transition happen without an explicit trigger/reason?
8. Can paper-trading assumptions look market-realistic without spread/slippage/replay marks?
9. Can old tests pass while the system remains unsafe?
10. Can a GitHub visitor misunderstand this as an investment product?

Each answer must come with a one-line citation: file:line, test name, or explicit "documented in README + AUDIT".

---

## 10. Final Executive Summary

```text
Claude verdict:
This repo should not try to become production-ready in one hackathon.
The correct next step is to make it structurally honest.
The core fix is not another metaphor layer.
The core fix is a typed truth → evidence → validation → veto → action-permission → decision ledger spine.
```

```text
Most important instruction to Codex:
Do not make the system look stronger. Make it harder for the system to lie.
```
