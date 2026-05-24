"""Source-run ledger + live-source refresh discipline.

Integrated Sprint — Part 3 (Kanté defensive batch 2).  Layered on top of
:mod:`scripts.persistence_integrity`: this module computes per-provider
freshness / availability / verification / schema scores and the aggregate
Live Payload Quality (LPQ) index used by Fresh-Discovery, FCS, and the
release gate.

Two modes:

* ``fixture`` — deterministic, no internet, CI-safe.  Sample providers are
  scored as ``FIXTURE_VERIFIED`` so the LPQ has a non-zero floor without
  pretending we hit the live network.
* ``live`` — *optional* network refresh.  Network failures degrade the
  provider to ``OFFLINE`` / ``UNVERIFIED`` rather than crashing, and an
  OFFLINE provider can never advance ``latest_provider_timestamp_utc``.

Pure-with-respect-to-runtime DB except in ``live`` mode (still optional).
No broker, no AI execution.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import persistence_integrity as _pi
except ModuleNotFoundError:  # pragma: no cover
    import persistence_integrity as _pi  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "live_source_refresh_summary.json"
)

# Source classes + per-source-class half-lives (hours).  These are the
# operational SLAs Fresh-Discovery / WHY_TODAY consume.
HALF_LIFE_HOURS: dict[str, float] = {
    "price_mover": 6.0,
    "filing": 36.0,
    "news_event": 12.0,
    "ai_report": 24.0,
}

# Mapping from provider key -> declared source class.
PROVIDER_CLASS: dict[str, str] = {
    "yfinance": "price_mover",
    "sec_edgar": "filing",
    "gdelt": "news_event",
    "newsapi": "news_event",
    "ai_reports": "ai_report",
}

# LPQ weights per source class (per spec).
LPQ_WEIGHTS: dict[str, float] = {
    "price_mover": 0.30,
    "filing": 0.25,
    "news_event": 0.25,
    "ai_report": 0.20,
}

VERIFICATION_SCORES: dict[str, float] = {
    "VERIFIED": 1.0,
    "FIXTURE_VERIFIED": 0.85,
    "UNVERIFIED": 0.5,
    "STALE": 0.25,
    "FALLBACK": 0.0,
    "MOCK": 0.0,
}

AVAILABILITY_SCORES: dict[str, float] = {
    "SUCCESS": 1.0,
    "PARTIAL": 0.7,
    "STALE": 0.4,
    "FAILED": 0.0,
    "OFFLINE": 0.0,
    "STARTED": 0.0,
}

PROMOTION_BLOCKING_VERIFICATIONS: frozenset[str] = frozenset({
    "FALLBACK", "MOCK", "STALE",
})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def freshness_score(age_hours: float, half_life_hours: float) -> float:
    """``exp(-ln2 * age / half_life)`` — half-life decay, clamped to [0,1]."""
    if half_life_hours <= 0:
        return 0.0
    age = max(0.0, float(age_hours))
    return _clamp01(math.exp(-math.log(2.0) * age / float(half_life_hours)))


@dataclass
class ProviderResult:
    provider: str
    source_type: str
    status: str = "OFFLINE"
    verification_status: str = "UNVERIFIED"
    latest_provider_timestamp_utc: str | None = None
    events_seen: int = 0
    events_inserted: int = 0
    schema_score: float = 1.0
    last_error: str | None = None
    schema_valid: bool = True

    def as_summary(self, now_utc: str) -> dict[str, Any]:
        age_hours = _age_hours(self.latest_provider_timestamp_utc, now_utc)
        half_life = HALF_LIFE_HOURS.get(self.source_type, 24.0)
        f_score = freshness_score(age_hours, half_life)
        a_score = AVAILABILITY_SCORES.get(self.status, 0.0)
        v_score = VERIFICATION_SCORES.get(self.verification_status, 0.0)
        # OFFLINE / FAILED providers never returned a payload, so we cannot
        # honestly score schema validity — they get 0, never the default 1.0.
        # Same for FALLBACK / MOCK verifications: we don't credit schema for
        # data we don't trust.
        if (
            self.status in {"OFFLINE", "FAILED"}
            or self.verification_status in {"FALLBACK", "MOCK"}
        ):
            s_score = 0.0
        else:
            s_score = _clamp01(self.schema_score)
        run_health = _clamp01(
            0.35 * f_score + 0.25 * a_score + 0.25 * v_score + 0.15 * s_score
        )
        # FALLBACK / MOCK / OFFLINE / FAILED can never propagate as healthy
        # regardless of the formula — collapse the health to zero so LPQ
        # cannot be inflated by a fresh-looking-but-untrusted source.
        if (
            self.verification_status in {"FALLBACK", "MOCK"}
            or self.status in {"OFFLINE", "FAILED"}
        ):
            run_health = 0.0
        blocks_promotion = (
            self.status in {"FAILED", "OFFLINE"}
            or self.verification_status in PROMOTION_BLOCKING_VERIFICATIONS
        )
        return {
            "provider": self.provider,
            "source_type": self.source_type,
            "status": self.status,
            "verification_status": self.verification_status,
            "source_run_health": round(run_health, 6),
            "freshness_score": round(f_score, 6),
            "availability_score": round(a_score, 6),
            "verification_score": round(v_score, 6),
            "schema_score": round(s_score, 6),
            "age_hours": round(age_hours, 4),
            "half_life_hours": float(half_life),
            "latest_provider_timestamp_utc": self.latest_provider_timestamp_utc,
            "events_seen": int(self.events_seen),
            "events_inserted": int(self.events_inserted),
            "last_error": self.last_error,
            "blocks_promotion": bool(blocks_promotion),
        }


def _age_hours(timestamp: str | None, now_utc: str) -> float:
    if not timestamp:
        return float("inf") if False else 9999.0
    try:
        ts = timestamp
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        t = datetime.fromisoformat(ts).astimezone(timezone.utc)
        now_ts = now_utc
        if now_ts.endswith("Z"):
            now_ts = now_ts[:-1] + "+00:00"
        n = datetime.fromisoformat(now_ts).astimezone(timezone.utc)
        return max(0.0, (n - t).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 9999.0


def compute_lpq(providers: Iterable[dict[str, Any]]) -> float:
    """Aggregate LPQ from per-provider summaries.

    For each source class, take the *best* health across its providers (so
    duplicate news-event providers don't double-count); then weighted-sum per
    LPQ_WEIGHTS.  Missing classes contribute 0.
    """
    by_class: dict[str, float] = {}
    for prov in providers:
        cls = str(prov.get("source_type", ""))
        if cls not in LPQ_WEIGHTS:
            continue
        score = float(prov.get("source_run_health", 0.0) or 0.0)
        by_class[cls] = max(by_class.get(cls, 0.0), score)
    lpq = sum(LPQ_WEIGHTS[c] * by_class.get(c, 0.0) for c in LPQ_WEIGHTS)
    return round(_clamp01(lpq), 6)


def live_payload_quality_score(lpq_ratio: float) -> float:
    """Map a 0..1 LPQ ratio onto the 0..10 segment score the gate reads."""
    return round(10.0 * _clamp01(float(lpq_ratio)), 4)


# ----------------------------------------------------------------------
# Refresh entry points.
# ----------------------------------------------------------------------


def _fixture_providers(now_utc: str) -> list[ProviderResult]:
    """Deterministic fixture set — all providers FIXTURE_VERIFIED, fresh.

    Honest about being fixture data: nothing here is marked LIVE_VERIFIED.
    """
    # All ages well within their half-life so per-class health is high but
    # never identical to a real live PASS (we cap verification at 0.85).
    return [
        ProviderResult(
            provider="fixture.yfinance",
            source_type="price_mover",
            status="SUCCESS",
            verification_status="FIXTURE_VERIFIED",
            latest_provider_timestamp_utc=now_utc,
            events_seen=12, events_inserted=12,
        ),
        ProviderResult(
            provider="fixture.sec_edgar",
            source_type="filing",
            status="SUCCESS",
            verification_status="FIXTURE_VERIFIED",
            latest_provider_timestamp_utc=now_utc,
            events_seen=4, events_inserted=4,
        ),
        ProviderResult(
            provider="fixture.gdelt",
            source_type="news_event",
            status="SUCCESS",
            verification_status="FIXTURE_VERIFIED",
            latest_provider_timestamp_utc=now_utc,
            events_seen=20, events_inserted=20,
        ),
        ProviderResult(
            provider="fixture.ai_reports",
            source_type="ai_report",
            status="SUCCESS",
            verification_status="FIXTURE_VERIFIED",
            latest_provider_timestamp_utc=now_utc,
            events_seen=5, events_inserted=5,
        ),
    ]


def _live_providers(now_utc: str) -> list[ProviderResult]:
    """Best-effort live refresh.

    The MVP must never *invent* live verification, so this function makes
    *no* outbound HTTP call by default — it inspects whether each provider's
    enable flag is set and an explicit env hint (``MVP_LIVE_REFRESH_OK``) is
    present.  If either is missing the provider degrades to OFFLINE/
    UNVERIFIED honestly.  When tests / operators actually hit the network,
    the real adapter modules can be wired here later; the formula and
    summary contract stay stable.
    """
    out: list[ProviderResult] = []
    network_ok = os.environ.get("MVP_LIVE_REFRESH_OK", "").lower() in {
        "1", "true", "yes", "on",
    }
    for provider, source_type in PROVIDER_CLASS.items():
        # Without explicit operator opt-in we report OFFLINE rather than
        # fake a successful live touch.  This is the *honest* default.
        if not network_ok:
            out.append(ProviderResult(
                provider=provider, source_type=source_type,
                status="OFFLINE", verification_status="UNVERIFIED",
                last_error="MVP_LIVE_REFRESH_OK not set; not contacting network",
            ))
            continue
        # With opt-in we *still* don't crash the gate if the adapter is
        # absent — surface UNVERIFIED + the missing-module error.
        out.append(ProviderResult(
            provider=provider, source_type=source_type,
            status="PARTIAL", verification_status="UNVERIFIED",
            last_error="live adapter wiring is operator-deployed; surfaced honestly",
        ))
    return out


def refresh(mode: str = "fixture") -> dict[str, Any]:
    """Refresh providers and build the summary dict (does not write to disk)."""
    if mode not in {"fixture", "live"}:
        raise ValueError(f"mode must be 'fixture' or 'live'; got {mode!r}")
    now = _utc_iso()
    results = (_fixture_providers if mode == "fixture" else _live_providers)(now)
    provider_summaries = [r.as_summary(now) for r in results]
    lpq = compute_lpq(provider_summaries)

    verified_count = sum(
        1 for p in provider_summaries
        if p["verification_status"] == "VERIFIED"
    )
    fixture_verified_count = sum(
        1 for p in provider_summaries
        if p["verification_status"] == "FIXTURE_VERIFIED"
    )
    stale_count = sum(
        1 for p in provider_summaries
        if p["verification_status"] == "STALE"
    )
    fallback_count = sum(
        1 for p in provider_summaries
        if p["verification_status"] in {"FALLBACK", "MOCK"}
    )
    offline_count = sum(
        1 for p in provider_summaries if p["status"] == "OFFLINE"
    )

    return {
        "report": "live_source_refresh_summary",
        "ok": lpq >= 0.6,
        "mode": mode,
        "ran_at_utc": now,
        "lpq": lpq,
        "live_payload_quality_score": live_payload_quality_score(lpq),
        "providers": provider_summaries,
        "verified_provider_count": verified_count,
        "fixture_verified_provider_count": fixture_verified_count,
        "stale_provider_count": stale_count,
        "fallback_provider_count": fallback_count,
        "offline_provider_count": offline_count,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(
    path: Path | None = None,
    *,
    mode: str = "fixture",
) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = refresh(mode=mode)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="source_run_ledger.py",
        description=(
            "Compute per-provider source-run health + the aggregate Live "
            "Payload Quality index. Fixture mode is deterministic and offline; "
            "live mode is opt-in (MVP_LIVE_REFRESH_OK=1) and degrades gracefully."
        ),
    )
    p.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = (
        write_summary(mode=args.mode) if args.write_summary
        else refresh(mode=args.mode)
    )
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"live_payload_quality_score = "
              f"{summary['live_payload_quality_score']} (lpq={summary['lpq']})")
        for p in summary["providers"]:
            print(f"  {p['provider']:30s} {p['source_type']:14s} "
                  f"status={p['status']:7s} verif={p['verification_status']:18s} "
                  f"health={p['source_run_health']:.3f} "
                  f"blocks_promotion={p['blocks_promotion']}")
    return 0


__all__ = [
    "HALF_LIFE_HOURS", "PROVIDER_CLASS", "LPQ_WEIGHTS",
    "VERIFICATION_SCORES", "AVAILABILITY_SCORES",
    "PROMOTION_BLOCKING_VERIFICATIONS",
    "DEFAULT_SUMMARY_PATH",
    "ProviderResult",
    "freshness_score", "compute_lpq", "live_payload_quality_score",
    "refresh", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
