# Mythos observation samples

Small, deterministic, **non-sensitive** observation clusters for driving the
advisory runner from disk. These are advisory-only inputs — they carry no
real-money execution path.

Each file is a JSON list of `MythosObservation` dicts (see
`scripts/signal_arbitrage/mythos.py`). The runner reconstructs them via
`_obs_from_dict`, so any field on `MythosObservation` is accepted; everything
else is ignored.

## `reality_up_narrative_down.json`

The canonical Mythos divergence: **economic reality is improving while the
narrative is quiet/negative** (`REALITY_UP_NARRATIVE_DOWN`). The same retention
thesis is corroborated across **three distinct ecologies** (an official filing,
a community post, a commercial web-traffic vendor), so it clears corroboration
and routes to Fable 5 for scoring.

Run it (read-only, no capture):

```bash
python -m scripts.signal_arbitrage.advisory_runner \
  --observations examples/mythos_observations/reality_up_narrative_down.json
```

The output is stamped `advisory_status=ADVISORY_ONLY` and
`real_money_execution=PROHIBITED`. By default **nothing is written**. To capture
the decision into a local calibration corpus, see
`docs/OPERATOR_QUICKSTART.md`.
