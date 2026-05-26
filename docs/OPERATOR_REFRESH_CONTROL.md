# Operator Refresh Control

**Sprint:** Calibration Corpus + Hosted Canary, Phase 4.

An in-app, advisory-only button that surfaces the last operator refresh
truth and, when permitted, can re-invoke the locked `POST
/api/live-refresh/run` endpoint.

> **The button is NOT execution.** It does not place trades, does not
> call a broker, does not increment AI execution count, and does not
> turn the execution gate green.  Every response includes
> `advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`,
> `broker_api_called=false`, `ai_execution_count=0`.

## Where it lives

`frontend/src/components/RunRefreshButton.tsx`, mounted on the home
page (`frontend/src/app/page.tsx`) directly under the source-health
warnings strip.

## Button copy (canonical, do not change without re-running the FE tests)

> **Button label:** "Run advisory-only source refresh"
>
> **Subtext:** "Refreshes read-only public/configured sources. Does
> not trade. execution_gate=LOCKED."

Forbidden words anywhere on the button itself: `execute`, `trade now`,
`order`, `buy`, `sell`, `place ` (and trailing space), `broker`.  The
button does have the disclaiming phrase "Does not trade" in subtext —
this is allowed; the FE test explicitly checks that the BUTTON LABEL
never promises execution.

## Backend contract

`POST /api/live-refresh/run` returns the merged envelope:

```jsonc
{
  "advisory_status": "ADVISORY_ONLY",
  "execution_gate": "LOCKED",
  "broker_api_called": false,
  "ai_execution_count": 0,
  "refresh_status": "SUCCESS | PARTIAL | FAILED | SKIPPED | MOCK_UNAVAILABLE",
  "sources_attempted": N,
  "sources_succeeded": N,
  "sources_skipped": N,
  "sources_failed": N,
  "rows_written": N,
  "started_at_utc": "…",
  "finished_at_utc": "…",
  "source_results": [
    { "source": "gdelt", "status": "SUCCESS", "rows_written": 20,
      "skipped": false, "error_redacted": "" }
  ],
  // Legacy locked-envelope banner (still emitted for backwards compat)
  "ok": true,
  "warnings": ["…"]
}
```

The route does NOT initiate a network refresh from the HTTP path.  It
reads `runtime/release/operator_live_provider_refresh_summary.json` —
the artifact that `scripts/operator_live_provider_refresh.py` writes —
and converts the per-provider evidence into the structured truth above.

## What the operator does

1. Run the local refresh:
   ```bash
   python scripts/operator_live_provider_refresh.py
   ```
   This is the only command that actually issues network requests.
2. Click the **Run advisory-only source refresh** button in the cockpit.
   The button calls `POST /api/live-refresh/run` and renders the
   truthful counts + per-source status.

When the backend is offline, the button shows a degraded warning and
explicitly states `Backend offline — no refresh attempted.`  It never
fabricates SUCCESS.

## What the button is NOT

* Not an order button.
* Not a broker proxy.
* Not an execution control.
* Not a private-trading bridge.  The same auth gate the rest of the
  API uses (`MVP_API_TOKEN`) is in force; setting a token does NOT
  authorise execution.
