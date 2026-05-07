# Hedge Trade Entry Playbook

This layer keeps hedge math, trade entry eligibility, leverage safety, net exposure, tail-loss control, and execution-quality review separate from live execution. It is offline-first, deterministic, and diagnostic only.

Core formulas:

- `HedgeRatio = FuturesHedgeNotional / SpotNotional`
- `NetExposure = SpotLongNotional + FuturesLongNotional - FuturesShortNotional`
- `NetExposureRatio = NetExposure / GrossSpotNotional`
- `NetEdge = ExpectedPriceEdge - Fees - FundingCost - LiquidationRiskPenalty - ComplexityPenalty`
- `ConflictCost = Fees + FundingCost + MonitoringLoad + LiquidationRisk`
- `TailDrag = ChaosLossFrequency × AverageChaosLoss`
- `Expectancy = (WinRate × AverageWin) - (LossRate × AverageLoss)`
- `AnnualizedReturn = (1 + PeriodReturn)^(52 / PeriodWeeks) - 1`
- `ExecutionQuality = RealizedReturn / AvailableSignalReturn`

Entry doctrine:

- signal does not equal entry
- leverage is not the hedge
- chaos should be vetoed, not negotiated with
- weak signals deserve protection
- strong signals deserve room
- human remains final executor

Runtime artifact:

- `runtime/hedge_trade_entry_report.json`
