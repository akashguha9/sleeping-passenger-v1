# STOP-LOSS OPERATOR CONFIRMATION REQUIRED

_Generated 2026-07-04T14:00:01Z - the risk engine is **BLOCKED** until every entry below is confirmed by YOU._

Template: `C:\Users\akash\sleeping-passenger-v1\data\daily_payload\stop_loss_backfill_template.json`

For each entry set ALL of:

- `stop_loss` (review/edit the suggested level)
- `stop_loss_confirmed: true`
- `stop_loss_confirmed_at`: current UTC timestamp
- `operator_confirmation_id`: any identifier you choose
- `risk_acknowledgement: true`
- `operator_confirmation_text`: exactly `I_CONFIRM_THESE_STOPS_ARE_MY_OPERATOR_RISK_LIMITS`
- `leverage_risk_acknowledged: true` on LEVERAGED entries

Then run:

```powershell
python scripts/holdings_truth_gate.py --validate-template
python scripts/holdings_truth_gate.py --apply-confirmed --dry-run
python scripts/holdings_truth_gate.py --apply-confirmed --write
```

## Pending entries

- **NASDAQ:ANET** (leverage 1x, suggested stop 134.8715) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NYSE:XOM** (leverage 1x, suggested stop 150.024) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NYSE:RTX** (leverage 1x, suggested stop 162.621) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NYSE:LMT** (leverage 1x, suggested stop 496.375) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NYSE:CVX** (leverage 1x, suggested stop 185.4115) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NASDAQ:MSFT** (leverage 1x, suggested stop 397.1475) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NSE:HDFCBANK** (leverage 4x, suggested stop 749.3362) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NSE:RELIANCE** (leverage 4x, suggested stop 1301.82) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NASDAQ:ASML** (leverage 1x, suggested stop 1387.3705) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)
- **NYSE:TSM** (leverage 1x, suggested stop 373.597) - UNCONFIRMED: not confirmed (stop_loss_confirmed != true)

_No stop becomes active until confirmed. Nothing in this repo can
confirm on your behalf._
