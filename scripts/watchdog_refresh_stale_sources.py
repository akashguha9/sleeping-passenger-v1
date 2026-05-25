"""
scripts/watchdog_refresh_stale_sources.py — self-healing stale-source watchdog.

The 6-hour scheduled refresh keeps the orchestrator running.  But cleanly
exited subprocess != freshness improved — upstream APIs can rate-limit,
time out, or skip for an entire cycle, leaving the cockpit's "stale active
sources" panel populated while the scheduled task still reports PASS.

This watchdog reconciles those two states:

  1. Read the *canonical* stale-active source list using the same registry
     helpers the cockpit ``/live-sources/status`` endpoint uses.
  2. Excludes optional/config-missing sources (Etherscan when no key) from
     the failure count — they are not real failures, just unconfigured.
  3. Excludes planned-not-implemented adapters for the same reason.
  4. If any active source is stale, run ``refresh_live_signals.py --write``
     scoped to the parent stale sources first, then re-check freshness.
  5. If freshness has not improved, retry with exponential-backoff (default
     60s/180s/300s).  ``--no-sleep`` skips waits for tests.
  6. For the Prediction Market Disagreement derived source, only invokes
     the scanner once both parents (Polymarket + Kalshi) are FRESH; never
     pretends the derived source is fresh while a parent is stale.
  7. Writes ``runtime/refresh_watchdog_summary.json`` with before/after
     state and exits 0 (HEALTHY / IMPROVED_BUT_STALE) or 1
     (STALE_UNCHANGED / ERROR).

Safety
------
ADVISORY_ONLY.  This script DOES NOT trade, place orders, or call a broker
API.  No execution route exists; ``execution_gate`` stays LOCKED on every
output.  ``broker_api_called`` is always False.  ``can_execute`` is always
False.  ``ai_execution_count`` is always 0.  It only invokes existing
local Python scripts and reads SQLite metadata.

Examples
--------
  python scripts/watchdog_refresh_stale_sources.py
  python scripts/watchdog_refresh_stale_sources.py --ttl-hours 6 --max-retries 3
  python scripts/watchdog_refresh_stale_sources.py --no-sleep --json
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_TTL_HOURS = 6
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = (60, 180, 300)
DEFAULT_BACKOFF_JITTER_PCT = 0.15
MIN_SLEEP_SECONDS = 1.0
DEFAULT_SUMMARY_PATH = _REPO_ROOT / "runtime" / "refresh_watchdog_summary.json"
DEFAULT_REFRESH_COMMAND = (sys.executable, "scripts/refresh_live_signals.py", "--write")
DEFAULT_DISAGREEMENT_COMMAND = (
    sys.executable,
    "scripts/prediction_market_disagreement_scanner.py",
    "--write",
    "--limit",
    "50",
    "--embedding-provider",
    "deterministic",
)

# Tracked stale sources from the current cockpit screenshot.  Used only to
# guarantee per-source before/after rows appear in the summary JSON even
# when one of them is missing from the registry response.
TRACKED_STALE_SOURCES: tuple[str, ...] = (
    "kalshi",
    "gdelt",
    "prediction_market_disagreement",
)

DERIVED_SOURCE_KEYS: frozenset[str] = frozenset({"prediction_market_disagreement"})
DERIVED_PARENT_KEYS: dict[str, tuple[str, ...]] = {
    "prediction_market_disagreement": ("polymarket", "kalshi"),
}

# Mirrors scripts.live_source_registry.FRESHNESS_DEGRADED_PARENT_STALE.
# Re-declared here so the watchdog has no runtime dependency on the
# registry during the snapshot dataclass build — kept in lockstep.
FRESHNESS_DEGRADED_PARENT_STALE = "degraded_parent_stale"

STATUS_HEALTHY = "HEALTHY"
STATUS_IMPROVED_BUT_STALE = "IMPROVED_BUT_STALE"
STATUS_STALE_UNCHANGED = "STALE_UNCHANGED"
STATUS_ERROR = "ERROR"

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_only": True,
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "can_execute": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "human_review_required": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _compute_jittered_sleep(
    base_seconds: float,
    jitter_pct: float,
    *,
    rng: random.Random | None = None,
) -> float:
    """Return ``base_seconds`` perturbed by ±jitter_pct using ``rng``.

    Deterministic when callers inject a seeded ``random.Random``; bounded
    below by ``MIN_SLEEP_SECONDS`` so jitter never produces a near-zero
    sleep that defeats the back-off, and never returns a negative value.

    A zero or negative ``jitter_pct`` disables jitter and returns the
    base value unchanged.  A zero ``base_seconds`` returns 0 (i.e. don't
    sleep at all) — the floor only applies when the operator did intend
    to sleep.
    """
    base = float(base_seconds)
    if base <= 0:
        return 0.0
    pct = float(jitter_pct or 0.0)
    if pct <= 0.0:
        return base
    rng = rng if rng is not None else random.Random()
    delta = base * pct
    perturbed = base + rng.uniform(-delta, delta)
    if perturbed < MIN_SLEEP_SECONDS:
        return MIN_SLEEP_SECONDS
    return perturbed


def _tail(text: str, limit: int = 1200) -> str:
    """Trim a stdout/stderr blob to a safe tail.  Never returns more than
    ``limit`` chars and strips any obvious secret-looking tokens."""
    if not text:
        return ""
    body = str(text)
    if len(body) > limit:
        body = body[-limit:]
    # Conservative redaction of obvious api_key=... / token=... patterns.
    import re as _re

    body = _re.sub(
        r"(?i)(api[_-]?key|token|secret|bearer)\s*[=:\s]\s*[A-Za-z0-9_\-\.]+",
        r"\1=<redacted>",
        body,
    )
    return body


@dataclass
class SourceSnapshotEntry:
    source_key: str
    tier: str
    adapter_status: str
    requires_api_key: bool
    credential_configured: bool
    freshness_state: str
    last_success_at: str | None
    last_refresh_attempt_at: str | None
    last_refresh_success: bool
    last_refresh_skipped: bool
    last_refresh_error: str
    last_refresh_skipped_reason: str
    latest_event_at: str | None
    hours_since_last_success: float | None
    excluded_reason: str | None
    is_stale_active: bool
    is_derived: bool
    parent_sources: tuple[str, ...]
    # Dependency-critical metadata.  Populated for parents like Kalshi
    # whose stale-ness cascades into a derived signal (e.g. Prediction
    # Market Disagreement).  ``stale_severity`` defaults to "" for
    # non-critical sources; when this source is dependency_critical AND
    # stale, the watchdog reports ``"dependency_blocking"`` so the
    # cockpit can show a louder chip than the soft optional grade.
    dependency_critical: bool = False
    used_by_derived: tuple[str, ...] = ()
    stale_severity: str = ""
    degraded_parent_stale_parents: tuple[str, ...] = ()


@dataclass
class Snapshot:
    """Canonical health snapshot used by the watchdog.

    Built with the same primitives that drive ``/live-sources/status`` —
    ``compute_source_freshness`` + ``get_latest_refresh_run_per_source`` +
    ``get_persisted_row_stats_per_source`` — so the watchdog and the
    cockpit cannot disagree about which sources are stale.
    """

    generated_at_utc: str
    entries: dict[str, SourceSnapshotEntry] = field(default_factory=dict)
    ttl_hours: int = DEFAULT_TTL_HOURS

    @property
    def active_sources(self) -> list[str]:
        return [k for k, e in self.entries.items() if not e.excluded_reason]

    @property
    def stale_active_sources(self) -> list[str]:
        return [k for k, e in self.entries.items() if e.is_stale_active]

    @property
    def excluded_optional_sources(self) -> list[str]:
        return [
            k
            for k, e in self.entries.items()
            if e.excluded_reason == "optional_config_missing"
        ]

    @property
    def skipped_config_missing_sources(self) -> list[str]:
        return self.excluded_optional_sources

    @property
    def planned_sources(self) -> list[str]:
        return [
            k for k, e in self.entries.items() if e.excluded_reason == "planned_not_scored"
        ]

    @property
    def parent_stale_derived_sources(self) -> list[str]:
        out: list[str] = []
        for k, e in self.entries.items():
            if not e.is_derived:
                continue
            parents = e.parent_sources
            if not parents:
                continue
            if any(self._parent_is_stale(p) for p in parents):
                out.append(k)
        return out

    def _parent_is_stale(self, parent: str) -> bool:
        p = self.entries.get(parent)
        if p is None:
            return True
        if p.excluded_reason:
            return True
        if p.freshness_state != "fresh":
            return True
        return False

    def per_source_status_view(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key, e in self.entries.items():
            out[key] = {
                "tier": e.tier,
                "adapter_status": e.adapter_status,
                "credential_configured": e.credential_configured,
                "freshness_state": e.freshness_state,
                "last_success_at": e.last_success_at,
                "last_refresh_attempt_at": e.last_refresh_attempt_at,
                "last_refresh_success": e.last_refresh_success,
                "last_refresh_skipped": e.last_refresh_skipped,
                "last_refresh_error": e.last_refresh_error,
                "last_refresh_skipped_reason": e.last_refresh_skipped_reason,
                "latest_event_at": e.latest_event_at,
                "hours_since_last_success": e.hours_since_last_success,
                "excluded_reason": e.excluded_reason,
                "is_stale_active": e.is_stale_active,
                "is_derived": e.is_derived,
                "parent_sources": list(e.parent_sources),
                "dependency_critical": e.dependency_critical,
                "used_by_derived": list(e.used_by_derived),
                "stale_severity": e.stale_severity,
                "degraded_parent_stale_parents": list(e.degraded_parent_stale_parents),
            }
        return out


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------


def _load_snapshot(*, ttl_hours: int, now_epoch: float | None = None) -> Snapshot:
    """Build a canonical snapshot from persistence + the registry."""
    try:
        from scripts.live_source_registry import (
            DEPENDENCY_CRITICAL_SOURCES as _DEP_CRIT,
            compute_source_freshness,
            detect_source_credential_state,
            list_live_source_families,
        )
        from scripts.persistence import (
            get_latest_refresh_run_per_source,
            get_latest_source_run_per_source,
            get_persisted_row_stats_per_source,
        )
    except ModuleNotFoundError:  # pragma: no cover
        from live_source_registry import (  # type: ignore[no-redef]
            DEPENDENCY_CRITICAL_SOURCES as _DEP_CRIT,
            compute_source_freshness,
            detect_source_credential_state,
            list_live_source_families,
        )
        from persistence import (  # type: ignore[no-redef]
            get_latest_refresh_run_per_source,
            get_latest_source_run_per_source,
            get_persisted_row_stats_per_source,
        )

    latest_runs = get_latest_source_run_per_source()
    freshness = compute_source_freshness(
        latest_runs, cadence_hours=ttl_hours, now_epoch=now_epoch
    )
    try:
        refresh_runs = get_latest_refresh_run_per_source()
    except Exception:
        refresh_runs = {}
    try:
        persisted_stats = get_persisted_row_stats_per_source()
    except Exception:
        persisted_stats = {}
    cred = detect_source_credential_state()

    entries: dict[str, SourceSnapshotEntry] = {}
    for fam in list_live_source_families():
        key = fam["source_key"]
        f = freshness.get(key, {}) or {}
        rr = refresh_runs.get(key, {}) or {}
        ps = persisted_stats.get(key, {}) or {}
        c = cred.get(key, {}) or {}

        tier = str(fam.get("tier") or "optional").lower()
        adapter_status = str(fam.get("adapter_status") or "").lower()
        credential_configured = bool(c.get("configured"))
        freshness_state = str(f.get("freshness_state") or "unknown").lower()

        excluded_reason: str | None = None
        if adapter_status == "planned" or tier == "planned":
            excluded_reason = "planned_not_scored"
        elif tier == "optional" and not credential_configured:
            excluded_reason = "optional_config_missing"

        is_stale_active = False
        if excluded_reason is None:
            if freshness_state in {
                "stale",
                "overdue",
                "never_run",
                "failed",
                FRESHNESS_DEGRADED_PARENT_STALE,
            }:
                is_stale_active = True
            hours = f.get("hours_since_last_success")
            if isinstance(hours, (int, float)) and hours is not None and hours > ttl_hours:
                is_stale_active = True

        parents = DERIVED_PARENT_KEYS.get(key, ())
        is_derived = key in DERIVED_SOURCE_KEYS

        # Dependency-critical metadata.  Kalshi is the canonical example —
        # registry tier remains ``optional`` for scoring continuity, but the
        # watchdog grades a stale Kalshi as ``dependency_blocking`` because
        # it cascades into the Prediction Market Disagreement signal.
        dep_info = _DEP_CRIT.get(key, {})
        dep_critical = bool(dep_info.get("dependency_critical"))
        used_by = tuple(dep_info.get("used_by") or ())
        if dep_critical and is_stale_active:
            stale_severity_label = str(
                dep_info.get("stale_severity_when_active") or "dependency_blocking"
            )
        elif is_stale_active and tier == "core":
            stale_severity_label = "loud"
        elif is_stale_active and tier == "secondary":
            stale_severity_label = "moderate"
        elif is_stale_active:
            stale_severity_label = "soft"
        else:
            stale_severity_label = ""

        degraded_parent_stale_parents = tuple(
            f.get("degraded_parent_stale_parents") or ()
        )

        entries[key] = SourceSnapshotEntry(
            source_key=key,
            tier=tier,
            adapter_status=adapter_status,
            requires_api_key=bool(fam.get("requires_api_key")),
            credential_configured=credential_configured,
            freshness_state=freshness_state,
            last_success_at=(f.get("last_success_at") or None),
            last_refresh_attempt_at=(rr.get("finished_at") or rr.get("started_at") or None),
            last_refresh_success=bool(int(rr.get("success", 0) or 0)),
            last_refresh_skipped=bool(int(rr.get("skipped", 0) or 0)),
            last_refresh_error=str(rr.get("error_message") or "")[:240],
            last_refresh_skipped_reason=str(rr.get("skipped_reason") or "")[:240],
            latest_event_at=(ps.get("latest_fetched_at") or None),
            hours_since_last_success=(
                round(float(f.get("hours_since_last_success")), 4)
                if isinstance(f.get("hours_since_last_success"), (int, float))
                else None
            ),
            excluded_reason=excluded_reason,
            is_stale_active=is_stale_active,
            is_derived=is_derived,
            parent_sources=parents,
            dependency_critical=dep_critical,
            used_by_derived=used_by,
            stale_severity=stale_severity_label,
            degraded_parent_stale_parents=degraded_parent_stale_parents,
        )

    return Snapshot(
        generated_at_utc=_utc_now_iso(), entries=entries, ttl_hours=int(ttl_hours)
    )


# ---------------------------------------------------------------------------
# Improvement evaluation
# ---------------------------------------------------------------------------


def _source_improved(
    before: SourceSnapshotEntry, after: SourceSnapshotEntry
) -> tuple[bool, list[str]]:
    """Return (improved, reasons) for one source's before/after pair.

    Improvement is intentionally conservative: the ``improved`` bool only
    flips True when the source crossed the stale boundary or its
    freshness_state advanced to ``fresh``.  A successful refresh attempt
    that left the source stuck in ``stale`` / ``overdue`` is recorded as
    a diagnostic *reason* but does NOT mark improvement — otherwise the
    watchdog would lie about progress every time the orchestrator runs
    cleanly without the upstream API actually returning new data.
    """
    diagnostics: list[str] = []
    materially_improved = False

    if before.is_stale_active and not after.is_stale_active:
        diagnostics.append("stale_cleared")
        materially_improved = True
    if (
        before.freshness_state != "fresh"
        and after.freshness_state == "fresh"
    ):
        diagnostics.append(f"freshness_state {before.freshness_state} -> fresh")
        materially_improved = True

    # The following reasons are diagnostic only — they explain *why* a
    # source might have moved (or why it didn't), but they don't count
    # as real improvement on their own.
    if before.is_stale_active:
        if (
            before.last_success_at != after.last_success_at
            and after.last_success_at
            and (before.last_success_at is None or after.last_success_at > before.last_success_at)
        ):
            diagnostics.append("newer_last_success_at")
        if (
            before.latest_event_at != after.latest_event_at
            and after.latest_event_at
            and (before.latest_event_at is None or after.latest_event_at > before.latest_event_at)
        ):
            diagnostics.append("newer_latest_event_at")
        if (
            before.last_refresh_attempt_at != after.last_refresh_attempt_at
            and after.last_refresh_attempt_at
            and (
                before.last_refresh_attempt_at is None
                or after.last_refresh_attempt_at > before.last_refresh_attempt_at
            )
            and after.last_refresh_success
        ):
            diagnostics.append("newer_successful_refresh_attempt")
    return (materially_improved, diagnostics)


def _diff_snapshots(before: Snapshot, after: Snapshot) -> dict[str, Any]:
    """Compare two snapshots and return improvement diagnostics."""
    per_source: dict[str, dict[str, Any]] = {}
    any_improved = False
    for key, b_entry in before.entries.items():
        a_entry = after.entries.get(key)
        if a_entry is None:
            continue
        improved, reasons = _source_improved(b_entry, a_entry)
        any_improved = any_improved or improved
        per_source[key] = {
            "improved": bool(improved),
            "improvement_reasons": reasons,
            "before_freshness_state": b_entry.freshness_state,
            "after_freshness_state": a_entry.freshness_state,
            "before_is_stale_active": b_entry.is_stale_active,
            "after_is_stale_active": a_entry.is_stale_active,
            "before_last_success_at": b_entry.last_success_at,
            "after_last_success_at": a_entry.last_success_at,
            "before_excluded_reason": b_entry.excluded_reason,
            "after_excluded_reason": a_entry.excluded_reason,
        }
    stale_before = set(before.stale_active_sources)
    stale_after = set(after.stale_active_sources)
    if stale_after < stale_before:
        any_improved = True
    return {
        "any_improved": bool(any_improved),
        "per_source": per_source,
        "stale_before": sorted(stale_before),
        "stale_after": sorted(stale_after),
        "stale_count_before": len(stale_before),
        "stale_count_after": len(stale_after),
    }


# ---------------------------------------------------------------------------
# Retry planning
# ---------------------------------------------------------------------------


_REFRESHABLE_VIA_REFRESH_SCRIPT = frozenset({
    "polymarket",
    "kalshi",
    "gdelt",
    "sec_edgar",
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
})

_PARENT_PRIORITY = ("polymarket", "kalshi", "gdelt", "sec_edgar")


def _build_retry_plan(snapshot: Snapshot, *, source_filter: list[str] | None) -> dict[str, Any]:
    """Return a structured plan: which sources to retry via refresh script,
    and whether to invoke the disagreement scanner afterwards.

    ``source_filter`` (if provided) is intersected with the active stale set
    to let an operator scope a single watchdog tick to a subset.
    """
    stale = list(snapshot.stale_active_sources)
    if source_filter:
        wanted = {s.strip().lower() for s in source_filter if s and s.strip()}
        stale = [k for k in stale if k in wanted]
    refreshable = [k for k in stale if k in _REFRESHABLE_VIA_REFRESH_SCRIPT]
    derived = [k for k in stale if k in DERIVED_SOURCE_KEYS]

    # Promote parent priority order so polymarket/kalshi/gdelt come first.
    def _priority(k: str) -> int:
        try:
            return _PARENT_PRIORITY.index(k)
        except ValueError:
            return 99

    refreshable.sort(key=_priority)

    # Even when no derived source is itself in the stale list, recomputing
    # disagreement after a successful Kalshi/Polymarket retry is harmless
    # and the right thing to do — but only when both parents are present
    # in the snapshot and not optional-missing.  We do NOT force-run the
    # scanner if a parent is still stale after refresh; that's checked at
    # invocation time.
    invoke_disagreement = bool(derived) or (
        "kalshi" in refreshable or "polymarket" in refreshable
    )

    return {
        "stale_active_sources": stale,
        "refresh_targets": refreshable,
        "derived_targets": derived,
        "invoke_disagreement": invoke_disagreement,
    }


# ---------------------------------------------------------------------------
# Subprocess execution
# ---------------------------------------------------------------------------


SubprocessRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_subprocess_runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603 - args are constructed from constants
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=600,
    )


def _run_refresh_command(
    targets: list[str],
    *,
    runner: SubprocessRunner,
    quiet: bool = False,
) -> dict[str, Any]:
    cmd = list(DEFAULT_REFRESH_COMMAND)
    if targets:
        cmd.extend(["--sources", ",".join(targets)])
    if quiet:
        cmd.append("--quiet")
    started = _utc_now_iso()
    t0 = time.monotonic()
    try:
        proc = runner(cmd)
        returncode = int(proc.returncode or 0)
        stdout = str(getattr(proc, "stdout", "") or "")
        stderr = str(getattr(proc, "stderr", "") or "")
    except Exception as exc:  # noqa: BLE001 - never crash watchdog
        return {
            "command": cmd,
            "started_at_utc": started,
            "finished_at_utc": _utc_now_iso(),
            "duration_s": round(time.monotonic() - t0, 3),
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": _tail(f"{type(exc).__name__}: {exc}"),
            "raised": True,
        }
    return {
        "command": cmd,
        "started_at_utc": started,
        "finished_at_utc": _utc_now_iso(),
        "duration_s": round(time.monotonic() - t0, 3),
        "returncode": returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "raised": False,
    }


def _run_disagreement_command(
    *, runner: SubprocessRunner
) -> dict[str, Any]:
    cmd = list(DEFAULT_DISAGREEMENT_COMMAND)
    started = _utc_now_iso()
    t0 = time.monotonic()
    try:
        proc = runner(cmd)
        returncode = int(proc.returncode or 0)
        stdout = str(getattr(proc, "stdout", "") or "")
        stderr = str(getattr(proc, "stderr", "") or "")
    except Exception as exc:  # noqa: BLE001
        return {
            "command": cmd,
            "started_at_utc": started,
            "finished_at_utc": _utc_now_iso(),
            "duration_s": round(time.monotonic() - t0, 3),
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": _tail(f"{type(exc).__name__}: {exc}"),
            "raised": True,
        }
    return {
        "command": cmd,
        "started_at_utc": started,
        "finished_at_utc": _utc_now_iso(),
        "duration_s": round(time.monotonic() - t0, 3),
        "returncode": returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "raised": False,
    }


# ---------------------------------------------------------------------------
# Top-level watchdog loop
# ---------------------------------------------------------------------------


def _parse_backoff(raw: str | Iterable[int] | None) -> tuple[int, ...]:
    if raw is None or raw == "":
        return DEFAULT_BACKOFF_SECONDS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p) for p in raw]
    out: list[int] = []
    for p in parts:
        try:
            n = int(p)
            if n >= 0:
                out.append(n)
        except ValueError:
            continue
    return tuple(out) if out else DEFAULT_BACKOFF_SECONDS


def _ensure_tracked_in_summary(
    payload: dict[str, Any],
    snapshot: Snapshot,
    suffix: str,
) -> None:
    """Make sure summary always carries kalshi/gdelt/disagreement before/after
    rows even if one is missing from the snapshot (defensive)."""
    for src in TRACKED_STALE_SOURCES:
        entry = snapshot.entries.get(src)
        if entry is None:
            payload[f"{src}_status_{suffix}"] = {"present": False}
        else:
            payload[f"{src}_status_{suffix}"] = {
                "present": True,
                "freshness_state": entry.freshness_state,
                "is_stale_active": entry.is_stale_active,
                "excluded_reason": entry.excluded_reason,
                "last_success_at": entry.last_success_at,
                "last_refresh_attempt_at": entry.last_refresh_attempt_at,
                "last_refresh_error": entry.last_refresh_error,
                "last_refresh_skipped_reason": entry.last_refresh_skipped_reason,
                "tier": entry.tier,
                "parent_sources": list(entry.parent_sources),
                "dependency_critical": entry.dependency_critical,
                "used_by": list(entry.used_by_derived),
                "stale_severity": entry.stale_severity,
                "degraded_parent_stale_parents": list(
                    entry.degraded_parent_stale_parents
                ),
            }


@dataclass
class WatchdogResult:
    status: str
    exit_code: int
    summary: dict[str, Any]


def run_watchdog(
    *,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: Iterable[int] = DEFAULT_BACKOFF_SECONDS,
    backoff_jitter_pct: float = DEFAULT_BACKOFF_JITTER_PCT,
    disable_jitter: bool = False,
    jitter_seed: int | None = None,
    no_sleep: bool = False,
    summary_path: Path | str | None = None,
    source_filter: list[str] | None = None,
    subprocess_runner: SubprocessRunner | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    snapshot_fn: Callable[..., Snapshot] | None = None,
    quiet: bool = False,
) -> WatchdogResult:
    """Run one watchdog tick.

    Returns a ``WatchdogResult`` whose ``summary`` is also persisted to
    ``summary_path`` (default ``runtime/refresh_watchdog_summary.json``).

    All collaborators are injectable so the tests can avoid real
    subprocess invocations, real DB reads, and real sleeps.
    """
    runner = subprocess_runner or _default_subprocess_runner
    sleep = sleep_fn or time.sleep
    load = snapshot_fn or _load_snapshot
    target_summary = Path(summary_path) if summary_path else DEFAULT_SUMMARY_PATH
    backoff = tuple(backoff_seconds) if backoff_seconds else DEFAULT_BACKOFF_SECONDS
    jitter_enabled = (not disable_jitter) and float(backoff_jitter_pct or 0.0) > 0.0
    jitter_rng = (
        random.Random(jitter_seed) if jitter_seed is not None else random.Random()
    )
    planned_sleeps: list[float] = []
    actual_sleeps: list[float] = []

    run_id = uuid.uuid4().hex[:16]
    started_at = _utc_now_iso()
    t0 = time.monotonic()

    # --- before snapshot ------------------------------------------------
    try:
        before = load(ttl_hours=ttl_hours)
    except Exception as exc:  # noqa: BLE001
        finished_at = _utc_now_iso()
        summary = {
            "operation": "refresh_watchdog",
            "run_id": run_id,
            "status": STATUS_ERROR,
            "errors": [f"snapshot_load_failed: {type(exc).__name__}: {exc}"],
            "warnings": [],
            "ttl_hours": int(ttl_hours),
            "max_retries": int(max_retries),
            "backoff_seconds": list(backoff),
            "backoff_jitter_pct": float(backoff_jitter_pct or 0.0),
            "jitter_enabled": bool(jitter_enabled),
            "planned_sleep_seconds_per_retry": planned_sleeps,
            "actual_sleep_seconds_per_retry": actual_sleeps,
            "refresh_command": list(DEFAULT_REFRESH_COMMAND),
            "refresh_attempts": [],
            "retries_attempted": 0,
            "stale_sources_before": [],
            "stale_sources_after": [],
            "fresh_sources_before": [],
            "fresh_sources_after": [],
            "degraded_sources_before": [],
            "degraded_sources_after": [],
            "excluded_optional_sources": [],
            "skipped_config_missing_sources": [],
            "active_sources_checked": [],
            "parent_stale_derived_sources": [],
            "derived_source_dependency_status": {},
            "dependency_critical_sources": [],
            "freshness_improved": False,
            "improvement_reasons": [],
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "duration_s": round(time.monotonic() - t0, 3),
            "generated_at_utc": finished_at,
            **_SAFETY_STAMPS,
        }
        _write_summary(target_summary, summary)
        return WatchdogResult(status=STATUS_ERROR, exit_code=1, summary=summary)

    refresh_attempts: list[dict[str, Any]] = []
    retries_attempted = 0
    any_improvement_ever = False
    improvement_reasons: list[str] = []
    current = before

    # --- main loop ------------------------------------------------------
    while True:
        plan = _build_retry_plan(current, source_filter=source_filter)
        if not current.stale_active_sources:
            break

        attempt_no = len(refresh_attempts) + 1
        attempt_payload: dict[str, Any] = {
            "attempt_number": attempt_no,
            "started_at_utc": _utc_now_iso(),
            "plan": plan,
            "actions": [],
        }
        t_attempt = time.monotonic()

        # Parent refresh.  Always run refresh_live_signals.py — even when
        # the only stale items are derived: refreshing parents is the
        # closest analogue to "make the derived source recomputable".
        targets = plan["refresh_targets"]
        if not targets and plan["invoke_disagreement"]:
            # When only the derived signal is stale, retry both its
            # parents so the scanner has fresh inputs to chew on.
            for parent in DERIVED_PARENT_KEYS.get(
                "prediction_market_disagreement", ()
            ):
                if parent not in targets:
                    targets.append(parent)
        if targets:
            refresh_result = _run_refresh_command(targets, runner=runner, quiet=quiet)
            attempt_payload["actions"].append(
                {"kind": "refresh_live_signals", **refresh_result}
            )

        # Re-snapshot AFTER parent refresh and BEFORE optional scanner.
        # Disagreement only runs when both parents are now fresh.
        try:
            mid = load(ttl_hours=ttl_hours)
        except Exception as exc:  # noqa: BLE001
            mid = current
            attempt_payload["mid_snapshot_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

        # Derived scanner, if eligible.
        if plan["invoke_disagreement"]:
            parents = DERIVED_PARENT_KEYS.get(
                "prediction_market_disagreement", ()
            )
            parent_states = {p: (mid.entries.get(p).freshness_state if p in mid.entries else "missing") for p in parents}
            parents_fresh = all(
                p in mid.entries
                and mid.entries[p].freshness_state == "fresh"
                and not mid.entries[p].excluded_reason
                for p in parents
            )
            if parents_fresh:
                scanner_result = _run_disagreement_command(runner=runner)
                attempt_payload["actions"].append(
                    {
                        "kind": "prediction_market_disagreement_scanner",
                        "parent_states": parent_states,
                        **scanner_result,
                    }
                )
            else:
                attempt_payload["actions"].append(
                    {
                        "kind": "prediction_market_disagreement_scanner",
                        "skipped": True,
                        "reason": "parents_not_fresh",
                        "parent_states": parent_states,
                    }
                )

        # Final after-snapshot for this attempt.
        try:
            after_attempt = load(ttl_hours=ttl_hours)
        except Exception as exc:  # noqa: BLE001
            after_attempt = mid
            attempt_payload["after_snapshot_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

        diff = _diff_snapshots(current, after_attempt)
        attempt_payload["finished_at_utc"] = _utc_now_iso()
        attempt_payload["duration_s"] = round(time.monotonic() - t_attempt, 3)
        attempt_payload["stale_sources_after_attempt"] = diff["stale_after"]
        attempt_payload["freshness_improved_after_attempt"] = diff["any_improved"]
        attempt_payload["per_source_improvement"] = diff["per_source"]
        refresh_attempts.append(attempt_payload)

        if diff["any_improved"]:
            any_improvement_ever = True
            for reasons_list in (diff["per_source"][k]["improvement_reasons"] for k in diff["per_source"]):
                for r in reasons_list:
                    if r not in improvement_reasons:
                        improvement_reasons.append(r)

        current = after_attempt
        # If we've cleared the stale set, exit the loop early.
        if not current.stale_active_sources:
            break
        # If no improvement and we've used all retries, give up.
        if retries_attempted >= max_retries:
            break
        retries_attempted += 1
        base_delay = backoff[min(retries_attempted - 1, len(backoff) - 1)] if backoff else 0
        if jitter_enabled and base_delay:
            planned = _compute_jittered_sleep(
                float(base_delay), float(backoff_jitter_pct), rng=jitter_rng
            )
        else:
            planned = float(base_delay)
        planned_sleeps.append(round(planned, 4))
        if not no_sleep and planned > 0:
            sleep(planned)
            actual_sleeps.append(round(planned, 4))
        else:
            actual_sleeps.append(0.0)

    # --- finalise -------------------------------------------------------
    after = current
    diff_total = _diff_snapshots(before, after)
    if not after.stale_active_sources:
        status = STATUS_HEALTHY
        exit_code = 0
    elif any_improvement_ever or diff_total["any_improved"]:
        status = STATUS_IMPROVED_BUT_STALE
        exit_code = 0
    else:
        status = STATUS_STALE_UNCHANGED
        exit_code = 1

    derived_dep_status: dict[str, Any] = {}
    for derived_key, parents in DERIVED_PARENT_KEYS.items():
        d_entry = after.entries.get(derived_key)
        if d_entry is None:
            continue
        derived_dep_status[derived_key] = {
            "freshness_state": d_entry.freshness_state,
            "is_stale_active": d_entry.is_stale_active,
            "degraded_parent_stale_parents": list(d_entry.degraded_parent_stale_parents),
            "parents": {
                p: {
                    "freshness_state": (
                        after.entries[p].freshness_state
                        if p in after.entries
                        else "missing"
                    ),
                    "is_stale_active": (
                        after.entries[p].is_stale_active
                        if p in after.entries
                        else False
                    ),
                    "dependency_critical": (
                        after.entries[p].dependency_critical
                        if p in after.entries
                        else False
                    ),
                }
                for p in parents
            },
        }

    dependency_critical_sources = sorted(
        k for k, e in after.entries.items() if e.dependency_critical
    )

    fresh_before = sorted(
        k for k, e in before.entries.items() if e.freshness_state == "fresh"
    )
    fresh_after = sorted(
        k for k, e in after.entries.items() if e.freshness_state == "fresh"
    )
    degraded_before = sorted(
        k
        for k, e in before.entries.items()
        if e.is_stale_active and e.freshness_state in {"stale", "overdue"}
    )
    degraded_after = sorted(
        k
        for k, e in after.entries.items()
        if e.is_stale_active and e.freshness_state in {"stale", "overdue"}
    )
    finished_at = _utc_now_iso()

    # Convenience top-level dependency-tracking fields the cockpit panel
    # reads.  ``_ensure_tracked_in_summary`` already emits the rich
    # ``<source>_status_before/after`` objects; these short ``*_freshness_*``
    # strings are the chip-level summary for fast frontend rendering.
    pmd_after = after.entries.get("prediction_market_disagreement")
    pmd_before = before.entries.get("prediction_market_disagreement")
    prediction_market_disagreement_freshness_before = (
        pmd_before.freshness_state if pmd_before else "missing"
    )
    prediction_market_disagreement_freshness_after = (
        pmd_after.freshness_state if pmd_after else "missing"
    )
    kalshi_before_entry = before.entries.get("kalshi")
    kalshi_after_entry = after.entries.get("kalshi")
    kalshi_freshness_before_chip = (
        kalshi_before_entry.freshness_state if kalshi_before_entry else "missing"
    )
    kalshi_freshness_after_chip = (
        kalshi_after_entry.freshness_state if kalshi_after_entry else "missing"
    )

    summary: dict[str, Any] = {
        "operation": "refresh_watchdog",
        "run_id": run_id,
        "status": status,
        "errors": [],
        "warnings": [],
        "ttl_hours": int(ttl_hours),
        "max_retries": int(max_retries),
        "backoff_seconds": list(backoff),
        "backoff_jitter_pct": float(backoff_jitter_pct or 0.0),
        "jitter_enabled": bool(jitter_enabled),
        "planned_sleep_seconds_per_retry": planned_sleeps,
        "actual_sleep_seconds_per_retry": actual_sleeps,
        "refresh_command": list(DEFAULT_REFRESH_COMMAND),
        "refresh_attempts": refresh_attempts,
        "retries_attempted": int(retries_attempted),
        "stale_sources_before": sorted(before.stale_active_sources),
        "stale_sources_after": sorted(after.stale_active_sources),
        "fresh_sources_before": fresh_before,
        "fresh_sources_after": fresh_after,
        "degraded_sources_before": degraded_before,
        "degraded_sources_after": degraded_after,
        "excluded_optional_sources": sorted(after.excluded_optional_sources),
        "skipped_config_missing_sources": sorted(after.skipped_config_missing_sources),
        "active_sources_checked": sorted(after.active_sources),
        "parent_stale_derived_sources": sorted(after.parent_stale_derived_sources),
        "derived_source_dependency_status": derived_dep_status,
        "dependency_critical_sources": dependency_critical_sources,
        "kalshi_freshness_before": kalshi_freshness_before_chip,
        "kalshi_freshness_after": kalshi_freshness_after_chip,
        "prediction_market_disagreement_freshness_before": (
            prediction_market_disagreement_freshness_before
        ),
        "prediction_market_disagreement_freshness_after": (
            prediction_market_disagreement_freshness_after
        ),
        "freshness_improved": bool(any_improvement_ever or diff_total["any_improved"]),
        "improvement_reasons": improvement_reasons,
        "diff_total": diff_total,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "duration_s": round(time.monotonic() - t0, 3),
        "generated_at_utc": finished_at,
        "per_source_before": before.per_source_status_view(),
        "per_source_after": after.per_source_status_view(),
        **_SAFETY_STAMPS,
    }
    _ensure_tracked_in_summary(summary, before, "before")
    _ensure_tracked_in_summary(summary, after, "after")

    _write_summary(target_summary, summary)

    return WatchdogResult(status=status, exit_code=exit_code, summary=summary)


def _write_summary(target_path: Path, summary: dict[str, Any]) -> None:
    """Best-effort write of the watchdog summary JSON."""
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception:
        # Never crash the watchdog because of a disk hiccup; the caller
        # already has the summary in memory and the exit code reflects
        # success/failure.
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Self-healing stale-source watchdog. Reads the canonical source "
            "freshness state, retries refreshes for sources that are stale "
            "beyond TTL, and persists a structured summary. ADVISORY_ONLY."
        ),
    )
    parser.add_argument(
        "--ttl-hours",
        type=int,
        default=DEFAULT_TTL_HOURS,
        help=f"Freshness TTL in hours. Default: {DEFAULT_TTL_HOURS}.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum retry attempts. Default: {DEFAULT_MAX_RETRIES}.",
    )
    parser.add_argument(
        "--backoff-seconds",
        default=",".join(str(s) for s in DEFAULT_BACKOFF_SECONDS),
        help=(
            "Comma-separated backoff in seconds. "
            f"Default: {','.join(str(s) for s in DEFAULT_BACKOFF_SECONDS)}."
        ),
    )
    parser.add_argument(
        "--backoff-jitter-pct",
        type=float,
        default=DEFAULT_BACKOFF_JITTER_PCT,
        help=(
            "Random jitter applied to each backoff sleep as a fraction of "
            "the base value (e.g. 0.15 => ±15%). Prevents multiple watchdog "
            "tasks from retrying in lockstep. "
            f"Default: {DEFAULT_BACKOFF_JITTER_PCT}."
        ),
    )
    parser.add_argument(
        "--disable-jitter",
        action="store_true",
        help=(
            "Disable backoff jitter; sleep values exactly match "
            "--backoff-seconds. Used for deterministic manual runs."
        ),
    )
    parser.add_argument(
        "--jitter-seed",
        type=int,
        default=None,
        help=(
            "Optional integer seed for deterministic jitter (tests/dev only). "
            "Without it, jitter draws from an unseeded RNG."
        ),
    )
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help="Skip actual sleeps between retries (tests/dev only).",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_SUMMARY_PATH),
        help=f"Destination for the summary JSON. Default: {DEFAULT_SUMMARY_PATH}.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON to stdout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-line output; the summary file is still written.",
    )
    parser.add_argument(
        "--sources",
        default="",
        help=(
            "Optional comma-separated source filter intersected with the "
            "stale-active set."
        ),
    )
    return parser.parse_args(argv)


def _format_text_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sleeping Passenger — Refresh Watchdog")
    lines.append("=" * 72)
    lines.append(f"status:                  {summary.get('status')}")
    lines.append(f"generated_at_utc:        {summary.get('generated_at_utc')}")
    lines.append(f"ttl_hours:               {summary.get('ttl_hours')}")
    lines.append(f"max_retries:             {summary.get('max_retries')}")
    lines.append(f"retries_attempted:       {summary.get('retries_attempted')}")
    lines.append(f"freshness_improved:      {summary.get('freshness_improved')}")
    lines.append(f"advisory_only:           {summary.get('advisory_only')}")
    lines.append(f"execution_gate:          {summary.get('execution_gate')}")
    lines.append(f"broker_api_called:       {summary.get('broker_api_called')}")
    lines.append("")
    lines.append(f"stale_sources_before:    {summary.get('stale_sources_before')}")
    lines.append(f"stale_sources_after:     {summary.get('stale_sources_after')}")
    lines.append(
        f"excluded_optional:       {summary.get('excluded_optional_sources')}"
    )
    lines.append(
        f"parent_stale_derived:    {summary.get('parent_stale_derived_sources')}"
    )
    lines.append(
        f"dependency_critical:     {summary.get('dependency_critical_sources')}"
    )
    if summary.get("jitter_enabled"):
        lines.append(
            f"jitter:                  pct={summary.get('backoff_jitter_pct')} "
            f"planned={summary.get('planned_sleep_seconds_per_retry')} "
            f"actual={summary.get('actual_sleep_seconds_per_retry')}"
        )
    else:
        lines.append("jitter:                  disabled")
    lines.append("")
    for src in TRACKED_STALE_SOURCES:
        b = summary.get(f"{src}_status_before") or {}
        a = summary.get(f"{src}_status_after") or {}
        lines.append(
            f"  {src:<32} before: freshness={b.get('freshness_state')} "
            f"stale_active={b.get('is_stale_active')} excluded={b.get('excluded_reason')}"
        )
        lines.append(
            f"  {src:<32} after:  freshness={a.get('freshness_state')} "
            f"stale_active={a.get('is_stale_active')} excluded={a.get('excluded_reason')}"
        )
    attempts = summary.get("refresh_attempts") or []
    if attempts:
        lines.append("")
        lines.append("Attempts:")
        for at in attempts:
            lines.append(
                f"  - attempt={at.get('attempt_number')} "
                f"improved={at.get('freshness_improved_after_attempt')} "
                f"stale_after={at.get('stale_sources_after_attempt')}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    backoff = _parse_backoff(args.backoff_seconds)
    source_filter = [s for s in (args.sources or "").split(",") if s.strip()]

    result = run_watchdog(
        ttl_hours=int(args.ttl_hours),
        max_retries=int(args.max_retries),
        backoff_seconds=backoff,
        backoff_jitter_pct=float(args.backoff_jitter_pct),
        disable_jitter=bool(args.disable_jitter),
        jitter_seed=(int(args.jitter_seed) if args.jitter_seed is not None else None),
        no_sleep=bool(args.no_sleep),
        summary_path=str(args.summary_path),
        source_filter=source_filter or None,
        quiet=bool(args.quiet),
    )

    if args.json:
        sys.stdout.write(
            json.dumps(result.summary, indent=2, ensure_ascii=False, default=str) + "\n"
        )
    elif not args.quiet:
        sys.stdout.write(_format_text_summary(result.summary) + "\n")
    else:
        sys.stdout.write(
            f"status={result.status} "
            f"stale_before={len(result.summary.get('stale_sources_before', []))} "
            f"stale_after={len(result.summary.get('stale_sources_after', []))} "
            f"improved={result.summary.get('freshness_improved')}\n"
        )
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
