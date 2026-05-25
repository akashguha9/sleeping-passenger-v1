# Privacy Inventory — Local Advisory MVP

> **Engineering honesty, not legal advice.**  This document and the
> companion JSON (`runtime/compliance/privacy_inventory.json`) record the
> engineer's read of the data categories the MVP processes, where they
> live, and the residual privacy risk.

## Posture summary

- The MVP is a **local, single-operator** advisory tool.
- No third-party PII is processed.
- No multi-tenant user model exists.
- No public hosting of operator data.

## Categories

The canonical machine-readable list is
`runtime/compliance/privacy_inventory.json`.  This file documents the same
categories with prose context.

### 1. Operator manual trades

- **Source:** Operator's manual entries (`manual_trades` table) +
  paper-trade ledger.
- **Storage:** `runtime/mvp_local.db` (local SQLite, gitignored), JSONL
  audit (`logs/`).
- **Retention:** Indefinite (operator-owned).
- **Deletion:** Operator-initiated DELETE from SQLite.
- **Access scope:** Local machine only.
- **Third-party processor:** None.
- **Risk level:** Low.
- **Mitigation:** Local-only storage; not exported by default.

### 2. Provider payloads

- **Source:** yfinance, SEC EDGAR, GDELT, NewsAPI, Polymarket, Kalshi,
  xAI/Grok.
- **Storage:** `signal_events` table (canonical) + ingestion summary
  JSON.  Raw payloads carry the provider's terms; no
  redistribution.
- **Retention:** Bounded by table size / TTL.
- **Deletion:** Quarantine via `scripts/toxic_signal_quarantine.py`.
- **Access scope:** Local machine only.
- **Third-party processor:** Each provider in transit; no other
  processor.
- **Risk level:** Low (no operator PII embedded).
- **Mitigation:** Read-only; never republished; rate-limited.

### 3. AI reports

- **Source:** xAI (Grok) and other locally-run interpretation lanes.
- **Storage:** `data/ai_reports/` (file-based, gitignored), normalized
  into the canonical DB via `scripts/ai_report_ingestion.py`.
- **Retention:** Indefinite (operator-owned), no automatic delete.
- **Deletion:** Operator-initiated.
- **Access scope:** Local machine.
- **Third-party processor:** Inference provider (xAI) when called.
- **Risk level:** Medium — input prompts may carry operator context.
- **Mitigation:** `scripts/ai_output_schema.py` redacts secret-like
  tokens; advisory-only invariants block any execution path.

### 4. Candidate outputs

- **Source:** Daily synthesis + promotion pipeline.
- **Storage:** `data/daily_payload/`, `runtime/` JSON, SQLite.
- **Retention:** Indefinite.
- **Deletion:** Operator-initiated.
- **Access scope:** Local machine.
- **Third-party processor:** None.
- **Risk level:** Low.
- **Mitigation:** Local-only; never shipped to providers.

### 5. Operator audit log

- **Source:** `scripts/operator_audit_log.py` + persistence.
- **Storage:** `runtime/operator_audit_log.jsonl`.
- **Retention:** Indefinite (operator review).
- **Deletion:** Operator-initiated.
- **Access scope:** Local machine.
- **Third-party processor:** None.
- **Risk level:** Low.
- **Mitigation:** No secrets recorded; advisory-only stamps in every row.

### 6. Local secrets (.env)

- **Source:** Operator-entered API keys.
- **Storage:** `.env` (gitignored).
- **Retention:** Until operator rotates / deletes.
- **Deletion:** Operator-initiated.
- **Access scope:** Local machine only.
- **Third-party processor:** None (used only to authenticate to
  providers).
- **Risk level:** High if leaked.
- **Mitigation:** gitignored; export scan; `.env.example` only carries
  placeholders.

## Operational principles

1. **No third-party PII** is ingested or stored.
2. **No multi-tenant user data** exists in the current MVP.
3. **No cloud canonical storage** — only the optional operator-initiated
   Sheets export.
4. **Secrets stay in `.env`**; the file is never committed.
5. **Exports are scanned** for secret-like tokens before commit
   (`compliance_preflight.py`).
