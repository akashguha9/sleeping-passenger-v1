# Hosted / Private Beta Proof Plan

**Sprint:** proof_loop_hardening_sprint, Phase 9.

This is the *plan* — nothing here is deployed yet.  Claude did not
deploy any resource as part of this sprint.

## What "private beta readiness" requires

```
private_beta_ready =
        hosted_uptime_pct >= 99.0 over >= 7 days
    AND evidence_status in {SUFFICIENT_FOR_INVESTOR_DEMO,
                            SUFFICIENT_FOR_PRIVATE_BETA}
    AND N_real >= 20
    AND no execution endpoints
    AND secrets managed outside repo
    AND auth enabled
```

All five conditions must hold simultaneously.  Any one missing → not
ready.

## Uptime math

`scripts/hosted_uptime_report.py` reads a local JSON/CSV of pings and
computes:

```
uptime_pct = 100 * successful_checks / total_checks
```

with windows `window_start_utc` / `window_end_utc` so partial windows
can be flagged.  The default is offline / dry-run: pings are read from
disk, never live network calls.

## Why this is offline by default

- No cloud resource is required.
- No secret is read.
- No broker / order endpoint exists, period.
- The script can be pointed at a real `--url` only when an operator
  consciously enables live mode; default behaviour never makes a
  network request.

## Operator runbook (when ready)

```powershell
# Offline: feed it a local pings JSON
python scripts/hosted_uptime_report.py --pings runtime/ops/pings.json --write

# Output goes to runtime/release/hosted_uptime_report.json
```

The `evidence_manifest.py` then reads that file and unlocks
`SUFFICIENT_FOR_PRIVATE_BETA` *only if* the rest of the proof loop has
also closed.

## Hard rules

- Do NOT add a broker / order / fill / position / execution endpoint.
- Do NOT bypass the local API token gate.
- Do NOT log secrets, ever.
- Do NOT inflate uptime to make the manifest pass.

## Cross-references

- `docs/EVIDENCE_BUNDLE.md` — how this feeds the readiness label.
- `docs/HOSTED_DEPLOYMENT_PLAN.md` — design of the eventual deploy.
- `docs/PRIVATE_BETA_AUTH_DESIGN.md` — auth design.
- `docs/CREDENTIAL_HYGIENE.md` — secret handling.
