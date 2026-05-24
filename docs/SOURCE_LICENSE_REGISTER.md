# Source License / ToS Register (Integrated Sprint)

> **Engineering honesty, not legal advice.**  This is the engineer's
> current read of each external data source's terms.  The companion
> machine-readable register at
> `runtime/compliance/source_license_register.json` is the canonical form
> the release gate validates against.  The legacy human-readable register
> lives at `docs/DATA_SOURCE_LICENSE_REGISTER.md`.

Each entry's posture is one of:

- `VERIFIED` — the engineer has read the terms and the recorded answer
  reflects that reading.
- `NEEDS_REVIEW` — the engineer is uncertain and a lawyer must review
  before non-operator use.
- `UNVERIFIED` — terms have not been read.

## Sources covered

| Provider          | Source type    | Auth required | Verification |
|-------------------|----------------|---------------|--------------|
| yfinance          | price          | No            | NEEDS_REVIEW |
| SEC EDGAR         | filings        | UA only       | VERIFIED     |
| GDELT             | news_event     | No            | VERIFIED     |
| NewsAPI           | news_event     | API key       | NEEDS_REVIEW |
| Polymarket Gamma  | prediction     | No            | NEEDS_REVIEW |
| Polymarket CLOB   | prediction     | No            | NEEDS_REVIEW |
| Kalshi            | prediction     | API key       | NEEDS_REVIEW |
| Etherscan         | onchain        | API key       | NEEDS_REVIEW |
| Blockscout        | onchain        | No            | NEEDS_REVIEW |
| xAI (Grok)        | ai_report      | API key       | NEEDS_REVIEW |
| Local fixtures    | local_fixture  | No            | VERIFIED     |

## Constraints already enforced in code

- **No redistribution** — provider payloads never leave the local SQLite DB.
- **Read-only adapters** — every loader is read-only; no broker order is
  ever placed.
- **Rate limits** — `scripts/rate_limiter.py`, per-source runners.
- **Secrets** — every key lives in `.env` (gitignored).
- **Attribution** — surface docs already attribute SEC EDGAR and GDELT.

## Items requiring lawyer review

1. `yfinance` redistribution terms (use is personal / non-commercial).
2. `NewsAPI` free-tier commercial restrictions.
3. `Polymarket` and `Kalshi` prediction-market terms (read-only, no
   trading via this MVP, but the engineer cannot confirm commercial-use
   posture).
4. `xAI` ToS for output handling.

## Adding a new source

1. Add a row to the JSON register under
   `runtime/compliance/source_license_register.json`.
2. Confirm the loader is read-only.
3. Put any credential in `.env` (never inline).
4. Re-run `python -m scripts.compliance_preflight`.
5. Re-run `python scripts/release_gate.py --json` and confirm
   `compliance_surface_ok=true`.
