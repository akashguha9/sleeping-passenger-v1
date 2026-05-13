# Source ToS Checklist

> Operational checklist for verifying that each live source family is being
> used inside the bounds of its provider's Terms of Service.
>
> **Engineering hygiene, not legal sign-off.** Reproduce this checklist as
> part of the private-beta checklist in `docs/LEGAL_PRIVACY_NOTES.md` and have
> counsel approve before any external user is onboarded.

How to use this doc:
- Fill in the date you last verified each row.
- If a "redistribution" answer turns to YES (i.e. external users will see
  the data), the row needs a fresh legal review before it can ship.
- Anything marked **placeholder** is not wired to a real provider in this
  MVP — re-evaluate before implementing.

| # | Source family | Provider URL | Read-only? | Bulk redistribution? | Attribution required? | API key in `.env` only? | Last verified |
|---:|---|---|---|---|---|---|---|
| 1 | Polymarket | gamma-api.polymarket.com | YES | NO | YES (recommended) | n/a | YYYY-MM-DD |
| 2 | GDELT | gdelt.org | YES | NO | YES | n/a | YYYY-MM-DD |
| 3 | SEC EDGAR | data.sec.gov | YES | NO | YES + UA email | `SEC_USER_AGENT` only | YYYY-MM-DD |
| 4 | NewsAPI | newsapi.org | YES | NO (free tier) | YES | `NEWS_API_KEY` only | YYYY-MM-DD |
| 5 | Event Registry | eventregistry.org | YES | NO | YES | `EVENT_REGISTRY_API_KEY` only | YYYY-MM-DD |
| 6 | Etherscan | etherscan.io | YES | NO (free tier) | YES | `ETHERSCAN_API_KEY` only | YYYY-MM-DD |
| 7 | Grok/xAI | x.ai | YES (LLM call) | NO (provider ToS) | xAI ToS | `XAI_API_KEY` only | YYYY-MM-DD |
| 8 | Market Data (yfinance) | finance.yahoo.com (via yfinance) | YES | NO (Yahoo ToS) | YES if displayed | n/a | YYYY-MM-DD |
| 9 | India (NSE/RBI/SEBI) | nseindia.com, rbi.org.in, sebi.gov.in | YES | NO | YES | n/a | YYYY-MM-DD |
| 10 | Global Filings — ASX | asx.com.au | YES | NO | YES | n/a | YYYY-MM-DD |
| 10 | Global Filings — HKEX | hkex.com.hk | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 10 | Global Filings — SGX | sgx.com | **PLACEHOLDER** | n/a | YES | API key required | n/a |
| 10 | Global Filings — UK RNS | londonstockexchange.com | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 10 | Global Filings — ESMA | esma.europa.eu | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 10 | Global Filings — SEDAR | sedarplus.ca | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 10 | Global Filings — TDNet | release.tdnet.info | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 11 | Asia Disclosure — SSE | sse.com.cn | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 11 | Asia Disclosure — SZSE | szse.cn | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 11 | Asia Disclosure — HKEX | hkex.com.hk | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 11 | Asia Disclosure — TDNet | release.tdnet.info | **PLACEHOLDER** | n/a | YES | n/a | n/a |
| 11 | Asia Disclosure — SGX | sgx.com | **PLACEHOLDER** | n/a | YES | API key required | n/a |
| 11 | Asia Disclosure — DART | dart.fss.or.kr | **PLACEHOLDER** | n/a | YES | API key required | n/a |

## Cross-cutting rules

- **No commercial use** of any source's data without a paid commercial
  agreement where the provider's ToS requires one. NewsAPI and Event Registry
  free tiers are *not* commercial.
- **No silent caching** that would let external users see past data the
  provider would not currently surface. Source data is freshness-tagged
  by the live source registry.
- **No reverse-engineering** of provider rate-limits, paywalls, or login
  flows. If a provider blocks us, we stop.
- **Attribution** is shown in the UI wherever a third party's data is
  displayed. (Not yet wired — track via Day 31 showcase work.)
- **Quota burn protection**: the `--write` flag on `scripts/run_live_refresh.py`
  is **explicit**. Default is `--dry-run`. The Windows / cron scheduler
  template in `docs/LIVE_SIGNALS_SCHEDULING.md` documents how to switch.

## Before private beta

For each row whose **"redistribution"** answer would change to YES under the
private-beta deployment (i.e. external users will see the data), open a
separate "ToS-clearance" ticket and complete:

- [ ] Re-read the provider's current ToS.
- [ ] Confirm the planned display pattern is permitted.
- [ ] If not permitted, switch to a derived summary or skip the source.
- [ ] Document the decision in this table.

## Before public launch

The full public-launch criteria are in `docs/LEGAL_PRIVACY_NOTES.md` §6. This
checklist alone is **not** sufficient for public launch.
