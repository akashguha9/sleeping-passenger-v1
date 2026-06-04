# Pre-Real-Money Readiness Gate (v2)

`scripts/pre_real_money_preflight.py :: assess_real_money_readiness` and
`GET /api/readiness/real-money`. Read-only; never authorises execution.

## Dimensional score
`R_raw = 10·(0.15A + 0.15E + 0.10P + 0.10L + 0.10J + 0.15C + 0.10F + 0.10T +
0.03B + 0.02U)` — A advisory, E no-exec-surface, P persistence, L leverage
governance, J securities coverage, C calibration, F feedback loop, T tests,
B backup, U UI clarity.

## Caps
exec surface → 0 (SCALE_BLOCKED) · L<0.8 → 5 · C=0 / NO_DATA / FIXTURE_ONLY /
LOW_SAMPLE → 6.5 · CALIBRATING or PAPER-calibrated (real_n<50) → 7.0 ·
REAL_CALIBRATED (n≥50) → 8.0 · tests failing / preflight blocking → 6.0 ·
securities coverage <0.80 → 7.0. **READINESS_MAX = 8.0 — never scaling.**

## Modes
PAPER_ONLY (<6) · TINY_MANUAL_PROBE_ONLY (6–7) ·
MANUAL_REAL_MONEY_READY_SMALL_ONLY (7–8) ·
MANUAL_REAL_MONEY_READY_CALIBRATED (8) · SCALE_BLOCKED (hard fail).

Even at the top mode: no execution, no broker orders, human execution only,
human-controlled sizing, Year-1 survival mode.
