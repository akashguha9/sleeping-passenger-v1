# Second-Pass Adversarial Audit — Post Canonical Spine

> Branch: `claude/implement-hackathon-fixes-DfxS5`
> Date: 2026-05-08
> Scope: re-audit AFTER the canonical truth / evidence / decision / action-permission spine landed (commit `4e23626`).
> Posture: brutal. No flattery. Tests passing is not validity.

---

## 0. Executive Verdict

| Category | Before first audit | After spine implementation (claimed) | Honest current score | Reason |
| -------- | -----------------: | -----------------------------------: | -------------------: | ------ |
| Overall MVP | 4.8 | "much better" | **5.3** | Typed contracts and honest summary added, but only the health report consumes them. Core runtime path (action_engine, signal_refinery, run_diagnostics_pipeline) is untouched. |
| Scientific validity | 2.7 | "improved" | **3.0** | Zero new external labels, zero replay datasets, zero baselines, zero FP/FN accounting. Only the *vocabulary* for honesty improved, not the science. |
| Engineering maintainability | 4.1 | "improved" | **4.6** | Contracts are clean and isolated; legacy sprawl unchanged. `pipeline_health_report.py` is now 5,173 lines (was ~5,000); the spine added a 100-line block, not a refactor. |
| Evidence/truth spine | 1.8 | "spine added" | **3.0** | `EvidenceLedger` exists and is well-tested as a pure module, but it is **not instantiated anywhere in the live runtime**. The health report fakes its summary by reading legacy counters. |
| Decision spine | 1.5 | "spine added" | **2.5** | `DecisionLedger` exists with JSONL serialisation but **is never used** by any orchestrator. `decision_ledger_status="IN_MEMORY_ONLY"` is a literal hard-coded string, not a real status from a real ledger. |
| Action permission enforcement | 1.0 | "enforced" | **2.5** | `resolve_action_permission` is called once, **only** in `pipeline_health_report.py`. `action_engine.py` does not import it. The summary reports a permission the action engine ignores. |
| Health report honesty | 4.5 | "much more honest" | **6.5** | Genuinely improved. The canonical block contradicts nothing and surfaces vetoes/forbidden uses cleanly. Largest real upgrade in this round. |
| State-machine clarity | 4.8 | "typed contract added" | **5.0** | `Archetype` enum and forbidden-transition set exist, but **no other module imports them**. Chess/tennis/signal-surface/extreme-state still use ad-hoc strings and their own enums. |
| Position reconciliation | 3.4 | "canonical state" | **4.2** | `resolve_position_integrity_contract` adds a typed mapping and is wired to the health report. Still no broker/venue truth. Still divergent in seeded mode. Action engine does not bind on the canonical state. |
| Calibration honesty | 2.8 | "honest now" | **3.8** | The label `DEMO_ONLY` is correct and binding, but the four "calibration reports" are synthesised in-line with `has_outcome_labels=False, sample_count=0`. There is no calibration *measurement* — just a calibration *naming convention*. |
| Test quality | 4.6 | 707 → 810 (+103) | **5.0** | New tests are mostly pure-function contract tests of the new modules. Behaviourally meaningful end-to-end tests are sparse: only `test_health_report_honesty.py` (15 cases) actually integrates. No replay-vs-seeded behavioural tests, no action-engine vetoed-by-spine test, no decision-ledger persistence test. |
| Documentation honesty | 3.5 | "much more honest" | **6.0** | README now states the forbidden uses, the seeded stance, and the typed invariants clearly. Best-improved area along with the health summary. |
| Showcase credibility | 5.9 | "looks more legitimate" | **6.0** | Slight upgrade from honest framing. But a recruiter who reads `action_engine.py` will see the spine is not enforced — that is a credibility hit. |
| Decision-readiness | 0.5 | unchanged | **0.5** | Untouched. No outcomes, no calibration, no external labels. The new contracts make this *more visibly honest*, not closer to true. |
| Deployability | 1.4 | unchanged | **1.5** | Still not deployable. Spine cannot make a system deployable; it can only stop the system from *pretending* to be. |

### Did the hackathon implementation genuinely improve the repo?

Yes — it materially improved **honesty surface** and **typed vocabulary**. It did not improve **scientific validity** or **runtime enforcement**.

### Did it mostly improve structure or actual validity?

**Structure.** The patch installed a typed contract spine and consumed it in exactly one place (the health report). Validity (predictive power, calibration, outcome-label coverage, FP/FN accounting, replay data) is untouched.

### What became more honest?

- The health summary now surfaces `canonical_action_permission`, `veto_reasons`, `external_truth_status`, `calibration_status`, `allowed_use`, `forbidden_use`. It is harder to read it as deployable.
- The README explicitly forbids capital deployment / investment advice / automated execution.
- `EvidenceRecord`/`TruthOrigin`/`ValidationStatus` enforce a typed gap between SEEDED/DEMO and external truth.
- `ExternalTruthSourceStub` honestly reports `NOT_CONFIGURED` instead of pretending.

### What is still fake or weak?

- `evidence_ledger_status` and `decision_ledger_status` in the health report are **hardcoded strings derived from legacy counters**, not from a real EvidenceLedger or DecisionLedger instance.
- `truth_origin_breakdown={canonical_truth_origin.value: 1}` literally fabricates a count of `1` regardless of how many records exist.
- The four "calibration reports" are synthesised in `pipeline_health_report.py` with `has_outcome_labels=False, sample_count=0` — they cannot ever be CALIBRATED by construction. The result is correct, but tautological, not measured.
- `action_engine.py`, `signal_refinery.py`, `signal_conversion_monitor.py`, `run_diagnostics_pipeline.py` — none of them import the new contracts. The action recommendations the user actually sees (`EXIT_NOW: UNG, FCG | …`) are still produced by the legacy path.
- `Archetype` enum is unused outside its own module and tests.
- `truth_sources.py` is unused outside its own tests. There is no replay dataset on disk.
- Position reconciliation is still visibility-only; no source of truth for reconciliation evidence exists.

### What is the highest-risk remaining illusion?

**The spine is reported but not enforced.** A reader of the health summary sees `canonical_action_permission=BLOCK_CAPITAL`, but the action engine that produces `what_should_i_do_next=EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM` does not consult that permission. If a future commit silently flipped seeded gates, the action engine would still emit confident per-ticker actions while the health summary continues to claim BLOCK_CAPITAL.

### What should be fixed next?

Wire `resolve_action_permission` into `action_engine.build_action_report`. Persist `DecisionLedger` to disk per run. Replace the synthesised calibration reports with a real (still empty) calibration registry. Add an end-to-end test that asserts: when canonical_action_permission == BLOCK_CAPITAL, action_engine never emits a non-blocking per-ticker action without explicit advisory framing.

---

## 1. Audit Method

### Commands run

```
git checkout claude/implement-hackathon-fixes-DfxS5
git log --oneline -10
python -m compileall scripts tests           -> exit 0
python -m pytest tests -q                    -> 810 passed in 10.10s
python scripts/pipeline_health_report.py --summary --no-write
```

### Key command outputs

- `python -m pytest tests -q` → **810 passed in 10.10s** (claim verified).
- `python -m compileall scripts tests` → exit 0 (no syntax errors).
- Health summary contains: `canonical_action_permission=BLOCK_CAPITAL`, `veto_reasons=[NO_EXTERNAL_TRUTH,SEEDED_TRUTH_ONLY,POSITION_DIVERGED,POLICY_RESTRICTED,CHAOS_VETO,CALIBRATION_MISSING,INTERPRETATION_DISABLED,JAIL_MODE_ACTIVE]`, `truth_origin_breakdown=SEEDED=1`, `external_truth_status=NO_EXTERNAL_TRUTH`, `evidence_ledger_status=SEEDED_ONLY`, `decision_ledger_status=IN_MEMORY_ONLY`, `calibration_status=DEMO_ONLY`. Claims verified.

### Files inspected (full or substantial)

- `AUDIT_BRUTAL_MVP_ASSESSMENT.md` (1,274 lines)
- `CLAUDE_CODEX_HACKATHON_FIX_PLAN.md` (977 lines, head)
- `README.md` (392 lines, head 1–120)
- `scripts/runtime_contracts.py` (full)
- `scripts/evidence_ledger.py` (full)
- `scripts/decision_ledger.py` (full)
- `scripts/action_permission.py` (full)
- `scripts/state_machine_contracts.py` (full)
- `scripts/calibration_status.py` (full)
- `scripts/truth_sources.py` (full)
- `scripts/pipeline_health_report.py` — canonical-block region (lines 4400–4700) and grepped imports
- `scripts/position_truth_resolver.py` — `resolve_position_integrity_contract` region (lines 365–449)
- `scripts/action_engine.py` (lines 1–580)
- `tests/test_action_permission_contract.py` (head)
- `tests/test_decision_ledger.py` (head)
- `tests/test_evidence_ledger.py` (full)
- `tests/test_health_report_honesty.py` (full)
- Greps across all `scripts/` for canonical-spine imports.

### Files NOT fully inspected (acknowledged gaps)

- `scripts/run_diagnostics_pipeline.py` (633 lines) — only grepped, not read line-by-line. Grep confirms zero canonical-spine imports.
- `scripts/signal_refinery.py` (1,299 lines) — grepped only. Zero canonical-spine imports.
- `scripts/signal_conversion_monitor.py` (809 lines) — grepped only. Zero canonical-spine imports.
- The full 5,173-line `pipeline_health_report.py` was not read end-to-end; the canonical block (~110 lines around 4450–4565) was read in detail.
- `scripts/_quarantine/*` ignored (intentional).
- Tests were inspected by name and selectively read; the new contract tests are read substantially.

### Assumptions

- Tests passing is taken as evidence the contracts are internally consistent, **not** as evidence of behavioural correctness.
- The "live" runtime path is `run_diagnostics_pipeline.py` → `pipeline_health_report.py` → `action_engine.py` (the canonical chain in v5.7).
- `_quarantine` modules are inactive.

---

## 2. What Improved For Real

### Improvement 2.1 — Typed runtime contracts

```
Improvement: Single typed home for TruthOrigin / ValidationStatus / PolicyState / PositionIntegrityState / ActionPermission / VetoReason
Files: scripts/runtime_contracts.py, tests/test_runtime_contracts.py
Evidence: Enums are str-Enums with deterministic .value tokens; coercion helpers handle cross-module enum identity (`coerce_truth_origin`, `coerce_policy_state`, `coerce_position_state`, `coerce_system_mode`). `is_external_truth_origin` is the single rule that gates capital permission.
Why it matters: The whole repo previously used loose strings. Now there is exactly one set of authoritative tokens, and `is_external_truth_origin` is the single function that cannot be tricked into upgrading SEEDED to LIVE.
Remaining limitation: Only `pipeline_health_report.py`, `position_truth_resolver.py`, and the spine's own modules import these enums. Legacy modules still use bare strings.
Score impact: +0.3 on engineering maintainability; +0.2 on architecture coherence.
```

### Improvement 2.2 — Action-permission resolver

```
Improvement: Single deterministic resolve_action_permission() with seven ordered gates.
Files: scripts/action_permission.py, tests/test_action_permission_contract.py (~15 cases)
Evidence: Deterministic ordering of veto reasons; _strongest() picks the most restrictive permission; default fall-through is `DECISION_SUPPORT_ADVISORY`, never `DEPLOY_CAPITAL`.
Why it matters: There is finally one function that says BLOCK_CAPITAL and explains why, instead of a dozen advisory captions.
Remaining limitation: Only the health report calls it. action_engine.py does not.
Score impact: +0.5 on action permission enforcement (only because reporting layer enforces it).
```

### Improvement 2.3 — Health report honesty surface

```
Improvement: A dedicated canonical block at the end of build_pipeline_health_report; tested by test_health_report_honesty.py.
Files: scripts/pipeline_health_report.py:4450–4565, tests/test_health_report_honesty.py
Evidence: Asserts `canonical_action_permission == BLOCK_CAPITAL` in seeded mode; cross-checks contradiction with legacy `system_readiness_state`/`can_deploy_capital`.
Why it matters: This is the only place where the spine is actually consumed by a real pipeline run. It is also the public face of the repo — a recruiter running `--summary` sees an honest stance.
Remaining limitation: It is reporting honesty, not runtime honesty. The actions the user sees in `what_should_i_do_next` are produced upstream of this block.
Score impact: +2.0 on health report honesty.
```

### Improvement 2.4 — Calibration honesty layer

```
Improvement: CalibrationStatus enum, classify_calibration_status, aggregate_calibration_status with strict rules: only CALIBRATED supports capital permission.
Files: scripts/calibration_status.py, tests/test_calibration_status.py
Evidence: ARBITRARY_THRESHOLD / INSUFFICIENT_SAMPLES / REQUIRES_EXTERNAL_LABELS / DEMO_ONLY are mutually exclusive states tied to numeric thresholds.
Why it matters: It is now structurally impossible to call a heuristic threshold "calibrated" without passing both an outcome-label flag and a sample-count gate.
Remaining limitation: There is no real calibration registry. The four scores the health report classifies are hardcoded names with hardcoded `has_outcome_labels=False, sample_count=0`. Result is always `DEMO_ONLY`. No measurement is performed.
Score impact: +1.0 on calibration honesty.
```

### Improvement 2.5 — Position-integrity contract translation

```
Improvement: resolve_position_integrity_contract maps legacy CLEAN/DIVERGED/etc. onto the canonical PositionIntegrityState; downgrades MATCHED to UNKNOWN when truth_origin is SEEDED/DEMO.
Files: scripts/position_truth_resolver.py:365–438, tests/test_position_reconciliation_contract.py
Evidence: A MATCHED state in seeded mode is honestly downgraded to UNKNOWN; explicit reconciliation_evidence is required to upgrade to RECONCILED.
Why it matters: It is the first place the repo explicitly says "matched without external check is not reconciled."
Remaining limitation: Only health report uses this. action_engine.py still consults the legacy `position_integrity_state` string.
Score impact: +0.8 on position reconciliation.
```

### Improvement 2.6 — State-machine forbidden-transition contract

```
Improvement: Archetype enum + FORBIDDEN_TRANSITIONS frozenset + StateMachine class that raises StateMachineError on bad transitions; HURACAN validation-floor enforcement.
Files: scripts/state_machine_contracts.py, tests/test_state_machine_contracts.py
Evidence: Eight forbidden direct transitions; HURACAN→DEPLOY blocked below 0.6 validation_score.
Why it matters: A future module that constructs StateMachine cannot silently fast-track MIURA→GALLARDO or DIABLO→DEPLOY.
Remaining limitation: No legacy module instantiates a StateMachine. The contract is dormant.
Score impact: +0.2 on state-machine clarity (potential, not realised).
```

### Improvement 2.7 — Truth source interface

```
Improvement: SeedTruthSource / ReplayTruthSource / ExternalTruthSourceStub typed interface; OutcomeLabel container.
Files: scripts/truth_sources.py, tests/test_truth_sources.py
Evidence: SeedTruthSource cannot upgrade to LIVE_EXTERNAL; ReplayTruthSource only promotes to REPLAY_LABELED when an OutcomeLabel is attached; ExternalTruthSourceStub returns NOT_CONFIGURED.
Why it matters: Provides a place to land a real adapter without losing the typed gap between seed/replay/live.
Remaining limitation: No instance is constructed anywhere in the live pipeline. No replay dataset exists on disk. No real adapter implements TruthSource yet.
Score impact: +0.2 on evidence/truth spine.
```

### Improvement 2.8 — README honesty

```
Improvement: README now states "research/demo MVP", "not deployable", "not decision-ready", lists the canonical invariants, and prints the seeded BLOCK_CAPITAL output.
Files: README.md
Evidence: Lines 1–55.
Why it matters: A reader cannot mistake the repo for a tradeable product without ignoring the first paragraph.
Remaining limitation: README still calls the system a "decision shell" and lists "verified now" features whose verification is internal-coherence only.
Score impact: +2.5 on documentation honesty.
```

---

## 3. What Is Still Fake / Fragile / Underwired

### Weakness 3.1 — DecisionLedger is in-memory only AND is never instantiated

```
Weakness: decision_ledger_status="IN_MEMORY_ONLY" is a hardcoded string in pipeline_health_report.py; no DecisionLedger() is ever constructed in the live pipeline.
Why it is still weak: Decisions are not persisted, not replayable, and not auditable. The status string is performance art.
Files involved: scripts/pipeline_health_report.py:4539, scripts/decision_ledger.py (never imported by orchestrators)
Evidence from code: grep -rn "DecisionLedger" scripts/ → only matches inside decision_ledger.py itself. The literal `decision_ledger_status = "IN_MEMORY_ONLY"` at line 4539 is a string assignment, not derived from a ledger instance.
Failure mode: A run produces no JSONL. Tomorrow's run cannot replay yesterday's decision. The health summary lies by suggesting an in-memory ledger exists.
Severity: 8/10
Required fix: Construct a DecisionLedger inside build_pipeline_health_report; record one DecisionRecord per run; persist via to_jsonl_path('runtime/decision_ledger.jsonl'); set decision_ledger_status from len(ledger).
```

### Weakness 3.2 — EvidenceLedger is never instantiated; status is faked from legacy counters

```
Weakness: evidence_ledger_status is computed from `seeded_signal_count + external_signal_count` integer reads from the legacy report dict — not from an EvidenceLedger.
Why it is still weak: The "ledger" never holds typed EvidenceRecord instances; the typed contract is decorative.
Files involved: scripts/pipeline_health_report.py:4528–4538
Evidence from code: 
  evidence_ledger_status = "EMPTY" if seeded+external==0 else ("SEEDED_ONLY" if external==0 else "MIXED_OR_EXTERNAL")
  No EvidenceLedger() constructor anywhere outside evidence_ledger.py and its test.
Failure mode: A future bug that mis-counts seeded vs external in the legacy path will silently mis-label evidence_ledger_status. The typed ledger that was supposed to be the canonical truth is unused.
Severity: 8/10
Required fix: Build an EvidenceLedger from the actual seeded fixtures + (eventually) external adapter outputs; pass `summary=ledger.summary()` into resolve_action_permission; derive evidence_ledger_status from the ledger.
```

### Weakness 3.3 — truth_origin_breakdown is fabricated, not counted

```
Weakness: `truth_origin_breakdown = {canonical_truth_origin.value: 1}` always reports exactly one record.
Why it is still weak: It looks like a real distribution but is a single-key dict with hardcoded count 1.
Files involved: scripts/pipeline_health_report.py:4520–4522
Evidence from code: literal `{canonical_truth_origin.value: 1,}`
Failure mode: A reader believes the system has seen exactly one record. The number is decorative.
Severity: 6/10
Required fix: Replace with `EvidenceLedger.truth_origin_breakdown()` after the ledger is populated.
```

### Weakness 3.4 — Calibration reports are synthesised, not measured

```
Weakness: The four CalibrationReport instances passed to aggregate_calibration_status are constructed in-line with has_outcome_labels=False and sample_count=0. The result is mathematically forced to DEMO_ONLY.
Why it is still weak: Looks like calibration. Is naming convention.
Files involved: scripts/pipeline_health_report.py:4485–4500
Evidence from code: 
  calibration_reports = [classify_calibration_status(score_name=name, has_outcome_labels=False, sample_count=0, ...) for name in (...)]
Failure mode: A reader assumes calibration is being measured. There is no measurement. There is also no registry of which scores SHOULD be calibrated; the four names are hardcoded.
Severity: 7/10
Required fix: Move the score registry to a config (e.g., config/calibration_registry.yaml). Read sample counts from a real outcome ledger (currently nonexistent). Wire FP/FN/calibration-curve computation from a labeled replay dataset.
```

### Weakness 3.5 — resolve_action_permission is reported, not enforced

```
Weakness: resolve_action_permission is called only inside pipeline_health_report.py. No other module imports it.
Why it is still weak: The action engine continues to emit per-ticker actions (EXIT_NOW / REDUCE / HOLD / MONITOR / BLOCK_ENTRY) using legacy logic that has never seen the canonical permission.
Files involved: scripts/action_engine.py (no import), scripts/signal_refinery.py (no import), scripts/run_diagnostics_pipeline.py (no import)
Evidence from code: grep -rn "resolve_action_permission" scripts/ → 4 hits, all in pipeline_health_report.py and action_permission.py.
Failure mode: A user reads the per-ticker action table and acts on it, while the canonical block 50 lines below says BLOCK_CAPITAL. Two contradictory recommendations co-exist in one report.
Severity: 9/10
Required fix: action_engine.build_action_report must consume canonical_action_permission. When BLOCK_CAPITAL or QUARANTINE, all per-ticker rows must carry an explicit `canonical_block_capital=True` and the recommended action must be downgraded to advisory text.
```

### Weakness 3.6 — Archetype enum is unused outside its module

```
Weakness: scripts/state_machine_contracts.Archetype defines MIURA/HURACAN/GALLARDO/AVENTADOR/ISLERO/DIABLO/MURCIELAGO/JAIL/DEPLOY but is imported by zero other modules.
Why it is still weak: Legacy modules use ad-hoc strings ("MIURA_BULL", "DIABLO_CHAOS_SURFACE_VETO"), per-module enums (ChessArchetype with 16 members), or free-text states. State-name fragmentation persists.
Files involved: scripts/state_machine_contracts.py (defined), scripts/chess_archetype_decision_layer.py (own enum), scripts/contextual_interpretation*, scripts/signal_surface_engine.py, scripts/extreme_state*, scripts/board_control_safety_layer.py
Evidence from code: grep -rn "from scripts.state_machine_contracts" scripts/ → zero matches outside tests.
Failure mode: Two modules can disagree on whether the system is in MIURA. The canonical enum cannot resolve the dispute because nothing references it.
Severity: 6/10
Required fix: Replace the most-used legacy state strings with the canonical Archetype enum in at least signal_surface_engine.py and contextual_interpretation_engine.py; add a cross-module consistency test.
```

### Weakness 3.7 — Truth sources are dormant; no replay dataset exists

```
Weakness: SeedTruthSource / ReplayTruthSource / ExternalTruthSourceStub are exported but instantiated only in their unit tests. No replay JSONL with outcome labels exists on disk.
Why it is still weak: The "replay-ready" interface has no replay data. REPLAY_LABELED is theoretical — there are zero such records anywhere.
Files involved: scripts/truth_sources.py, runtime/*.jsonl (none are replay-with-labels)
Evidence from code: find . -name "*replay*" -or -name "*outcome*" → no matches outside generic decision/feedback logs.
Failure mode: The interface lulls reviewers into thinking replay validation is a small step away. It is not — there is no curated dataset, no label schema, no instrument coverage plan.
Severity: 8/10
Required fix: Build a tests/fixtures/replay_with_labels/ directory with at least 30 instrument×date rows + outcome labels; build a cli that loads it through ReplayTruthSource and emits an EvidenceLedger summary.
```

### Weakness 3.8 — Position reconciliation has no source of truth

```
Weakness: resolve_position_integrity_contract is wired to the health report and correctly downgrades MATCHED→UNKNOWN under seeded truth, but the only way to ever produce RECONCILED is to set `reconciliation_evidence=True` on the input dict — and nothing in the pipeline ever does so.
Why it is still weak: There is no broker, no venue, no third-party position truth feed. The "contract" is honest but the feedback loop is empty.
Files involved: scripts/position_truth_resolver.py, paper_reconciliation.py, no live broker adapter
Evidence from code: grep -rn "reconciliation_evidence" scripts/ → only in resolve_position_integrity_contract; never set elsewhere.
Failure mode: Even if the seeded fixtures matched perfectly, the canonical state would still be UNKNOWN. The contract gates capital permission on something nobody can supply.
Severity: 7/10
Required fix: Define a typed ReconciliationEvidence record (broker-pos, venue-pos, runtime-pos, timestamp, agreement bits). Provide a paper-only synthetic emitter for tests. Real broker integration is P2.
```

### Weakness 3.9 — JAIL_MODE_ACTIVE is internally derived but treated as an external veto

```
Weakness: VetoReason.JAIL_MODE_ACTIVE is added to veto_reasons whenever `false_negative_casino_monopoly_report["jail_mode"]["jail_mode_active"]` is True. This is computed from internal scores (chaos, model_uncertainty, edge_compression).
Why it is still weak: The veto looks like a hard external safety gate but is a soft self-assessment. Tomorrow's heuristic tweak can flip it.
Files involved: scripts/false_negative_casino_monopoly_layer.py:629, scripts/pipeline_health_report.py:3715–4517
Evidence from code: jail_mode_active = len(reasons) > 0 — driven by internal thresholds.
Failure mode: A future tuning change silently exits JAIL mode and the canonical permission lifts, even with no external truth.
Severity: 5/10
Required fix: Either (a) tag JAIL veto explicitly as a heuristic-derived warning rather than a structural veto, or (b) decompose JAIL into structural + heuristic components and only the structural part fires VetoReason.JAIL_MODE_ACTIVE.
```

### Weakness 3.10 — New tests are mostly contract-level, not behavioural

```
Weakness: Of the +103 new tests, the overwhelming majority are pure-function unit tests on dataclasses/enums in the new modules. Only test_health_report_honesty.py (15 tests) exercises a real pipeline build.
Why it is still weak: Could pass while the runtime is silently degraded. No test asserts "if canonical_action_permission == BLOCK_CAPITAL, action_engine emits zero non-advisory rows." No test asserts "external_signal_count > 0 implies origin must be LIVE_EXTERNAL or REPLAY_LABELED in the actual pipeline payload."
Files involved: tests/test_action_permission_contract.py, tests/test_decision_ledger.py, tests/test_evidence_ledger.py, tests/test_truth_sources.py, tests/test_calibration_status.py, tests/test_state_machine_contracts.py, tests/test_position_reconciliation_contract.py, tests/test_runtime_contracts.py
Evidence from code: file sizes 99/111/113/127/132/147/209/80 lines — small contract suites.
Failure mode: 810 tests pass while the pipeline silently emits actionable text under BLOCK_CAPITAL.
Severity: 8/10
Required fix: Add tests/test_action_engine_canonical_block.py asserting the action report carries canonical_block flags; tests/test_decision_ledger_persistence.py asserting per-run JSONL exists; tests/test_pipeline_canonical_consistency.py asserting health_report and action_report agree on canonical_action_permission.
```

### Weakness 3.11 — pipeline_health_report.py is now 5,173 lines

```
Weakness: The hackathon added a 110-line canonical block to an already 5,000-line file. No refactor.
Why it is still weak: The single most central file in the repo grew further. New honesty lives next to legacy entanglement.
Files involved: scripts/pipeline_health_report.py
Evidence from code: wc -l → 5,173.
Failure mode: Any change to the canonical block must be done inside the largest file; refactor risk is now higher.
Severity: 5/10
Required fix: Extract the canonical block + format_pipeline_health_summary into scripts/health_report_canonical.py.
```

### Weakness 3.12 — Showcase risk: a recruiter who reads action_engine.py will see the disconnect

```
Weakness: The README claims a typed canonical spine. action_engine.py has no canonical-spine import. A skeptical reader will spot this in 5 minutes.
Why it is still weak: The narrative is "spine integrated"; the runtime says "spine reported".
Files involved: README.md vs scripts/action_engine.py
Evidence from code: grep "canonical_action_permission" scripts/action_engine.py → zero hits.
Failure mode: Credibility loss when the gap is observed.
Severity: 6/10
Required fix: Either wire the spine into action_engine.py or change README phrasing from "spine" to "honesty contract" until wiring is complete.
```

---

## 4. Contract vs Runtime Integration Audit

Legend: ✅ = wired, ⚠️ = partial, ❌ = not wired.

| Contract / Spine Component | Exists? | Tested? | Used by health report? | Used by actual decision flow? | Used by action engine? | Used by reporting? | Risk if disconnected |
| -------------------------- | :-----: | :-----: | :--------------------: | :---------------------------: | :--------------------: | :----------------: | -------------------- |
| `runtime_contracts.py` (enums + coerce helpers) | ✅ | ✅ | ✅ (TruthOrigin/PolicyState/PositionIntegrityState coerced) | ❌ | ❌ | ✅ (formatter) | Token drift — legacy modules invent new strings |
| `EvidenceLedger` | ✅ | ✅ | ❌ (status faked from legacy counts) | ❌ | ❌ | ❌ | Count fabrication; cannot trust evidence_ledger_status |
| `DecisionLedger` | ✅ | ✅ | ❌ (status is hardcoded literal) | ❌ | ❌ | ❌ | No persistence; no replay; status string is theatre |
| `resolve_action_permission` | ✅ | ✅ (15 cases) | ✅ (the only consumer) | ❌ | ❌ | ✅ | Action engine emits per-ticker actions independent of canonical permission |
| `position_truth_resolver.resolve_position_integrity_contract` | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | Action engine binds on legacy `position_integrity_state` instead |
| `state_machine_contracts.Archetype` + StateMachine | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Dormant; cross-module state ambiguity persists |
| `calibration_status` | ✅ | ✅ | ⚠️ (4 in-line synthesised reports; result tautologically DEMO_ONLY) | ❌ | ❌ | ✅ | No measurement; classification is by construction |
| `truth_sources` (Seed/Replay/ExternalStub) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Dormant; no replay dataset exists |

**Brutal summary:** Of eight new spine components, **only `resolve_action_permission` and the position-contract translator are consumed by any real pipeline run, and both only by the health-report layer.** Every other contract is a dataclass + test pair with no live consumer. The user-visible "what should I do next" line is still produced upstream of the spine.

---

## 5. Scientific Validity Reality Check

```
Does the MVP now have external labels?               NO
Does it have replay datasets?                         NO
Does it have out-of-sample validation?                NO
Does it have baseline comparisons?                    NO
Does it track false positives?                        NO
Does it track false negatives?                        NO (despite a "false_negative_casino_monopoly_layer" by name)
Does it have calibration curves?                      NO
Does it have uncertainty intervals?                   NO
Does it separate correlation from causation?          NO
Does it measure predictive accuracy?                  NO
Does it measure decision quality?                     NO (only refusal frequency)
```

```
Scientific validity current score:                 3.0 / 10
Scientific validity ceiling without external labels: 3.5 / 10
What would move it to 5/10:
   - 30+ replay records with outcome labels in tests/fixtures/replay_with_labels/
   - A baseline (e.g., random / always-HOLD / momentum) emitted alongside system action
   - A test asserting baseline_outcome vs system_outcome on a frozen replay slice
What would move it to 6/10:
   - FP/FN/precision/recall counters per archetype, written to a metrics ledger
   - An honest README table showing baseline vs system on the replay dataset
   - Out-of-sample split (train/test) wired into the calibration registry
What would move it to 7/10:
   - Calibration curve (predicted-vs-realised) for at least one canonical score
   - Uncertainty intervals (bootstrap or Bayesian) on key metrics
   - A real LIVE_EXTERNAL adapter producing >100 records
What would move it to 8/10:
   - Prospective hold-out evaluation (live or paper-with-real-fills) on instruments
     not seen in calibration
   - Documented null-hypothesis test that the system beats the baseline
   - Reproducible artifact (snapshotted dataset hash + commit hash + metrics)
```

This area is unchanged by the hackathon. The new vocabulary ("REPLAY_LABELED", "OUTCOME_LABELED", "CALIBRATED") *describes* what would be needed for higher scores, but does not move the needle on any of them.

---

## 6. Test Suite Audit After +103 Tests

| Test file | What it proves | What it does not prove | Quality /10 | Missing integration test |
| --------- | -------------- | ---------------------- | ----------: | ------------------------ |
| `test_runtime_contracts.py` | Enums coerce correctly; `is_external_truth_origin` rejects SEEDED/DEMO/REPLAY/UNKNOWN | Nothing about runtime usage of the enums | 7 | Cross-module token consistency test |
| `test_evidence_ledger.py` | Records aggregate correctly; SEEDED+DEMO never count as external; warnings fire | EvidenceLedger is never built from real pipeline state | 7 | "build ledger from real run, assert payload_hash stable" |
| `test_decision_ledger.py` | Records serialise; JSONL deterministic; status reflects latest record | No test that the live pipeline persists a DecisionLedger | 6 | "run health report, assert runtime/decision_ledger.jsonl appended" |
| `test_action_permission_contract.py` (~15 cases) | Each gate fires the right veto; permission ordering is deterministic | No test that the action engine respects the result | 8 | "if BLOCK_CAPITAL, action_report emits zero non-advisory rows" |
| `test_calibration_status.py` | DEMO_ONLY/ARBITRARY_THRESHOLD/INSUFFICIENT_SAMPLES classify correctly | The four scores in the health report are synthesised; no real samples are tested | 6 | "feed labeled replay into classifier and assert non-DEMO_ONLY" |
| `test_state_machine_contracts.py` | Forbidden transitions raise; HURACAN floor enforced | No legacy module uses StateMachine | 6 | "instantiate StateMachine from a legacy archetype string and assert no contradiction" |
| `test_truth_sources.py` | Seed≠external; replay-with-labels promotes to REPLAY_LABELED; stub returns NOT_CONFIGURED | No real source produces real records | 6 | "build EvidenceLedger from ReplayTruthSource with labels, assert has_external_truth" |
| `test_position_reconciliation_contract.py` | MATCHED downgrades under SEEDED; severity HIGH→DIVERGED | action_engine still uses legacy state | 6 | "feed seeded summary into action_engine and assert it sees canonical state" |
| `test_health_report_honesty.py` (15 cases) | The full build produces canonical block; no contradiction with legacy readiness | Action engine output is never inspected for contradiction with canonical block | **9** | The single best test in this batch |
| Older `test_pipeline_health_*.py` | Legacy fields still present | Cannot detect canonical-spine drift | 6 | — |
| `test_action_engine.py` | Legacy action selection logic | Does not check canonical_block consumption | 5 | — |

### Are the new tests behaviourally meaningful?

Mostly **no**. They prove the new modules are internally consistent. They do not prove the runtime uses the modules, nor that two parts of the pipeline cannot disagree.

### Could the system still be unsafe while 810 tests pass?

**Yes.** Specifically: the action engine could emit `EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM` (which it does today) while the canonical block reports BLOCK_CAPITAL. No test asserts these two views of the same pipeline are consistent.

### Top 15 missing tests now

1. `test_action_engine_blocks_under_canonical_block_capital` — action_report must carry `canonical_action_permission` field and degrade per-ticker actions to advisory when BLOCK_CAPITAL.
2. `test_decision_ledger_persisted_per_run` — running health report writes a DecisionRecord JSONL line.
3. `test_evidence_ledger_built_from_real_pipeline` — `pipeline_health_report` constructs an `EvidenceLedger` whose `summary().to_dict()["external_signal_count"]` matches `external_signal_count` reported in the health summary.
4. `test_truth_origin_breakdown_reflects_actual_ledger` — breakdown is derived from EvidenceLedger, not synthesised.
5. `test_pipeline_canonical_consistency` — `pipeline_health_report.canonical_action_permission` equals `action_engine.report["canonical_action_permission"]`.
6. `test_replay_labeled_runtime_path` — given a replay-with-labels fixture, the pipeline ends up with `truth_origin in {REPLAY_LABELED, LIVE_EXTERNAL}` and at least one external_signal.
7. `test_state_machine_legacy_string_compatibility` — legacy state strings ("MIURA_BULL", "DIABLO_CHAOS_SURFACE_VETO") coerce to canonical Archetype with no surprises.
8. `test_chess_archetype_to_canonical_archetype_mapping` — explicit mapping from ChessArchetype to canonical Archetype if any.
9. `test_calibration_registry_loaded_from_config` — the four calibration score names live in a config file, not in a list literal.
10. `test_baseline_comparison_emits_metrics` — a baseline strategy outputs metrics on the replay dataset and they are recorded.
11. `test_fp_fn_accounting_records` — per-archetype FP/FN counters exist and round-trip JSONL.
12. `test_position_reconciliation_evidence_required_for_RECONCILED` — MATCHED + reconciliation_evidence ⇒ RECONCILED; without ⇒ UNKNOWN under SEEDED.
13. `test_external_truth_source_stub_blocks_capital` — wiring an ExternalTruthSourceStub leaves canonical_action_permission == BLOCK_CAPITAL.
14. `test_jail_mode_decomposition` — JAIL veto emitted only when its structural component is set, not its heuristic component.
15. `test_no_legacy_action_path_bypasses_canonical_block` — an integration test running run_diagnostics_pipeline + action_engine and asserting any per-ticker EXIT/REDUCE/HOLD is annotated with the canonical permission.

---

## 7. Health Report Honesty Audit

### Is the health report now more honest?

Yes — materially so. The canonical block is the largest real upgrade. A reader who scrolls only to the new fields can correctly conclude the system is BLOCK_CAPITAL and not deployable.

### Is it coherent?

Mostly. The canonical block is internally consistent. But the **report as a whole** still emits legacy fields next to the canonical fields:

- `recommended_next_action=BLOCKED_BY_DIABLO`, `chess_decision=WAIT`, `tennis_summary_recommendation=KEEP_IN_MIURA_RAW_DETECTION`, `what_should_i_do_next=EXIT_NOW: UNG, FCG | …` — **the last of these is actionable text emitted under canonical BLOCK_CAPITAL**.
- `system_readiness_state=DO_NOT_DEPLOY` and `can_deploy_capital=false` are consistent with the canonical block, but the structural_design_state, signal_surface_logic, and pre_execution_scan blocks each declare their own decisions in their own vocabulary.

### Does it contradict itself anywhere?

**Yes, soft contradiction:** `what_should_i_do_next=EXIT_NOW: UNG, FCG | …` is an actionable instruction co-existing in the same summary as `canonical_action_permission=BLOCK_CAPITAL` and `forbidden_use=automated execution`. There is no test asserting these cannot both appear.

### Does it surface allowed/forbidden use clearly?

Yes — `allowed_use=demo/research diagnostics only; internal review; narrative/structure exploration` and `forbidden_use=capital deployment; investment advice; automated execution` are present and tested.

### Does it expose veto reasons clearly?

Yes — eight reasons enumerated in a single comma-separated bracket-list. Tested.

### Does it make the repo more credible?

To a reader who reads top-to-bottom, yes. To a skeptical reader who searches `action_engine.py`, no — see Weakness 3.12.

### Does it still risk looking like progress because it prints more fields?

**Yes, partially.** `truth_origin_breakdown=SEEDED=1` and `evidence_ledger_status=SEEDED_ONLY` look quantitative. They are derived from a hardcoded `1` and a legacy integer comparison. Printed numbers feel like measurement; they aren't.

### Weaknesses in the formatting / data layer

- Duplicate state surfaces: `position_integrity_state=DIVERGED` (legacy) and `canonical_position_integrity_state=DIVERGED` (canonical) both printed; the canonical is the more truthful one.
- `truth_origin=seeded` (lowercase legacy) coexists with `canonical_truth_origin=SEEDED` (uppercase enum value).
- `temporal_integrity_warnings=decision_timestamp_unavailable` — the system prints a temporal-integrity warning it does not act on.
- Synthesised fields: `truth_origin_breakdown`, calibration_reports score list, `decision_ledger_status`.
- Default seeded evidence is implicit in the report path — no record of which fixtures were loaded.

---

## 8. Action Permission Enforcement Audit

### Where is action permission calculated?

Inside `pipeline_health_report.build_pipeline_health_report` at lines 4507–4518.

### Where is it consumed?

Only inside the same function (added to the `report` dict and printed by `format_pipeline_health_summary`).

### Does `action_engine.py` consume it?

**No.** Zero references to `canonical_action_permission`, `resolve_action_permission`, `ActionPermission`, `VetoReason`, or any spine import. The action engine's `_select_action` chooses among `EXIT_NOW`, `REDUCE`, `HOLD`, `MONITOR`, `BLOCK_ENTRY`, `REVIEW_FOR_ENTRY` based on legacy logic only.

### Does any downstream function ignore it?

Yes — every downstream function does. `run_diagnostics_pipeline.py`, `signal_refinery.py`, `signal_conversion_monitor.py`, `paper_execution.py` all have zero spine imports.

### Can any old path still produce action-like output without canonical permission?

**Yes — and it does, by default.** `what_should_i_do_next=EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM | DO NOT ADD NEW RISK` is the live example.

### Can demo/research states still accidentally look actionable?

Yes. The text "EXIT_NOW: UNG, FCG" is actionable language. Even with the canonical block printed nearby, an inattentive reader could parse the action line and ignore the spine.

### Per-flow enforcement table

| Flow | Uses canonical permission? | If no, risk | Required fix |
| ---- | -------------------------- | ----------- | ------------ |
| `pipeline_health_report.build_pipeline_health_report` | ✅ | — | — |
| `pipeline_health_report.format_pipeline_health_summary` | ✅ (prints fields) | — | — |
| `action_engine.build_action_report` | ❌ | Per-ticker actions emitted under BLOCK_CAPITAL with no awareness | Pass canonical_action_permission into build_action_report; emit advisory text only |
| `action_engine._select_action` | ❌ | Selects EXIT_NOW/REDUCE/HOLD without canonical check | Add a final pass: when canonical_action_permission ∈ {BLOCK_CAPITAL, QUARANTINE}, prefix every reason list with "advisory_only: canonical_block_capital" |
| `run_diagnostics_pipeline.main` | ❌ | Orchestrator runs all stages identically regardless of canonical state | Print canonical block at top of stdout output; refuse to write runtime artifacts that imply execution under BLOCK_CAPITAL |
| `signal_refinery.*` | ❌ | Refines as if signals could matter for capital | Tag refined signals with truth_origin and surface BLOCK_CAPITAL header |
| `signal_conversion_monitor.*` | ❌ | Same as refinery | Same |
| `paper_execution.*` | ❌ | Paper fill at default 100.0 still allowed without canonical check | Refuse fills while canonical_action_permission == BLOCK_CAPITAL unless explicit `--paper-only` and `--allow-block-capital` flags |
| `paper_reconciliation.*` | ❌ | Reconciles seeded fixtures; never marks reconciliation_evidence | Emit reconciliation_evidence=False explicitly; integrate into resolve_position_integrity_contract |
| Legacy what_should_i_do_next builder | ❌ | Strongest user-visible contradiction with canonical block | Wrap output in advisory framing whenever canonical_action_permission != DECISION_SUPPORT_ADVISORY+ |

---

## 9. Remaining P0 Fixes

### P0-1 — Wire DecisionLedger into actual runtime persistence

```
P0 Fix: Construct DecisionLedger in build_pipeline_health_report and persist per run.
Why it matters: Without persistence, "decision spine" is in-name-only.
Files to modify: scripts/pipeline_health_report.py, scripts/decision_ledger.py (already done), runtime/decision_ledger.jsonl (new artifact)
Implementation outline:
  1. After resolve_action_permission, build a DecisionRecord via build_decision_record.
  2. Append to a module-level or run-scoped DecisionLedger instance.
  3. Call DecisionLedger.to_jsonl_path(REPO_ROOT/"runtime"/"decision_ledger.jsonl") (append mode in production).
  4. Replace the literal `decision_ledger_status = "IN_MEMORY_ONLY"` with `f"{len(ledger)}_RECORDS_PERSISTED"` etc.
Tests required:
  - tests/test_decision_ledger_persistence.py: run health report, assert file exists, assert JSONL parses, assert latest entry matches canonical_action_permission.
Acceptance criteria:
  - `runtime/decision_ledger.jsonl` exists after running pipeline_health_report.
  - decision_ledger_status reads from len(ledger), not a literal.
Expected score movement: decision spine 2.5 → 4.0; engineering maintainability +0.2.
```

### P0-2 — Make action_engine consume canonical permission

```
P0 Fix: action_engine.build_action_report imports resolve_action_permission and tags every action_row with canonical state.
Why it matters: Eliminates the contradiction between spine and per-ticker output. This is the highest-severity weakness today.
Files to modify: scripts/action_engine.py, scripts/runtime_common.py (load canonical inputs)
Implementation outline:
  1. In build_action_report, after policy is loaded, call resolve_action_permission with the same inputs the health report uses.
  2. Add `canonical_action_permission`, `canonical_veto_reasons`, `canonical_block_capital` to each action_row.
  3. When BLOCK_CAPITAL, override action to `BLOCK_ENTRY` (or new `ADVISORY_ONLY`) and prefix reasons with "canonical_block_capital".
Tests required:
  - tests/test_action_engine_canonical_block.py: run build_action_report under seeded mode, assert no row has action ∈ {EXIT_NOW, REDUCE, HOLD without advisory prefix}.
Acceptance criteria:
  - No per-ticker action contradicts canonical_action_permission.
Expected score movement: action permission enforcement 2.5 → 5.5; overall MVP +0.3.
```

### P0-3 — Replace ad-hoc archetype/state strings with canonical Archetype enum where safe

```
P0 Fix: Migrate signal_surface_engine and contextual_interpretation_engine to canonical Archetype.
Why it matters: Cross-module state ambiguity is the root cause of the "many vetoes, none enforced" pattern.
Files to modify: scripts/signal_surface_engine.py, scripts/contextual_interpretation_engine.py, scripts/state_machine_contracts.py (extend aliases), scripts/extreme_state_logic.py
Implementation outline:
  1. Replace string returns like "MIURA_BULL" with `Archetype.MIURA.value`.
  2. Add cross-module test that all archetype outputs coerce via _coerce_archetype to a non-UNKNOWN value.
  3. Leave ChessArchetype / TennisArchetype isolated (semantic enums, not pipeline states) but document the boundary.
Tests required:
  - tests/test_archetype_consistency.py: every module's archetype output coerces to canonical enum without UNKNOWN fallback.
Acceptance criteria:
  - 0 UNKNOWN coercions across canonical archetype outputs.
Expected score movement: state-machine clarity 5.0 → 6.0.
```

### P0-4 — Build replay dataset loader with outcome labels

```
P0 Fix: Curate a tests/fixtures/replay_with_labels/ dataset and a CLI loader.
Why it matters: Without a labelled replay dataset, REPLAY_LABELED is theoretical and scientific validity is capped at ~3.5.
Files to modify: tests/fixtures/replay_with_labels/*.json (new), scripts/replay_runner.py (new), scripts/truth_sources.py (extend)
Implementation outline:
  1. 30+ instrument×date rows with: signal_payload, observed_outcome (e.g. "up_5pct_in_24h"), observed_at.
  2. CLI: python scripts/replay_runner.py --fixture tests/fixtures/replay_with_labels/foo.json
  3. Loader builds a ReplayTruthSource with OutcomeLabels and emits an EvidenceLedger summary.
Tests required:
  - tests/test_replay_runner.py: loader yields >0 REPLAY_LABELED records; EvidenceLedger.has_external_truth is True.
Acceptance criteria:
  - End-to-end: replay_runner produces an EvidenceLedger with external_signal_count > 0.
Expected score movement: scientific validity 3.0 → 4.0; evidence/truth spine 3.0 → 4.5.
```

### P0-5 — Add baseline comparison framework

```
P0 Fix: A baseline strategy (e.g. always-HOLD, random, naive momentum) emits actions on the same replay dataset and metrics are recorded side-by-side.
Why it matters: Without baselines, a positive metric is meaningless.
Files to modify: scripts/baseline_strategies.py (new), scripts/replay_runner.py (extend)
Implementation outline:
  1. BaselineStrategy ABC with .act(record) -> action.
  2. Three concrete: AlwaysHold, RandomChoice, NaiveMomentum.
  3. Replay runner emits per-strategy outcome metrics.
Tests required:
  - tests/test_baseline_strategies.py: each baseline produces deterministic output on a fixed seed.
Acceptance criteria:
  - Replay output JSON contains baseline_metrics block alongside system_metrics.
Expected score movement: scientific validity 4.0 → 5.0.
```

### P0-6 — Add false-positive / false-negative accounting

```
P0 Fix: Per-archetype FP/FN counters persisted to runtime/fp_fn_metrics.jsonl.
Why it matters: A "false_negative_casino_monopoly_layer" exists by name but never measures false negatives against outcome labels.
Files to modify: scripts/fp_fn_accounting.py (new), scripts/replay_runner.py (extend)
Implementation outline:
  1. Given (predicted_action, observed_outcome), classify as TP/FP/TN/FN per archetype.
  2. Persist counters; emit precision/recall.
Tests required:
  - tests/test_fp_fn_accounting.py: synthetic labels round-trip to correct counters.
Acceptance criteria:
  - runtime/fp_fn_metrics.jsonl exists after replay; canonical block surfaces precision/recall per archetype.
Expected score movement: scientific validity 5.0 → 5.5.
```

### P0-7 — Calibration curve scaffolding

```
P0 Fix: Per-score calibration curve (predicted bucket → realised rate) computed from labelled replay.
Why it matters: CalibrationStatus.CALIBRATED is currently unreachable because no curve is computed.
Files to modify: scripts/calibration_curves.py (new), scripts/calibration_status.py (consume)
Implementation outline:
  1. Bucket predictions, compute realised rates per bucket, emit curve.
  2. Feed sample_count and has_outcome_labels into classify_calibration_status from real data.
Tests required:
  - tests/test_calibration_curves.py: synthetic perfectly-calibrated data yields CALIBRATED; underconfident data yields INSUFFICIENT_SAMPLES at low N.
Acceptance criteria:
  - At least one canonical score reaches CALIBRATED on a labelled fixture.
Expected score movement: calibration honesty 3.8 → 5.5.
```

### P0-8 — End-to-end tests proving seeded → blocked, replay-labeled → research/paper-only, no veto bypass

```
P0 Fix: tests/test_pipeline_canonical_consistency.py covering three scenarios.
Why it matters: 810 tests pass while the system silently contradicts itself. This test class makes that impossible.
Files to modify: tests/test_pipeline_canonical_consistency.py (new), scripts/replay_runner.py (must exist for replay scenario)
Implementation outline:
  1. Scenario A: seeded mode → canonical_action_permission == BLOCK_CAPITAL ∧ action_engine emits zero non-advisory rows.
  2. Scenario B: replay-with-labels mode → canonical_action_permission ∈ {RESEARCH_ONLY, PAPER_TRADING_ONLY}; capital still blocked.
  3. Scenario C: external+calibrated+reconciled mode → canonical_action_permission == DECISION_SUPPORT_ADVISORY at most; never DEPLOY_CAPITAL without explicit operator flag.
Tests required: all three above.
Acceptance criteria:
  - Three integration tests that fail if any veto is bypassed.
Expected score movement: test quality 5.0 → 6.5; overall MVP +0.4.
```

### P0-9 — Resolve position reconciliation into explicit source inventory

```
P0 Fix: Define a typed ReconciliationEvidence dataclass and emitter for paper-mode synthetic agreement.
Why it matters: Today the only way to ever produce RECONCILED is to set a flag nobody sets.
Files to modify: scripts/position_truth_resolver.py, scripts/runtime_contracts.py, scripts/paper_reconciliation.py
Implementation outline:
  1. ReconciliationEvidence(broker_pos, venue_pos, runtime_pos, timestamp, agreement_bits).
  2. paper_reconciliation emits it deterministically when curated == runtime.
  3. resolve_position_integrity_contract consumes the typed object, not the bool.
Tests required:
  - tests/test_position_reconciliation_evidence.py: matched fixtures + evidence ⇒ RECONCILED; matched fixtures without evidence ⇒ UNKNOWN under SEEDED.
Acceptance criteria:
  - At least one path can produce canonical state RECONCILED in tests.
Expected score movement: position reconciliation 4.2 → 5.2.
```

### P0-10 — Add a public demo mode that is honest and clean

```
P0 Fix: A scripts/demo_run.py that runs the pipeline, prints only the canonical block + 5-line summary, and refuses to emit per-ticker actionable lines.
Why it matters: The current `--summary` output emits 80+ lines including `EXIT_NOW: UNG, FCG`. A recruiter or investor seeing that takes the wrong impression.
Files to modify: scripts/demo_run.py (new), README.md (point demos here)
Implementation outline:
  1. Run build_pipeline_health_report.
  2. Print canonical_action_permission, veto_reasons, allowed_use, forbidden_use, calibration_status, evidence_ledger_status.
  3. Refuse to print what_should_i_do_next or per-ticker actions.
Tests required:
  - tests/test_demo_run.py: stdout contains canonical block; stdout does not contain "EXIT_NOW", "REDUCE", "HOLD".
Acceptance criteria:
  - Demo output is honest and short.
Expected score movement: showcase credibility 6.0 → 7.0.
```

---

## 10. Next Hackathon Implementation Prompt

> Paste the following into Claude Code or Codex on a new branch.

```text
You are Claude Code / Codex acting as a senior implementation engineer
on the pipeline-v5.7-core repo. Work on a new branch:

    claude/wire-canonical-spine-into-runtime-NEXT

Context:
A first hackathon implementation added the canonical truth/evidence/decision/
action-permission spine (see scripts/runtime_contracts.py, evidence_ledger.py,
decision_ledger.py, action_permission.py, calibration_status.py,
state_machine_contracts.py, truth_sources.py, and the canonical block in
scripts/pipeline_health_report.py).

A second adversarial audit (AUDIT_SECOND_PASS_POST_SPINE.md on branch
claude/implement-hackathon-fixes-DfxS5) found that the spine is REPORTED but
NOT ENFORCED. resolve_action_permission is called only by the health report.
DecisionLedger is never instantiated. EvidenceLedger is faked from legacy
counters. truth_origin_breakdown is hardcoded {SEEDED: 1}. The action engine,
diagnostics orchestrator, signal refinery, signal conversion monitor, and
paper execution have ZERO canonical-spine imports. There is no replay-with-
labels dataset, no baseline strategy, no FP/FN accounting, no calibration
curve, no end-to-end test asserting that canonical_action_permission and
action_engine output cannot contradict each other.

Your task: implement the next P0 wave. Do not implement everything. Implement
in this order, each as one or two commits:

1. Wire resolve_action_permission into scripts/action_engine.py.
   - build_action_report must produce a canonical_block dict and tag every
     action_row with canonical_action_permission, canonical_veto_reasons,
     and canonical_block_capital.
   - When canonical_action_permission in {BLOCK_CAPITAL, QUARANTINE}, all
     per-ticker action recommendations must be downgraded to advisory text
     and the action field must be ADVISORY_ONLY.
   - Add tests/test_action_engine_canonical_block.py.

2. Persist DecisionLedger per run.
   - Build a DecisionLedger inside scripts/pipeline_health_report.py.
   - Persist to runtime/decision_ledger.jsonl (overwrite on each run is OK
     for the MVP; document this).
   - Replace the literal `decision_ledger_status = "IN_MEMORY_ONLY"` with a
     status derived from len(ledger).
   - Add tests/test_decision_ledger_persistence.py.

3. Build EvidenceLedger from real pipeline state.
   - Replace `truth_origin_breakdown = {canonical_truth_origin.value: 1}`
     with `EvidenceLedger.summary().truth_origin_breakdown`.
   - The ledger should be populated from the seeded fixtures actually used by
     this run (and from external adapter outputs once they exist).
   - Add tests/test_evidence_ledger_real_pipeline.py.

4. Create a labelled replay dataset and runner.
   - tests/fixtures/replay_with_labels/sample.json with at least 30 rows.
   - scripts/replay_runner.py CLI that wires ReplayTruthSource ->
     EvidenceLedger -> resolve_action_permission and emits a JSON report.
   - Under labelled replay, has_external_truth=True and canonical_action_
     permission must move from BLOCK_CAPITAL to RESEARCH_ONLY or PAPER_
     TRADING_ONLY (not DEPLOY_CAPITAL).

5. Add baseline comparison scaffolding.
   - scripts/baseline_strategies.py with AlwaysHold, RandomChoice,
     NaiveMomentum.
   - replay_runner emits per-strategy outcome metrics side-by-side.
   - tests/test_baseline_strategies.py.

6. Add FP/FN accounting.
   - scripts/fp_fn_accounting.py.
   - replay_runner persists runtime/fp_fn_metrics.jsonl.
   - tests/test_fp_fn_accounting.py.

7. Add the three end-to-end consistency tests.
   - tests/test_pipeline_canonical_consistency.py with three scenarios:
     seeded -> BLOCK_CAPITAL + zero non-advisory rows;
     replay-with-labels -> RESEARCH_ONLY/PAPER_TRADING_ONLY + capital still
     blocked;
     external+calibrated+reconciled -> at most DECISION_SUPPORT_ADVISORY.

Hard rules:
- Deployability MUST stay blocked. Do not introduce DEPLOY_CAPITAL anywhere
  except behind an explicit operator flag that is OFF by default and is
  documented in README as forbidden in this MVP.
- Do not weaken any existing veto rule.
- Do not add fields to the health report that look like measurement but are
  hardcoded — every count must derive from a real container.
- Do not add docstrings or comments that overclaim. Match README's "research/
  demo MVP, not deployable" framing.
- Tests must remain deterministic.
- After each step: run `python -m compileall scripts tests`, then
  `python -m pytest tests -q`, then
  `python scripts/pipeline_health_report.py --summary --no-write` and copy
  the canonical block into the commit message.
- Commit and push after each step. Do not bundle.

When done, write AUDIT_THIRD_PASS_RUNTIME_WIRED.md summarising what landed,
what scores moved, and what is still fake.
```

---

## 11. Final Brutal Assessment

1. **Did the repo become better or just bigger?**
   Both — but mostly *more honest*, not bigger. ~1,800 lines of new typed-contract code + ~1,000 lines of new tests, against a 5,000-line health report that grew by ~110 lines. The honesty surface is the genuine win.

2. **What is the strongest real upgrade?**
   The health report canonical block (lines 4450–4565) plus `test_health_report_honesty.py`. It is the only place where the spine is consumed by a real run and proven by a behavioural test.

3. **What is the biggest remaining illusion?**
   That the spine is "integrated". It is *reported*. The action engine does not consume it. Two parts of the same `--summary` output give contradictory readings.

4. **What would a serious engineer criticize first now?**
   "You added eight new modules and only the reporting layer uses them." Followed by "your decision ledger has a status field whose value is a hardcoded string."

5. **What would a quant researcher criticize first now?**
   "You have zero outcome labels, zero baselines, zero FP/FN, zero calibration curves. Your `CALIBRATED` state is unreachable by construction. You are calling things `SEED_ONLY` correctly, but you have not measured anything."

6. **What would a recruiter like now?**
   The README, the canonical block, the test count (810), the typed contracts file. It signals discipline.

7. **What would a recruiter distrust now?**
   The 5,173-line health report. The 192 scripts. The vendored `tribev2`. The contradiction between `EXIT_NOW: UNG, FCG` and `forbidden_use=automated execution` in the same summary.

8. **What should remain private?**
   The full repo as-is. Specifically: `_quarantine/`, the legacy state-name sprawl, the unenforced spine wiring, the synthesised calibration reports.

9. **What can be shown publicly?**
   The README plus the seven canonical-spine modules + their tests + `test_health_report_honesty.py`. Pin commit `4e23626`. Frame as: *honest typed contracts for a research MVP; runtime enforcement is in progress.*

10. **What is the fastest path from 5.3 (current) to 7?**
    P0-2 (wire to action_engine) + P0-1 (persist decision ledger) + P0-4 (replay dataset) + P0-8 (consistency tests). Two days of focused work.

11. **What is the fastest path from scientific 3 to 5?**
    P0-4 (replay dataset with labels) + P0-5 (baseline strategies) + P0-6 (FP/FN accounting). One week.

12. **What is the fastest path from scientific 5 to 6?**
    P0-7 (calibration curves) + a documented out-of-sample split + a real LIVE_EXTERNAL adapter producing >100 records. Two weeks if external data access is solved.

13. **What is unrealistic to claim right now?**
    "Decision-ready", "validated", "calibrated", "predictive", "tradeable", "investment-grade", "live", "deployable", "spine-enforced", "outcome-aware", "calibrated against real data".

14. **The one sentence you need to hear even if it hurts:**
    > **The hackathon installed the vocabulary of honesty, not the mechanism of it — the system can still emit `EXIT_NOW: UNG, FCG` while loudly declaring `BLOCK_CAPITAL` two lines below, and 810 tests will not catch it.**

---
*End of audit.*
