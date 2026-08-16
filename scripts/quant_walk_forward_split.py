"""Quant hackathon — chronological walk-forward splits + purge/embargo.

Missions 28–29.  Absolutely no random train/test splits for time-series
claims; the split object enforces:

    Train_k = [t0, t_k),  Test_k = [t_k, t_k + test_span)

with an optional PURGE (drop training samples whose OUTCOME window
[t, t+h] overlaps the test window) and EMBARGO (skip a buffer after each
test window before training data may resume in later folds).

``assert_no_lookahead`` is the single leakage guard every experiment
should call: a sample enters the information set at time t only if its
availability timestamp satisfies t_available <= t.
"""
from __future__ import annotations

from typing import Any, Sequence

OK = "OK"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class LookaheadError(ValueError):
    """Raised when a sample's availability timestamp exceeds signal time."""


def assert_no_lookahead(samples: Sequence[dict[str, Any]], *,
                        time_key: str = "t",
                        available_key: str = "t_available") -> int:
    """Every sample must satisfy t_available <= t.  Returns count checked."""
    for s in samples:
        t, avail = s.get(time_key), s.get(available_key)
        if t is None or avail is None:
            raise LookaheadError(
                f"sample missing {time_key}/{available_key}: {s}")
        if str(avail) > str(t):
            raise LookaheadError(
                f"lookahead: available {avail} > signal time {t}")
    return len(samples)


def walk_forward_folds(sorted_times: Sequence[str], *, n_folds: int = 3,
                       min_train: int = 8, horizon: int = 0,
                       embargo: int = 0, expanding: bool = True,
                       ) -> dict[str, Any]:
    """Build chronological folds over sorted, unique sample times.

    ``horizon`` (in index units) purges the last ``horizon`` training
    samples before each test start — their outcome windows would overlap
    the test period.  ``embargo`` skips samples immediately after each
    test window in later training sets (only relevant for rolling reuse).
    """
    times = list(sorted_times)
    if sorted(times) != times:
        raise ValueError("sample times must be pre-sorted ascending")
    n = len(times)
    test_span = (n - min_train) // n_folds if n_folds else 0
    if n < min_train + n_folds or test_span < 1:
        return {"status": INSUFFICIENT_DATA, "n": n,
                "n_min": min_train + n_folds}
    folds = []
    for k in range(n_folds):
        test_start = min_train + k * test_span
        test_end = test_start + test_span if k < n_folds - 1 else n
        train_end = max(0, test_start - horizon)      # purge
        train_start = 0 if expanding else max(0, train_end - min_train)
        train_idx = list(range(train_start, train_end))
        if embargo and k > 0:
            prev_test_end = min_train + k * test_span
            embargo_zone = set(range(prev_test_end,
                                     min(n, prev_test_end + embargo)))
            train_idx = [i for i in train_idx if i not in embargo_zone]
        folds.append({
            "fold": k + 1,
            "train_times": [times[i] for i in train_idx],
            "test_times": times[test_start:test_end],
            "purged": test_start - train_end,
        })
    for f in folds:  # invariant: max(train) < min(test) — leak-free
        if f["train_times"] and f["test_times"]:
            assert max(f["train_times"]) < min(f["test_times"])
    return {"status": OK, "n": n, "folds": folds,
            "expanding": expanding, "horizon_purge": horizon,
            "embargo": embargo}
