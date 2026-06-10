"""Probabilistic calibration metrics for advisory scores (Pass 4).

Turns "the model said 0.8" into an honest question: of everything it
said 0.8 about, how many actually happened? Metrics (test-pinned against
synthetic data with known answers):

    Brier   = (1/N) Σ (p_i - y_i)²
    LogLoss = -(1/N) Σ [y_i ln(p_i) + (1-y_i) ln(1-p_i)]   (clipped ε)
    ECE     = Σ_k (n_k/N) · |acc(B_k) - conf(B_k)|

plus reliability bins and abstention-threshold analysis (what happens to
accuracy/coverage if the model abstains below confidence τ).

Hard rules: probabilities outside [0,1] are rejected (not clipped —
clipping hides bugs); empty bins are skipped, never divide-by-zero;
N < 50 emits a small-sample warning and N < 10 refuses to summarize ECE
at all. Advisory-only: numbers for a human, never a trade.
"""
from __future__ import annotations

import datetime as _dt
import math
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EPS = 1e-12
SMALL_SAMPLE_N = 50
MIN_ECE_N = 10


class CalibrationError(ValueError):
    """Raised on malformed probability/outcome input."""


def _validate(probs: list[float], outcomes: list[int]) -> None:
    if len(probs) != len(outcomes):
        raise CalibrationError(
            f"length mismatch: {len(probs)} probabilities vs {len(outcomes)} outcomes"
        )
    for i, p in enumerate(probs):
        if not isinstance(p, (int, float)) or p != p:
            raise CalibrationError(f"p[{i}]={p!r} is not a number")
        if not (0.0 <= p <= 1.0):
            raise CalibrationError(
                f"p[{i}]={p} outside [0,1] — rejected, not clipped (clipping hides bugs)"
            )
    for i, y in enumerate(outcomes):
        if y not in (0, 1):
            raise CalibrationError(f"y[{i}]={y!r} must be 0 or 1")


def brier_score(probs: list[float], outcomes: list[int]) -> float:
    _validate(probs, outcomes)
    if not probs:
        raise CalibrationError("no samples")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def log_loss(probs: list[float], outcomes: list[int]) -> float:
    """Clipped at ε so a confident wrong answer is finite but brutal."""
    _validate(probs, outcomes)
    if not probs:
        raise CalibrationError("no samples")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(max(p, _EPS), 1.0 - _EPS)
        total += y * math.log(p) + (1 - y) * math.log(1 - p)
    return -total / len(probs)


def reliability_bins(
    probs: list[float], outcomes: list[int], n_bins: int = 10
) -> list[dict]:
    """Equal-width bins over [0,1]; empty bins reported as empty."""
    _validate(probs, outcomes)
    if n_bins < 2:
        raise CalibrationError("need at least 2 bins")
    bins: list[dict] = []
    for k in range(n_bins):
        lo, hi = k / n_bins, (k + 1) / n_bins
        members = [
            (p, y) for p, y in zip(probs, outcomes)
            if (lo <= p < hi) or (k == n_bins - 1 and p == 1.0)
        ]
        if members:
            conf = sum(p for p, _ in members) / len(members)
            acc = sum(y for _, y in members) / len(members)
            bins.append({"bin": k, "lo": lo, "hi": hi, "n": len(members),
                         "confidence": conf, "accuracy": acc,
                         "gap": abs(acc - conf)})
        else:
            bins.append({"bin": k, "lo": lo, "hi": hi, "n": 0,
                         "confidence": None, "accuracy": None, "gap": None})
    return bins


def expected_calibration_error(
    probs: list[float], outcomes: list[int], n_bins: int = 10
) -> float:
    _validate(probs, outcomes)
    n = len(probs)
    if n < MIN_ECE_N:
        raise CalibrationError(
            f"N={n} < {MIN_ECE_N}: refusing to summarize ECE on a sample "
            "this small — it would be noise wearing a number"
        )
    ece = 0.0
    for b in reliability_bins(probs, outcomes, n_bins):
        if b["n"]:
            ece += (b["n"] / n) * b["gap"]
    return ece


def abstention_analysis(
    probs: list[float], outcomes: list[int],
    thresholds: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9),
) -> list[dict]:
    """If the model abstains when max(p, 1-p) < τ: coverage vs accuracy.

    Decisions are p >= 0.5 → predict 1 else 0; certainty = max(p, 1-p).
    """
    _validate(probs, outcomes)
    rows = []
    for tau in thresholds:
        kept = [(p, y) for p, y in zip(probs, outcomes) if max(p, 1 - p) >= tau]
        if kept:
            correct = sum(1 for p, y in kept if (p >= 0.5) == bool(y))
            rows.append({"threshold": tau, "coverage": len(kept) / len(probs),
                         "n_kept": len(kept), "accuracy_on_kept": correct / len(kept)})
        else:
            rows.append({"threshold": tau, "coverage": 0.0, "n_kept": 0,
                         "accuracy_on_kept": None})
    return rows


def calibration_summary(
    probs: list[float], outcomes: list[int], n_bins: int = 10
) -> dict:
    _validate(probs, outcomes)
    n = len(probs)
    summary: dict = {
        "n": n,
        "brier": brier_score(probs, outcomes) if n else None,
        "log_loss": log_loss(probs, outcomes) if n else None,
        "bins": reliability_bins(probs, outcomes, n_bins),
        "abstention": abstention_analysis(probs, outcomes),
        "base_rate": sum(outcomes) / n if n else None,
        "warnings": [],
        "advisory_only": True,
    }
    if n < SMALL_SAMPLE_N:
        summary["warnings"].append(
            f"SMALL SAMPLE (N={n} < {SMALL_SAMPLE_N}): treat every number "
            "here as provisional"
        )
    try:
        summary["ece"] = expected_calibration_error(probs, outcomes, n_bins)
    except CalibrationError as exc:
        summary["ece"] = None
        summary["warnings"].append(str(exc))
    return summary


def render_report(summary: dict, model_name: str = "advisory-signal") -> str:
    lines = [
        f"# Calibration report — {model_name}",
        "",
        f"Generated: {_dt.datetime.now(_dt.timezone.utc).isoformat()}",
        "Advisory-only. These numbers inform a human; nothing executes.",
        "",
        f"- N: {summary['n']}  ·  base rate: {summary['base_rate']}",
        f"- Brier: {summary['brier']}",
        f"- Log loss: {summary['log_loss']}",
        f"- ECE: {summary['ece']}",
        "",
    ]
    for w in summary["warnings"]:
        lines.append(f"> ⚠️ {w}")
    lines += ["", "## Reliability bins", "",
              "| bin | range | n | confidence | accuracy | gap |",
              "| --- | ----- | - | ---------- | -------- | --- |"]
    for b in summary["bins"]:
        rng = f"[{b['lo']:.1f},{b['hi']:.1f})"
        if b["n"]:
            lines.append(f"| {b['bin']} | {rng} | {b['n']} | "
                         f"{b['confidence']:.3f} | {b['accuracy']:.3f} | {b['gap']:.3f} |")
        else:
            lines.append(f"| {b['bin']} | {rng} | 0 | — | — | — |")
    lines += ["", "## Abstention analysis", "",
              "| threshold | coverage | n kept | accuracy on kept |",
              "| --------- | -------- | ------ | ---------------- |"]
    for r in summary["abstention"]:
        acc = f"{r['accuracy_on_kept']:.3f}" if r["accuracy_on_kept"] is not None else "—"
        lines.append(f"| {r['threshold']} | {r['coverage']:.3f} | {r['n_kept']} | {acc} |")
    lines.append("")
    return "\n".join(lines)


def write_report(
    probs: list[float], outcomes: list[int], *,
    model_name: str = "advisory-signal", out_dir: Path | None = None,
) -> Path:
    summary = calibration_summary(probs, outcomes)
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"calibration_report_{stamp}.md"
    path.write_text(render_report(summary, model_name), encoding="utf-8")
    return path
