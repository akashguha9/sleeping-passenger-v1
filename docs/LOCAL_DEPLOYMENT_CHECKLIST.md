# Local Deployment Checklist

> This MVP is intended for **local / single-operator demo** use only.
> It is not production trading software. It is not LAN-safe by default
> (depends on operator hardening). It is not internet-safe.

Before running the MVP locally:

## 1. Repository hygiene

- [ ] Working tree on a feature branch, not `main`.
- [ ] No `.env`, `.env.local`, or `*.env` file is tracked by git.
  Confirm with: `git ls-files | grep -i env` (should only show
  `*.env.example` templates).
- [ ] No raw Claude export is committed. Raw exports live outside the
  repo (e.g. `C:\Users\akash\Downloads\Claude Data\`). Only the
  sanitized digests under `docs/recovery/` may be committed.
- [ ] Runtime DB (`runtime/mvp_local.db`) is ignored.

`tests/test_local_security_floor.py` enforces several of these
automatically.

## 2. Backend bring-up

- [ ] Python 3.13+ installed.
- [ ] `pip install -r requirements.txt` succeeds.
- [ ] `python -m compileall scripts tests` succeeds.
- [ ] `python -m pytest tests -q` is green.
- [ ] `python scripts/api_server.py` starts on `127.0.0.1:8000` (the
  default). **Do not** bind to `0.0.0.0` on an untrusted network.
- [ ] `python scripts/pre_real_money_preflight.py` reports its readiness
  state. A `BLOCKED` outcome here is the system *working as designed*.

## 3. Frontend bring-up

- [ ] Node 20+.
- [ ] `cd frontend && npm install`.
- [ ] `npm run build` succeeds.
- [ ] `npm run dev` opens on `http://localhost:3000`.
- [ ] If you need a friendly hostname, use `npm run dev:sleepingpassenger`
  which binds `127.0.0.1`. Still local-only.

## 4. Safety invariants

Confirm visually on the running UI:

- [ ] Every page shows an `ADVISORY_ONLY` or `HUMAN_ONLY` badge.
- [ ] Manual trade log surface says "no broker call".
- [ ] Reconciliation page shows the backlog readiness chip.
- [ ] Signal inbox shows a `Reactor:` badge per card.
- [ ] Signal detail page shows the reactor diagnostics panel.
- [ ] Gallardo block, when present, renders a visible warning.

If any of these are missing, treat it as a bug, not a styling
preference.

## 5. Data hygiene

- [ ] No real-money credentials are stored anywhere in the repo.
- [ ] `MVP_API_TOKEN` is either unset (permissive local dev) or set
  via the local `.env` (never committed).
- [ ] If `MVP_API_TOKEN` is set, the frontend operator pastes the token
  into the **Local API token** panel on the Manual Trade Log page once
  per browser session.  The token is stored in `sessionStorage` only
  (cleared when the tab closes), is never displayed in full after save,
  is never sent via GET requests, and **does not authorise trade
  execution** — `execution_gate=LOCKED` stays locked regardless.
- [ ] No personal/medical/financial data is dumped into log files
  that get shipped to anyone.
- [ ] The Moltbook does not contain personally identifying notes that
  shouldn't leave the operator's machine.

## 6. Reset / clean state

To reset the local DB (destructive):

```
rm runtime/mvp_local.db
python -c "from scripts.persistence import ensure_schema; ensure_schema()"
```

This is destructive — only do it on a development machine.

## 7. What this checklist does NOT promise

- It does not make this MVP **production trading software**.
- It does not make this MVP **multi-user safe**.
- It does not promise **internet exposure safety** — CORS is configured
  for local development, not public deployment.
- It does not promise **HIPAA / GDPR / SOC2 compliance** — none of those
  are in scope.
- It does not unlock **broker execution** — broker execution is
  structurally impossible in this codebase by design (see
  `docs/ADVISORY_ONLY_SAFETY_MODEL.md`).

If you need any of the above, this is the wrong codebase.
