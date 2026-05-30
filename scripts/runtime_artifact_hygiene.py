"""Runtime artifact hygiene — catch stale / unstamped / leaky artifacts.

KANTE_RUNTIME_ARTIFACT_HYGIENE
==============================

Kanté Ceiling Push II, Workstream F.  Runtime artifacts (the daily reliability
JSON, coverage proofs, canaries) are written to ``runtime/`` and consumed by
read-only routes + the release gate.  A stale, unstamped, secret-bearing, or
oversized artifact is exactly the kind of invisible defect that breaks CI or
quietly misleads an operator.  This module is the tracking-back check that
classifies an artifact PASS / WARN / FAIL *before* it causes harm.

Hard safety contract
--------------------
* Read-only.  NEVER deletes a file, NEVER mutates an artifact.  It only reads
  and classifies — remediation is a human decision.
* A broker-execution field set true, an AI-execution count > 0, an unlocked
  execution gate, or a non-PROHIBITED real-money stamp is always a FAIL.
* No execution-instruction wording is ever emitted.

Verdicts
--------
* FAIL — unparseable, missing required stamps, missing ``generated_at_utc``,
  a *fresh/live* artifact past its TTL, a secret-like value, or a broker /
  AI-execution / unlocked / non-prohibited stamp.
* WARN — a *disabled* artifact past its TTL, an oversized file, or an
  unexpected location.  Non-blocking, but surfaced.
* PASS — parseable, stamped, fresh-or-honestly-disabled, secret-free, locked.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "RUNTIME_ARTIFACT_HYGIENE_PAPER_ONLY"

DEFAULT_TTL_HOURS = 24.0
DEFAULT_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MiB

# Stamps every runtime safety-bearing artifact must carry.
REQUIRED_STAMPS: tuple[str, ...] = (
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
    "real_money_sizing_impact",
)

# Secret-bearing key markers (substring match, case-insensitive).
_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "private_key",
    "access_key",
    "bearer",
    "password",
    "token",
)
# Suffixes that make a secret-looking key safe (booleans / status flags only).
_SAFE_SECRET_SUFFIXES = ("_present", "_redacted", "_configured", "_set", "_count")
# Sentinel values that are explicitly safe even under a secret-looking key.
_SAFE_SECRET_VALUES = {"", "NONE", "REDACTED", "***", "<REDACTED>", "N/A"}

# Statuses / flags that mean "this artifact is NOT claiming live freshness".
_DISABLED_MARKERS = {
    "DISABLED",
    "CONFIG_MISSING",
    "NOT_CONFIGURED",
    "MOCK_ONLY",
    "NO_PAYLOAD",
    "ERROR_SAFE",
    "NETWORK_DISABLED",
}
# Statuses that DO claim live freshness.
_FRESH_MARKERS = {"OK", "LIVE", "LIVE_VERIFIED", "FRESH", "ACTIVE"}


def _parse_ts(value: Any) -> datetime | None:
    s = "" if value is None else str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now(now_utc: Any) -> datetime:
    dt = _parse_ts(now_utc)
    return dt if dt is not None else datetime.now(timezone.utc)


def _find_secret_leak(value: Any) -> str | None:
    """Return a redacted key path if a secret-like value is found, else None."""
    if isinstance(value, dict):
        for k, v in value.items():
            kl = str(k).lower()
            looks_secret = any(m in kl for m in _SECRET_KEY_MARKERS)
            safe_suffix = any(kl.endswith(sfx) for sfx in _SAFE_SECRET_SUFFIXES)
            if looks_secret and not safe_suffix:
                if isinstance(v, str) and v.strip().upper() not in _SAFE_SECRET_VALUES:
                    return str(k)
            nested = _find_secret_leak(v)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_secret_leak(item)
            if nested is not None:
                return nested
    return None


def _claims_fresh(data: dict[str, Any]) -> bool:
    if data.get("live_verified") is True:
        return True
    if data.get("enabled") is True and data.get("disabled_intentionally") is not True:
        return True
    for key in ("status", "external_evidence_status", "maturity_label"):
        if str(data.get(key) or "").upper() in _FRESH_MARKERS:
            return True
    return False


def _is_disabled(data: dict[str, Any]) -> bool:
    if data.get("enabled") is False:
        return True
    if data.get("disabled_intentionally") is True:
        return True
    for key in ("status", "external_evidence_status", "maturity_label"):
        if str(data.get(key) or "").upper() in _DISABLED_MARKERS:
            return True
    return False


def evaluate_artifact(
    data: dict[str, Any] | None,
    *,
    age_hours: float | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    size_bytes: int | None = None,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    location_ok: bool = True,
    parse_ok: bool = True,
    artifact_name: str = "artifact",
) -> dict[str, Any]:
    """Classify an artifact dict PASS / WARN / FAIL (pure).  Never raises."""
    fail_reasons: list[str] = []
    warn_reasons: list[str] = []
    required_stamp_missing: list[str] = []

    if not parse_ok or not isinstance(data, dict):
        fail_reasons.append("artifact_not_parseable")
        return _result(
            artifact_name=artifact_name,
            verdict=FAIL,
            fail_reasons=fail_reasons,
            warn_reasons=warn_reasons,
            required_stamp_missing=list(REQUIRED_STAMPS),
            age_hours=age_hours,
            ttl_hours=ttl_hours,
        )

    # --- required safety stamps
    for stamp in REQUIRED_STAMPS:
        if stamp not in data:
            required_stamp_missing.append(stamp)
    if not ("advisory_status" in data or "advisory_only" in data):
        required_stamp_missing.append("advisory_status_or_advisory_only")
    if "generated_at_utc" not in data:
        required_stamp_missing.append("generated_at_utc")
    if required_stamp_missing:
        fail_reasons.append(
            "required_stamp_missing: " + ", ".join(required_stamp_missing)
        )

    # --- execution / broker / AI safety stamps
    if data.get("broker_api_called") is True:
        fail_reasons.append("broker_api_called_true")
    ai_count = data.get("ai_execution_count")
    if isinstance(ai_count, (int, float)) and ai_count > 0:
        fail_reasons.append("ai_execution_count_gt_zero")
    if "execution_gate" in data and str(data.get("execution_gate")) != "LOCKED":
        fail_reasons.append("execution_gate_not_locked")
    if (
        "real_money_sizing_impact" in data
        and str(data.get("real_money_sizing_impact")) != REAL_MONEY_SIZING_IMPACT
    ):
        fail_reasons.append("real_money_sizing_not_prohibited")

    # --- secrets
    leak = _find_secret_leak(data)
    if leak is not None:
        fail_reasons.append(f"secret_like_value:{leak}")

    # --- freshness vs TTL
    stale = age_hours is not None and age_hours > ttl_hours
    if stale:
        if _claims_fresh(data) and not _is_disabled(data):
            fail_reasons.append(
                f"stale_fresh_artifact (age={round(age_hours, 3)}h > ttl={ttl_hours}h)"
            )
        else:
            warn_reasons.append(
                f"stale_disabled_artifact (age={round(age_hours, 3)}h > ttl={ttl_hours}h)"
            )

    # --- size + location (non-blocking)
    if size_bytes is not None and size_bytes > max_size_bytes:
        warn_reasons.append(f"oversized_artifact ({size_bytes} bytes)")
    if not location_ok:
        warn_reasons.append("unexpected_artifact_location")

    if fail_reasons:
        verdict = FAIL
    elif warn_reasons:
        verdict = WARN
    else:
        verdict = PASS

    return _result(
        artifact_name=artifact_name,
        verdict=verdict,
        fail_reasons=fail_reasons,
        warn_reasons=warn_reasons,
        required_stamp_missing=required_stamp_missing,
        age_hours=age_hours,
        ttl_hours=ttl_hours,
    )


def _result(
    *,
    artifact_name: str,
    verdict: str,
    fail_reasons: list[str],
    warn_reasons: list[str],
    required_stamp_missing: list[str],
    age_hours: float | None,
    ttl_hours: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "report": "runtime_artifact_hygiene",
        "artifact_name": artifact_name,
        "verdict": verdict,
        "fail_reasons": fail_reasons,
        "warn_reasons": warn_reasons,
        "reasons": fail_reasons + warn_reasons,
        "required_stamp_missing": required_stamp_missing,
        "artifact_age_hours": None if age_hours is None else round(age_hours, 6),
        "ttl_hours": ttl_hours,
        # This checker never executes anything; its own output is stamped too.
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


def check_artifact_file(
    path: Path,
    *,
    now_utc: Any = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    expected_root: Path | None = None,
) -> dict[str, Any]:
    """Read + classify a runtime artifact file (read-only).  Never raises."""
    path = Path(path)
    name = path.name
    if not path.exists():
        return evaluate_artifact(
            None, parse_ok=False, artifact_name=name, ttl_hours=ttl_hours
        )
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        parse_ok = isinstance(data, dict)
    except (OSError, json.JSONDecodeError):
        data, parse_ok = None, False

    age_hours: float | None = None
    if isinstance(data, dict):
        ts = _parse_ts(data.get("generated_at_utc"))
        if ts is not None:
            age_hours = (_now(now_utc) - ts).total_seconds() / 3600.0

    location_ok = True
    if expected_root is not None:
        try:
            location_ok = str(path.resolve()).startswith(str(Path(expected_root).resolve()))
        except OSError:
            location_ok = True

    return evaluate_artifact(
        data if parse_ok else None,
        age_hours=age_hours,
        ttl_hours=ttl_hours,
        size_bytes=size_bytes,
        max_size_bytes=max_size_bytes,
        location_ok=location_ok,
        parse_ok=parse_ok,
        artifact_name=name,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runtime_artifact_hygiene.py",
        description=(
            "Classify a runtime artifact PASS/WARN/FAIL for staleness, missing "
            "stamps, secrets, and broker/AI-execution leaks. Read-only; never "
            "deletes; never mutates artifacts."
        ),
    )
    p.add_argument("--path", required=True, help="path to the runtime artifact JSON")
    p.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    p.add_argument("--json", action="store_true", help="print the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = check_artifact_file(Path(args.path), ttl_hours=args.ttl_hours)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("runtime_artifact_hygiene")
        print(f"  artifact        : {result['artifact_name']}")
        print(f"  verdict         : {result['verdict']}")
        print(f"  age_hours       : {result['artifact_age_hours']}")
        if result["reasons"]:
            print(f"  reasons         : {'; '.join(result['reasons'])}")
    # FAIL → non-zero exit so CI can gate on it.
    return 1 if result["verdict"] == FAIL else 0


__all__ = [
    "PASS",
    "WARN",
    "FAIL",
    "REQUIRED_STAMPS",
    "DEFAULT_TTL_HOURS",
    "evaluate_artifact",
    "check_artifact_file",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
