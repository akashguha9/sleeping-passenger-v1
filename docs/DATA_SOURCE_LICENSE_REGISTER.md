# Data Source License / ToS Register

> **Engineering honesty, not legal advice.** This register records the
> engineer's current understanding of each external data source, its access
> tier, and the terms-of-service constraint that applies. A qualified lawyer
> should review before any non-operator / commercial use. See also
> `docs/SOURCE_TOS_CHECKLIST.md`.

All sources below are used for **advisory, read-only observation** in a local
single-operator context. No source is redistributed; no scraped content is
republished; no source authorizes broker execution.

| Source | Access tier | Auth | ToS / license constraint | Use in MVP |
|---|---|---|---|---|
| Yahoo Finance (yfinance) | Public/unofficial | None | Personal, non-commercial; no redistribution of raw data. | Quote / OHLCV observation only. |
| SEC EDGAR / EFTS | Public | None (fair-use UA) | Fair-access policy; rate-limited; attribution. | Filings signal observation. |
| GDELT | Public | None | Open, attribution requested. | News/event observation. |
| NewsAPI | Freemium | API key | Dev tier non-commercial; no redistribution of full articles. | Headline observation. |
| Polymarket (Gamma / CLOB) | Public API | None | Read-only market data; no trading via this MVP. | Event-market observation. |
| Etherscan / Blockscout | Freemium | API key | Read-only chain data; rate-limited. | On-chain observation. |
| xAI (Grok) | Paid API | API key | Provider ToS; outputs treated as advisory interpretation. | AI interpretation. |
| EDINET / OpenDART (Asia) | Public | Key (OpenDART) | Read-only disclosure data; attribution. | Asia disclosure observation. |
| Event Registry | Freemium | API key | Dev tier limits; no redistribution. | Event observation. |

## Constraints enforced in code

- **No redistribution**: data stays in the local SQLite DB; exports are
  operator-initiated and scanned for secrets (`compliance_preflight.py`).
- **Read-only**: adapters observe; none place orders.
- **Secrets**: every API key lives in `.env` (gitignored). Keys are never
  committed and are redacted from AI payloads (`ai_output_schema.py`).
- **Rate limits**: handled by `scripts/rate_limiter.py` and per-source runners.

## When adding a new source

1. Add a row above with its access tier, auth, and ToS constraint.
2. Confirm read-only usage and no redistribution.
3. Put any credential in `.env` (never inline).
4. Re-run `python -m scripts.compliance_preflight`.
