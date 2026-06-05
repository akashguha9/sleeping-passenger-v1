# Zip Simulation Corpus Ingestion (`src/simulation_zip`)

**SIMULATION_ONLY · ZIP_CORPUS_DERIVED · NOT_LIVE_TRADING_EVIDENCE ·
NOT_BROKER_DATA · NOT_FINANCIAL_ADVICE**

A safe, fail-closed subsystem that turns a large local zip archive (chess
PGNs, hackathon material, scraped text, code, and — only if genuinely present —
market data) into **simulation / training / benchmark** records, then scores
how much the *zip-simulation subsystem* hardens the MVP's reasoning,
provenance, calibration, and decision discipline.

It never auto-executes trades, never creates broker orders, never gives
financial advice, and never treats chess/hackathon/scraped data as market
outcomes. Market metrics are produced **only** when the archive actually
contains dated, tickered, priced, outcome-bearing rows above explicit minimum
thresholds; otherwise the result is `NO_DATA`, never a fabricated number.

## Run it

```bash
# Windows (operator machine where the local zip is reachable):
python -m src.simulation_zip.run --zip "C:\Users\akash\Downloads\hackathon_scraper.zip"

# Or via env var:
set SIMULATION_ZIP_PATH=C:\Users\akash\Downloads\hackathon_scraper.zip
python -m src.simulation_zip.run
```

> **Environment note.** This subsystem was authored and tested inside the
> Claude Code cloud container, which **cannot** reach a local `C:\` path. The
> code is fully exercised there against synthetic fixtures and the fail-closed
> (missing/corrupt/zip-slip) paths. To get **real numbers for the 700 MB
> corpus, run the command above on the Windows machine that holds the zip.**

Outputs (written to `runtime/reports/`, which is git-ignored):

- `zip_simulation_baseline_<ts>.json` — pre-change repo + test baseline
- `zip_simulation_inventory_<ts>.json` — safe manifest (no full extraction)
- `zip_simulation_run_<ts>.json` — full run report
- `zip_simulation_scores_<ts>.json` — segmented before/after scores
- `zip_simulation_summary_<ts>.md` — short human summary
- `zip_simulation_integration_<ts>.md` — the full Phase-5 integration report

Exit code is `0` for SAFE/WARNING and `2` for BLOCKED (fail-closed).

## Safety model

| Check | Effect |
|---|---|
| Missing file / wrong extension / unreadable / corrupted | **BLOCKED** |
| Zip-slip (`../`), absolute path, drive letter, UNC | **BLOCKED** |
| Declared uncompressed size over cap (zip-bomb risk) | **BLOCKED** |
| Per-file or archive compression ratio over limit | **WARNING** (flagged, not blocked) |
| Member larger than the parse cap | streamed/hashed only, never parsed as text |

Hashing is streaming (chunked) — a 700 MB member is never loaded into memory.
Every parsed record carries a `provenance_id =
SHA256(zip_path :: archive_path :: sha256(file_bytes))`.

## Scoring (conservative, fail-closed)

Twelve categories are scored `before` (subsystem absent) vs `after` (measured
run), weighted into an overall **simulation-readiness** score. The category
weights as stated in the original spec sum to 1.10; they are normalized to a
true simplex (sum = 1.0) while preserving the intended emphasis.

Caps: tests failing → `overall_after ≤ 60`; advisory guardrails broken →
`overall_after ≤ 30`; provenance missing → evidence/provenance categories
`≤ 50`. Advisory-only guardrail preservation is scored as *preserved* (Δ 0),
not as an "improvement".

**Scope.** These scores measure the incremental simulation-readiness
contributed by this subsystem — **not** total MVP capability, and **not** live
trading performance. They do not prove profitability or stock-prediction
accuracy.

## Tests

`tests/test_simulation_zip.py` builds tiny synthetic zips (the real 700 MB zip
is never used in automated tests) and covers: missing/corrupt zip, zip-slip and
absolute-path rejection, compression-ratio warning, manifest + classification,
all four parsers, provenance + score determinism, the test-failure and
guardrail caps, advisory-only preservation, and a CLI smoke test.
