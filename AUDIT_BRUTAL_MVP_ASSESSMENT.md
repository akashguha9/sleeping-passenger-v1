# Brutal MVP Audit — pipeline-v5.7-core

## 0. Executive Verdict

- Overall MVP score: **4.8 / 10**
- Current deployability score: **1.4 / 10**
- Research/prototype quality score: **6.1 / 10**
- Production-readiness score: **2.2 / 10**
- Scientific validity score: **2.7 / 10**
- Engineering maintainability score: **4.1 / 10**
- Operational usefulness score: **4.6 / 10**
- Investor/employer showcase credibility score: **5.9 / 10**
- Risk of self-deception score: **8.7 / 10**
- Risk of false confidence score: **8.2 / 10**

Verdict: **RESEARCH MVP**

Current state:
- A large deterministic diagnostics lab with real engineering effort, good refusal posture, and weak external truth.

Best honest use:
- Internal research harness for testing admission logic, veto hierarchies, paper-only scaffolds, and explainability contracts before any serious real-data claim.

Worst misuse:
- Treating the health report, archetype labels, or score stack as evidence that the system can already rank or trade real geopolitical or prediction-market opportunities.

Main bottleneck:
- There is no empirically validated canonical decision spine. There are many modules, but too many terminate in reports instead of constraining one measurable, externally testable final decision path.

Most dangerous illusion:
- Internal coherence is being mistaken for external validity. Passing tests and producing consistent summaries are not the same thing as having predictive, calibrated, or decision-useful signal quality.

Highest-leverage fix:
- Collapse the sprawling score/state surface into one auditable decision ledger fed by real historical data, explicit outcomes, naive benchmarks, false-positive accounting, and reconciliation against externally observed truth.

## 1. Audit Method

This audit was grounded in the actual repository, not in generic startup advice.

Files inspected:
- Core orchestrators: `scripts/run_diagnostics_pipeline.py`, `scripts/pipeline_health_report.py`, `scripts/runtime_common.py`
- Action and state flow: `scripts/action_engine.py`, `scripts/signal_refinery.py`, `scripts/signal_conversion_monitor.py`, `scripts/position_truth_resolver.py`, `scripts/paper_execution.py`, `scripts/paper_reconciliation.py`
- New interpretation and safety layers: `scripts/contextual_interpretation_engine.py`, `scripts/contextual_interpretation/interpretation_engine.py`, `scripts/signal_surface_engine.py`, `scripts/pre_execution_scan_engine.py`, `scripts/board_control_safety_layer.py`, `scripts/extreme_state/*`
- External evidence and Apollo modules: `scripts/external_adapters/*`, `scripts/core/apollo_abort_guard.py`, `scripts/core/apollo_checklist_gate.py`, `scripts/core/apollo_priority_scheduler.py`, `scripts/core/external_evidence_router.py`
- Demos and smoke-like scripts: `scripts/run_contextual_interpretation_demo.py`, external observation pipeline tests, seeded/real-signal ingestion tests
- Docs/config: `README.md`, `docs/integrations/*`, `docs/contextual_interpretation_layer.md`, config JSON/YAML files including `config/thresholds.yaml`, `config/external_adapters.yaml`
- Tests: all `tests/*.py` at directory level plus targeted inspection of high-leverage files such as `test_signal_refinery.py`, `test_external_observation_pipeline_integration.py`, `test_real_signal_ingestion.py`, `test_contextual_interpretation_engine.py`, `test_paper_execution.py`, `test_board_control_safety_layer.py`

Test files inspected:
- The repo contains **90 Python test files**.

Scripts inspected:
- The repo contains **192 Python scripts**.

Demos inspected:
- `scripts/run_contextual_interpretation_demo.py`
- Presence of external/vendored demo material under `docs/external/tribev2/tribe_demo.ipynb` and `scripts/external/tribev2/tribev2/demo_utils.py`

Docs inspected:
- The repo contains **31 Markdown docs**.

Config files inspected:
- The repo contains **17 config files** under `config/`.

Commands run:

```powershell
git branch --show-current
git status --short
git log --oneline -5
python --version
python -m compileall scripts tests
python -m pytest tests -q
python scripts/pipeline_health_report.py --summary --no-write
```

Results:
- Branch: `feat/ci-position-truth-scm-bridge`
- Git status before writing this audit: clean
- Python: `3.13.4`
- `python -m compileall scripts tests`: exit code `0`
- `python -m pytest tests -q`: **707 passed in 61.48s**
- `python scripts/pipeline_health_report.py --summary --no-write`: succeeded and reported:
  - `system_readiness_state=DO_NOT_DEPLOY`
  - `can_deploy_capital=false`
  - `policy_state=RESTRICTED`
  - `position_integrity_state=DIVERGED`
  - `truth_origin=seeded`
  - `external_signal_count=0`
  - `board_control_safety=state=GLOBAL_CLEARANCE_BLOCKED, score=0.1029, weakest_path=0.35, hidden_drift=0.0, action=BLOCK_PROMOTION`
  - `pre_execution_scan=state=UNKNOWN_PRE_EXECUTION_STATE, readiness=MAPPED, pressure=COMPRESSED, turn=QUARANTINE, decision=QUARANTINE, score=0.2648`
  - `signal_surface_logic=state=DIABLO_CHAOS_SURFACE_VETO, decision=QUARANTINE, score=0.0358, damage=CONTAMINATED, bull=DIABLO_CHAOS_SURFACE_VETO`
  - `contextual_interpretation_enabled=false`

Files that could not be fully inspected:
- Temporary/runtime debris under `tests/.pytest_tmp`, `tests/_tmp_runtime/*`, `tests/fixtures/external_adapters/_generated_poly_data/*`, and `tests/pytest-cache-files-*` emitted repeated access-denied errors during broad filesystem enumeration. This did not block source inspection, but it is itself repo-hygiene evidence.

Assumptions made:
- I treated the diagnostics pipeline as the canonical runtime path because `scripts/run_diagnostics_pipeline.py` and `scripts/pipeline_health_report.py` clearly behave that way.
- I treated seeded/default behavior as the current truth because the health report reports `truth_origin=seeded` and `external_signal_count=0`.
- I treated isolated modules not referenced by the orchestrator or action engine as non-canonical unless tests or docs proved otherwise.

## 2. Segmented Scores

| Segment | Score /10 | Current ceiling | What stops it reaching 10 | Evidence | Fix |
| ------- | --------: | --------------: | ------------------------- | -------- | --- |
| Core architecture | 5.0 | 6.5 | The repo has many modules but no single canonical decision spine. | `run_diagnostics_pipeline.py` builds many reports; `action_engine.py` does not consume most new layers. | Define one canonical typed decision contract and force every action recommendation through it. |
| Signal detection quality | 4.5 | 6.0 | Detection is mostly seeded and heuristic. | `pipeline_health_report.py --summary` shows `truth_origin=seeded`, `external_signal_count=0`. | Add real historical ingestion with labeled outcomes and provenance. |
| Signal validation quality | 4.0 | 5.5 | Validation is mostly internal-consistency scoring, not truth validation. | `signal_refinery.py` uses heuristic thresholds and score blending; no outcome-based calibration. | Add outcome labels, false-positive accounting, and benchmark comparison. |
| External truth integration | 2.0 | 4.5 | External adapters exist but are not operationally central. | `ExternalAdapterRegistry` and Apollo modules are present, but not wired into canonical diagnostics/action flow. | Integrate external evidence into one evidence ledger and show when it changed a decision. |
| Data ingestion robustness | 4.2 | 6.0 | The code is defensive, but real feeds are absent or sidecar-only. | `market_data_adapter.py` is explicitly placeholder; external observation is optional and fake-provider-tested. | Build one stable real-data ingest path with schema validation and replayable snapshots. |
| Contextual interpretation | 5.8 | 7.0 | The logic is thoughtful but still heuristic and self-referential. | `contextual_interpretation_engine.py` has strong formulas/tests, but inputs are often derived from sparse signal dicts with defaults. | Connect it to measured context features rather than derived placeholders. |
| State machine clarity | 4.8 | 6.5 | There are many states, but the hierarchy is fragmented. | MIURA/HURACAN/MURCIELAGO/etc. appear across multiple subsystems with different triggers. | Create one state ontology and one override hierarchy. |
| Archetype logic consistency | 4.2 | 5.5 | Archetypes are semantically rich but not uniformly operational. | Bull mappings differ across signal surface, pre-execution, board control, contextual interpretation. | Consolidate archetype semantics and require cross-module consistency tests. |
| Risk management | 5.7 | 7.0 | Risk refusal is stronger than risk measurement. | `DO_NOT_DEPLOY`, `RESTRICTED`, and many veto layers are present, but capital/risk consequences are mostly blocked, not quantified. | Add numeric risk budgets, scenario loss assumptions, and explicit risk-accounting outputs. |
| Chaos / veto logic | 6.4 | 7.5 | Chaos refusal exists, but many layers are advisory, not binding. | Multiple DIABLO/chaos guards; action engine does not consume all of them. | Make chaos/policy vetoes part of the central action contract. |
| Position truth and reconciliation | 3.4 | 5.0 | Truth is surfaced but not resolved. | `position_truth_resolver.py` explicitly says “never pick a side as truth”; health report shows `position_integrity_state=DIVERGED`. | Create a canonical ledger with reconciliation rules and escalation outcomes. |
| Paper-trading realism | 3.0 | 4.5 | It is simulation scaffolding, not realistic paper execution. | `paper_execution.py` can fall back to `DEFAULT_FILL_PRICE = 100.0`. | Add venue-like price snapshots, slippage, spreads, latency, and mark-to-market rules. |
| Backtesting credibility | 2.2 | 4.0 | Backtest scripts exist, but there is no demonstrated calibrated backtest discipline. | Repo contains backtest-related scripts without visible test coverage or outcome-validation spine. | Build one end-to-end backtest with train/test split, naive baselines, and archived results. |
| Threshold calibration | 2.8 | 4.5 | Thresholds are configurable but arbitrary. | Many hard-coded cutoffs in `signal_refinery.py`, YAML thresholds, and safety engines. | Introduce threshold provenance docs and calibration scripts. |
| Scoring model validity | 3.1 | 4.8 | Scores are logically motivated but empirically unvalidated. | Most engines use weighted sums/products with deterministic unit tests only. | Replace or augment with calibration curves and outcome-based error analysis. |
| Explainability | 7.0 | 8.0 | Explainability is good internally, but detached from external truth. | Health report, audit trails, EngineScore diagnostics, structured runtime artifacts. | Tie explanations to evidence provenance and decision deltas. |
| Auditability | 6.5 | 7.5 | There are many runtime artifacts, but no single canonical ledger. | `runtime_common.py` manages many paths; health report loads many files. | Add one canonical event/decision ledger with immutable IDs. |
| Test coverage | 7.2 | 8.0 | Broad unit coverage, weak real-world coverage. | 707 passing tests across 90 files. | Add integration tests over real datasets and multi-module decision flow. |
| Test quality | 5.8 | 7.0 | Many tests validate deterministic toy outputs, not predictive behavior. | `test_signal_refinery.py` asserts exact seeded counts and ratios. | Shift more tests toward invariants, failure modes, and replayed historical episodes. |
| CI readiness | 6.0 | 7.0 | The suite passes, but filesystem hygiene is poor. | Access-denied debris under `tests/_tmp_runtime` and generated fixture paths. | Clean temporary directories and enforce consistent test isolation. |
| Runtime reliability | 5.2 | 6.5 | The system fails closed well, but relies heavily on seeded defaults. | Health report shows seeded truth, no external signals, and broad report-path dependence. | Add artifact existence checks plus deterministic degraded-mode contracts. |
| Error handling | 6.8 | 7.8 | The code often degrades gracefully, but degradation can hide missing capability. | External adapters and observation lane return structured degraded outputs. | Distinguish “safe degraded” from “architecturally missing” in summaries. |
| Configuration management | 6.0 | 7.5 | There is lots of config, but no provenance or calibration governance. | Multiple JSON/YAML config files with thresholds and weights. | Add config schemas, versioning, and provenance comments for every threshold family. |
| Secret handling | 7.5 | 8.0 | Good because almost nothing sensitive is enabled. | No live trading, no wallet, no private-key logic. | Preserve this and add secret scanning in CI. |
| Logging quality | 5.8 | 7.0 | There are many reports, fewer coherent logs. | Report-heavy runtime architecture; less evidence of canonical structured event logging. | Standardize structured logs per decision/event step. |
| Report generation | 7.3 | 8.0 | Strong breadth, weak synthesis. | `pipeline_health_report.py` is massive and surfaces a lot. | Refactor into subreports plus one canonical summary model. |
| CLI usability | 5.0 | 6.5 | Many scripts exist; user pathways are not clean. | 192 Python scripts, many specialized entrypoints. | Add one top-level CLI with subcommands and quickstart flows. |
| Documentation quality | 6.2 | 7.2 | Better than average, but too architecture-heavy and not outcome-grounded enough. | Integrations docs are careful; README has useful doctrine but encoding issues. | Fix encoding, add architecture diagram, sample workflows, and benchmark narrative. |
| User onboarding | 4.4 | 6.0 | Newcomers face script sprawl and metaphor density. | Repo volume is high; canonical minimal path is not obvious. | Create “read this first” developer journey and one smoke demo. |
| Maintainability | 4.1 | 5.8 | Several giant files are doing too much. | `pipeline_health_report.py` 4996 lines, `runtime_common.py` 1336, many large monolith engines. | Split by contract and concern; reduce monolithic report builder logic. |
| Modularity | 6.3 | 7.0 | Modules exist, but many are not meaningfully composed. | Large set of engines with weak downstream consumption. | Enforce module contracts via typed report objects consumed by central orchestration. |
| Code duplication | 3.8 | 5.0 | Utility logic is repeated aggressively. | Search found 29 separate `clamp01`/`_clamp` definitions. | Consolidate common math/validation helpers into shared libraries. |
| Naming clarity | 5.0 | 6.5 | Some names are clear; many are metaphor-first. | `false_negative_casino_monopoly_layer.py`, bull-state proliferation, etc. | Separate operational names from metaphor labels. |
| Dependency hygiene | 6.8 | 7.5 | Core dependency set is conservative, but vendored external material muddies scope. | `scripts/external/tribev2/**` and docs vendoring. | Isolate or remove non-core vendored experiments. |
| Performance/scalability | 4.2 | 5.5 | Plenty of JSON/report processing, unclear scaling model. | Many report builders and full-runtime-state dict mutations. | Introduce typed streaming/event model and benchmark large signal batches. |
| Reproducibility | 6.5 | 7.0 | Seeded mode is reproducible, but reality mode is absent. | Health report exposes Python version, requirements, CI, runtime metadata. | Add replay packs with versioned input snapshots and expected outputs. |
| Scientific validity | 2.7 | 4.0 | There is almost no external falsification loop. | No strong evidence of outcome labels, calibration, or OOS evaluation in canonical flow. | Build measurement first, architecture second. |
| Financial-market realism | 2.4 | 4.0 | Market realism is mostly mocked, seeded, or placeholder. | `market_data_adapter.py` placeholder, paper fills at default `100.0`. | Add historical prices, spreads, liquidity, and resolution labels. |
| Geopolitical-signal realism | 3.2 | 4.8 | Narrative/geopolitical ambition exceeds data plumbing. | Lots of interpretation layers, little canonical real-source ingestion. | Connect to archived event/news datasets with provenance and lag handling. |
| Narrative-signal realism | 4.3 | 5.5 | Trend/attention logic exists, but live evidence is not central. | TrendRadar adapter is optional sidecar; attention proxy engine is internal. | Add archived narrative corpora and explicit narrative-outcome mapping tests. |
| Legal/compliance posture | 6.8 | 7.5 | Strong disclaimers, but public-facing repo still risks overstatement through architecture complexity. | Docs clearly say paper-only and no financial advice. | Add stronger public model-risk statement and non-advisory warning in README top section. |
| Ethical safety | 7.0 | 8.0 | Refusal and non-live constraints are strong. | Real execution disabled across adapters and paper engine. | Preserve this and add explicit misuse scenarios. |
| Public GitHub showcase quality | 5.6 | 7.0 | Impressive surface area, but too easy to read as overbuilt theater. | Huge script count, metaphor density, encoding issues in README. | Curate a public-facing subset and show one measured result. |
| Employer credibility | 6.1 | 7.5 | The repo shows real effort and testing discipline, but also overdesign risk. | Broad modules and 707 tests; weak empirical grounding. | Reduce noise, highlight canonical flow, add calibration and benchmark evidence. |
| Investor credibility | 3.8 | 5.5 | It looks ambitious but not investable as a decision engine yet. | No validated edge, no outcome tracking, no real data spine. | Prove one narrow use case with measurable edge and error accounting. |
| Demo quality | 5.8 | 7.0 | Demos exist, but many behaviors are seeded and synthetic. | Contextual interpretation demo is deterministic and polished, but non-operational. | Build one replay demo from historical cases with clear expected outcomes. |
| Roadmap clarity | 5.5 | 7.0 | The implied roadmap exists in architecture, not in explicit priority order. | Many subsystems point to future capabilities, but no hard spine. | Publish a risk-first roadmap tied to outcome milestones. |
| Moat / uniqueness | 5.7 | 6.5 | The synthesis is unusual; the moat is not proven. | Board-control, Apollo, surface logic, contextual interpretation, etc. | Show that the synthesis improves measurable decisions over simpler baselines. |
| Risk of overfitting metaphors | 8.8 | 9.5 | Too many metaphor layers can become conceptual camouflage. | Bull archetypes, surface repair, football scan, Apollo doctrine, chess/tennis logic. | Keep metaphors only where they map to measurable variables. |
| Risk of fake sophistication | 8.4 | 9.0 | Module and state count currently outpaces validated utility. | Many large engines produce scores and states that do not yet feed action decisions or external truth tests. | Delete or quarantine ornamental layers until they prove they change measurable outcomes. |

## 3. Gap Analysis

### 3.1 Fatal gaps

1. **No external truth spine**
   - Why it is fatal: You cannot claim signal quality if you do not systematically compare output against reality.
   - Where it appears: `pipeline_health_report.py` shows `truth_origin=seeded`; `market_data_adapter.py` is a placeholder; external adapters are disabled and mostly not integrated.
   - Failure it could cause: Internal scores look precise while actual signal accuracy is unknown.
   - Minimum fix: Replay historical labeled datasets through one canonical pipeline.
   - Ideal fix: Versioned evidence ledger, outcome labels, calibration curves, error accounting, and rolling OOS evaluation.

2. **No canonical action-decision spine**
   - Why it is fatal: The repo has many guards, but there is no proof that the final action recommendation is actually constrained by all of them.
   - Where it appears: `run_diagnostics_pipeline.py` builds board-control, pre-execution, surface, extreme-state, and contextual reports; `action_engine.py` does not consume most of them.
   - Failure it could cause: Safety layers become advisory theater rather than binding control logic.
   - Minimum fix: Define one `CanonicalDecision` object with required gate inputs.
   - Ideal fix: Persisted state machine with decision provenance, veto hierarchy, and action-delta traces.

3. **Validation is mostly heuristic self-consistency**
   - Why it is fatal: Internal agreement does not equal truth.
   - Where it appears: `signal_refinery.py` and multiple engines use weight/threshold blends with no empirical provenance.
   - Failure it could cause: High “validated” status without predictive power.
   - Minimum fix: Add baseline comparison and false-positive tracking.
   - Ideal fix: Outcome-linked probabilistic validation with calibration and benchmark competition.

4. **Paper trading is not market-realistic**
   - Why it is fatal: Paper-only scaffolding is acceptable, but the current version is not serious enough to justify edge claims.
   - Where it appears: `paper_execution.py` uses default fill logic and can fall back to `100.0`.
   - Failure it could cause: Artificially flattering PnL, fill, and execution-discipline assumptions.
   - Minimum fix: Use historical or replayed marks/spreads and explicit fill assumptions.
   - Ideal fix: Event-driven paper broker simulator with latency, partial fills, slippage, and reconciliation.

5. **Position truth is observed, not resolved**
   - Why it is fatal: A system that cannot reconcile position truth cannot graduate toward any serious capital context.
   - Where it appears: `position_truth_resolver.py` explicitly refuses to resolve truth; health report shows `position_integrity_state=DIVERGED`.
   - Failure it could cause: Misstated exposure, duplicated entries, incorrect close logic.
   - Minimum fix: Canonical ledger selection plus divergence escalation state.
   - Ideal fix: Transaction journal, mark journal, reconciliation journal, and conflict resolution policy.

### 3.2 Serious gaps

- `pipeline_health_report.py` is too large and absorbs too much integration logic.
- External evidence architecture exists but is mostly isolated from canonical runtime decisions.
- README/showcase quality is hurt by encoding corruption and architecture sprawl.
- Tests are broad but skew toward deterministic internal assertions over historical/adversarial validation.
- There is no clear benchmark layer proving these heuristics beat simpler baselines.

### 3.3 Medium gaps

- Utility duplication such as repeated `clamp01` implementations.
- Too many runtime artifacts without one canonical evidence/decision ledger.
- Limited CLI unification across 192 scripts.
- Vendored non-core experiments such as `scripts/external/tribev2/**` muddy project boundaries.

### 3.4 Cosmetic gaps

- Naming is often metaphor-first rather than operator-first.
- Public-facing docs could separate “serious measured claims” from “architectural ideas.”
- Summary output is informative but overwhelming.

## 4. Leakage Analysis

### Leakage 1: Raw signal to interpreted signal leakage

Input:
- Seeded or sparse signal dicts.

Expected transformation:
- Raw detections should become context-rich interpreted meaning with explicit uncertainty.

Actual transformation:
- Interpretation is often derived from partial signal dicts using safe defaults.

Where leakage occurs:
- `scripts/contextual_interpretation_engine.py` via `raw_from_signal_dict(...)`

Why it matters:
- The engine is mathematically consistent, but input sparsity forces it to infer meaning from guessed defaults.

Severity:
- High

Fix:
- Require explicit input completeness/confidence and record which interpretation fields were imputed.

### Leakage 2: Interpreted signal to validated signal leakage

Input:
- Many interpretation/safety reports.

Expected transformation:
- Interpretation should materially constrain validation and action.

Actual transformation:
- Several reports enrich summaries but do not bind `action_engine.py`.

Where leakage occurs:
- `run_diagnostics_pipeline.py` vs `scripts/action_engine.py`

Why it matters:
- Architecture volume is overstating operational integration.

Severity:
- Fatal

Fix:
- Make action generation impossible without passing through interpreted/surface/board/pre-execution gate objects.

### Leakage 3: Validated signal to action recommendation leakage

Input:
- Validated/refined/admitted signals.

Expected transformation:
- Action decisions should reflect the strongest safety and validation signals.

Actual transformation:
- The canonical action layer remains thinner than the diagnostic layer.

Where leakage occurs:
- `action_engine.py`, `signal_refinery.py`, downstream summary generation

Why it matters:
- “Validated” status can exist without materially changing the final recommendation path.

Severity:
- High

Fix:
- Create one immutable decision object that records each gate’s contribution.

### Leakage 4: Action recommendation to risk guard leakage

Input:
- Candidate actions.

Expected transformation:
- Risk/chaos guards should hard-bind action permissions.

Actual transformation:
- Some guards are advisory/reporting outputs rather than action-engine inputs.

Where leakage occurs:
- Board-control, signal-surface, pre-execution, Apollo modules

Why it matters:
- A guard that does not change downstream action is not a guard. It is a caption.

Severity:
- High

Fix:
- Move hard vetoes into a shared `ActionPermission` contract.

### Leakage 5: Risk guard to final output leakage

Input:
- Veto and restriction states.

Expected transformation:
- Final output should show exactly which guard bound the outcome.

Actual transformation:
- Health summaries show many states at once, but the causal winner is not always obvious.

Where leakage occurs:
- `pipeline_health_report.py`

Why it matters:
- Too much summary breadth weakens interpretability.

Severity:
- Medium

Fix:
- Emit one `winning_guardrail` and one `primary_blocker_chain`.

### Leakage 6: State machine transition leakage

Input:
- Multiple state and archetype layers.

Expected transformation:
- Explicit, logged, testable transition hierarchy.

Actual transformation:
- Similar states exist across modules with different semantics.

Where leakage occurs:
- `signal_surface_engine.py`, `pre_execution_scan_engine.py`, `board_control_safety_layer.py`, `contextual_interpretation_engine.py`

Why it matters:
- Cross-module state meaning becomes ambiguous.

Severity:
- High

Fix:
- Define a repo-wide state ontology and forbidden-transition matrix.

### Leakage 7: Diagnostic output leakage

Input:
- Many runtime JSON artifacts and summary fields.

Expected transformation:
- Diagnostics should improve operator truth.

Actual transformation:
- The volume of output can obscure the few outputs that truly matter.

Where leakage occurs:
- `runtime_common.py`, `pipeline_health_report.py`

Why it matters:
- More reporting can create more confidence without more information.

Severity:
- Medium

Fix:
- Define canonical reports vs auxiliary reports and label them accordingly.

### Leakage 8: External adapter evidence leakage

Input:
- Sidecar/optional evidence candidates.

Expected transformation:
- Evidence should either inform decisions or remain clearly advisory.

Actual transformation:
- Good contracts exist, but little canonical downstream use.

Where leakage occurs:
- `scripts/external_adapters/*`, `scripts/core/*`

Why it matters:
- Integration architecture currently overstates operational reality.

Severity:
- Medium

Fix:
- Add one integrated evidence-routing example in the main diagnostics path.

## 5. Lacks / Missing Capabilities

### 5.1 Missing data capabilities

- Historical labeled outcomes for signals
  - Why it matters: Without labels, validation is internal only.
  - Workaround: Seeded and deterministic fixtures.
  - Minimum viable implementation: One archived case dataset with outcomes.
  - Ideal implementation: Multi-source event/market/outcome warehouse.
  - Priority: **P0**

- Real market price, liquidity, and spread history
  - Why it matters: Paper execution currently lacks realism.
  - Workaround: Seeded marks and default fill prices.
  - Minimum viable implementation: Historical market snapshot replay.
  - Ideal implementation: Full market replay engine.
  - Priority: **P0**

- Source-quality history and provenance ledger
  - Why it matters: Evidence credibility should be learned over time.
  - Workaround: Static quality proxies.
  - Minimum viable implementation: Per-source historical hit-rate table.
  - Ideal implementation: Time-decayed source trust model.
  - Priority: **P1**

- Narrative and news corpora
  - Why it matters: Narrative engines need real input, not only heuristics.
  - Workaround: Sidecar adapters and seeded signals.
  - Minimum viable implementation: Archived narrative dataset.
  - Ideal implementation: Versioned multi-source narrative ingestion.
  - Priority: **P1**

### 5.2 Missing modeling capabilities

- Calibration curves and probability reliability testing
  - Why it matters: Scores are currently mostly rank-like heuristics.
  - Workaround: Deterministic thresholds.
  - Minimum viable implementation: Reliability chart for one score family.
  - Ideal implementation: Full calibration pipeline across regimes.
  - Priority: **P0**

- Naive benchmarks
  - Why it matters: There is no proof the architecture beats simple baselines.
  - Workaround: None that matters.
  - Minimum viable implementation: Compare against frequency, momentum, or market-implied baselines.
  - Ideal implementation: Multi-benchmark evaluation harness.
  - Priority: **P0**

- False-positive / false-negative accounting
  - Why it matters: Refusal can look safe while still being useless.
  - Workaround: Refusal doctrine.
  - Minimum viable implementation: Count and review decision misses.
  - Ideal implementation: Decision confusion matrix by regime.
  - Priority: **P0**

- Regime detection and causal separation
  - Why it matters: Narrative and geopolitical signals are regime-sensitive.
  - Workaround: Heuristic chaos/state layers.
  - Minimum viable implementation: Regime tags and segmented evaluation.
  - Ideal implementation: Explicit latent-regime model with ablation tests.
  - Priority: **P1**

### 5.3 Missing operational capabilities

- Canonical signal ledger
  - Why it matters: Current truth is spread across runtime artifacts and ledgers.
  - Workaround: Multiple JSON files and reports.
  - Minimum viable implementation: One append-only signal journal.
  - Ideal implementation: Typed event store with lineage.
  - Priority: **P0**

- Canonical paper-trade ledger with reconciled marks
  - Why it matters: Paper execution is not auditable enough yet.
  - Workaround: Local ledgers and reconciliation helpers.
  - Minimum viable implementation: Single paper-trade state store.
  - Ideal implementation: Event-driven paper broker model.
  - Priority: **P0**

- Kill-switch and recovery mode contract
  - Why it matters: You have vetoes, but not one recovery policy object.
  - Workaround: State summaries.
  - Minimum viable implementation: `NO_NEW_RISK` and recovery-state persistence.
  - Ideal implementation: Structured incident playbook and state transition log.
  - Priority: **P1**

### 5.4 Missing product capabilities

- One canonical CLI
  - Why it matters: 192 scripts is not product UX.
  - Workaround: ad hoc script running.
  - Minimum viable implementation: top-level CLI with `diagnose`, `replay`, `paper`, `report`.
  - Ideal implementation: polished operator CLI plus Streamlit/HTML dashboard.
  - Priority: **P1**

- Public architecture diagram and quickstart
  - Why it matters: The repo is hard to evaluate quickly.
  - Workaround: README and docs.
  - Minimum viable implementation: one architecture diagram and 5-minute demo path.
  - Ideal implementation: recruiter/professor-friendly landing doc and screenshots.
  - Priority: **P2**

### 5.5 Missing governance capabilities

- Model cards / score cards
  - Why it matters: Scores currently lack provenance and limits.
  - Workaround: formula comments and docs.
  - Minimum viable implementation: model card for each major engine.
  - Ideal implementation: standardized score registry with assumptions and failure modes.
  - Priority: **P1**

- Stronger external adapter operational terms
  - Why it matters: License docs are good, but runtime governance is still mostly documentation.
  - Workaround: sidecar-only contracts and tests.
  - Minimum viable implementation: adapter enablement checklist.
  - Ideal implementation: compliance gate plus source-term registry.
  - Priority: **P2**

## 6. What Is Fake Strength vs Real Strength

### 6.1 Real strengths

- **Fail-closed safety posture**
  - Evidence: `real_execution_allowed = false` across external adapters; paper-only constraints; `DO_NOT_DEPLOY`.
  - Why useful: The project is not pretending to be safely executable.
  - Preserve: Keep policy and no-live constraints central.

- **Broad deterministic test suite**
  - Evidence: 707 passing tests across 90 files.
  - Why useful: It protects internal contracts and refactors.
  - Preserve: Keep the unit discipline while adding reality-facing integration tests.

- **Explicit runtime artifact and health summary discipline**
  - Evidence: `runtime_common.py` artifact paths, `pipeline_health_report.py` metadata and summaries.
  - Why useful: The system is unusually inspectable for an MVP.
  - Preserve: Keep observability, but simplify and prioritize.

- **Thoughtful license boundaries on third-party evidence**
  - Evidence: `docs/integrations/license_boundaries.md`, adapter contracts, no-real-execution enforcement.
  - Why useful: This is legally and architecturally more careful than most early repos.
  - Preserve: Keep GPL/AGPL isolation strict.

- **Pure-function-like safety engines**
  - Evidence: board control, pre-execution, signal surface, contextual interpretation all have deterministic tests.
  - Why useful: These are testable and refactorable.
  - Preserve: Keep pure scoring cores even if many should be consolidated.

### 6.2 Fake or fragile strengths

- **Apparent strength: massive architecture**
  - Why fragile: Module count is outpacing validated integration.
  - Evidence: many report builders, limited action-engine consumption.
  - Test whether real: trace one signal end to end and record which modules changed the action.
  - Harden: prune or merge layers that do not change measured outcomes.

- **Apparent strength: many scores**
  - Why fragile: Most are not calibrated.
  - Evidence: weight/threshold-heavy heuristics across many engines.
  - Test whether real: correlation, calibration, and ablation against outcomes.
  - Harden: keep only scores that improve measured decisions.

- **Apparent strength: safety depth**
  - Why fragile: A refusal-heavy system can still be useless.
  - Evidence: health report ends in `DO_NOT_DEPLOY` and many quarantine states under seeded mode.
  - Test whether real: measure false negatives and missed good opportunities.
  - Harden: add decision-quality accounting, not just refusal accounting.

- **Apparent strength: external integration architecture**
  - Why fragile: It is largely optional, mocked, and not central.
  - Evidence: external adapters and Apollo modules exist but are not on the canonical decision path.
  - Test whether real: enable one external source and show a changed decision with provenance.
  - Harden: route evidence into one canonical ledger and summary delta.

- **Apparent strength: paper trading**
  - Why fragile: The simulation layer is not yet venue-like.
  - Evidence: default fill price fallback, seeded marks.
  - Test whether real: replay historical data and compare simulated fills to realistic assumptions.
  - Harden: event-driven paper execution and reconciliation.

## 7. Architecture Review

### 7.1 Current architecture map

```text
Seeded / Optional External Inputs
    ↓
External Observation Lane / External Adapters / Sidecars
    ↓
Runtime Common / Config / Artifact Paths
    ↓
Trend / Attention / Signal Refinery / Perception Control
    ↓
Structural Admission / Contextual Interpretation
    ↓
Signal Surface / Pre-Execution Scan / Board Control / Extreme State
    ↓
Action Engine
    ↓
Paper Execution / Reconciliation / Position Truth Helpers
    ↓
Pipeline Health Report / Runtime JSON / Diagnostics Summary
```

Actual weakness:
- Several middle layers are built and reported, but not clearly enforced inside the final action engine.

### 7.2 Broken or weak interfaces

- `runtime_state` is a broad mutable dict passed through many layers. This is flexible but weakly typed and easy to silently underfill.
- `raw_from_signal_dict(...)` in contextual interpretation is robust but proves the system often lacks native input contracts.
- Summary/report builders often act as adapters because core contracts are missing.

### 7.3 Overcoupled modules

- `pipeline_health_report.py` is overcoupled to nearly everything.
- `runtime_common.py` carries too many orthogonal responsibilities.
- `run_diagnostics_pipeline.py` is coordinating many layers without a strong typed orchestration contract.

### 7.4 Undercoupled modules

- External adapter registry and Apollo modules are undercoupled to canonical runtime decisions.
- Board-control, pre-execution, and signal-surface reports are undercoupled to `action_engine.py`.

### 7.5 Dead or ornamental modules

- Anything that produces a report but never influences a downstream decision is at least partially ornamental.
- External adapter and Apollo core modules are currently near this line.
- Vendored `tribev2` material is not part of the core MVP path and muddies the repo’s narrative.

### 7.6 Missing central contracts

- A canonical `SignalEvidence`
- A canonical `ValidatedSignal`
- A canonical `ActionPermission`
- A canonical `DecisionLedgerEntry`
- A canonical `PaperTradeLedgerEntry`
- A canonical `PositionTruthState`

## 8. State Machine / Archetype Audit

The state/archetype system is ambitious but fragmented.

- **MIURA**
  - Where: contextual interpretation, pre-execution, other bull mappings
  - Trigger: usually raw/high-noise or blind detection
  - Operational or metaphor: partly operational, partly metaphor
  - Score: **5/10**

- **HURACAN**
  - Where: contextual interpretation, pre-execution, signal systems
  - Trigger: fast-track momentum under floors
  - Issue: semantics differ by layer
  - Score: **4/10**

- **MURCIELAGO**
  - Where: contextual interpretation, board/surface/pre-execution logic
  - Trigger: durability/pressure validation
  - Issue: conceptually useful, not consistently centralized
  - Score: **6/10**

- **AVENTADOR**
  - Where: multiple promotion layers
  - Trigger: promoted/actionable
  - Issue: not always tied to one action consequence
  - Score: **5/10**

- **GALLARDO**
  - Where: some decision-ready (advisory) mappings
  - Trigger: disciplined execution readiness
  - Issue: often defined but intentionally not assigned in some layers
  - Score: **4/10**

- **DIABLO**
  - Where: chaos/surface/pre-execution/extreme-state logic
  - Trigger: chaos, veto, no-new-risk
  - Strength: best-defined archetype because it usually means stop
  - Score: **7/10**

- **ISLERO**
  - Where: shock/reclassification logic
  - Trigger: shock or contradiction
  - Issue: operationally useful, but still duplicated across engines
  - Score: **6/10**

- **WATCH / VALIDATE / PAPER_TRADE / QUARANTINE / REJECT / HOLD**
  - Where: signal refinement, paper trade, pre-execution, surface systems
  - Issue: there is no one repo-wide transition model.
  - Score: **5/10**

Missing elements:
- Repo-wide transition logger
- Forbidden-transition table
- State persistence standard
- State confidence standard
- One override hierarchy across all state families

StateQuality =
`ExplicitTrigger × TransitionValidity × TestCoverage × RuntimePersistence × ActionConsequence × ExplanationQuality`

Current verdict:
- Explicit triggers and test coverage are decent in isolation.
- Transition validity, runtime persistence, and action consequence are inconsistent across the full repo.

## 9. Scoring and Threshold Audit

Representative scoring systems:

- `scripts/signal_refinery.py`
  - What it scores: confirmation, state quality, validation, launch control
  - Class: **C**
  - Issue: coherent heuristic, not empirically calibrated

- `scripts/contextual_interpretation_engine.py`
  - What it scores: meaning, learning velocity, hidden capability, promotion
  - Class: **B/C**
  - Issue: logically grounded, but still synthetic and calibration-free

- `scripts/pre_execution_scan_engine.py`
  - What it scores: pre-scan quality, surprise risk, optionality, final score
  - Class: **C**
  - Issue: useful discipline, unproven predictive contribution

- `scripts/board_control_safety_layer.py`
  - What it scores: board control, weakest path, hidden drift, investable signal
  - Class: **C**
  - Issue: strong logic vocabulary, weak empirical linkage

- `scripts/signal_surface_engine.py`
  - What it scores: repair/surface integrity and action permission
  - Class: **D**
  - Issue: informative metaphor-to-score mapping, but far from external validation

- `scripts/core/apollo_abort_guard.py`
  - What it scores: safety clearance
  - Class: **B**
  - Issue: as a refusal/veto framework it is logically grounded, but not yet canonical

Most useful score:
- The simplest restriction outputs such as `policy_state`, `can_deploy_capital`, and explicit veto conditions are more trustworthy than the more ornate multi-factor meaning scores.

Most dangerous score:
- Any “promotion” or “investable” score that looks quantitative without an outcome-based calibration loop. The current versions can create false precision.

Most arbitrary threshold:
- The many score cutoffs around ~0.55-0.75 across contextual, pre-execution, board-control, and signal-refinery layers. They are reasonable-looking numbers, not evidenced numbers.

Score that should be removed or renamed:
- Any score named as though it implies market edge or investability without external validation. `investable_signal_score` is too strong a name today.

Score that should become a confidence interval:
- Meaning confidence, promotion score, and market-edge-like scores.

Scores that should be consolidated:
- Overlapping “quality”, “promotion”, “actionability”, and “admission” scores across signal refinement, contextual interpretation, pre-execution, and board-control.

Canonical decision spine candidates:
- Policy veto
- Chaos veto
- External truth completeness
- Validation confidence
- Durability
- Reconciliation state
- Paper-execution permission

## 10. Testing Audit

The test suite is broad and serious by MVP standards, but it mostly proves deterministic internal correctness, not real-world usefulness.

- Number of tests: **707**
- Number of test files: **90**
- What the tests cover well:
  - Deterministic formulas
  - Safety refusal
  - External adapter degradation
  - Structured runtime/report contracts
  - Many boundary conditions and JSON serialization contracts
- What the tests do not cover well:
  - External truth
  - Historical replay validity
  - Calibration
  - False-positive / false-negative economics
  - Realistic paper execution
  - Canonical end-to-end decision enforcement

| Test file | What it covers | Quality /10 | Blind spots | Recommended additions |
| --------- | -------------- | ----------: | ----------- | --------------------- |
| `tests/test_signal_refinery.py` | Seeded signal scoring and summaries | 6 | Exact seeded counts can overfit implementation | Add replayed historical cases and adversarial input sets |
| `tests/test_contextual_interpretation_engine.py` | Meaning engine formulas and safeguards | 7 | No external truth or measured benefit | Add cross-module integration with real signal snapshots |
| `tests/test_board_control_safety_layer.py` | Board-control scoring and veto logic | 7 | No proof it improves real decisions | Add action-engine integration tests |
| `tests/test_pre_execution_scan_engine.py` | Scan formulas, archetypes, gates | 7 | No real telemetry or decision-delta proof | Add historical replay and delta-on-decision tests |
| `tests/test_signal_surface_engine.py` | Surface integrity model | 6 | Highly metaphorical and internally scoped | Add pruning decision: prove or quarantine |
| `tests/test_external_adapter_registry.py` | Adapter config and degradation | 7 | Registry is not canonical runtime path | Add diagnostics-path integration test |
| `tests/test_apollo_abort_guard.py` | Safety alarms | 7 | Guard not central enough yet | Add end-to-end abort binding test |
| `tests/test_paper_execution.py` | Paper-only order handling | 6 | Fill realism and mark realism absent | Add slippage/partial-fill assumptions |
| `tests/test_external_observation_pipeline_integration.py` | Fake provider integration and fail-closed behavior | 8 | No live or archived real-provider replay | Add archived feed replay test |
| `tests/test_real_signal_ingestion.py` | Structured ingestion path | 5 | “Real” still uses fabricated external rows | Add archived external snapshots |

Top 10 missing tests:
1. End-to-end canonical decision test proving which safety layers actually bind action output
2. Historical replay with known outcomes
3. Naive benchmark comparison tests
4. Reconciliation conflict resolution tests
5. Paper execution with realistic fill assumptions
6. External evidence changing final decision tests
7. Calibration / reliability tests
8. False-positive / false-negative accounting tests
9. State transition persistence tests
10. Cleanup/isolation tests preventing temp-dir accumulation

Top 10 tests to rewrite:
1. Exact-count seeded refinery tests that bake in implementation-specific ratios
2. Any test that treats a deterministic mock output as “real signal”
3. Any test that validates large summary strings over underlying decision contracts
4. Any action test that does not assert binding veto precedence
5. Any “integration” test that never touches canonical action output
6. Any external adapter test that stops at normalization instead of downstream effect
7. Any paper-trading test that ignores fill realism
8. Any board/pre-execution/surface test that proves formulas but not action consequence
9. Any state/archetype test that does not check forbidden transitions
10. Any report test that never verifies provenance or causal blocker

Top 10 valuable tests to preserve:
1. External adapter base/validation tests
2. Apollo abort/checklist tests
3. External observation fail-closed tests
4. Policy/chaos non-live execution tests
5. JSON serialization tests for report artifacts
6. Boundary clamp tests across formula engines
7. Position/paper ledger contract tests
8. Contextual interpretation deterministic consistency tests
9. Registry graceful degradation tests
10. Runtime metadata / health-report consistency checks

## 11. Product Readiness Audit

- **Professor**: 6/10
  - Would like: ambition, formalized heuristics, deterministic architecture
  - Would distrust: lack of falsification and benchmark evidence
  - To take seriously: one measured study with labeled outcomes
  - To dismiss: metaphor density without empirical evaluation

- **Recruiter**: 6/10
  - Would like: project scope, tests, docs, safety boundaries
  - Would distrust: complexity that is hard to summarize
  - To take seriously: a concise public narrative and architecture diagram
  - To dismiss: unreadable repo sprawl

- **Technical hiring manager**: 6.5/10
  - Would like: extensive test discipline and modular ambition
  - Would distrust: monolith files and over-architecting
  - To take seriously: evidence of pruning, integration discipline, and typed contracts
  - To dismiss: “smart-sounding” layers not used in the main path

- **Quant researcher**: 3.5/10
  - Would like: separation of signal, risk, paper-only discipline
  - Would distrust: no calibration, no OOS, no benchmark, no realistic execution model
  - To take seriously: one falsifiable narrow use case with measured edge
  - To dismiss: score inflation without market truth

- **VC**: 3/10
  - Would like: unusual architecture story
  - Would distrust: no validated moat, no external results
  - To take seriously: demonstrated edge or user adoption
  - To dismiss: architecture as product

- **Football/data person**: 5/10
  - Would like: pre-execution scan and contextual interpretation ideas
  - Would distrust: metaphor-to-score jump
  - To take seriously: historical replay or case-study evidence
  - To dismiss: overextended analogy

- **Finance professional**: 2.5/10
  - Would like: refusal to live-trade prematurely
  - Would distrust: seeded truth and unrealistic paper execution
  - To take seriously: real historical datasets, reconciled ledgers, and market-realistic paper layer
  - To dismiss: current “investable” language

- **GitHub visitor**: 5.5/10
  - Would like: lots of engineering and tests
  - Would distrust: giant repo, unclear spine, encoding issues
  - To take seriously: curated README and one strong demo
  - To dismiss: volume without clarity

- **Future collaborator**: 5/10
  - Would like: many interesting subproblems already explored
  - Would distrust: unclear priority order and integration depth
  - To take seriously: explicit roadmap and central contracts
  - To dismiss: too many parallel metaphors and no pruning discipline

## 12. Scientific and Quant Validity Audit

- Does the MVP make falsifiable claims? **Weakly**
- Are predictions measurable? **Partially**
- Are outcomes tracked? **Insufficiently**
- Are baselines defined? **Not credibly enough**
- Is there a naive benchmark? **Not in the canonical path**
- Is there out-of-sample testing? **Not meaningfully**
- Are false positives tracked? **Not as a core discipline**
- Are false negatives tracked? **Not adequately**
- Are confidence levels calibrated? **No**
- Are causal claims separated from correlations? **Not robustly**
- Are narrative claims separated from price claims? **Partially**
- Are regime shifts handled? **Heuristically**
- Are uncertainty and ignorance represented honestly? **Better than average**
- Does the system distinguish internal consistency from external truth? **Partially in doctrine, weakly in evidence**
- Does it distinguish paper-readiness from real-capital readiness? **Yes, strongly**

- Scientific validity score: **2.7 / 10**
- Quant validity score: **2.5 / 10**
- Current ceiling: **4.0 / 10**
- To reach 8/10:
  - labeled outcomes
  - benchmark comparisons
  - calibration curves
  - error accounting
  - historical replay
  - OOS validation
  - reconciliation-backed paper performance
- To reach 10/10:
  - this repo would need to become a measured research system first, then a production candidate. That is a multi-quarter program, not a refactor.

ScientificValidity =
`Falsifiability × MeasurementQuality × BaselineComparison × OutOfSampleValidation × Calibration × ErrorAccounting × Reproducibility`

Right now reproducibility is acceptable in seeded mode. Almost every other term is too weak.

## 13. Risk Audit

- **Technical risk**
  - Severity: 7
  - Probability: 8
  - Current mitigation: tests, deterministic engines
  - Missing mitigation: simplification and stronger contracts
  - Owner: `run_diagnostics_pipeline.py`, `pipeline_health_report.py`, `runtime_common.py`

- **Model risk**
  - Severity: 9
  - Probability: 8
  - Current mitigation: refusal-heavy doctrine
  - Missing mitigation: calibration, labels, benchmarks
  - Owner: scoring engines broadly

- **Data risk**
  - Severity: 9
  - Probability: 9
  - Current mitigation: seeded mode and explicit truth-origin reporting
  - Missing mitigation: real historical ingestion and provenance ledger
  - Owner: ingestion/adapters/runtime

- **Financial risk**
  - Severity: 8
  - Probability: 3 currently
  - Current mitigation: no real execution
  - Missing mitigation: none until live ambitions increase
  - Owner: paper execution / future execution modules

- **Legal risk**
  - Severity: 5
  - Probability: 4
  - Current mitigation: sidecar boundaries and documentation
  - Missing mitigation: stronger repo-level public disclaimers
  - Owner: docs/integrations

- **Ethical risk**
  - Severity: 5
  - Probability: 4
  - Current mitigation: non-advisory and no-live stance
  - Missing mitigation: explicit misuse examples
  - Owner: README/docs

- **Reputation risk**
  - Severity: 7
  - Probability: 7
  - Current mitigation: good tests and honesty in some docs
  - Missing mitigation: pruning fake sophistication
  - Owner: entire repo narrative

- **Overconfidence risk**
  - Severity: 9
  - Probability: 8
  - Current mitigation: many vetoes
  - Missing mitigation: false-negative and calibration accounting
  - Owner: scoring/reporting/action layers

- **Operational risk**
  - Severity: 7
  - Probability: 6
  - Current mitigation: fail-closed behavior
  - Missing mitigation: canonical ledger and recovery model
  - Owner: runtime/paper/reconciliation

- **Security risk**
  - Severity: 4
  - Probability: 3
  - Current mitigation: no secret-heavy or live execution logic
  - Missing mitigation: secret scanning and stricter file hygiene
  - Owner: repo config/CI

- **IP risk**
  - Severity: 5
  - Probability: 4
  - Current mitigation: license docs and sidecar rules
  - Missing mitigation: better quarantine of vendored experiments
  - Owner: external integration areas

- **License contamination risk**
  - Severity: 6
  - Probability: 3
  - Current mitigation: explicit GPL/AGPL sidecar contracts
  - Missing mitigation: CI policy to prevent accidental source import
  - Owner: adapter/integration boundaries

- **False-confidence risk**
  - Severity: 10
  - Probability: 8
  - Current mitigation: `DO_NOT_DEPLOY`
  - Missing mitigation: hard distinction between measured and heuristic confidence
  - Owner: health report, scoring engines, docs

## 14. Limit Analysis

- Architecture: current ceiling **6.5/10**
  - Reason: too many modules, too few canonical contracts.
  - To break ceiling: prune and centralize decision flow.

- Signal detection: current ceiling **6.0/10**
  - Reason: seeded/default inputs dominate.
  - To break ceiling: real replayable feeds.

- Contextual interpretation: current ceiling **7.0/10**
  - Reason: good logic, weak measured inputs.
  - To break ceiling: connect to real context features and validate predictive lift.

- Validation: current ceiling **5.5/10**
  - Reason: internal scoring without external truth.
  - To break ceiling: labels, benchmarks, calibration.

- Risk: current ceiling **7.0/10**
  - Reason: refusal is strong, quantitative risk is weak.
  - To break ceiling: explicit risk budgets and consequence modeling.

- State machine: current ceiling **6.5/10**
  - Reason: fragmented state ontologies.
  - To break ceiling: one transition hierarchy and persistence model.

- Testing: current ceiling **8.0/10**
  - Reason: broad unit tests, weak reality tests.
  - To break ceiling: historical/integration/OOS tests.

- Data ingestion: current ceiling **6.0/10**
  - Reason: placeholder and sidecar-heavy.
  - To break ceiling: one production-grade ingest path.

- Backtesting: current ceiling **4.0/10**
  - Reason: not central, not clearly validated.
  - To break ceiling: one rigorous backtest harness.

- Paper trading: current ceiling **4.5/10**
  - Reason: execution realism too weak.
  - To break ceiling: realistic mark/fill/reconciliation model.

- Reporting: current ceiling **8.0/10**
  - Reason: rich but overloaded.
  - To break ceiling: canonical report spine and causal blocker summaries.

- Documentation: current ceiling **7.2/10**
  - Reason: good doctrine, weak curation.
  - To break ceiling: public-friendly simplification and empirical evidence pages.

- Productization: current ceiling **5.5/10**
  - Reason: script sprawl.
  - To break ceiling: unified CLI and curated user journeys.

- Scientific validity: current ceiling **4.0/10**
  - Reason: no serious external evaluation loop.
  - To break ceiling: measurement-first rebuild.

- Showcase credibility: current ceiling **7.0/10**
  - Reason: impressive engineering volume, but credibility is capped by missing proof.
  - To break ceiling: one narrow validated result and a cleaner public narrative.

## 15. Full-Potential Roadmap

### P0 — Must fix before any serious claim

1. Build canonical evidence and decision ledger
2. Wire all binding vetoes into one action-permission contract
3. Add historical labeled replay dataset
4. Add naive benchmark comparison
5. Add calibration and error-accounting reports
6. Replace default paper fill assumptions with replayed marks/spreads
7. Resolve position truth through a canonical ledger policy

### P1 — Must fix before public technical showcase

1. Refactor `pipeline_health_report.py` into smaller contracts
2. Fix README encoding and curation
3. Remove or quarantine ornamental/vendored experiments from the public narrative
4. Add one architecture diagram and one canonical walkthrough
5. Consolidate duplicate math/helpers

### P2 — Must fix before using for real decisions

1. Real external ingestion with provenance and rate-limited degraded modes
2. Paper broker realism and reconciliation discipline
3. State ontology consolidation and forbidden-transition tests
4. Source reliability history

### P3 — Nice but non-critical

1. Better dashboard UX
2. Richer demo packaging
3. Performance optimization and batch processing improvements

## 16. 30-Day Hardening Plan

Day 1-3:
- Goal: define canonical contracts
- Touch: `action_engine.py`, `run_diagnostics_pipeline.py`, new shared models
- Work: create `CanonicalDecision` and `SignalEvidence` types
- Tests: action-gate integration tests
- Exit criteria: one typed decision object governs action output
- Risk reduced: fake integration

Day 4-6:
- Goal: build truth ledger
- Touch: runtime/paper/reconciliation modules
- Work: append-only decision and signal journal
- Tests: persistence and replay
- Exit criteria: every decision has provenance
- Risk reduced: audit leakage

Day 7-10:
- Goal: historical replay dataset
- Touch: ingestion, fixtures, replay scripts
- Work: ingest one real archived dataset with outcomes
- Tests: deterministic replay
- Exit criteria: one narrow real replay works end to end
- Risk reduced: seeded-only illusion

Day 11-13:
- Goal: baseline comparisons
- Touch: signal validation and reporting
- Work: naive benchmark layer
- Tests: benchmark summaries in reports
- Exit criteria: every evaluation has a baseline
- Risk reduced: self-deception

Day 14-16:
- Goal: calibration
- Touch: scoring/reporting modules
- Work: reliability stats and threshold provenance
- Tests: calibration report generation
- Exit criteria: at least one score family has calibration diagnostics
- Risk reduced: false confidence

Day 17-19:
- Goal: paper execution realism
- Touch: `paper_execution.py`, reconciliation, marks
- Work: slippage/spread/partial-fill assumptions
- Tests: event-driven fill tests
- Exit criteria: no default `100.0` fallback in serious mode
- Risk reduced: PnL fantasy

Day 20-22:
- Goal: state machine hardening
- Touch: bull/state modules
- Work: unified state ontology and override order
- Tests: forbidden transitions, persistence
- Exit criteria: one state hierarchy doc and contract
- Risk reduced: ambiguous semantics

Day 23-25:
- Goal: external evidence integration
- Touch: adapter registry, Apollo, diagnostics
- Work: canonical evidence-routing example
- Tests: evidence changes final decision or explicitly does not
- Exit criteria: external evidence no longer ornamental
- Risk reduced: fake integration

Day 26-28:
- Goal: report simplification
- Touch: `pipeline_health_report.py`
- Work: split into subreports and canonical summary
- Tests: summary invariants
- Exit criteria: fewer giant-file responsibilities
- Risk reduced: maintainability collapse

Day 29-30:
- Goal: public credibility pass
- Touch: README/docs
- Work: fix encoding, add architecture diagram, one measured case study
- Tests: smoke CLI and doc consistency
- Exit criteria: repo can be shown without overselling
- Risk reduced: showcase misfire

## 17. Brutal Final Assessment

1. What is genuinely impressive here?
   - The amount of deterministic safety/reporting/test scaffolding is unusually serious for an MVP.
2. What is dangerously weak?
   - External truth, calibration, and canonical action enforcement.
3. What is missing that you may be avoiding?
   - Historical labels, naive benchmarks, false-positive accounting, and pruning of weak layers.
4. What is overbuilt?
   - The metaphor-driven score/state surface.
5. What is underbuilt?
   - Real data ingestion, reconciliation, and measurable evaluation.
6. What should be deleted?
   - Anything that does not change a measured decision or produce unique evidence after a proof period. Vendored non-core experiments should be isolated or removed from the main story.
7. What should be renamed?
   - Any score implying investability or strong validity before calibration. `investable_signal_score` is too ambitious today.
8. What should become the central spine of the MVP?
   - `Evidence → Interpretation → Validation → Risk/Veto → Canonical Decision → Paper Ledger → Reconciliation → Health Summary`
9. What should remain private?
   - The most metaphor-heavy experimental layers until they prove decision value.
10. What can be shown publicly?
   - The disciplined safety posture, the testing discipline, one clear architecture diagram, and one validated historical replay.
11. What would a serious engineer criticize first?
   - Giant files, weak typed interfaces, and under-integrated modules.
12. What would a quant person criticize first?
   - No calibration, no OOS, no realistic execution, no benchmark.
13. What would an employer like?
   - Ambition, systemization, testing, and fail-closed thinking.
14. What would an employer distrust?
   - Overengineering and metaphor inflation without pruning.
15. What would make this MVP cross from interesting to serious?
   - One narrow, measured, replayable use case with documented error rates and benchmark superiority.
16. What is the fastest path to 7/10?
   - Canonical decision spine + one real replay dataset + benchmark + reconciliation cleanup.
17. What is the fastest path to 8/10?
   - Add calibration, realistic paper execution, and state-machine hardening on top of that.
18. What would be required for 9/10?
   - Multi-regime external validation, stable operations, real provenance, and serious paper-track history.
19. What is unrealistic about reaching 10/10?
   - A repo this ambitious cannot jump from seeded architecture lab to production-grade scientific engine by adding more modules.
20. What is the one sentence you need to hear, even if it hurts?
   - **Right now this repo is better at describing what a good signal system should think about than at proving it can actually make good signal decisions.**

## 18. Scorecard Summary

| Category | Current score | 30-day realistic score | 90-day realistic score | True 10/10 requirement |
| -------- | ------------: | ---------------------: | ---------------------: | ---------------------- |
| Architecture | 5.0 | 6.2 | 7.0 | Canonical typed decision spine with pruned modules |
| Data | 2.5 | 4.5 | 6.5 | Multi-source labeled historical and live-quality data |
| Signal quality | 4.5 | 5.5 | 6.8 | Measured predictive lift over benchmarks |
| Validation | 4.0 | 5.2 | 6.8 | Calibration, OOS testing, false-positive accounting |
| Risk | 5.7 | 6.5 | 7.2 | Quantified risk budgets and enforced action gating |
| Testing | 7.2 | 7.8 | 8.5 | Reality-facing integration and replay coverage |
| Reporting | 7.3 | 7.8 | 8.2 | Canonical decision and blocker summaries |
| Product | 4.6 | 5.8 | 6.8 | Unified CLI, dashboard, onboarding, case-study flow |
| Scientific validity | 2.7 | 4.8 | 6.8 | Outcome-linked, reproducible, calibrated research discipline |
| Showcase credibility | 5.9 | 6.8 | 7.6 | Clean public narrative plus measured evidence |
| Overall MVP | 4.8 | 5.9 | 7.0 | Real truth loop, canonical decision spine, calibrated validation |

## 19. Required Output Style

This audit intentionally used:
- Direct language
- No hype
- No motivational filler
- File-grounded claims
- Concrete examples
- Tables where useful
- Equations where useful
- Brutal honesty
- Clear priorities

The main conclusion is simple:
- The repo is not a toy in the sense of effort.
- It is a toy if judged by externally validated decision quality.
- It is a promising research architecture if it stops mistaking module count for proof.
