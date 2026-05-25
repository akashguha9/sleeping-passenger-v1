# Legal / Privacy / Compliance Model

> **Engineering honesty, not legal advice.** This document states the
> engineer's intent and the repo's *visible, testable* behaviour. A qualified
> lawyer must review every external-facing claim before any non-operator use.
> Companion docs: `ADVISORY_DISCLOSURE.md`, `DATA_SOURCE_LICENSE_REGISTER.md`,
> `LEGAL_PRIVACY_NOTES.md`, `ADVISORY_ONLY_SAFETY_MODEL.md`.

## 1. Product posture

- **Local-first, single-operator.** One person, one machine.
- **Advisory-only.** No automated execution surface exists anywhere.
- **No broker integration.** No code path places, modifies, or cancels an order.
- **No personalized financial advice.** Outputs are interpretations, scores,
  and flags — never personal investment recommendations.
- **Human-in-command.** A human makes the final decision on every trade.

These are not aspirations — they are enforced by tests and by
`scripts/compliance_preflight.py`, which fails if a broker route, an autonomous
trading claim, an unlocked execution flag, or a missing disclosure appears.

## 2. The compliance gate

`python -m scripts.compliance_preflight` checks, read-only and offline:

| Check | Fails when |
|---|---|
| `no_broker_execution_routes` | API server exposes a broker / order route. |
| `no_autonomous_trading_claims` | A surface doc claims autonomous execution. |
| `advisory_disclosure_present` | `ADVISORY_DISCLOSURE.md` missing / lacks the statement. |
| `human_final_decision_language` | The disclosure lacks human-final-decision language. |
| `data_source_register_exists` | `DATA_SOURCE_LICENSE_REGISTER.md` missing. |
| `secrets_not_committed` | `.env` is not gitignored. |
| `jsonl_audit_only_sqlite_canonical` | The truth model is violated. |
| `exports_no_secrets` | A committed export contains a secret-like token. |
| `no_personalized_adviser_claim` | A doc claims to be a personal financial advisor. |

## 3. Data & privacy

- All operator data lives in local SQLite (`runtime/mvp_local.db`,
  `MVP_DB_PATH`-configurable). **SQLite is canonical.**
- JSONL logs are an **audit-only mirror** — never canonical. Nothing in the
  repo may flip this (`advisory_contract.canonical_truth_declaration`).
- No personal data leaves the machine except calls the operator explicitly
  makes to configured data sources (see the license register).
- API keys live only in `.env` (gitignored) and are redacted from AI payloads.

## 4. Authorization & responsibility

- Local roles (`scripts/operator_auth.py`): **VIEWER < OPERATOR < ADMIN**.
  This is a local authorization *floor*, not a SaaS auth system. No role — not
  even ADMIN — can unlock broker execution.
- The operator is solely responsible for every decision, for compliance with
  each data source's ToS, and for obtaining qualified advice before acting.

## 5. Limits of this model

- This is not a substitute for legal counsel.
- It does not warrant data accuracy, completeness, or timeliness.
- It is not a public SaaS; there are no user accounts beyond a local token and
  no payment processing.
