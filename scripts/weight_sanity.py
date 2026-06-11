"""Empirical weight sanity layer (Pass 5, Phase 6).

The scoring weights are hand-set priors. This module does NOT pretend to
fix that without data — it (a) inventories every production weight set,
(b) statically detects structural problems, (c) measures fragility with
the Pass-4 sensitivity analyzer, and (d) offers CONSTRAINED fitting that
flatly refuses to run without enough outcome data
(``INSUFFICIENT_DATA_FOR_FIT``).

Static checks: weights not summing to 1 where required; negative weights
where not allowed; single-feature dominance; threshold cliffs (decision
thresholds within ε of the neutral-score mass); correlated duplicate
features (needs sample data); unused features; high-sensitivity weights.

Constrained fit (only with ≥ MIN_FIT_SAMPLES outcomes):

    maximize  OOS_Utility(w) = mean(R_net_val) − λ·MDD_val − γ·turnover
                               − η·calibration_error
    s.t.      Σ w_j = 1,  0 ≤ w_j ≤ w_max,  turnover(w, w_old) ≤ τ

Fit on TRAIN, select on VALIDATION, report on TEST — never fit or select
on the test split, never shuffle time order, and the result is labeled
"candidate", never "optimized", unless its TEST utility beats the old
weights out-of-sample.

Advisory-only: weight hygiene for a human-reviewed score.
"""
from __future__ import annotations

import datetime as _dt
import itertools
import json
import statistics
from pathlib import Path

try:
    from scripts.sensitivity_analysis import analyze as _sensitivity_analyze
    from scripts.backtest_advisory_signals import max_drawdown as _mdd
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from sensitivity_analysis import analyze as _sensitivity_analyze  # type: ignore[no-redef]
    from backtest_advisory_signals import max_drawdown as _mdd  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_FIT_SAMPLES = 100
INSUFFICIENT_DATA_FOR_FIT = "INSUFFICIENT_DATA_FOR_FIT"
_DOMINANCE_LIMIT = 0.5
_CLIFF_EPS = 0.05
_CORRELATION_FLAG = 0.95


def production_weight_inventory() -> dict[str, dict]:
    """Import the live production weight sets (the real ones, not copies)."""
    inventory: dict[str, dict] = {}
    try:
        from scripts import daily_scoring as ds

        inventory["FCS_WEIGHTS"] = {
            "weights": dict(ds.FCS_WEIGHTS), "require_sum_1": True,
            "allow_negative": False, "source": "scripts/daily_scoring.py",
        }
        inventory["ERS_WEIGHTS"] = {
            "weights": dict(ds.ERS_WEIGHTS), "require_sum_1": True,
            "allow_negative": False, "source": "scripts/daily_scoring.py",
        }
        inventory["FCS_PENALTIES"] = {
            "weights": dict(getattr(ds, "FCS_PENALTIES", {})),
            "require_sum_1": False, "allow_negative": False,
            "source": "scripts/daily_scoring.py",
        }
    except Exception:  # pragma: no cover - import resilience
        pass
    try:
        from scripts import fresh_market_discovery as fmd

        inventory["CQS_WEIGHTS"] = {
            "weights": dict(fmd.CQS_WEIGHTS), "require_sum_1": False,
            "allow_negative": True,  # includes documented penalty terms
            "source": "scripts/fresh_market_discovery.py",
        }
    except Exception:  # pragma: no cover
        pass
    return inventory


def static_checks(
    name: str,
    weights: dict[str, float],
    *,
    require_sum_1: bool = True,
    allow_negative: bool = False,
    thresholds: dict[str, float] | None = None,
    neutral_features: dict[str, float] | None = None,
) -> list[dict]:
    """Structural findings for one weight set. severity: severe|warn|info."""
    findings: list[dict] = []
    if not weights:
        return [{"check": "empty", "severity": "severe",
                 "detail": f"{name}: no weights found"}]
    total = sum(weights.values())
    if require_sum_1 and abs(total - 1.0) > 1e-6:
        findings.append({"check": "sum_to_one", "severity": "severe",
                         "detail": f"{name}: weights sum to {total:.6f}, expected 1.0"})
    for key, w in weights.items():
        if w < 0 and not allow_negative:
            findings.append({"check": "negative_weight", "severity": "severe",
                             "detail": f"{name}.{key} = {w} (negative not allowed)"})
        if w == 0:
            findings.append({"check": "unused_feature", "severity": "warn",
                             "detail": f"{name}.{key} = 0 (dead feature — remove or justify)"})
    mass = sum(abs(w) for w in weights.values()) or 1.0
    for key, w in weights.items():
        share = abs(w) / mass
        if share > _DOMINANCE_LIMIT:
            findings.append({
                "check": "single_feature_dominance", "severity": "warn",
                "detail": f"{name}.{key} carries {share:.0%} of weight mass "
                          f"(> {_DOMINANCE_LIMIT:.0%}) — fragile by construction",
            })
    if thresholds and neutral_features:
        neutral_score = sum(weights.get(k, 0.0) * v
                            for k, v in neutral_features.items())
        for tname, tval in thresholds.items():
            if abs(neutral_score - tval) < _CLIFF_EPS:
                findings.append({
                    "check": "threshold_cliff", "severity": "warn",
                    "detail": f"{name}: neutral score {neutral_score:.3f} sits "
                              f"within {_CLIFF_EPS} of threshold "
                              f"{tname}={tval} — tiny input noise flips the tier",
                })
    return findings


def correlated_duplicates(
    feature_samples: list[dict[str, float]], threshold: float = _CORRELATION_FLAG
) -> list[dict]:
    """Flag feature pairs with |Pearson r| ≥ threshold (needs ≥ 10 samples)."""
    if len(feature_samples) < 10:
        return [{"check": "correlation", "severity": "info",
                 "detail": f"only {len(feature_samples)} samples — "
                           "correlation screen skipped (needs ≥ 10)"}]
    keys = sorted(feature_samples[0].keys())
    findings = []
    for a, b in itertools.combinations(keys, 2):
        xs = [float(s[a]) for s in feature_samples]
        ys = [float(s[b]) for s in feature_samples]
        sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
        if sx == 0 or sy == 0:
            continue
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)
        if abs(r) >= threshold:
            findings.append({
                "check": "correlated_duplicate", "severity": "warn",
                "detail": f"{a} vs {b}: |r|={abs(r):.3f} ≥ {threshold} — "
                          "two names for one signal inflate its real weight",
            })
    return findings


def sensitivity_findings(weights: dict[str, float],
                         neutral_value: float = 0.6) -> list[dict]:
    """Run the Pass-4 analyzer on neutral inputs; surface fragility."""
    clean = {k: max(0.0, float(w)) for k, w in weights.items()}
    total = sum(clean.values()) or 1.0
    clean = {k: w / total for k, w in clean.items()}
    features = {k: neutral_value for k in clean}
    report = _sensitivity_analyze(clean, features, decision_threshold=0.5,
                                  require_weight_sum_1=True)
    findings = []
    if report["recommendation"] == "ABSTAIN":
        findings.append({"check": "sensitivity_abstain", "severity": "warn",
                         "detail": "; ".join(report["recommendation_reasons"])})
    findings.append({"check": "dominant_feature", "severity": "info",
                     "detail": f"dominant: {report['dominant_feature']} "
                               f"({report['dominance'][report['dominant_feature']]:.0%})"})
    return findings


# ---------------------------------------------------------------------------
# Constrained fitting (refuses without data)
# ---------------------------------------------------------------------------


def oos_utility(net_returns: list[float], *, lam: float = 1.0,
                gamma: float = 0.1, eta: float = 0.5,
                turnover: float = 0.0, calibration_error: float = 0.0) -> float:
    if not net_returns:
        return float("-inf")
    return (statistics.fmean(net_returns) - lam * _mdd(net_returns)
            - gamma * turnover - eta * calibration_error)


def _turnover(w_new: dict[str, float], w_old: dict[str, float]) -> float:
    keys = set(w_new) | set(w_old)
    return 0.5 * sum(abs(w_new.get(k, 0.0) - w_old.get(k, 0.0)) for k in keys)


def constrained_fit(
    samples: list[dict],
    w_old: dict[str, float],
    *,
    w_max: float = 0.5,
    max_turnover: float = 0.3,
    step: float = 0.05,
    train_frac: float = 0.5,
    val_frac: float = 0.25,
) -> dict:
    """Coordinate grid search under constraints, time-ordered splits.

    ``samples``: chronologically ordered dicts with ``features`` (dict)
    and ``net_return`` (float). Refuses below MIN_FIT_SAMPLES. The
    returned candidate is adopted-worthy ONLY if it beats w_old on the
    untouched TEST split; either way the test utilities are reported.
    """
    if len(samples) < MIN_FIT_SAMPLES:
        return {"status": INSUFFICIENT_DATA_FOR_FIT,
                "samples": len(samples), "required": MIN_FIT_SAMPLES,
                "note": "no fit attempted — hand-set priors remain in force"}
    n = len(samples)
    n_train, n_val = int(n * train_frac), int(n * val_frac)
    train = samples[:n_train]
    val = samples[n_train:n_train + n_val]
    test = samples[n_train + n_val:]

    keys = sorted(w_old.keys())

    def portfolio_returns(w: dict[str, float], rows: list[dict]) -> list[float]:
        # Signal = Σ w_j x_j; realized utility proxy: act when signal>0.5,
        # collect that sample's net return (advisory hypothetical).
        out = []
        for row in rows:
            score = sum(w[k] * float(row["features"].get(k, 0.0)) for k in keys)
            if score > 0.5:
                out.append(float(row["net_return"]))
        return out

    def normalize(w: dict[str, float]) -> dict[str, float] | None:
        if any(v < 0 or v > w_max for v in w.values()):
            return None
        total = sum(w.values())
        if total <= 0:
            return None
        w = {k: v / total for k, v in w.items()}
        if any(v > w_max + 1e-9 for v in w.values()):
            return None
        if _turnover(w, w_old) > max_turnover:
            return None
        return w

    # Greedy coordinate ascent on VALIDATION utility, starting at w_old.
    best = dict(w_old)
    best_val = oos_utility(portfolio_returns(best, val),
                           turnover=0.0)
    improved = True
    iterations = 0
    while improved and iterations < 20:
        improved = False
        iterations += 1
        for k in keys:
            for delta in (-step, step):
                cand = dict(best)
                cand[k] = cand[k] + delta
                cand_n = normalize(cand)
                if cand_n is None:
                    continue
                # Fit signal direction on TRAIN: require non-degenerate
                # train utility before even scoring validation.
                if not portfolio_returns(cand_n, train):
                    continue
                u = oos_utility(portfolio_returns(cand_n, val),
                                turnover=_turnover(cand_n, w_old))
                if u > best_val + 1e-9:
                    best, best_val = cand_n, u
                    improved = True

    test_old = oos_utility(portfolio_returns(w_old, test))
    test_new = oos_utility(portfolio_returns(best, test))
    return {
        "status": "candidate" if test_new > test_old else "rejected_oos",
        "label": ("candidate weights beat old weights OUT-OF-SAMPLE — "
                  "still requires owner sign-off, never auto-adopted"
                  if test_new > test_old else
                  "candidate did NOT beat old weights on the test split — keep priors"),
        "w_old": w_old, "w_candidate": best,
        "turnover": round(_turnover(best, w_old), 4),
        "utility_validation": best_val,
        "utility_test_old": test_old, "utility_test_new": test_new,
        "splits": {"train": len(train), "validation": len(val), "test": len(test)},
        "advisory_only": True,
    }


def run_sanity(feature_samples: list[dict] | None = None) -> dict:
    """Full sanity sweep over the production inventory."""
    inventory = production_weight_inventory()
    findings: dict[str, list[dict]] = {}
    severe = 0
    for name, spec in inventory.items():
        f = static_checks(name, spec["weights"],
                          require_sum_1=spec["require_sum_1"],
                          allow_negative=spec["allow_negative"])
        if spec["require_sum_1"]:
            f += sensitivity_findings(spec["weights"])
        findings[name] = f
        severe += sum(1 for x in f if x["severity"] == "severe")
    if feature_samples:
        findings["_feature_correlations"] = correlated_duplicates(feature_samples)
    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "weight_sets": {k: v["weights"] for k, v in inventory.items()},
        "findings": findings,
        "severe_count": severe,
        "fit_status": INSUFFICIENT_DATA_FOR_FIT,
        "advisory_only": True,
        "human_review_required": True,
    }


def write_report(result: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"weight_sanity_report_{stamp}.json"
    json_path.write_text(json.dumps(result, indent=2, default=str) + "\n",
                         encoding="utf-8")
    lines = [
        "# Weight sanity report", "",
        f"Generated: {result['generated_utc']} · severe findings: "
        f"{result['severe_count']} · fit: {result['fit_status']}",
        "", "Advisory-only. Weights remain hand-set priors until a "
        "constrained fit beats them out-of-sample AND the owner signs off.", "",
    ]
    for name, items in result["findings"].items():
        lines.append(f"## {name}")
        for f in items:
            lines.append(f"- **{f['severity']}** [{f['check']}] {f['detail']}")
        if not items:
            lines.append("- clean")
        lines.append("")
    md_path = out_dir / f"weight_sanity_report_{stamp}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


if __name__ == "__main__":
    result = run_sanity()
    md, js = write_report(result)
    print(f"[ok] {md}\n[ok] {js}\nsevere findings: {result['severe_count']}")
    raise SystemExit(1 if result["severe_count"] else 0)
