# Value-of-Information Methodology (with the Surprise)

`value_of_information.py` turns uncertainty into a BOUNDED research agenda and can
conclude that **no research is currently worth the cost**.

## Ranking
For each item in a fixed catalogue (filing, transcript, guidance, competitor,
sector, price, volume, macro, regulatory, alt-source, governance, supply-chain,
analyst-dispersion, benchmark) that targets a **reducible** uncertainty type, it
estimates: decision-change probability, expected uncertainty reduction, expected
regret reduction, tail relevance, acquisition cost. Net VoI =
`raw · (1 − redundancy) · calibration_amplifier − cost`. Output is bounded (≤8)
and yields one of `ACQUIRE / WAIT_FOR_CATALYST / NO_RESEARCH_WORTHWHILE`.

## The surprise: redundancy-discounted, calibration-aware VoI
Discovered by noticing naive VoI recommends acquiring evidence the system already
effectively has. Two couplings, both measurable by ablation:
1. **Redundancy discount** — value is cut for items that duplicate existing
   (concentrated) evidence; when the council already holds a robust, well-sourced
   consensus, new information is largely redundant and the verdict flips to
   NO_RESEARCH_WORTHWHILE (tested).
2. **Calibration amplifier** — VoI is amplified where the system is *poorly
   calibrated* in this regime (its beliefs are untrustworthy → reducing epistemic
   uncertainty is worth more) and damped where well-calibrated. Measured: net VoI
   0.137 (miscalibrated) vs 0.003 (well-calibrated) for the same item.

This couples research spending to the learning loop — most VoI engines ignore both.
With unknown calibration it uses a conservative neutral prior (0.5 → amplifier 1.0).
