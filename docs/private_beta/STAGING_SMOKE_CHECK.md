# Staging Smoke Check

> Advisory-only.  No live staging URL is currently deployed.  This doc
> defines the **shape** of the smoke check so the readiness report can
> honestly record `staging_deploy=0` until the URL exists.

## Required surfaces

A passing staging smoke check produces, in order:

1. `GET /health` → 200 with `advisory_status=ADVISORY_ONLY`,
   `execution_gate=LOCKED`, `broker_api_called=false`,
   `ai_execution_count=0`.
2. `GET /live-sources/status` → 200, payload renders with at least one
   source.
3. `GET /source-health/summary` → 200, all entries carry the safety
   stamps.
4. `GET /calibration/report` → 200 (or 503 with a structured stamp) and
   the embedded report has `predictive_claim_allowed=false` until the
   calibration corpus reaches N_real ≥ 200.
5. `GET /watchdog/summary` → 200 or 503; both must carry the stamps.

## What the smoke check must reject

- A 200 response with `broker_api_called=true`.
- A 200 response with `execution_gate != "LOCKED"`.
- Any payload missing `advisory_status`.
- Any error payload that contains a credential-shaped string.

## Local rehearsal

```
python scripts/api_server.py &
curl -fsS http://127.0.0.1:8000/health | jq -e '.execution_mode=="HUMAN_ONLY"'
curl -fsS http://127.0.0.1:8000/live-sources/status | jq -e '.advisory_status=="ADVISORY_ONLY"'
curl -fsS http://127.0.0.1:8000/source-health/summary | jq -e '.execution_gate=="LOCKED"'
```

When a hosted staging URL exists, swap `127.0.0.1:8000` for that URL
and the same contract applies.  Until then,
`runtime/release/private_beta_readiness_report.json` honestly reports
`staging_deploy=0`.
