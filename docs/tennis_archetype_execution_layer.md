# Tennis Archetype Execution Layer

Purpose: classify signal execution style using tennis archetypes without adding execution authority.

Core rules:
- `DetectedSignal != ExecutableSignal`
- `InvestableSignal = Detection * Validation * Durability * ExecutionSurvivability`
- policy veto outranks chaos control, durability, fast-track, style fit, and raw attractiveness
- aesthetic appeal cannot override structural reliability
- momentum cannot override validation floor

Execution styles:
- `FRICTIONLESS_CONTROL`
- `PRESSURE_DURABILITY`
- `CHAOS_ABSORPTION`
- `PATTERN_DISRUPTION`
- `FIRST_STRIKE`
- `SINGLE_WEAPON_DOMINANCE`
- `HYBRID_FAST_TRACK`
- `CONTROLLED_CHAOS`
- `EMOTIONAL_VOLATILITY`
- `REPEATABLE_PRECISION`
- `MOMENTUM_SPIKE`
- `AESTHETIC_RAW_SIGNAL`
- `HIGH_VARIANCE_SHOTMAKING`

Bull-state mapping:
- Federer -> `FRICTIONLESS_CONTROL` -> `GALLARDO`
- Nadal -> `PRESSURE_DURABILITY` -> `MURCIELAGO`
- Djokovic -> `CHAOS_ABSORPTION` -> `AVENTADOR` with `DIABLO` guard
- Murray -> `PATTERN_DISRUPTION` -> `ISLERO`
- Roddick -> `FIRST_STRIKE` -> `HURACAN`
- Del Potro -> `SINGLE_WEAPON_DOMINANCE` -> `AVENTADOR`
- Alcaraz -> `HYBRID_FAST_TRACK` -> `HURACAN`
- Bublik -> `CONTROLLED_CHAOS` -> `DIABLO/ISLERO`
- Safin -> `EMOTIONAL_VOLATILITY` -> `DIABLO` risk
- Nishikori -> `REPEATABLE_PRECISION` -> `GALLARDO`
- Shelton -> `MOMENTUM_SPIKE` -> `HURACAN + MIURA`
- Tsitsipas -> `AESTHETIC_RAW_SIGNAL` -> `MIURA` until validated
- Verdasco -> `HIGH_VARIANCE_SHOTMAKING` -> `MIURA + DIABLO` risk

Runtime artifact:
- `runtime/tennis_archetype_report.json`

Threshold config:
- `config/tennis_archetype_config.json`
