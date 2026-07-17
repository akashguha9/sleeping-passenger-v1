# Component Role Contracts

Every major SIL component has a **versioned, immutable** role contract declared in
`scripts/simulation_intelligence/role_contracts.py` (`ROLE_CONTRACT_VERSION`).
Contracts are declared **before** evaluation and their dimension weights are
immutable copies — a component can never choose an easier role after seeing its
results.

Each contract carries: component id/name, role template, primary + secondary +
**forbidden** mandates, responsibilities, non-responsibilities, required inputs,
expected outputs, failure modes, success/prevention/recovery events, reliability
expectation, evidence requirements, an immutable dimension-weight vector, and an
**honest ceiling** on the role-adjusted performance score.

Every contract shares a universal forbidden-mandate block: *place a broker order,
route an order, size a position automatically, execute a trade, raise
`ai_execution_count`, unlock `execution_gate`, present simulated evidence as
measured.*

## Registered components (18)

| Component | Role template | Primary mandate | Honest ceiling | Top-weighted dimensions |
|---|---|---|--:|---|
| `lens.physics` | SIM_LENS | interpret the candidate through the Physics lens and contribute orthog | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `lens.chemistry` | SIM_LENS | interpret the candidate through the Chemistry lens and contribute orth | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `lens.biology` | SIM_LENS | interpret the candidate through the Biology lens and contribute orthog | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `lens.racing` | SIM_LENS | interpret the candidate through the Racing lens and contribute orthogo | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `lens.chess` | SIM_LENS | interpret the candidate through the Chess lens and contribute orthogon | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `lens.poker` | SIM_LENS | interpret the candidate through the Poker lens and contribute orthogon | 9.4 | coverage, role_fidelity, uncertainty_handling |
| `council` | COUNCIL | aggregate six lenses without naive averaging and produce an explainabl | 9.3 | role_fidelity, risk_interception, error_prevention |
| `risk_engine` | RISK_ENGINE | intercept tail risk and prevent unsafe confidence; fail closed | 9.4 | risk_interception, error_prevention, role_fidelity |
| `calibration` | CALIBRATION | link SIL predictions to leakage-safe outcomes and report honest calibr | 9.3 | calibration_integrity, evidence_quality, role_fidelity |
| `evidence_provenance` | EVIDENCE_PROVENANCE | deduplicate evidence and measure source concentration so shared inputs | 9.4 | evidence_quality, role_fidelity, information_efficiency |
| `scenario_generator` | SCENARIO_GENERATOR | provide broad, orthogonal India/US stress + operational scenarios | 9.3 | coverage, role_fidelity, context_difficulty |
| `stress_testing` | STRESS_TESTING | apply scenarios under bounded stochastic runs and surface tail impact | 9.2 | risk_interception, coverage, adversarial_resilience |
| `replay` | REPLAY | reproduce a stored run exactly from its seed + data cutoff | 9.5 | reliability, consistency, role_fidelity |
| `operator_frontend` | OPERATOR_FRONTEND | make simulated-vs-measured evidence and warnings unmistakable so the o | 9.1 | operator_usefulness, explainability, error_prevention |
| `adapter.stockfish` | ADAPTER | report availability honestly and degrade gracefully; never become a re | 9.0 | reliability, role_fidelity, recovery_ability |
| `adapter.copasi` | ADAPTER | report availability honestly and degrade gracefully; never become a re | 9.0 | reliability, role_fidelity, recovery_ability |
| `signal_reactor` | SIGNAL_REACTOR | surface fresh, provenance-tagged candidates and fail closed on stale o | 9.0 | risk_interception, error_prevention, role_fidelity |
| `signal_bridge` | SIGNAL_BRIDGE | turn live signal/OHLCV state into a validated MarketObservation withou | 9.2 | role_fidelity, error_prevention, information_efficiency |
## The 20 dimensions

`role_fidelity, coverage, risk_interception, error_prevention, decision_influence,
reliability, consistency, context_difficulty, recovery_ability, collaboration,
information_efficiency, uncertainty_handling, explainability, operator_usefulness,
resource_efficiency, evidence_quality, calibration_integrity,
adversarial_resilience, runtime_reach, regression_resistance`

## Role templates

Weights are role-specific (`_ROLE_WEIGHTS`): a `RISK_ENGINE` weights
`risk_interception`/`error_prevention` highest and gives near-zero weight to
opportunity generation; an `OPERATOR_FRONTEND` weights `operator_usefulness`/
`explainability` highest; a `SIM_LENS` weights `coverage`/`uncertainty_handling`/
`decision_influence` and is never punished for not executing trades. See
`docs/kante_index_methodology.md` for how the weights feed the score.
