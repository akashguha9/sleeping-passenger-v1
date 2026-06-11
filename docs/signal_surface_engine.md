# Signal Surface Engine

`scripts/signal_surface_engine.py` adds a read-only signal surface integrity layer to the MVP.

## Doctrine

- Shape first, finish last.
- Do not polish broken structure.
- Wax cannot fix a bad repair.
- Presentation is allowed only after validation.
- A repair is not finished until it survives stress.
- The visible surface is only the final layer of a hidden stack.

Presentation does not increase structural validity.

## Formula Stack

### Seamless output

`SeamlessSignalOutput = StructuralCorrectionScore × ResidualSmoothnessScore × AdhesionCompatibilityScore × NarrativeFitScore × ValidationProtectionScore × PresentationClarityScore`

### Visible distortion

`VisibleSignalDistortion = 0.45 × StructuralDistortion + 0.35 × ReflectionDistortion + 0.20 × FinishDistortion`

### Core layers

- `SubstrateIntegrityScore = 0.35 × source_reliability_score + 0.25 × data_completeness_score + 0.20 × (1 − raw_noise_score) + 0.20 × (1 − contradiction_score)`
- `AdhesionCompatibilityScore = 0.40 × schema_readiness_score + 0.30 × context_compatibility_score + 0.20 × metadata_completeness_score + 0.10 × data_completeness_score`
- `NarrativeFitScore = 0.45 × narrative_clarity_score + 0.25 × context_compatibility_score + 0.20 × raw_signal_strength + 0.10 × source_reliability_score`
- `NarrativeFitScore *= (1 − 0.50 × contradiction_score)`
- `ValidationProtectionScore = 0.30 × source_reliability_score + 0.25 × (1 − contradiction_score) + 0.20 × (1 − volatility_score) + 0.15 × data_completeness_score + 0.10 × (1 − heat_risk_score)`

### Boundary blending

- `BoundaryVisibility = 0.35 × DataMismatch + 0.30 × LogicMismatch + 0.20 × ToneMismatch + 0.15 × InterfaceMismatch`
- `BoundaryBlendingScore = 1 − BoundaryVisibility`

### Cure gate

- veto, contradiction shock, or chaos can reset cure to `SHOCK_RESET`
- insufficient stabilization time keeps the surface in `CURING`
- unstable volatility blocks promotion

### Final quality

- `CoreIntegrityScore` is a weighted geometric blend of substrate, structure, smoothness, preparation, and adhesion
- `FinishDurabilityScore` is a weighted geometric blend of narrative fit, validation protection, boundary blending, cure stability, presentation clarity, and stress survival
- `SurfaceSystemScore = SubstrateIntegrity × Preparation × Adhesion × BoundaryBlending × FinishDurability`
- `OutputQualityCeiling = SubstrateIntegrityScore × ProcessQualityScore`
- `FinalCappedScore = min(weighted_geometric_score_all_layers, OutputQualityCeiling + allowed_process_alpha)`

## Enums

- `DamageClass`
- `RepairMode`
- `LayerStatus`
- `CureGateStatus`
- `FinishHonestyFlag`
- `SurfaceDecision`
- `BullSurfaceState`

## Bull mapping

- `MIURA_RAW_DENT`: raw strength without validation
- `MURCIELAGO_DURABILITY_REPAIR`: repair and stress-survival stage
- `AVENTADOR_VALIDATED_SURFACE`: validated but not execution-finish ready
- `GALLARDO_EXECUTION_FINISH`: validated and decision-ready (advisory surface finish — never broker execution)
- `ISLERO_SHOCK_RECLASSIFICATION`: contradiction or cure shock reset
- `DIABLO_CHAOS_SURFACE_VETO`: policy or chaos veto
- `HURACAN_FAST_TRACK_SURFACE`: only after policy, chaos, validation, stress, and cure gates pass

## Safety doctrine

- Policy veto outranks all surface improvements.
- Chaos, contradiction shock, and cure instability outrank presentation.
- HURACAN fast-track never bypasses policy, chaos, validation, stress-survival, or cure gates.
- The surface layer is diagnostic only. It does not create live execution authority.
