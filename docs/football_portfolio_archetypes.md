# Football Portfolio Archetypes

This layer classifies assets into football-derived portfolio roles without
turning the MVP into an execution bot. It suggests, ranks, blocks, logs, and
explains only.

## Doctrine

Gate order is preserved:

`Policy veto > Chaos / Heat / Risk Guards > Primary Role Integrity > Durability / Validation > Archetype Score > Raw Signal`

Primary role integrity outranks secondary contribution.

## Core Formulas

```text
PreferredAsset = RoleIntegrity * DurableOutput * ControlledUpside
BainesValue = MultiChannelOutput / RelativeCost
NetValue = Upside - StructuralFailureCost
TarkowskiValue = DefensiveReliability + RareSetPieceUpside
IdealUpside = HighImpactEvent * ZeroStructuralCompromise
RoleMismatchScore = OutputPercentile - PricePercentile
BPM = ValidatedOutputScore / RiskAdjustedCost
SystemDependencyRisk = Weakness * ExposureLevel
RareUpsideScore = CatalystProbability * ImpactMagnitude * StructuralSafety
TrueValue = Output / (Cost + Fragility + Attention)
CapitalAdmission = Signal * Validation * Durability * ExecutionSurvivability
AcceptUpside iff StructuralCompromise = 0
```

Scoring blocks:

```text
BAINES_SCORE =
    0.25 * RoleMismatch
  + 0.25 * MultiChannelOutput
  + 0.20 * Repeatability
  + 0.15 * Catalyst
  + 0.15 * AttentionDiscount

TARKOWSKI_SCORE =
    0.50 * Defense
  + 0.30 * Survival
  + 0.20 * RareUpside
```

## Archetypes

- `BAINES_EXPANSION`: undervalued, role-sound, multi-channel expansion candidate
- `TARKOWSKI_CORE`: defensive-core, survival-first candidate with rare upside
- `ALONSO_FINISHER_VARIANT`: defensive label with finisher-like upside, still role-sound
- `TRENT_SYSTEM_DEPENDENT_RISK`: high-output but support-system dependent
- `REJECT_PRIMARY_ROLE_FAILURE`: upside ignored because primary role failed
- `REJECT_CHAOS_REGIME`: chaos regime blocked non-defensive-core candidate
- `UNCLASSIFIED`: observation-grade only

## Hard Gates

- `PRIMARY_ROLE_THRESHOLD = 0.60`
- `STRUCTURAL_COMPROMISE_MAX = 0.45`
- `SYSTEM_DEPENDENCY_MAX = 0.65`
- `CHAOS_ALLOWED_ARCHETYPES = {TARKOWSKI_CORE}`

If `policy_state` forbids new risk, archetype output is advisory only and
admission is blocked.

## Allocation Guidance

Normal regime:

- Tarkowski core: `40-60%`
- Baines expansion: `30-40%`
- Optional spikes: `5-15%`

Chaos or restricted regime:

- Tarkowski core: `70-100%`
- Baines expansion: `0%`
- Optional spikes: `0%`

These are recommendation bands only. Human remains final executor.

## Diagnostics Fields

The health report surfaces:

- `football_portfolio_archetype_engine_available`
- `football_portfolio_archetype_engine_state`
- `football_baines_candidates_count`
- `football_tarkowski_candidates_count`
- `football_alonso_variant_count`
- `football_trent_risk_count`
- `football_primary_role_rejections_count`
- `football_chaos_rejections_count`
- `football_top_baines_candidate`
- `football_top_tarkowski_candidate`
- `football_portfolio_mode`
- `football_allocation_recommendation`
- `football_policy_veto_applied`

If runtime writes are enabled, a stamped report is written to:

- `runtime/football_portfolio_archetype_report.json`
