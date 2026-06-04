# Demo Readiness Checklist

Advisory-only product. This checklist is the one-glance verification path for a
demo. Nothing here authorizes execution.

## One-command verification

**Frontend** (from `frontend/`):
```
npm test          # vitest — full suite, 0 act warnings expected
npx tsc --noEmit  # typecheck (no `typecheck` script; tsc is canonical)
npm run build     # Next.js production build
```

**Backend** (from repo root):
```
python -m pytest tests -q
python scripts/run_diagnostics_pipeline.py --summary   # governance locks
python scripts/mvp_readiness_report.py --summary        # unified readiness headline
```

## What "demo ready" means here

| Check | Expectation |
|---|---|
| Frontend tests | all pass, **0 React act warnings** |
| Typecheck | `tsc --noEmit` clean |
| Build | `next build` succeeds for all routes |
| Demo pages import | cockpit / live-signals / reconciliation / manual-trade-log render (smoke: `demo-smoke.spec.tsx`) |
| Source tabs | strictly source-filtered (Kalshi/Polymarket/Disagreement tabs exclude foreign rows; switching replaces, never appends) |
| Advisory language | every advisory card shows advisory chips; **no** BUY/SELL/EXECUTE/ARBITRAGE wording |
| Governance | `DO_NOT_DEPLOY`, `can_deploy_capital=false`, `action_authority=REVOKED`, `execution_integrity_state=LOCKED_EXECUTION`, `busquets_audit_state=HARD_VETO` |

## What demo readiness does NOT mean

- It does **not** mean the system can trade. Execution authority is REVOKED and
  doctrine is UNRATIFIED.
- It does **not** mean forward-observation confidence has been earned (see
  `docs/CHRONOLOGY_OBSERVATION_READINESS.md`).
- The Manual Decision Board is advisory human-review only
  (`docs/MANUAL_DECISION_BOARD_DOCTRINE.md`).
