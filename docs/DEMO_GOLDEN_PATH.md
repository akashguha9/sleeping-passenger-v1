# Demo Golden Path — for a skeptical reviewer

Fifteen minutes, no faith required. Every claim below is a command you
run or a test that pins it.

## What this is

An **advisory-only** trading journal and decision-intelligence system.
It scores candidate theses through a layered simulator (signal physics,
market adaptation, edge lifecycle, risk convergence), explains every
verdict's causes, records falsifiable predictions, and grades itself
against resolved outcomes. It cannot trade: no broker code exists, CI
gates forbid it (`kante_defensive_gate`), and every response stamps
`execution_gate: LOCKED`.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate        # Python 3.12+
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q                            # ~7k tests, ~4 min
python scripts/api_server.py                         # binds 127.0.0.1:8000
cd frontend && npm ci && npm run dev                 # localhost:3000
```

## The five proof points

1. **A verdict that explains itself.** `POST /simulator/evaluate` with
   `tests/test_simulator_cherry_pick_pipeline.py::STRONG_PAYLOAD`-style
   JSON. The response carries the decision, every gate result, reason
   codes, self-feed provenance (which engine derived which input), and
   the risk-convergence committee's minutes.
2. **A model that doubts itself.** Add `"counterfactual_audit": true`
   to the payload: 16 perturbations grade whether the verdict survives
   alternative histories; the gaming surface is published, not denied
   (`gameable_inputs`).
3. **A thesis with a death date.** Add a `lifecycle` section: the
   expiry clock (`t = h·log₂(E₀/T)`), carrying-capacity bottleneck,
   kill switches, and fragility ship with the verdict.
4. **Calibration that can't lie about itself.**
   `python scripts/import_outcomes.py examples/outcomes/first_light_empirical.jsonl --streak`
   — 4 real operator-attested trades; no alpha claimed without a
   benchmark, no verdict below the observation floor, tiers never
   blended. Read `docs/CALIBRATION_FIRST_LIGHT.md` for what this does
   and does not prove.
5. **A repo that knows its own live surface.**
   `python scripts/live_surface_census.py` — which modules can touch
   user output (72), which are batch CLIs (31), which are quarantined
   (4, pinned by a CI guard).

## Where the evidence lives

`docs/LIVE_SURFACE.md` (code map) · `docs/THREAT_MODEL.md` (security)
· `docs/CALIBRATION_FIRST_LIGHT.md` (outcome evidence) ·
`docs/STRATEGY_ENGINE.md` + `docs/MARKET_PHYSICS_SIMULATOR.md` (model
doctrine, worked examples test-pinned).

## What is intentionally NOT claimed

No claim of edge (n=4 resolved trades; the streak audit itself says
`SMALL_SAMPLE`). No live data feeds. No fitted weights — every
threshold is doctrine-derived and labeled. No execution, ever.
