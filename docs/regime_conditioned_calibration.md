# Regime-Conditioned Calibration

`regime.py` classifies the market context a Decision Twin is frozen in:
volatility (LOW/NORMAL/HIGH/EXTREME), trend, liquidity, dispersion, data-quality,
freshness — plus a compact `regime_key` used as the calibration cohort.

## Why
A model calibrated in one regime may fail in another. Every twin and every frozen
prediction stores its `calibration_cohort = regime_key`, so once outcomes resolve,
calibration can be reported by market / sector / regime / horizon / advisory-state /
confidence-bin / evidence-grade / disagreement-class.

## Low-sample discipline
Regime cohorts are small early on. The calibration harness applies minimum-sample
requirements and `LOW_SAMPLE` labels (never CALIBRATED below 50); the VoI engine's
calibration amplifier uses a conservative neutral prior when a cohort is thin. Tiny
cohorts are never presented as reliable metrics.
