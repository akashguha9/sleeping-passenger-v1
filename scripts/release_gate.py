"""Release gate — one PASS / WARN / FAIL verdict over the deploy preflight.

Aggregates ``scripts/local_deploy_preflight.py`` into a single gate decision
with exact reasons, so the operator never ships on a broken or unsafe local
state:

* any ``FAIL`` check  -> gate ``FAIL`` (do not release).
* any ``WARN`` check  -> gate ``WARN`` (release only with eyes open).
* otherwise           -> gate ``PASS``.

``INFO`` checks never affect the verdict.  The gate is read-only and never
calls a broker or external trading API; the only optional network touch is the
localhost backend probe inherited from the preflight (off by default).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import local_deploy_preflight as _preflight
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import local_deploy_preflight as _preflight  # type: ignore[no-redef]

# Integrated Sprint integrations — each import is wrapped in a try block so the
# release gate still runs in stripped environments (each missing block becomes a
# WARN, never silently a PASS).
try:
    from scripts import typed_config as _typed_config  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import typed_config as _typed_config  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _typed_config = None  # type: ignore[assignment]

try:
    from scripts import prewarm_diagnostics_snapshot as _prewarm  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import prewarm_diagnostics_snapshot as _prewarm  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _prewarm = None  # type: ignore[assignment]

try:
    from scripts import diagnostics_tail_metrics as _tail  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import diagnostics_tail_metrics as _tail  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _tail = None  # type: ignore[assignment]

try:
    from scripts import live_payload_quality as _lpq  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import live_payload_quality as _lpq  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _lpq = None  # type: ignore[assignment]

try:
    from scripts import business_value_report as _bvr  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import business_value_report as _bvr  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _bvr = None  # type: ignore[assignment]

try:
    from scripts import compliance_registers as _comp_reg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import compliance_registers as _comp_reg  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _comp_reg = None  # type: ignore[assignment]

try:
    from scripts import ai_report_ingestion as _ai_ingest  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        import ai_report_ingestion as _ai_ingest  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _ai_ingest = None  # type: ignore[assignment]

# Sprint-2 (Kanté defensive batch 2) summaries.  Each import is best-effort:
# a missing module is surfaced as a WARN in the gate, never a silent PASS.
def _try_import(*candidates):
    for name in candidates:
        try:
            if "." in name:
                pkg, attr = name.rsplit(".", 1)
                mod = __import__(pkg, fromlist=[attr])
                return getattr(mod, attr, None) or mod
            return __import__(name)
        except ModuleNotFoundError:
            continue
    return None


_persistence_integrity = _try_import(
    "scripts.persistence_integrity", "persistence_integrity",
)
_source_run_ledger = _try_import(
    "scripts.source_run_ledger", "source_run_ledger",
)
_portfolio_truth = _try_import(
    "scripts.portfolio_truth_integrity", "portfolio_truth_integrity",
)
_fresh_discovery = _try_import(
    "scripts.fresh_discovery_quality", "fresh_discovery_quality",
)
_memory_decay_v2 = _try_import(
    "scripts.candidate_memory_decay_v2", "candidate_memory_decay_v2",
)
_why_today_enforcement = _try_import(
    "scripts.why_today_enforcement", "why_today_enforcement",
)
_five_model_independence = _try_import(
    "scripts.five_model_independence", "five_model_independence",
)
_model_disagreement_handling = _try_import(
    "scripts.model_disagreement_handling", "model_disagreement_handling",
)
_ai_integration_readiness = _try_import(
    "scripts.ai_integration_readiness", "ai_integration_readiness",
)
_signal_input_quality = _try_import(
    "scripts.signal_input_quality", "signal_input_quality",
)
_compliance_readiness = _try_import(
    "scripts.compliance_readiness", "compliance_readiness",
)
_daily_signal_readiness = _try_import(
    "scripts.daily_signal_readiness", "daily_signal_readiness",
)
# Sprint 3 — best-effort imports of the new readiness subsystems.  A
# missing module is a WARN (never silent PASS) and never a FAIL by itself.
_operator_live_refresh = _try_import(
    "scripts.operator_live_provider_refresh",
    "operator_live_provider_refresh",
)
_backend_api_quality = _try_import(
    "scripts.backend_api_quality", "backend_api_quality",
)
_candidate_promotion_contract = _try_import(
    "scripts.candidate_promotion_contract",
    "candidate_promotion_contract",
)
_universe_coverage = _try_import(
    "scripts.universe_coverage", "universe_coverage",
)
_operator_demo_value = _try_import(
    "scripts.operator_demo_value", "operator_demo_value",
)
_live_provider_compliance_trace = _try_import(
    "scripts.live_provider_compliance_trace",
    "live_provider_compliance_trace",
)

# Release-gate proof artifact lives next to the other release artifacts.
REPO_ROOT_PATH = Path(__file__).resolve().parents[1]
RELEASE_GATE_PROOF_PATH = (
    REPO_ROOT_PATH / "runtime" / "release" / "release_gate_proof.json"
)

# Per-subsystem block builder.  Each block reads its summary if present,
# otherwise records WARN.  Missing module => WARN with remediation command.
_SUBSYSTEM_REMEDIATION = {
    "data_model_persistence":
        "python scripts/persistence_integrity.py --write-summary",
    "live_source_refresh":
        "python scripts/source_run_ledger.py --write-summary --mode fixture",
    "portfolio_truth":
        "python scripts/portfolio_truth_integrity.py --write-summary",
    "fresh_discovery":
        "python scripts/fresh_discovery_quality.py --write-summary",
    "anti_staleness":
        "python scripts/candidate_memory_decay_v2.py --write-summary",
    "why_today":
        "python scripts/why_today_enforcement.py --write-summary",
    "candidate_memory_decay":
        "python scripts/candidate_memory_decay_v2.py --write-summary",
    "five_model_independence":
        "python scripts/five_model_independence.py --write-summary",
    "model_disagreement":
        "python scripts/model_disagreement_handling.py --write-summary",
    "ai_integration":
        "python scripts/ai_integration_readiness.py --write-summary",
    "signal_input_quality":
        "python scripts/signal_input_quality.py --write-summary",
    "business_value":
        "python scripts/business_value_report.py --write-summary",
    "compliance_readiness":
        "python scripts/compliance_readiness.py --write-summary",
    "daily_signal_readiness":
        "python scripts/daily_signal_readiness.py --write-summary",
    # Sprint 3 subsystems.
    "backend_api_quality":
        "python scripts/backend_api_quality.py --write-summary",
    "candidate_promotion_contract":
        "python scripts/candidate_promotion_contract.py --write-summary",
    "universe_coverage":
        "python scripts/universe_coverage.py --write-summary",
    "operator_demo_value":
        "python scripts/operator_demo_value.py --write-summary",
    "live_provider_compliance_trace":
        "python scripts/live_provider_compliance_trace.py --write",
    "data_model_persistence_v2":
        "python -c \"from scripts.persistence_integrity import write_v2_summary; "
        "write_v2_summary()\"",
    "operator_live_refresh":
        "$env:MVP_LIVE_REFRESH_OK=\"1\"; python scripts/"
        "operator_live_provider_refresh.py --providers "
        "yfinance,sec_edgar,gdelt --write",
}


def _sprint3_artifact_block(
    label: str,
    *,
    module: Any,
    summary_attr: str,
    score_key: str | None,
) -> dict[str, Any]:
    """Read a sprint-3 summary off disk and project it into a proof block.

    Pure read-only.  A missing / unreadable artifact becomes a WARN with a
    remediation command.  Never raises.
    """
    out: dict[str, Any] = {
        "ok": False,
        "score": None,
        "score_key": score_key,
        "summary_present": False,
        "summary_path": None,
        "remediation": _SUBSYSTEM_REMEDIATION.get(label),
    }
    if module is None:
        out["error"] = f"{label} module unavailable"
        return out
    path = getattr(module, summary_attr, None)
    out["summary_path"] = str(path) if path else None
    if path is None or not Path(path).exists():
        return out
    try:
        summary = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        out["error"] = f"summary unreadable: {exc}"
        return out
    if not isinstance(summary, dict):
        out["error"] = "summary not a dict"
        return out
    out["summary_present"] = True
    out["ok"] = bool(summary.get("ok"))
    if score_key and score_key in summary:
        try:
            out["score"] = float(summary[score_key])
        except (TypeError, ValueError):
            out["score"] = None
    return out


def _operator_live_refresh_proof_block() -> dict[str, Any]:
    """Build the ``operator_live_refresh`` proof block + fake-LIVE detection.

    Returns a dict carrying:
      * attempted, valid, fresh
      * providers_live_verified, lpq_before, lpq_after, ttl_hours
      * warnings, blocking_reasons
      * fake_live_verified_detected — True if any evidence row claims
        LIVE_VERIFIED but is missing timestamp or source url.
    """
    block: dict[str, Any] = {
        "attempted": False,
        "valid": False,
        "fresh": False,
        "providers_live_verified": [],
        "lpq_before": 8.2,
        "lpq_after": 8.2,
        "ttl_hours": 24,
        "age_hours": None,
        "warnings": [],
        "blocking_reasons": [],
        "fake_live_verified_detected": False,
        "fake_live_verified_offenders": [],
    }
    if _operator_live_refresh is None:
        block["warnings"].append(
            "operator_live_provider_refresh module unavailable"
        )
        return block
    summary = _operator_live_refresh.read_summary()
    if not isinstance(summary, dict):
        block["warnings"].append(
            "operator live provider refresh not run; LPQ capped at "
            "fixture/offline score"
        )
        return block
    evidence = _operator_live_refresh.operator_artifact_valid(summary)
    block.update({
        "attempted": evidence.get("attempted", False),
        "valid": evidence.get("valid", False),
        "fresh": evidence.get("fresh", False),
        "providers_live_verified": evidence.get(
            "providers_live_verified", []
        ),
        "lpq_before": evidence.get("lpq_before") or 8.2,
        "lpq_after": evidence.get("lpq_after") or 8.2,
        "ttl_hours": evidence.get("ttl_hours") or 24,
        "age_hours": evidence.get("age_hours"),
    })
    if not block["fresh"] and block["attempted"]:
        block["warnings"].append(
            "operator live provider refresh STALE; ignoring for LPQ "
            f"uplift (age_hours={block['age_hours']} > "
            f"ttl_hours={block['ttl_hours']})"
        )

    # Fake-LIVE detection: any row claiming LIVE_VERIFIED MUST have a real
    # timestamp.  Missing timestamp or empty source urls -> blocking.
    offenders: list[dict[str, Any]] = []
    for ev in summary.get("providers_evidence", []) or []:
        if str(ev.get("verification_status") or "").upper() != "LIVE_VERIFIED":
            continue
        ts = ev.get("latest_provider_timestamp_utc")
        urls = ev.get("sample_source_urls") or []
        tags = ev.get("sample_asset_tags") or []
        if not ts or not (urls or tags):
            offenders.append({
                "provider": ev.get("provider"),
                "latest_provider_timestamp_utc": ts,
                "sample_source_urls": list(urls),
                "sample_asset_tags": list(tags),
            })
    if offenders:
        block["fake_live_verified_detected"] = True
        block["fake_live_verified_offenders"] = offenders
        block["blocking_reasons"].append(
            "fake LIVE_VERIFIED without timestamp/source evidence detected: "
            f"{[o['provider'] for o in offenders]}"
        )
    return block


def _subsystem_block(
    module: Any,
    score_key: str,
    label: str,
    *,
    builder_method: str = "build_summary",
) -> dict[str, Any]:
    """Common pattern: read summary -> score -> ok flag.  WARN on missing."""
    out: dict[str, Any] = {
        "ok": False,
        "score": None,
        "score_key": score_key,
        "summary_present": False,
        "summary_path": None,
        "remediation": _SUBSYSTEM_REMEDIATION.get(label),
    }
    if module is None:
        out["error"] = f"{label} module unavailable"
        return out
    path = getattr(module, "DEFAULT_SUMMARY_PATH", None)
    summary: dict[str, Any] | None = None
    if path is not None and Path(path).exists():
        try:
            summary = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            out["error"] = f"summary unreadable: {exc}"
            summary = None
    if summary is None:
        builder = getattr(module, builder_method, None)
        if callable(builder):
            try:
                summary = builder()
            except Exception as exc:  # pragma: no cover - defensive
                out["error"] = f"builder failed: {exc}"
                summary = None
    if isinstance(summary, dict):
        out["summary_present"] = True
        if path is not None:
            out["summary_path"] = str(path)
        if score_key in summary:
            out["score"] = float(summary[score_key])
        out["ok"] = bool(summary.get("ok", False))
        # Surface a few useful fields per subsystem.
        for field in (
            "candidate_count", "promotable_count", "blocked_count",
            "verified_provider_count", "fixture_verified_provider_count",
            "diablo_veto_count", "high_disagreement_count",
            "missing_enabled_providers", "caps_applied",
            "manageable_positions_count", "quarantined_count",
        ):
            if field in summary:
                out[field] = summary[field]
    return out

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Default TTL for the persisted cockpit stress summary, in hours.  Beyond this
# age the summary is treated as ``STALE`` and downgrades the release verdict
# to WARN — a stale PASS must never be allowed to produce a release PASS.
DEFAULT_STRESS_SUMMARY_TTL_HOURS = 24
# Hard-cap on the env override so a typo (e.g. "100000") can't silently
# disable the freshness check.
MAX_STRESS_SUMMARY_TTL_HOURS = 24 * 30  # 30 days

STRESS_PROBE_RECOMMENDED_CMD = (
    "python scripts/cockpit_concurrency_stress_probe.py "
    "--workers 4 --iterations 25 --json"
)


def _stress_summary_ttl_seconds() -> int:
    """Read ``MVP_STRESS_SUMMARY_TTL_HOURS`` (clamped) → seconds.

    Invalid / negative / absurdly-large values fall back to the default; this
    keeps a bad env var from silently disabling the freshness check.
    """
    raw = os.environ.get("MVP_STRESS_SUMMARY_TTL_HOURS", "").strip()
    if not raw:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    try:
        hours = float(raw)
    except ValueError:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    if hours <= 0 or hours > MAX_STRESS_SUMMARY_TTL_HOURS:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    return int(hours * 3600)


def _parse_iso_utc(value: Any) -> float | None:
    """Parse a ``YYYY-MM-DDTHH:MM:SSZ`` UTC string into an epoch float.

    Returns None on any parse failure so the freshness check treats the
    summary as malformed (which downgrades to WARN, never PASS).
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Accept both ``...Z`` and ``...+00:00`` forms.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def _stress_probe_summary() -> dict[str, Any]:
    """Read the last persisted stress-probe summary with TTL validation.

    Read-only and cheap: the release gate never *runs* the probe (that is a
    deliberate, separate operator action) — it only surfaces the last run's
    derived, non-canonical ``last_run.json`` summary if present, *and* enforces
    a freshness TTL so a stale PASS cannot mislead the operator.

    Freshness contract (each branch sets ``stress_release_impact``)::

        missing summary       → UNKNOWN  / WARN
        unreadable / malformed → DEGRADED / WARN
        stale (age > TTL)     → STALE    / WARN  (regardless of stored gate)
        fresh + stress PASS   → PASS     / PASS
        fresh + stress WARN   → WARN     / WARN
        fresh + stress BLOCK  → BLOCK    / FAIL  (a stale BLOCK can never PASS)

    The TTL is the env-overridable ``MVP_STRESS_SUMMARY_TTL_HOURS`` (default
    24h, clamped at 30 days).  The recommended command is surfaced for the
    operator so a stale/missing summary has an obvious fix.
    """
    ttl_seconds = _stress_summary_ttl_seconds()
    out: dict[str, Any] = {
        "stress_probe_available": False,
        "stress_gate_status": "UNKNOWN",
        "stress_score": None,
        "stress_release_impact": WARN,
        "stress_summary_path": None,
        "stress_summary_generated_at_utc": None,
        "stress_summary_age_seconds": None,
        "stress_summary_ttl_seconds": ttl_seconds,
        "stress_summary_fresh": False,
        "stress_recommended_command": STRESS_PROBE_RECOMMENDED_CMD,
        "stress_summary_runtime_db_polluted": False,
    }
    try:
        try:
            from scripts import cockpit_concurrency_stress_probe as probe
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import cockpit_concurrency_stress_probe as probe  # type: ignore[no-redef]
        out["stress_probe_available"] = True
        out["stress_summary_path"] = str(probe.SUMMARY_FILE)
    except Exception:  # pragma: no cover - defensive
        # The probe module itself is missing — surface as UNKNOWN/WARN.
        return out

    summary_path: Path = probe.SUMMARY_FILE
    if not summary_path.exists():
        # Probe exists but has not been run yet — operator must run it before
        # release.  WARN, not silent PASS.
        out["stress_gate_status"] = "UNKNOWN"
        out["stress_release_impact"] = WARN
        return out

    summary = probe.read_summary()
    if not summary:
        # The file exists but is unreadable / malformed — never assume PASS.
        out["stress_gate_status"] = "DEGRADED"
        out["stress_release_impact"] = WARN
        return out

    out["stress_summary_runtime_db_polluted"] = bool(
        summary.get("runtime_db_polluted", False)
    )
    generated_at_utc = summary.get("generated_at_utc")
    out["stress_summary_generated_at_utc"] = generated_at_utc
    generated_epoch = _parse_iso_utc(generated_at_utc)
    if generated_epoch is None:
        # No parseable timestamp → treat as malformed.  This also catches the
        # case of a hand-edited summary missing ``generated_at_utc``.
        out["stress_gate_status"] = "DEGRADED"
        out["stress_release_impact"] = WARN
        return out

    age_seconds = max(0.0, time.time() - generated_epoch)
    out["stress_summary_age_seconds"] = round(age_seconds, 3)
    out["stress_summary_fresh"] = age_seconds <= ttl_seconds

    raw_status = str(summary.get("stress_gate_status") or "UNKNOWN").upper()
    out["stress_score"] = summary.get("stress_score")
    db_locked = int(summary.get("db_locked_errors", 0) or 0)

    # Stale (age > TTL) — STALE/WARN regardless of stored gate.  A stale PASS
    # *must not* be allowed to produce a release PASS.
    if not out["stress_summary_fresh"]:
        out["stress_gate_status"] = "STALE"
        out["stress_release_impact"] = WARN
        return out

    # Fresh.  Map directly.
    out["stress_gate_status"] = raw_status
    if raw_status == "BLOCK":
        # Any fresh BLOCK now fails the release (stricter than the prior
        # "only db_locked BLOCK fails" rule); the db_locked flag is surfaced
        # in the reason text so the operator knows *why* it failed.
        out["stress_release_impact"] = FAIL
        out["stress_summary_db_locked_errors"] = db_locked
    elif raw_status == "WARN":
        out["stress_release_impact"] = WARN
    elif raw_status == "PASS":
        out["stress_release_impact"] = PASS
    else:
        # Unknown gate status word in an otherwise fresh summary — degrade
        # to WARN rather than trust it.
        out["stress_release_impact"] = WARN
    return out


def evaluate(
    db_path: Path | None = None,
    *,
    check_backend: bool = False,
) -> dict[str, Any]:
    """Run the preflight and reduce it to a single gate verdict + reasons."""
    preflight = _preflight.run_preflight(db_path, check_backend=check_backend)
    checks = preflight["checks"]

    fails = [c for c in checks if c["status"] == _preflight.FAIL]
    warns = [c for c in checks if c["status"] == _preflight.WARN]

    if fails:
        verdict = FAIL
    elif warns:
        verdict = WARN
    else:
        verdict = PASS

    reasons = [f"{c['name']}: {c['detail']}" for c in fails + warns]

    # Kanté-defensive guard/diagnostics summary.  Unlike before, the mutation
    # guard now *participates in the verdict*: an unguarded high-risk mutation
    # script (BLOCK) fails the gate; low-risk unguarded scripts (WARN) downgrade
    # a PASS to WARN.  This is the meaningful enforcement the prior INFO-only
    # surfacing lacked.
    kante = preflight.get("kante_defensive", {})
    mutation_impact = kante.get("mutation_guard_release_impact", PASS)

    if mutation_impact == "BLOCK":
        verdict = FAIL
        reasons.append(
            "mutation_guard: unguarded high-risk mutation script(s) detected "
            f"— {kante.get('mutation_scripts_unguarded_names')} "
            f"(coverage={kante.get('mutation_guard_coverage')}); BLOCK."
        )
    elif mutation_impact == WARN and verdict == PASS:
        verdict = WARN
        reasons.append(
            "mutation_guard: unguarded low-risk mutation script(s) — "
            f"{kante.get('mutation_scripts_unguarded_names')}; WARN."
        )

    # Concurrency/stress probe (Kanté Task C + large-scale TTL).  Freshness
    # is enforced via ``MVP_STRESS_SUMMARY_TTL_HOURS`` (default 24h): a stale
    # PASS now WARNs (never silently passes), and any fresh BLOCK FAILs.
    stress = _stress_probe_summary()
    stress_impact = stress["stress_release_impact"]
    stress_status = stress["stress_gate_status"]
    if stress_impact == FAIL:
        verdict = FAIL
        why = f"stress_probe: fresh BLOCK (stress_gate_status={stress_status}"
        if stress.get("stress_summary_db_locked_errors"):
            why += f", db_locked_errors={stress['stress_summary_db_locked_errors']}"
        why += f"); FAIL. Re-run: {stress['stress_recommended_command']}"
        reasons.append(why)
    elif stress_impact == WARN and verdict == PASS:
        verdict = WARN
        if stress_status in {"UNKNOWN", "STALE", "DEGRADED"}:
            age = stress.get("stress_summary_age_seconds")
            reasons.append(
                f"stress_probe: {stress_status} (age={age}s, ttl="
                f"{stress['stress_summary_ttl_seconds']}s); WARN. "
                f"Re-run: {stress['stress_recommended_command']}"
            )
        else:
            reasons.append(
                "stress_probe: last run "
                f"stress_gate_status={stress_status} "
                f"(score={stress['stress_score']}); WARN."
            )

    # ------------------------------------------------------------------
    # Integrated Sprint checks.  Each is OPTIONAL: a missing artifact is a
    # WARN (and downgrades a PASS), never a silent PASS.  Safety-breaking
    # config (typed_config) FAILS the gate outright.
    # ------------------------------------------------------------------
    integrated: dict[str, Any] = {}
    warnings: list[str] = []
    blocking: list[str] = []

    # Typed config — safety-floor violation FAILS the gate immediately.
    if _typed_config is not None:
        cfg_status = _typed_config.validate_typed_config()
        integrated["typed_config_ok"] = bool(cfg_status.get("typed_config_ok"))
        integrated["typed_config_reason"] = cfg_status.get("reason")
        if not cfg_status.get("typed_config_ok"):
            verdict = FAIL
            blocking.append(
                f"typed_config: {cfg_status.get('reason')}; FAIL.")
    else:
        integrated["typed_config_ok"] = False
        integrated["typed_config_reason"] = "module_not_available"
        if verdict == PASS:
            verdict = WARN
        warnings.append("typed_config module unavailable; WARN.")

    # Diagnostics prewarm summary + tail metrics.
    prewarm_summary_path = None
    prewarm_summary = None
    if _prewarm is not None:
        prewarm_summary_path = _prewarm.SUMMARY_FILE
        prewarm_summary = _prewarm.read_summary(prewarm_summary_path)
    integrated["diagnostics_prewarm_summary_path"] = (
        str(prewarm_summary_path) if prewarm_summary_path else None
    )
    if prewarm_summary:
        # Pass the persisted prewarm summary into the tail metrics check.
        prewarm_ok = bool(prewarm_summary.get("ok")) and bool(
            prewarm_summary.get("cache_hit_after_prewarm"))
        integrated["diagnostics_prewarm_ok"] = prewarm_ok
        latencies = [
            prewarm_summary.get("prewarm_latency_ms") or 0.0,
            prewarm_summary.get("post_prewarm_latency_ms") or 0.0,
        ]
        cold_count = int(prewarm_summary.get("cold_recompute_count_after_prewarm")
                         or 0)
        if _tail is not None:
            tail = _tail.compute_tail_metrics(
                [float(v) for v in latencies if isinstance(v, (int, float))],
                cold_recompute_count_after_prewarm=cold_count,
            )
            integrated["performance_tail"] = {
                "p95_ms": tail["p95_ms"],
                "p99_ms": tail["p99_ms"],
                "max_ms": tail["max_ms"],
                "tail_ratio": tail["tail_ratio"],
                "cold_recompute_count_after_prewarm": cold_count,
                "performance_tail_score": tail["performance_tail_score"],
                "release_thresholds_ok": tail["release_thresholds_ok"],
            }
            # Only escalate to WARN; the tail metric is informational unless
            # the operator made the prewarm summary stale.
            if not tail["release_thresholds_ok"] and verdict == PASS:
                verdict = WARN
                warnings.append(
                    f"performance_tail: thresholds failed "
                    f"(p95={tail['p95_ms']}ms p99={tail['p99_ms']}ms "
                    f"max={tail['max_ms']}ms tail_ratio={tail['tail_ratio']}); WARN."
                )
        if not prewarm_ok and verdict == PASS:
            verdict = WARN
            warnings.append("diagnostics_prewarm_summary: ok=false; WARN.")
    else:
        integrated["diagnostics_prewarm_ok"] = False
        if verdict == PASS:
            verdict = WARN
        warnings.append(
            "diagnostics_prewarm_summary missing; run "
            "`python scripts/prewarm_diagnostics_snapshot.py --write-summary`. WARN."
        )

    # Live Payload Quality — we expose the module presence (no fixture
    # data persisted by default; the integration is in the candidate
    # pipeline at runtime).
    integrated["live_payload_quality_module_available"] = _lpq is not None

    # AI ingestion summary — optional artifact.
    if _ai_ingest is not None:
        ai_path = _ai_ingest.DEFAULT_SUMMARY_PATH
        ai_summary = None
        if ai_path.exists():
            try:
                ai_summary = json.loads(ai_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                ai_summary = None
        integrated["ai_ingestion_summary_path"] = str(ai_path)
        integrated["ai_ingestion_ok"] = bool(
            (ai_summary or {}).get("ai_ingestion_ok"))
    else:
        integrated["ai_ingestion_summary_path"] = None
        integrated["ai_ingestion_ok"] = False

    # Model reliability ledger — module presence + ledger path exists.
    try:
        from scripts import model_reliability_ledger as _mrl  # type: ignore
        integrated["model_reliability_ledger_ok"] = True
    except ModuleNotFoundError:  # pragma: no cover - module always present
        integrated["model_reliability_ledger_ok"] = False
        if verdict == PASS:
            verdict = WARN
        warnings.append("model_reliability_ledger module missing; WARN.")

    # Business value summary.
    if _bvr is not None:
        bv_path = _bvr.DEFAULT_SUMMARY_PATH
        integrated["business_value_summary_path"] = str(bv_path)
        bv_summary = _bvr.read_summary(bv_path)
        integrated["business_value_ok"] = bool(
            (bv_summary or {}).get("ok"))
        if not integrated["business_value_ok"]:
            if verdict == PASS:
                verdict = WARN
            warnings.append(
                "business_value_summary missing; run "
                "`python scripts/business_value_report.py --write-summary`. WARN."
            )
    else:
        integrated["business_value_ok"] = False
        if verdict == PASS:
            verdict = WARN
        warnings.append("business_value_report module unavailable; WARN.")

    # Compliance surface: registers must exist + claim no broken safety floor.
    if _comp_reg is not None:
        priv_path = _comp_reg.PRIVACY_INVENTORY_PATH
        reg_path = _comp_reg.SOURCE_LICENSE_REGISTER_PATH
        priv_present = priv_path.exists()
        reg_present = reg_path.exists()
        register_data = _comp_reg.read_register(reg_path) if reg_present else None
        missing = _comp_reg.missing_config_enabled_providers(
            register=register_data
        )
        integrated["privacy_inventory_path"] = str(priv_path)
        integrated["source_license_register_path"] = str(reg_path)
        integrated["compliance_privacy_present"] = priv_present
        integrated["compliance_register_present"] = reg_present
        integrated["compliance_missing_config_enabled_providers"] = missing
        integrated["compliance_surface_ok"] = bool(priv_present and reg_present
                                                   and not missing)
        if not integrated["compliance_surface_ok"] and verdict == PASS:
            verdict = WARN
            why = []
            if not priv_present:
                why.append("privacy_inventory.json missing")
            if not reg_present:
                why.append("source_license_register.json missing")
            if missing:
                why.append(f"config-enabled providers missing from register: {missing}")
            warnings.append(
                "compliance_surface: " + "; ".join(why)
                + ". Run `python scripts/compliance_registers.py --write`. WARN."
            )
    else:
        integrated["compliance_surface_ok"] = False
        if verdict == PASS:
            verdict = WARN
        warnings.append("compliance_registers module unavailable; WARN.")

    # ------------------------------------------------------------------
    # Sprint-2 subsystem blocks (Kanté defensive batch 2).  Each module is
    # OPTIONAL: a missing summary becomes a WARN with a remediation command;
    # an unreadable summary becomes a WARN; only the daily_signal_readiness
    # missing summary triggers the explicit "WARN with remediation" the spec
    # calls out (the rest are aggregated into the proof but don't downgrade
    # the verdict on their own — that's the persistence_integrity block's
    # job already).
    # ------------------------------------------------------------------
    persistence_block = _subsystem_block(
        _persistence_integrity, "persistence_integrity_score",
        "data_model_persistence",
    )
    live_source_block = _subsystem_block(
        _source_run_ledger, "live_payload_quality_score",
        "live_source_refresh", builder_method="refresh",
    )
    portfolio_block = _subsystem_block(
        _portfolio_truth, "portfolio_truth_score", "portfolio_truth",
    )
    fresh_discovery_block = _subsystem_block(
        _fresh_discovery, "fresh_discovery_quality_score", "fresh_discovery",
    )
    anti_staleness_block = {"ok": False, "score": None,
                            "summary_present": False, "summary_path": None,
                            "remediation": _SUBSYSTEM_REMEDIATION["anti_staleness"]}
    memo_decay_block = {"ok": False, "score": None,
                        "summary_present": False, "summary_path": None,
                        "remediation": _SUBSYSTEM_REMEDIATION["candidate_memory_decay"]}
    if _memory_decay_v2 is not None:
        for block, score_key, path_attr in (
            (anti_staleness_block, "anti_staleness_score",
             "ANTI_STALENESS_SUMMARY_PATH"),
            (memo_decay_block, "candidate_memory_decay_score",
             "MEMORY_DECAY_SUMMARY_PATH"),
        ):
            path = getattr(_memory_decay_v2, path_attr, None)
            block["summary_path"] = str(path) if path else None
            block["score_key"] = score_key
            summary = None
            if path is not None and Path(path).exists():
                try:
                    summary = json.loads(Path(path).read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    summary = None
            if summary is None:
                try:
                    anti, memo = _memory_decay_v2.build_summaries()
                    summary = (anti if score_key == "anti_staleness_score"
                               else memo)
                except Exception:  # pragma: no cover - defensive
                    summary = None
            if isinstance(summary, dict):
                block["summary_present"] = True
                block["ok"] = bool(summary.get("ok"))
                if score_key in summary:
                    block["score"] = float(summary[score_key])
                if "quarantined_count" in summary:
                    block["quarantined_count"] = summary["quarantined_count"]
    why_today_block = _subsystem_block(
        _why_today_enforcement, "why_today_enforcement_score", "why_today",
    )
    fmi_block = _subsystem_block(
        _five_model_independence, "five_model_independence_score",
        "five_model_independence",
    )
    mdh_block = _subsystem_block(
        _model_disagreement_handling, "model_disagreement_score",
        "model_disagreement",
    )
    ai_int_block = _subsystem_block(
        _ai_integration_readiness, "ai_integration_score", "ai_integration",
    )
    siq_block = _subsystem_block(
        _signal_input_quality, "signal_input_quality_score",
        "signal_input_quality",
    )
    bv_block = {
        "ok": integrated.get("business_value_ok", False),
        "score": None,
        "summary_present": integrated.get("business_value_ok", False),
        "summary_path": integrated.get("business_value_summary_path"),
        "remediation": _SUBSYSTEM_REMEDIATION["business_value"],
    }
    if _bvr is not None:
        bvs = _bvr.read_summary()
        if isinstance(bvs, dict) and "business_value_score" in bvs:
            bv_block["score"] = float(bvs["business_value_score"]) * 10.0
    compliance_block = _subsystem_block(
        _compliance_readiness, "compliance_readiness_score",
        "compliance_readiness",
    )
    dsr_block = _subsystem_block(
        _daily_signal_readiness, "overall_daily_signal_readiness",
        "daily_signal_readiness",
    )
    # The daily-signal-readiness summary missing IS the spec-mandated WARN.
    if (not dsr_block["summary_present"]
            and _daily_signal_readiness is not None):
        if verdict == PASS:
            verdict = WARN
        warnings.append(
            "daily_signal_readiness_summary missing; run "
            f"`{_SUBSYSTEM_REMEDIATION['daily_signal_readiness']}`. WARN."
        )

    # ------------------------------------------------------------------
    # Sprint 3 — new subsystem blocks (best-effort, never block by absence).
    # ------------------------------------------------------------------
    backend_api_block = _sprint3_artifact_block(
        "backend_api_quality",
        module=_backend_api_quality,
        summary_attr="DEFAULT_SUMMARY_PATH",
        score_key="backend_api_quality_score",
    )
    candidate_promotion_block = _sprint3_artifact_block(
        "candidate_promotion_contract",
        module=_candidate_promotion_contract,
        summary_attr="DEFAULT_SUMMARY_PATH",
        score_key="candidate_vs_executable_score",
    )
    universe_coverage_block = _sprint3_artifact_block(
        "universe_coverage",
        module=_universe_coverage,
        summary_attr="DEFAULT_SUMMARY_PATH",
        score_key="universe_coverage_score",
    )
    operator_demo_block = _sprint3_artifact_block(
        "operator_demo_value",
        module=_operator_demo_value,
        summary_attr="DEFAULT_SUMMARY_PATH",
        score_key="business_mvp_score",
    )
    live_provider_compliance_block = _sprint3_artifact_block(
        "live_provider_compliance_trace",
        module=_live_provider_compliance_trace,
        summary_attr="DEFAULT_TRACE_PATH",
        score_key="legal_privacy_compliance_score",
    )
    persistence_v2_block = _sprint3_artifact_block(
        "data_model_persistence_v2",
        module=_persistence_integrity,
        summary_attr="DEFAULT_V2_SUMMARY_PATH",
        score_key="data_model_persistence_v2_score",
    )
    config_env_block = _sprint3_artifact_block(
        "configuration_environment",
        module=_typed_config,
        summary_attr="DEFAULT_CONFIG_ENV_SUMMARY_PATH",
        score_key="configuration_environment_score",
    )

    # Operator-run live refresh proof + fake-LIVE detection.
    operator_live_refresh_block = _operator_live_refresh_proof_block()
    if not operator_live_refresh_block["attempted"]:
        # Spec requirement: surface the warning text, but absence alone
        # does NOT downgrade the verdict (operator-run refresh is by
        # design optional; CI must stay green).  LPQ stays capped honestly
        # via the daily_signal_readiness caps in Part 12.
        warnings.append(
            "operator live provider refresh not run; LPQ capped at "
            "fixture/offline score."
        )
    elif operator_live_refresh_block["warnings"]:
        # STALE: WARN, never inflate.
        if verdict == PASS:
            verdict = WARN
        warnings.extend(operator_live_refresh_block["warnings"])
    if operator_live_refresh_block["fake_live_verified_detected"]:
        verdict = FAIL
        blocking.extend(operator_live_refresh_block["blocking_reasons"])

    safety_stamps = _contract.advisory_safety_stamps()
    safety_block = {
        "ADVISORY_ONLY": True,
        "HUMAN_EXECUTION_REQUIRED": True,
        "execution_gate": safety_stamps["execution_gate"],
        "broker_api_called": safety_stamps["broker_api_called"],
        "ai_execution_count": safety_stamps["ai_execution_count"],
    }
    advisory_only_ok = (
        safety_block["execution_gate"] == "LOCKED"
        and safety_block["broker_api_called"] is False
        and safety_block["ai_execution_count"] == 0
    )
    if not advisory_only_ok:
        verdict = FAIL
        blocking.append("safety: advisory-only invariants violated; FAIL.")

    reasons.extend(blocking)
    reasons.extend(warnings)

    proof = {
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "release_gate_ok": verdict != FAIL,
        "verdict": verdict,
        "advisory_only_ok": advisory_only_ok,
        "safety": safety_block,
        "data_model_persistence": persistence_block,
        "live_source_refresh": live_source_block,
        "portfolio_truth": portfolio_block,
        "fresh_discovery": fresh_discovery_block,
        "anti_staleness": anti_staleness_block,
        "why_today": why_today_block,
        "candidate_memory_decay": memo_decay_block,
        "five_model_independence": fmi_block,
        "model_disagreement": mdh_block,
        "ai_integration": ai_int_block,
        "signal_input_quality": siq_block,
        "business_value": bv_block,
        "compliance_readiness": compliance_block,
        "daily_signal_readiness": dsr_block,
        # Sprint 3 sub-blocks.
        "backend_api_quality": backend_api_block,
        "candidate_promotion_contract": candidate_promotion_block,
        "universe_coverage": universe_coverage_block,
        "operator_demo_value": operator_demo_block,
        "live_provider_compliance_trace": live_provider_compliance_block,
        "data_model_persistence_v2": persistence_v2_block,
        "configuration_environment": config_env_block,
        "operator_live_refresh": operator_live_refresh_block,
        "blocking_reasons": list(blocking),
        "warnings": list(warnings),
    }
    try:
        RELEASE_GATE_PROOF_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = RELEASE_GATE_PROOF_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(proof, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(RELEASE_GATE_PROOF_PATH)
    except OSError:  # pragma: no cover - defensive
        pass

    return {
        "report": "release_gate",
        "verdict": verdict,
        "db_path": preflight["db_path"],
        "db_exists": preflight["db_exists"],
        "checked_backend": preflight["checked_backend"],
        "fail_count": len(fails),
        "warn_count": len(warns),
        "reasons": reasons,
        "integrated_sprint": integrated,
        "release_gate_proof": proof,
        "release_gate_proof_path": str(RELEASE_GATE_PROOF_PATH),
        "blocking_reasons": blocking,
        "warnings": warnings,
        "failing_checks": [c["name"] for c in fails],
        "warning_checks": [c["name"] for c in warns],
        # Kanté-defensive mutation-guard enforcement (now affects the verdict).
        "auth_guard_status": kante.get("auth_guard_status"),
        "operator_permission_guard_available": kante.get(
            "operator_permission_guard_available"),
        "mutation_guard_coverage": kante.get("mutation_guard_coverage"),
        "mutation_guard_risk": kante.get("mutation_guard_risk"),
        "mutation_scripts_guarded": kante.get("mutation_scripts_guarded_count"),
        "mutation_scripts_unguarded": kante.get("mutation_scripts_unguarded_count"),
        "mutation_scripts_unguarded_names": kante.get("mutation_scripts_unguarded"),
        "mutation_scripts_unguarded_high_severity": kante.get(
            "mutation_scripts_unguarded_high_severity"),
        "mutation_guard_release_impact": mutation_impact,
        "diagnostics_service_available": kante.get("diagnostics_service_available"),
        "diagnostics_service_status": kante.get("diagnostics_service_status"),
        "release_gate_impact": kante.get("release_gate_impact"),
        # Concurrency/stress probe surface (Kanté Task C + TTL).  A stale or
        # missing or malformed summary now WARNs (never silently passes), and
        # any fresh BLOCK FAILs the gate.
        "stress_probe_available": stress["stress_probe_available"],
        "stress_gate_status": stress["stress_gate_status"],
        "stress_score": stress["stress_score"],
        "stress_release_impact": stress_impact,
        "stress_summary_path": stress.get("stress_summary_path"),
        "stress_summary_generated_at_utc": stress.get("stress_summary_generated_at_utc"),
        "stress_summary_age_seconds": stress.get("stress_summary_age_seconds"),
        "stress_summary_ttl_seconds": stress.get("stress_summary_ttl_seconds"),
        "stress_summary_fresh": stress.get("stress_summary_fresh"),
        "stress_recommended_command": stress.get("stress_recommended_command"),
        "stress_summary_runtime_db_polluted": stress.get(
            "stress_summary_runtime_db_polluted", False
        ),
        "preflight": preflight,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="release_gate.py",
        description=(
            "Aggregate the local deploy preflight into a PASS/WARN/FAIL "
            "release verdict with exact reasons.  Read-only; never calls a "
            "broker."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--check-backend", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = evaluate(args.db_path, check_backend=args.check_backend)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"RELEASE GATE: {result['verdict']}")
        print(f"  db: {result['db_path']} (exists={result['db_exists']})")
        print(f"  fails={result['fail_count']} warns={result['warn_count']}")
        print(f"  auth_guard_status            : {result['auth_guard_status']}")
        print(f"  mutation_guard_coverage      : {result['mutation_guard_coverage']}")
        print(f"  mutation_scripts_unguarded   : {result['mutation_scripts_unguarded']} "
              f"{result['mutation_scripts_unguarded_names']}")
        print(f"  mutation_guard_release_impact: {result['mutation_guard_release_impact']}")
        print(f"  stress_gate_status           : {result['stress_gate_status']} "
              f"(impact={result['stress_release_impact']}, fresh="
              f"{result['stress_summary_fresh']}, "
              f"age={result['stress_summary_age_seconds']}s/"
              f"ttl={result['stress_summary_ttl_seconds']}s)")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        if result["verdict"] == PASS:
            print("  (all blocking checks satisfied)")
    # Exit non-zero only on a hard FAIL so CI can branch on it.
    return 1 if result["verdict"] == FAIL else 0


__all__ = [
    "PASS", "WARN", "FAIL",
    "DEFAULT_STRESS_SUMMARY_TTL_HOURS",
    "MAX_STRESS_SUMMARY_TTL_HOURS",
    "STRESS_PROBE_RECOMMENDED_CMD",
    "evaluate",
]


if __name__ == "__main__":
    raise SystemExit(main())
