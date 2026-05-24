# Polymarket: Belief, Not Truth

## Purpose

Polymarket is **priced belief**, not prophecy. This diagnostic separates clean
prediction-market signal from distortion (thin liquidity, whales, wide spreads,
ambiguous resolution). Lives in `compute_polymarket_distortion` in
`scripts/bruce_lee_signal_discipline_report.py`; heavier production engines are
`narrative_distortion_index.py` and `signal_distortion_index.py`.

## Inputs

0–1 factors. Signal: odds_move, volume_change, liquidity_depth, open_interest,
trader_dispersion, market_relevance, resolution_clarity. Distortion:
low_liquidity, whale_concentration, wide_spread, low_trader_count,
ambiguous_resolution, sudden_unconfirmed_move.

## Formula

```
PMScore = 0.20*OddsMove + 0.18*VolumeChange + 0.16*LiquidityDepth
        + 0.14*OpenInterest + 0.12*TraderDispersion + 0.10*MarketRelevance
        + 0.10*ResolutionClarity
DistortionRisk = 0.25*LowLiquidity + 0.20*WhaleConcentration + 0.18*WideSpread
        + 0.15*LowTraderCount + 0.12*AmbiguousResolution
        + 0.10*SuddenUnconfirmedMove
PMCleanSignal = PMScore - DistortionRisk
```

## Outputs

`pm_score`, `distortion_risk`, `pm_clean_signal`.

## State consequence

A low-liquidity / high-whale / wide-spread move yields a high `distortion_risk`
and a low (possibly negative) `pm_clean_signal`, which feeds the triangulation
clean-signal and the Diablo `polymarket_move_thinness` term — a thin PM move on
a high-impact asset escalates to `DIABLO_REVIEW`. Polymarket can never be
treated as truth; it is one pointer among many in the reality check.

## Tests

`tests/test_bruce_lee_signal_discipline_report.py::test_polymarket_distortion_penalises_low_liquidity_and_whales`
— low liquidity + whales raise distortion and lower clean signal.

## Failure modes

* All-zero inputs → zero score, zero distortion (no signal, not a false
  positive).
* Ambiguous resolution + sudden unconfirmed move with no volume → high
  distortion, suppressed clean signal.

## Advisory-only safety note

Pure function; no DB, network, or broker calls. PM signal never authorises a
trade; it only adjusts an advisory score.

## How to verify locally

```powershell
python -m pytest tests\test_bruce_lee_signal_discipline_report.py -q -k polymarket
```
