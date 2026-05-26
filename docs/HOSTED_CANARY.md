# Hosted Real-API Canary

**Sprint:** Calibration Corpus + Hosted Canary, Phase 2.

A nightly GitHub Actions job that runs the existing opt-in real-API
canary tests against public read-only endpoints (GDELT, SEC EDGAR,
Polymarket, public Kalshi, optionally NewsAPI).  The canary is the
single mechanism that surfaces upstream schema drift before it breaks
local refresh runs.

## Workflow

`.github/workflows/real-api-canary.yml`

* **Triggers:** nightly cron (`17 3 * * *` UTC) and `workflow_dispatch`
  for manual runs.
* **Env:** `RUN_REAL_API_CANARY=1` so the otherwise-skipped tests run.
* **Secrets:** `NEWS_API_KEY` is optional — sourced from
  `${{ secrets.NEWS_API_KEY }}` if present; absent → NewsAPI sub-canary
  skips cleanly.  No keys ever appear in logs (the canary redacts any
  16+ alnum run before logging).
* **Artifact:** `runtime/release/real_api_canary_report.json` and
  `runtime/release/real_api_canary_junit.xml` are uploaded for 14 days.

## What the canary verifies

| Source | Endpoint | Auth | Expected behaviour |
|---|---|---|---|
| GDELT | `api.gdeltproject.org/api/v2/doc/doc` | none | 200/204; list of articles or `{articles, GKG}` keys |
| SEC EDGAR | `data.sec.gov/submissions/CIK*.json` | UA only | 200/304; dict with `cik` + `filings` |
| Polymarket | `gamma-api.polymarket.com/markets` | none | 200/204; list of market dicts |
| Kalshi (public) | `api.elections.kalshi.com/trade-api/v2/exchange/status` | none | 200/401/403; dict on 200 |
| NewsAPI | `newsapi.org/v2/top-headlines` | optional | 200/429; `status=ok` on 200 |

The canary intentionally does NOT pin row content — upstream data
changes constantly.  It pins the *shape* of the response so missing
keys / a 5xx wave / an HTML redirect surface fast.

## Local opt-in

```bash
# default: every canary test is SKIPPED
python -m pytest tests/test_real_api_canary.py -q

# opt-in: run for real (consumes upstream quota)
RUN_REAL_API_CANARY=1 python -m pytest tests/test_real_api_canary.py -q
```

## What the canary is NOT

* It is NOT execution.  No POST/PUT/DELETE requests are formed.
* It does NOT touch private trading endpoints.
  `/orders`, `/buy`, `/sell`, `/execute`, `/portfolio`, `/positions`,
  `/fills`, `/balance` and `/api_keys` are explicitly absent from the
  canary URL list (asserted by
  `test_canary_advisory_and_no_execution_invariants`).
* It does NOT authorise trades.  Every artifact carries
  `advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`,
  `broker_api_called=false`, `ai_execution_count=0`.
* It does NOT publish failure details that contain secret material —
  the redactor strips any 16+ alphanumeric run before logging.
