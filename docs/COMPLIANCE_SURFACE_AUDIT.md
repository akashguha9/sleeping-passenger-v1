# Compliance Surface Audit — Local Advisory MVP

> **Engineering honesty, not legal advice.** This document is the engineer's
> current read of the compliance surface for the local single-operator
> Sleeping Passenger advisory MVP.  A qualified lawyer must review it before
> any non-operator use, public distribution, paid trial, or commercial use.

## Product posture

- **Advisory-only decision support.**  The MVP produces research candidates,
  watchlists, and human-review prompts.  It does **not** place orders.
- **No broker execution.**  No route in `scripts/api_server.py` calls a
  broker, places an order, or signs a trade.  This is enforced in
  `scripts/compliance_preflight.py` (`_BROKER_ROUTE_TOKENS` check).
- **No automated order placement.**  Every actionable output requires a
  human's manual action.  `ADVISORY_ONLY=true`, `HUMAN_EXECUTION_REQUIRED=true`,
  `EXECUTION_GATE=LOCKED`, `broker_api_called=false`,
  `ai_execution_count=0` are runtime invariants validated by
  `scripts/typed_config.py`.
- **No personalized investment advice claim.**  Surface docs are scanned for
  positive "your financial advisor / we trade for you" phrasing.

## Data sources

The engineer's understanding of the access tier and ToS posture for each
source is recorded in:

- `docs/DATA_SOURCE_LICENSE_REGISTER.md` (legacy human-readable register), and
- `runtime/compliance/source_license_register.json` (machine-readable register
  the release gate consumes).

## Storage

- **Canonical storage:** SQLite (`runtime/mvp_local.db`).  This is the single
  source of truth and is read-only for diagnostics + cockpit hot paths.
- **JSONL:** audit/fallback only.  Never canonical truth.  Asserted by
  `scripts/advisory_contract.py:canonical_truth_declaration`.
- **Local-only.**  No cloud storage of canonical data; the only optional
  cloud touchpoint is the operator-initiated Google Sheets reconciliation
  export (`scripts/sync_google_sheet_reconciliation.py`).

## Logs

- `logs/system_snapshots.jsonl` (seeded; auto-managed by `conftest.py`).
- `logs/live_signal_refresh_summary.json` (redirected to a tmp file under
  pytest, never overwriting the operator's real file in tests).

## Provider payloads

- All adapter calls live in `scripts/ingestion/*_loader.py` and
  `scripts/external_adapters/*.py`.  None of them call brokers or place
  orders; all are read-only.

## AI reports

- Normalized through `scripts/ai_output_schema.py` →
  `scripts/model_signal_normalizer.py` →
  `scripts/ai_report_ingestion.py`.  The ingestion module is advisory-only
  and refuses to set `execution_permission` to anything but `ADVISORY_ONLY`.
- DIABLO veto and high-disagreement signals **block promotion**; they do
  not unblock execution under any circumstance.

## Secrets / env vars

- All secrets live in `.env` (gitignored).  `.env.example` records the
  full env surface (typed schema in `scripts/typed_config.py`).
- Compliance preflight scans committed exports for secret-like tokens.
- `google-service-account.json` is present locally for the optional
  Sheets export — its real content must remain out of version control.

## External API calls

- yfinance (public, no auth).
- SEC EDGAR (public; UA required by fair-access policy).
- GDELT (public, no auth).
- NewsAPI (optional; key only).
- Polymarket Gamma/CLOB (public read-only).
- Kalshi (read-only; gated by `kalshi_runner`).
- xAI (Grok) — optional, AI-interpretation only, never execution.

## Exported reports

- Operator-initiated only (`scripts/export_paper_trades.py`,
  `scripts/gsheet_export.py`, etc.).
- Exports never contain secrets — compliance preflight scans committed
  exports for secret-like tokens.

## User-entered data

- Local single-operator.  No multi-tenant user model.
- Manual trade logs (`manual_trades` table) carry advisory stamps and an
  operator-readiness audit trail.

## Known gaps

These are the compliance items that still need lawyer review.  None of
them is a code defect — they are policy questions the engineer cannot
answer alone.

1. **Public hosting:** the MVP is currently a *local single-operator*
   product; any public hosting needs a privacy/ToS review.
2. **Source ToS uncertainty:** several sources (yfinance, NewsAPI free
   tier, Polymarket) carry redistribution restrictions that constrain
   what the MVP may show to a second operator.
3. **Personal data:** the operator's own trading history is "personal"
   data even though there is no third party; deletion semantics need
   documentation if the MVP ever ships to multiple operators.

## Pre-launch lawyer review checklist

Before any non-operator distribution or paid use:

- [ ] Confirm advisory-only posture is sufficient for the target market.
- [ ] Confirm source ToS allow the intended use.
- [ ] Review `.env` handling, secret rotation, and incident playbooks.
- [ ] Review export contents (Sheets export, paper-trade CSV) for any
      latent PII.
- [ ] Review `docs/SOURCE_LICENSE_REGISTER.md` and the JSON register for
      "needs review" entries.
- [ ] Review `docs/PRIVACY_INVENTORY.md` and the JSON inventory for
      categories marked `risk_level=high`.
- [ ] Confirm AI report ingestion never executes — DIABLO veto cannot be
      bypassed by config.

## Source-license uncertainty

See `runtime/compliance/source_license_register.json`.  Entries marked
`needs review` or `unknown` for `license_terms_status`,
`redistribution_allowed`, `commercial_use_status`, or `storage_allowed`
are unresolved and **must** be reviewed by a lawyer before any
non-operator use.

## Privacy risk notes

See `runtime/compliance/privacy_inventory.json`.  No category currently
contains personal data of third parties; the operator's own data is
local-only.
