# Legal / Privacy / Source-ToS Notes

> **This is engineering and product honesty, not legal advice.** Before any
> external user touches this software, a qualified lawyer should review every
> claim below. Where this document says "we do not", it is the engineer's
> current intent and visible behavior — not a binding warranty.

---

## 1. Product status

- **Local-first MVP.** Designed for a single operator on a single machine.
- **Advisory-only.** No automated execution surface exists.
- **Manual decision journal.** The product helps a person review signals,
  reflect, log manual trades, and reconcile outcomes.
- **No broker execution.** No broker API is integrated. No order is placed
  by any code path in this repository.
- **No financial advice.** Outputs are interpretations, scores, and flags —
  never personal investment recommendations.
- **No guarantee of accuracy.** Live source data, AI interpretations, and
  computed signals can be wrong, stale, or contradictory.
- **User-responsible.** Any trade or decision a user makes from this MVP is
  entirely their own.
- **Not a public SaaS.** No hosted deployment, no user accounts (beyond a
  shared local token), no payment processing.

---

## 2. Data storage

### What is stored

By default, all data is in a single local SQLite database at
`runtime/mvp_local.db` (configurable via `MVP_DB_PATH`). Tables:

| Table | Owner | Purpose |
|---|---|---|
| `signal_events` | shared | normalized live-source events |
| `signal_decisions` | operator | per-signal validate/discuss/reflect/decision |
| `user_reflections` | operator | written reflection text |
| `ai_discussion_summaries` | operator | AI-summary interpretations |
| `manual_trades` | operator | manual trade log entries |
| `reconciliation_results` | operator | reconciled outcomes |
| `moltbook_entries` | operator | Moltbook learning journal |
| `live_source_runs` | system | per-source run metadata (timestamp, fetched_count, error_message) |
| `global_securities` / `global_security_aliases` | shared | security master |

Backups land in `runtime/backups/` (configurable). Restore is opt-in and
non-destructive by default — the script always writes a pre-restore backup
of the current DB.

### What is **not** stored

- No passwords (the local token gate is a shared bearer; no per-user creds).
- No broker credentials (there is no broker integration).
- No payment information.
- No multi-user PII (until private-beta auth is implemented — see
  [[private-beta-auth-design]]).
- No third-party-fetched data is redistributed; rows persist locally only.

### Data lifetime

The operator owns the DB. Deletion is a manual `rm runtime/mvp_local.db`
followed by a restart. No remote replicas exist.

---

## 3. API keys and secrets

- Stored in `.env` (read by `python-dotenv`). The repo's `.gitignore`
  excludes `.env`.
- **Never expose to the frontend.** `NEXT_PUBLIC_*` is reserved for
  non-secret config like the API base URL. If a secret is ever prefixed
  `NEXT_PUBLIC_`, it is leaked.
- The Docker scaffold (`docker-compose.yml`) reads secrets at runtime from
  the host environment.
- **If a key leaks**, rotate immediately at the provider dashboard:
  xAI, NewsAPI, Event Registry, Etherscan, SEC `User-Agent` contact email.
- The source-health endpoint and the live-source registry deliberately
  redact secret values — only `configured: true/false` is surfaced.
- AI output validation (`scripts/ai_output_schema.py`) redacts secret-like
  patterns from `validation_errors` and `raw_response` before persistence.

---

## 4. Source data caveats

Live source families and their caveats. For each, the table below shows the
practical legal/ToS posture for a **local, single-operator, non-redistributing**
context. None of this is legal advice; redistribution or commercial use needs
a separate review.

| Source family | Public/third-party | ToS / license posture | Attribution | API key | Quota / rate-limit |
|---|---|---|---|---|---|
| **Polymarket** | Public REST | Read-only; CLOB orders are *not* used. No redistribution of market data without checking terms. | Polymarket attribution recommended when displaying market titles. | none | Generous; respect rate limits. |
| **GDELT** | Public DOC API | Free for research; commercial redistribution unclear. | "Data provided by GDELT Project" recommended. | none | Public; respect query frequency. |
| **SEC EDGAR** | Public | Permitted with a descriptive `SEC_USER_AGENT`. Bulk redistribution permitted; this MVP only fetches narrow filings. | SEC attribution recommended. | none, but UA required | 10 req/sec hard limit per SEC guidance. |
| **NewsAPI** | Paid/free tier | Free tier is developer-only; commercial use requires paid plan. Do not redistribute article bodies. | NewsAPI attribution required by ToS. | required | Free tier ≈ 100/day. |
| **Event Registry** | Paid/free tier | Similar to NewsAPI; check current plan. | Attribution required. | required | Per-plan quota. |
| **Etherscan** | Free tier | API ToS permits non-commercial use. Do not redistribute proprietary indices. | Etherscan attribution recommended. | required | 5 calls/sec free tier. |
| **Grok/xAI** | Paid | LLM provider ToS applies. Do not log or persist responses containing other users' data. AI output is *hypothesis* only. | xAI ToS terms apply. | required | Per-plan quota. |
| **Market Data (yfinance)** | Yahoo public | yfinance is a Yahoo-scraping convenience library; Yahoo's ToS arguably restricts redistribution of bulk data. Single-operator local read-only is the safest profile. | "Data from Yahoo! Finance" if displayed. | none | Best-effort; no formal SLA. |
| **India (NSE/RBI/SEBI)** | Public | NSE / RBI / SEBI public endpoints. Redistribution rights vary by source page. | Source attribution required. | none | Lightweight; respect public endpoints. |
| **Global Filings** | ASX public; others placeholder | ASX is permitted for non-commercial use. Other providers (HKEX, SGX, UK RNS, ESMA, SEDAR, TDNet) are *placeholders* in this MVP — no actual fetching. | Per-provider attribution. | varies | Per-provider quota. |
| **Asia Disclosure** | All placeholders | SSE/SZSE/HKEX/TDNet/SGX/DART are placeholders — no actual fetching in this MVP. | When implemented, per-provider attribution. | varies | Per-provider quota. |

**Key rule:** "Local analysis does not imply legal right to republish."

A future private-beta phase that displays third-party data to *other users*
crosses a redistribution line. Each source's ToS must be re-evaluated then.
See `docs/SOURCE_TOS_CHECKLIST.md`.

---

## 5. Financial / regulatory caveat

- **Not investment advice.** Nothing produced by this MVP is personalized
  investment advice as defined by SEC, FCA, SEBI, or any other regulator.
- **Not a broker-dealer.** No order routing, no custody, no execution.
- **Not a Registered Investment Adviser.** This is engineering output, not
  the work product of a registered adviser.
- **Not an execution product.** The MVP intentionally has no execution
  surface; `execution_gate = LOCKED` on every mutating route response.
- **Not a portfolio manager.** No allocation, no rebalancing, no
  trading-on-behalf-of.
- **No suitability checks.** The MVP does not assess the operator's risk
  tolerance, financial situation, or objectives.
- **Manual user judgment required.** Every decision is the operator's.

---

## 6. Private-beta checklist

Before *any* external user touches this software:

- [ ] Terms of Use drafted and reviewed by counsel.
- [ ] Privacy policy drafted and reviewed by counsel.
- [ ] Source provider ToS check for each family **(see `docs/SOURCE_TOS_CHECKLIST.md`)**.
- [ ] Legal review of advisory language end-to-end (UI copy, README,
      SHOWCASE.md, error messages).
- [ ] Hosted secrets management (Railway/Render/Fly environment store, or
      Vault) configured. Secrets are never in the repo.
- [ ] Real multi-user auth implemented and tested **(see [[private-beta-auth-design]])**.
- [ ] Per-user data isolation implemented and tested at the row level.
- [ ] Backup / retention policy documented and operational.
- [ ] User data delete/export procedure implemented and tested.
- [ ] Incident response process documented and rehearsed
      **(see `docs/MONITORING_AND_INCIDENTS.md`)**.
- [ ] Security review on the hosted surface (auth, rate limits, CORS, TLS,
      headers, input validation).
- [ ] Confirmation that no source's ToS prohibits the planned display /
      derivation pattern for external users.

---

## 7. Suggested UI copy

A short disclaimer to display in:
- the dashboard footer,
- the Help / Onboarding page,
- the README top section,
- any export file's header line.

> *This local MVP is advisory-only. It does not place trades, call broker
> APIs, or provide financial advice. You are responsible for all manual
> decisions and external execution. Live source data and AI interpretations
> may be incomplete, delayed, or wrong.*

For private beta (when implemented), expand to:

> *This service is provided for personal informational use only. It is not
> investment advice, not a broker, and not a registered investment adviser.
> Your data is stored on the operator's hosted backend; see Privacy Policy.
> Source data is provided by third parties under their own terms; we do not
> redistribute that data outside your account.*

---

## 8. What this document is **not**

- Not legal advice.
- Not a substitute for counsel review.
- Not a compliance certification.
- Not a warranty of accuracy of any signal, interpretation, or source.

If you are reading this because you are about to share the MVP with
non-operator users, **stop**, complete the private-beta checklist in
section 6, and have a lawyer read every public claim.
