"""Diagnostics latency tail metrics + performance_tail_score (Integrated Sprint — Part 1).

The 122k-row cockpit stress proof gives ``p95`` and ``p99`` good numbers, but a
single cold-recompute path can produce a ``max`` in the 32–50s range — a tail
the release gate previously did not see because it watched only p95.  This
module captures the tail explicitly:

    p95_ms     = percentile(L, 0.95)
    p99_ms     = percentile(L, 0.99)
    max_ms     = max(L)
    tail_ratio = max_ms / max(p99_ms, 1)

    performance_tail_score = 10 * clamp(
          0.30 * min(1, 1000 / max(p95_ms, 1))
        + 0.30 * min(1, 1500 / max(p99_ms, 1))
        + 0.25 * min(1, 3000 / max(max_ms, 1))
        + 0.10 * min(1, 2.5  / max(tail_ratio, 1))
        + 0.05 * I(cold_recompute_count_after_prewarm == 0),
        0, 1)

Release thresholds (122k fixture, post-prewarm)::

    hot_path_p95_ms                       <= 1000
    hot_path_p99_ms                       <= 1500
    hot_path_max_ms                       <= 3000
    tail_ratio                            <= 2.5
    cold_recompute_count_after_prewarm    == 0
    stale_snapshot_count                  == 0
    degraded_snapshot_count               == 0

Pure module; no DB, no network, no broker calls, no execution, no AI execution.
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

DEFAULT_HOT_P95_BUDGET_MS = 1000
DEFAULT_HOT_P99_BUDGET_MS = 1500
DEFAULT_HOT_MAX_BUDGET_MS = 3000
DEFAULT_TAIL_RATIO_BUDGET = 2.5


def _clamp01(value: float) -> float:
    if math.isnan(value) or value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def percentile(values: Iterable[float], p: float) -> float:
    """Linear-interpolated percentile over a numeric iterable.

    Empty input -> 0.0 (a tail metric over no samples is *vacuously safe*; the
    gate must check ``sample_count`` separately to refuse an empty proof).
    """
    arr = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not arr:
        return 0.0
    if p <= 0:
        return float(arr[0])
    if p >= 1:
        return float(arr[-1])
    k = (len(arr) - 1) * p
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(arr[lo])
    frac = k - lo
    return float(arr[lo] + (arr[hi] - arr[lo]) * frac)


def compute_tail_metrics(
    latencies_ms: Iterable[float],
    *,
    cold_recompute_count_after_prewarm: int = 0,
    stale_snapshot_count: int = 0,
    degraded_snapshot_count: int = 0,
    hot_p95_budget_ms: int = DEFAULT_HOT_P95_BUDGET_MS,
    hot_p99_budget_ms: int = DEFAULT_HOT_P99_BUDGET_MS,
    hot_max_budget_ms: int = DEFAULT_HOT_MAX_BUDGET_MS,
    tail_ratio_budget: float = DEFAULT_TAIL_RATIO_BUDGET,
) -> dict[str, Any]:
    """Compute p95/p99/max/tail_ratio + performance_tail_score + pass/fail flags."""
    latencies = [float(v) for v in latencies_ms if isinstance(v, (int, float))]
    sample_count = len(latencies)

    p95 = percentile(latencies, 0.95) if sample_count else 0.0
    p99 = percentile(latencies, 0.99) if sample_count else 0.0
    max_ms = max(latencies) if sample_count else 0.0
    tail_ratio = max_ms / max(p99, 1.0) if sample_count else 0.0

    no_cold = 1 if cold_recompute_count_after_prewarm == 0 else 0
    score_inner = (
        0.30 * min(1.0, hot_p95_budget_ms / max(p95, 1.0))
        + 0.30 * min(1.0, hot_p99_budget_ms / max(p99, 1.0))
        + 0.25 * min(1.0, hot_max_budget_ms / max(max_ms, 1.0))
        + 0.10 * min(1.0, tail_ratio_budget / max(tail_ratio, 1.0))
        + 0.05 * no_cold
    )
    performance_tail_score = round(10.0 * _clamp01(score_inner), 4)

    # The gate must hold ALL of these.  Each is surfaced for traceability.
    thresholds = {
        "hot_path_p95_ms_ok": p95 <= hot_p95_budget_ms,
        "hot_path_p99_ms_ok": p99 <= hot_p99_budget_ms,
        "hot_path_max_ms_ok": max_ms <= hot_max_budget_ms,
        "tail_ratio_ok": tail_ratio <= tail_ratio_budget,
        "cold_recompute_count_after_prewarm_ok":
            cold_recompute_count_after_prewarm == 0,
        "stale_snapshot_count_ok": stale_snapshot_count == 0,
        "degraded_snapshot_count_ok": degraded_snapshot_count == 0,
        "sample_count_ok": sample_count > 0,
    }
    release_thresholds_ok = all(thresholds.values())

    return {
        "report": "diagnostics_tail_metrics",
        "sample_count": sample_count,
        "p95_ms": round(p95, 3),
        "p99_ms": round(p99, 3),
        "max_ms": round(max_ms, 3),
        "tail_ratio": round(tail_ratio, 3),
        "cold_recompute_count_after_prewarm": int(cold_recompute_count_after_prewarm),
        "stale_snapshot_count": int(stale_snapshot_count),
        "degraded_snapshot_count": int(degraded_snapshot_count),
        "performance_tail_score": performance_tail_score,
        "hot_p95_budget_ms": hot_p95_budget_ms,
        "hot_p99_budget_ms": hot_p99_budget_ms,
        "hot_max_budget_ms": hot_max_budget_ms,
        "tail_ratio_budget": tail_ratio_budget,
        "thresholds": thresholds,
        "release_thresholds_ok": release_thresholds_ok,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagnostics_tail_metrics.py",
        description=(
            "Compute p95/p99/max/tail_ratio + performance_tail_score from a "
            "JSON list of latencies. Read-only; no broker calls; no execution."
        ),
    )
    p.add_argument("--latencies-json", type=str,
                   help="JSON list of latencies in ms (e.g. '[12, 45, 800]')")
    p.add_argument("--latencies-file", type=str,
                   help="Path to a JSON file containing the list")
    p.add_argument("--cold-recomputes", type=int, default=0)
    p.add_argument("--stale-count", type=int, default=0)
    p.add_argument("--degraded-count", type=int, default=0)
    p.add_argument("--json", action="store_true")
    return p


def _load_latencies_arg(args: argparse.Namespace) -> list[float]:
    if args.latencies_json:
        return list(json.loads(args.latencies_json))
    if args.latencies_file:
        from pathlib import Path
        return list(json.loads(Path(args.latencies_file).read_text(encoding="utf-8")))
    return []


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    metrics = compute_tail_metrics(
        _load_latencies_arg(args),
        cold_recompute_count_after_prewarm=args.cold_recomputes,
        stale_snapshot_count=args.stale_count,
        degraded_snapshot_count=args.degraded_count,
    )
    if args.json:
        print(json.dumps(metrics, indent=2, default=str))
    else:
        print("Diagnostics Tail Metrics (advisory)")
        print("===================================")
        for key in ("sample_count", "p95_ms", "p99_ms", "max_ms", "tail_ratio",
                    "cold_recompute_count_after_prewarm",
                    "performance_tail_score", "release_thresholds_ok"):
            print(f"  {key:<42} : {metrics.get(key)}")
    return 0 if metrics["release_thresholds_ok"] else 1


__all__ = [
    "DEFAULT_HOT_P95_BUDGET_MS",
    "DEFAULT_HOT_P99_BUDGET_MS",
    "DEFAULT_HOT_MAX_BUDGET_MS",
    "DEFAULT_TAIL_RATIO_BUDGET",
    "percentile",
    "compute_tail_metrics",
]


if __name__ == "__main__":
    raise SystemExit(main())
