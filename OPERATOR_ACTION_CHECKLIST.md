# OPERATOR ACTION CHECKLIST

_Generated 2026-07-04T14:06:51Z from the live truth surface. State: **BLOCKED**._

Work top to bottom; each item names its command.

1. [ ] Confirm stop-losses for every position (10 missing, 0 unconfirmed): edit `data/daily_payload/stop_loss_backfill_template.json` per `STOP_LOSS_CONFIRMATION_REQUIRED.md`, then run `python scripts/holdings_truth_gate.py --apply-confirmed --write`
2. [ ] Review the 2 LEVERAGED position(s) and set `leverage_risk_acknowledged: true` only after reading the max-loss-at-stop numbers in the template
3. [ ] Refresh holdings truth (set `holdings_confirmed_current: true` + timestamp in the template before --apply-confirmed) — current freshness: HOLDINGS_TRUTH_STALE
4. [ ] Re-run the risk gate and read the summary: `python scripts/holdings_truth_gate.py --show-summary`
5. [ ] Let the daily loop run (or force one): `python -m scripts.nbi_scheduler run-once` — it produces locked predictions, matures due outcomes, harvests settlements, refreshes discovery, and dispatches alerts
6. [ ] Prove the Sheets loop when you configure it: `python scripts/sheets_roundtrip_probe.py --fixture` (logic proof) or `--live-safe` with SHEETS_PROBE_SHEET_ID set
7. [ ] Inspect alerts: `runtime/alerts/operator_alerts.jsonl` (or the cockpit panel) — 5 in the latest snapshot
8. [ ] Wait for the next maturity date (2026-07-09; projected N -> 81) — do NOT try to shortcut outcomes

---

**DO NOT use real money.** The readiness gates are not passed: calibration is MEASURED_NOT_CALIBRATED (N=56), risk state is BLOCKED. The execution lock stays LOCKED regardless.

Next required action (truth surface): Confirm stops: python scripts/holdings_truth_gate.py --write-template, edit/confirm each entry, then --apply-confirmed --write
