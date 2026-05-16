# Paper Ledger Operating Routine (Sprint 10E)

This is the operator's working routine for the paper-trade ledger. It is
not a sales document. The paper ledger is **rehearsal/calibration data
only**. No broker is contacted, no order is placed, no real capital is
committed. The execution gate stays LOCKED.

> Paired tools:
> - `scripts/export_paper_trade_template.py`
> - `scripts/import_paper_trades.py`
> - `scripts/export_paper_trades.py`
> - `scripts/paper_trade_ledger.py`
> - `scripts/local_mvp_audit.py --section paper`
> - `scripts/calibration_gate.py` (Sprint 10F)
> - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md`
> - `docs/OUTCOME_CALIBRATION_GATE.md`

---

## 1. First-time setup

```powershell
# Write a blank template the operator can edit in Excel.
python scripts/export_paper_trade_template.py

# Default destination is exports/paper_trade_template.csv.
# The template is gitignored as part of the *.csv rule, except for
# explicit operator working files you keep deliberately outside the
# repo (recommended).
```

Recommendations:
- Keep the operator working copy **outside the repo** (e.g.
  `D:\private\sp\paper_trades_2026Q2.csv`). The repo-side `exports/`
  directory is gitignored but it is also routinely overwritten by
  templates and review exports.
- Open in Excel / LibreOffice. Save as CSV (UTF-8). Do not save as
  XLSX-only — the import script reads CSV.

---

## 2. Decision-time row creation

A row is created **before** the outcome is known. The rule is simple:
every reactor-snapshot and thesis field must be locked at the moment
of the decision, not edited later.

Required fields at decision time:

| Field | Why it matters |
|---|---|
| `paper_trade_id` | Stable identifier; lets reconciliation find this row later |
| `created_at` | UTC timestamp at decision time, not at reconciliation |
| `symbol` | Instrument identifier |
| `side` | long / short / hedge |
| `thesis` | One- or two-line statement of *why* you would enter |
| `invalidation` | The condition that would prove this thesis wrong |
| `horizon` | Time window you intend to evaluate over |
| `risk_notes` | What can go wrong; what you are not protected against |
| Reactor snapshot fields | Composite, environment, regime tags captured at decision time |
| `preflight_state` | The preflight gate outcome at decision time |
| Source freshness state | What the live source health looked like at decision time, if available |
| `trade_mode = PAPER` | Required for advisory invariants |
| `PAPER_TRADE_ONLY = true` | Required |
| `REAL_CAPITAL_AT_RISK = false` | Required |
| `BROKER_ORDER_ID = "NONE"` | Required |
| `BROKER_API_CALLED = false` | Required |
| `EXECUTION_REAL = false` | Required |

The DB schema and the manual-trade form already enforce most of these
when `trade_mode = PAPER`. The columns are listed here so the operator
remembers what discipline the row represents, not so they can edit them
freely.

---

## 3. Outcome update (later, not now)

Update these fields **only after** the outcome window has matured:

| Field | When |
|---|---|
| `outcome_status` | After horizon closes or invalidation triggers |
| `outcome_quality` | Operator judgement: clean / partial / messy / disqualified |
| `process_quality` | How well the decision discipline was followed |
| `mistake_tags` | Tags drawn from the moltbook taxonomy |
| `lesson` | One or two lines of process learning |
| `reconciled_at` | UTC timestamp when reconciliation was completed |

Do not edit any decision-time field while writing the outcome. Doing
so is **lookahead bias** and silently breaks calibration.

---

## 4. Import flow (operator-edited CSV -> DB)

Always dry-run first.

```powershell
# Validate without writing.
python scripts/import_paper_trades.py --file <path-to-csv> --dry-run

# Persist valid rows. PAPER mode is forced; broker stamps stay locked.
python scripts/import_paper_trades.py --file <path-to-csv> --write
```

Read the validation summary before writing. Rejected rows print their
reasons; duplicate rows are skipped. If `--write` reports
`rows_imported = 0` after a non-zero `rows_valid`, the DB already had
all those rows.

Use `--json` to script the dry-run output into a sanity check.

---

## 5. Export flow (DB -> CSV for review)

```powershell
# Round-trip current paper rows back to CSV for review/audit.
python scripts/export_paper_trades.py --out exports/paper_trades_review.csv
```

The export script is read-only with respect to the DB. The output CSV
is gitignored by default (*.csv pattern). Move it to your private
working directory if you intend to keep it.

---

## 6. Anti-lookahead rules (non-negotiable)

These are the rules that make paper-ledger data worth keeping:

1. **Never change reactor snapshot fields after outcome is known.**
   If a column on a paper-trade row had a value at decision time, that
   value is permanent. Edit a comment field if you need to annotate.
2. **Never backfill thesis or invalidation after the result.** If you
   forgot to write a thesis at decision time, mark the row
   `outcome_status = disqualified`. Do not invent the missing thesis
   retroactively.
3. **Mark uncertain rows honestly.** `outcome_status = partial /
   ambiguous / disqualified` are valid. They are *more* useful than
   forcing a clean win/loss.
4. **Small sample = no claim.** See section 7. Do not write summary
   statistics for n < 5.
5. **No edit-while-open.** If the horizon has not closed, do not
   touch reconciliation columns.

These rules apply equally to paper rows and real-manual rows.

---

## 7. Minimum sample thresholds

These thresholds come from the Sprint 10F calibration gate. They tell
the operator how much confidence to place in any paper-outcome read.

```
if n < 5:
    paper_calibration_confidence = none
elif n < 20:
    paper_calibration_confidence = very_low
elif n < 50:
    paper_calibration_confidence = low
else:
    paper_calibration_confidence = still_contextual
```

`still_contextual` is the maximum. Paper data never reaches "edge
proven" — see section 8 for what it cannot prove.

---

## 8. What paper trades can and cannot prove

### What paper trades CAN test

- **Workflow discipline**: did you capture thesis / invalidation /
  horizon at decision time?
- **Reactor capture completeness**: did the reactor snapshot record
  every diagnostic you wanted later?
- **Classification logic**: are operator-side tags consistent across
  similar setups?
- **Delayed reconciliation**: does the operator actually return on
  schedule to update outcomes?
- **Process mistakes**: which mistakes repeat — entry timing, sizing,
  invalidation discipline, attention bias?
- **Anti-lookahead behaviour**: are rows edited only in the right
  windows? (auditable via `created_at` vs `reconciled_at`).

### What paper trades CANNOT prove

- **Slippage**: there is no execution layer.
- **Fill quality**: no order book, no broker, no microstructure.
- **Real emotion**: paper P&L does not carry the loss aversion of
  real capital.
- **Broker execution**: by design, this MVP never contacts a broker.
- **Real alpha**: paper outcomes are a hygiene test, not an edge claim.
- **Profitability**: the system is advisory-only; profitability would
  require a live executor that does not and will not exist here.

If a future deck, screenshot, or report ever says "paper trades show
edge", that is the bias. Reset to the calibration gate's actual
output and the n-thresholds in section 7.

---

## 9. Backup expectations

Paper-ledger working CSVs are included by the Sprint 10C backup
script:

```powershell
python scripts/backup_local_state.py --dry-run
python scripts/backup_local_state.py
python scripts/verify_backup.py <backup_dir>
```

A row recorded in the DB is captured via the DB hot-copy. A row in a
CSV the operator has not yet imported is captured if the CSV lives
under `exports/paper_trade_*.csv`. If you keep your working CSV
outside the repo, back it up via your own routine — the script will
not reach it.

---

## 10. Safety invariants (always)

```
ADVISORY_ONLY = true
HUMAN_EXECUTION_REQUIRED = true
execution_gate = LOCKED
BROKER_ORDER_PERMISSION = false
AI_EXECUTION = 0
broker_api_called = false
execution_permission = false
can_execute = false
PAPER_TRADE_ONLY = true (for paper rows)
REAL_CAPITAL_AT_RISK = false (for paper rows)
BROKER_ORDER_ID = "NONE"
EXECUTION_REAL = false
```

Nothing about the paper-ledger routine relaxes these. If you ever feel
like the routine "wants" to authorize a real trade, stop. This routine
exists to make the operator's process learning legible. It does not
trade.
