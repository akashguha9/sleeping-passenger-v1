"""Repo discipline ratchets — two bug classes this repository actually
shipped, frozen so they can never grow back.

1. Eager ``db_path`` defaults (``db_path: Path = DB_PATH``) bind the
   database path at import time and silently ignore test/runtime
   injection.  This caused repeated real defects during the titration
   sprints (monkeypatched DB_PATH ignored by defaults).  Convention for
   ALL new code: ``db_path: Path | None = None`` + lazy resolution.

2. Wall-clock leaks in time-sensitive evaluators.  A pure evaluator
   without an injectable clock made nine chart-structure CI tests fail
   purely by calendar passage (STALE boundary crossed 2026-06-13).
   Every evaluator on the runtime path must accept ``now``.

Both ratchets are also live runtime checks inside
``scripts/system_integrity_probe.py``; these tests keep them enforced
in CI even if the probe is never called.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import system_integrity_probe as probe  # noqa: E402


# ---------------------------------------------------------------------------
# Ratchet 1 — eager DB_PATH defaults may shrink, never grow
# ---------------------------------------------------------------------------


def test_eager_db_path_defaults_do_not_grow():
    counts = probe.scan_eager_db_path_defaults()
    violations = []
    for fname, n in sorted(counts.items()):
        allowed = probe.EAGER_DB_PATH_BASELINE.get(fname, 0)
        if n > allowed:
            violations.append(f"{fname}: {n} > baseline {allowed}")
    assert not violations, (
        "New eager 'db_path: Path = DB_PATH' default(s) introduced:\n  "
        + "\n  ".join(violations)
        + "\nUse 'db_path: Path | None = None' and resolve DB_PATH lazily "
        "inside the function body (see titration_runtime_store.py for the "
        "pattern). If a legacy count legitimately shrank, lower the "
        "baseline in scripts/system_integrity_probe.py."
    )


def test_eager_db_path_baseline_is_exactly_current():
    """The baseline must track reality — if legacy occurrences shrink,
    ratchet the baseline down so they cannot silently reappear."""
    counts = probe.scan_eager_db_path_defaults()
    stale = {
        fname: (counts.get(fname, 0), allowed)
        for fname, allowed in probe.EAGER_DB_PATH_BASELINE.items()
        if counts.get(fname, 0) < allowed
    }
    assert not stale, (
        f"Baseline entries higher than reality (ratchet down): {stale}"
    )


# ---------------------------------------------------------------------------
# Ratchet 2 — every time-sensitive evaluator accepts an injected clock
# ---------------------------------------------------------------------------


def test_all_registered_evaluators_accept_injected_clock():
    import importlib
    missing = []
    for module_name, callable_name, param in probe.CLOCK_INJECTED_EVALUATORS:
        module = importlib.import_module(module_name)
        fn = getattr(module, callable_name)
        if param not in inspect.signature(fn).parameters:
            missing.append(f"{module_name}.{callable_name}({param}=...)")
    assert not missing, (
        "Evaluator(s) lost their injectable clock parameter — this is the "
        f"wall-clock time-bomb bug class: {missing}"
    )


def test_clock_registry_covers_the_known_evaluators():
    """The registry itself must not silently shrink."""
    registered = {f"{m}.{c}" for m, c, _ in probe.CLOCK_INJECTED_EVALUATORS}
    required = {
        "scripts.market_titration_engine.evaluate_market_titration",
        "scripts.market_data_freshness.evaluate",
        "scripts.chart_structure_price_truth.compute_price_truth",
        "scripts.chart_structure_api_context._get_chart_structure",
        "scripts.narrative_cascade_engine.build_cascade_report",
        "scripts.narrative_state_engine.build_narrative_state",
    }
    assert required <= registered, (
        f"Clock-injection registry lost entries: {required - registered}"
    )
