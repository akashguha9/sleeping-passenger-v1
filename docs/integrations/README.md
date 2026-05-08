# External Evidence Integrations

These integrations exist to ingest optional third-party outputs as evidence candidates, not as decision authority.

Doctrine:
- External output is evidence, not truth.
- Sidecar repos may detect, forecast, argue, or summarize.
- Only the MVP core may validate, veto, promote, and paper-execute.
- Real execution remains disabled.

Safety hierarchy:
- Policy veto
- Apollo Abort Guard
- Diablo chaos veto
- Heat/risk guards
- Murcielago durability validation
- Aventador promotion gate
- Gallardo paper execution discipline
- Analyst/model/trend opinions
- Raw signals

Evidence contract:
- Every evidence object must include `license_boundary`.
- Every evidence object must include `data_truth_origin`.
- `real_execution_allowed` is always `false`.
- Maximum allowed action is `PAPER_TRADE`.

Boundary types:
- Sidecar: exported files only, no source imports.
- Optional dependency: lazy import only, tests pass without install.
- Doctrine reference: original MVP implementation inspired by public-domain safety concepts.

Routing formula:

`InvestableSignal = Detection × ContextualInterpretation × MultiSourceValidation × Durability × ExecutionSurvivability × AbortSafety`

Doctrine:

`A repo can detect.`
`A model can forecast.`
`An agent can argue.`
`A trend monitor can observe.`
`A terminal can summarize.`
`But only the MVP core can validate, veto, promote, and paper-execute.`

How to enable:
- Edit `config/external_adapters.yaml`
- Enable only the adapters you intend to use
- Provide exported sidecar paths through env vars when needed

How to test:
- `python -m compileall scripts tests`
- `python -m pytest tests -q`

Future roadmap:
- richer evidence reconciliation
- additive health-report surfacing if needed
- offline evidence snapshots for diagnostics review
