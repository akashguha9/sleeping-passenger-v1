# Screenshot Pack Checklist

> Screenshots are **PENDING_OPERATOR_CAPTURE** until the operator
> actually records them.  This sprint does NOT fabricate, mock, or
> auto-generate screenshots.  The checklist below is a contract — when
> a screenshot is captured, update the manifest at
> `docs/demo/OPERATOR_PROOF_MANIFEST.json`.

| #  | Capture target                                                        | Expected truth marker                                            | Status                  |
|---:|-----------------------------------------------------------------------|------------------------------------------------------------------|-------------------------|
|  1 | Advisory-only banner (top of any page)                                | Contains "ADVISORY ONLY" literal                                 | PENDING_OPERATOR_CAPTURE |
|  2 | `TopTruthBar` in MOCK MODE                                            | Amber chip + "MOCK" label                                         | PENDING_OPERATOR_CAPTURE |
|  3 | `TopTruthBar` in LIVE BACKEND mode                                    | Green chip + "LIVE" label                                         | PENDING_OPERATOR_CAPTURE |
|  4 | `SourceConfigurationSnapshot` showing `C + N = T`                     | Three explicit counts                                            | PENDING_OPERATOR_CAPTURE |
|  5 | `RunRefreshButton` post-refresh result                                | Includes `execution_gate=LOCKED` in the response panel            | PENDING_OPERATOR_CAPTURE |
|  6 | Calibration report rendered (frontend or JSON)                        | `predictive_claim_allowed=false` while `N_real < 200`             | PENDING_OPERATOR_CAPTURE |
|  7 | `ManualTradeLogForm` open                                              | Form fields visible; no execute/order language                    | PENDING_OPERATOR_CAPTURE |
|  8 | `MoltbookEntryCard` populated                                          | Closed-loop learning section visible                              | PENDING_OPERATOR_CAPTURE |
|  9 | Segment role scorecard markdown                                       | Public SaaS row shows NOT_TARGETED_THIS_YEAR                      | PENDING_OPERATOR_CAPTURE |
| 10 | `WatchdogStatusPanel` showing a degraded source                       | Degraded source row red + last_success_at present                 | PENDING_OPERATOR_CAPTURE |

## How to capture

1. Run the demo from `DEMO_SCRIPT_5_MIN.md`.
2. After each step, take a PNG (1280×800 minimum).
3. Save to `docs/demo/screenshots/STEP_<n>_<short-name>.png`.
4. Update the row above to `CAPTURED_YYYY-MM-DD`.
5. Update `OPERATOR_PROOF_MANIFEST.json` to flip
   `screenshots_present: true` for the captured slot.

## What screenshots must NEVER contain

- Real credentials, tokens, or API keys.
- Live broker UI or any execution affordance.
- Synthetic data masquerading as live data.

If a screenshot would require live broker UI, the screenshot is
discarded.  The honest absence of a screenshot is preferable to a
faked one.
