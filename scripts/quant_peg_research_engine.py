"""Quant hackathon — PEG empirical research framework (mission 9/12).

The flagship falsifiable hypothesis:

    R̂_event_{i,t} = β · X_{i,e} · ΔP_t          (expected repricing)
    R_obs_{i,t}   = ln(S_{i,t} / S_{i,t-τ})      (observed repricing)
    PEG_{i,t}     = R̂ − R_obs                    (raw gap)
    PEG_Z_{i,t}   = PEG / (σ_i + ε)              (vol-normalized gap)

Falsification target:  E[AR_{t+h} | PEG > z] > E[AR_{t+h}]  — tested via
quantile conditioning, monotonicity, ΔP-only baseline, and a seeded
PLACEBO (security-mapping shuffle).  β defaults to 1.0 and is explicitly
HEURISTIC until calibrated.

Data honesty: every dataset row carries ``data_mode``.  Rows stamped
FIXTURE_DEMONSTRATION can exercise the machinery but the report ALWAYS
separates real N from fixture N — fixture rows can never masquerade as
evidence of alpha.  RESEARCH_ONLY; no trade decision may consume this.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from scripts.quant_event_study_engine import compare_to_baseline, event_study
from scripts.quant_statistics_engine import (
    EPS,
    INSUFFICIENT_DATA,
    OK,
    quantile_monotonicity,
)

RESEARCH_ONLY = "RESEARCH_ONLY"
HEURISTIC_BETA = 1.0        # documented default; calibration hook below
LIVE = "LIVE"
FIXTURE = "FIXTURE_DEMONSTRATION"


def peg_value(*, delta_p: float, exposure: float,
              observed_move: float, sigma_daily: float | None = None,
              beta: float = HEURISTIC_BETA) -> dict[str, Any]:
    """Compute PEG and PEG_Z for one (event, security, window).

    Invariant (tested): if R̂ == R_obs then PEG == 0.
    """
    expected = beta * exposure * delta_p
    peg = expected - observed_move
    out = {"expected_move": expected, "observed_move": observed_move,
           "peg": peg, "beta": beta,
           "beta_status": "HEURISTIC (uncalibrated default 1.0)"}
    out["peg_z"] = (peg / (sigma_daily + EPS)) if sigma_daily else None
    return out


def load_retrocast_corpus(path: Path) -> dict[str, Any]:
    """Load the PEG research corpus, splitting REAL from FIXTURE rows.

    Never fabricates observations: rows missing delta_p or forward
    returns are dropped and counted.
    """
    real: list[dict[str, Any]] = []
    fixture: list[dict[str, Any]] = []
    dropped = 0
    if not path.exists():
        return {"status": INSUFFICIENT_DATA, "real": [], "fixture": [],
                "reason": f"missing corpus: {path}"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            dropped += 1
            continue
        if row.get("delta_p") is None or row.get("fwd_return_5") is None:
            dropped += 1
            continue
        (fixture if row.get("data_mode") == FIXTURE else real).append(row)
    return {"status": OK, "real": real, "fixture": fixture,
            "n_real": len(real), "n_fixture": len(fixture),
            "dropped": dropped}


def build_peg_dataset(rows: list[dict[str, Any]], *,
                      exposure_default: float = 1.0) -> list[dict[str, Any]]:
    """Corpus rows -> PEG research samples with horizon AR ladders.

    The retrocast corpus provides fwd_return_{1,5,21} per (event, ticker).
    Exposure defaults to 1.0 (HEURISTIC) when the corpus has none — the
    default is stamped so conditioning on exposure knows it is fake.
    """
    samples = []
    for r in rows:
        pv = peg_value(delta_p=float(r["delta_p"]),
                       exposure=exposure_default,
                       observed_move=float(r.get("fwd_return_1") or 0.0))
        samples.append({
            "event_id": str(r.get("market_id") or r.get("record_id")),
            "record_id": str(r.get("record_id")),
            "ticker": str(r.get("ticker")),
            "data_mode": r.get("data_mode") or "UNLABELED",
            "delta_p": float(r["delta_p"]),
            "peg": pv["peg"],
            "exposure_status": "HEURISTIC_DEFAULT_1.0",
            "ar": {1: r.get("fwd_return_1"), 5: r.get("fwd_return_5"),
                   21: r.get("fwd_return_21")},
        })
    return samples


def peg_experiment(samples: list[dict[str, Any]], *,
                   horizons: tuple[int, ...] = (1, 5, 21),
                   n_min: int = 8, seed: int = 11) -> dict[str, Any]:
    """Full PEG study: signal quantiles + monotonicity + ΔP baseline +
    placebo shuffle.  All statistics carry N."""
    modes = sorted({s["data_mode"] for s in samples})
    base: dict[str, Any] = {"signal_class": RESEARCH_ONLY,
                            "data_modes_present": modes,
                            "n_samples": len(samples)}
    if len(samples) < n_min:
        return {**base, "status": INSUFFICIENT_DATA, "n_min": n_min}

    h_primary = 5 if 5 in horizons else horizons[0]
    sig = [s["peg"] for s in samples]
    fwd = [float(s["ar"][h_primary]) for s in samples
           if s["ar"][h_primary] is not None]
    sig = sig[:len(fwd)]

    # 1. Quantile conditioning + monotonicity (mission 12/22).
    mono = quantile_monotonicity(sig, fwd, k=min(5, len(fwd) // 5 or 2),
                                 n_min_per_bucket=4)

    # 2. Event study on top-quantile PEG vs ΔP-only baseline (mission 31).
    ranked_peg = sorted(samples, key=lambda s: -s["peg"])
    ranked_dp = sorted(samples, key=lambda s: -abs(s["delta_p"]))
    top_n = max(n_min, len(samples) // 3)
    study_peg = event_study(
        {s["record_id"]: {h: s["ar"][h] for h in horizons
                          if s["ar"][h] is not None}
         for s in ranked_peg[:top_n]}, horizons=horizons, n_min=n_min)
    study_dp = event_study(
        {s["record_id"]: {h: s["ar"][h] for h in horizons
                          if s["ar"][h] is not None}
         for s in ranked_dp[:top_n]}, horizons=horizons, n_min=n_min)
    study_all = event_study(
        {s["record_id"]: {h: s["ar"][h] for h in horizons
                          if s["ar"][h] is not None}
         for s in samples}, horizons=horizons, n_min=n_min)

    # 3. Placebo: shuffle the PEG->outcome mapping (mission: placebo test).
    rng = random.Random(seed)
    shuffled = fwd[:]
    rng.shuffle(shuffled)
    mono_placebo = quantile_monotonicity(
        sig, shuffled, k=min(5, len(fwd) // 5 or 2), n_min_per_bucket=4)

    return {
        **base, "status": OK, "primary_horizon": h_primary,
        "monotonicity": mono,
        "monotonicity_placebo": mono_placebo,
        "placebo_verdict": _placebo_verdict(mono, mono_placebo),
        "event_study_top_peg": study_peg,
        "event_study_top_delta_p_baseline": study_dp,
        "event_study_unconditional": study_all,
        "peg_vs_delta_p": compare_to_baseline(study_peg, study_dp),
        "peg_vs_unconditional": compare_to_baseline(study_peg, study_all),
        "exposure_caveat": "exposure defaulted to 1.0 (HEURISTIC) — PEG "
                           "here reduces to ΔP minus observed move",
    }


def _placebo_verdict(real: dict[str, Any], placebo: dict[str, Any]) -> str:
    if real.get("status") != OK or placebo.get("status") != OK:
        return INSUFFICIENT_DATA
    edge_real = real.get("top_minus_bottom") or 0.0
    edge_placebo = abs(placebo.get("top_minus_bottom") or 0.0)
    if abs(edge_real) <= edge_placebo * 1.5:
        return ("NO_EVIDENCE_BEYOND_PLACEBO — real spread does not "
                "meaningfully exceed shuffled spread")
    return "EXCEEDS_PLACEBO (necessary, not sufficient, for real signal)"
