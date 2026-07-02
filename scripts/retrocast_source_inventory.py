"""Retrocast source inventory — how much of the blocker is source vs code.

Classifies each retrocast data leg into:
  FULL_HISTORY_AVAILABLE / PARTIAL_HISTORY_AVAILABLE /
  RESOLUTION_ONLY_AVAILABLE / NO_HISTORY_AVAILABLE /
  BLOCKED_ADAPTER_LIMITATION

Evidence weights: 1.0 / 0.5 / 0.1 / 0.0 / 0.0. Resolution-only records may
support coverage inventories and mapping tests but can NEVER support beta
estimates, validation status, calibration improvement, or promotion —
ValidatedCategoryScore uses only weight >= 0.5 records.

Read-only probes; fail-closed reporting. ADVISORY_ONLY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

EVIDENCE_WEIGHT = {"FULL_HISTORY_AVAILABLE": 1.0,
                   "PARTIAL_HISTORY_AVAILABLE": 0.5,
                   "RESOLUTION_ONLY_AVAILABLE": 0.1,
                   "NO_HISTORY_AVAILABLE": 0.0,
                   "BLOCKED_ADAPTER_LIMITATION": 0.0}
VALIDATION_MIN_WEIGHT = 0.5


def classify_sources(probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pure classification from probe results:
    probes = {leg: {"reachable": bool, "history": bool, "resolutions": bool,
                    "detail": str}}"""
    legs: dict[str, Any] = {}
    for leg, p in probes.items():
        if not p.get("reachable"):
            status = "BLOCKED_ADAPTER_LIMITATION"
        elif p.get("history"):
            status = ("FULL_HISTORY_AVAILABLE"
                      if p.get("resolutions") else
                      "PARTIAL_HISTORY_AVAILABLE")
        elif p.get("resolutions"):
            status = "RESOLUTION_ONLY_AVAILABLE"
        else:
            status = "NO_HISTORY_AVAILABLE"
        w = EVIDENCE_WEIGHT[status]
        legs[leg] = {"status": status, "evidence_weight": w,
                     "supports_validation": w >= VALIDATION_MIN_WEIGHT,
                     "detail": p.get("detail", "")}
    return {"legs": legs,
            "validation_capable_legs": [k for k, v in legs.items()
                                        if v["supports_validation"]],
            "blocker_is_source_not_code": all(
                v["status"] != "FULL_HISTORY_AVAILABLE"
                for v in legs.values()),
            "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY}


def probe_live() -> dict[str, dict[str, Any]]:
    """Read-only probes of the actual retrocast legs from this network."""
    import urllib.request

    def _ok(url: str) -> tuple[bool, str]:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "sleeping-passenger advisory read-only"})
            raw = urllib.request.urlopen(req, timeout=20).read()
            return True, f"OK ({len(raw)} bytes)"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:120]}"

    base = "https://api.elections.kalshi.com/trade-api/v2"
    settled_ok, settled_d = _ok(f"{base}/markets?limit=2&status=settled")
    series_ok, series_d = _ok(f"{base}/series?category=Economics")
    poly_ok, poly_d = _ok(
        "https://gamma-api.polymarket.com/markets?limit=1&closed=true")
    return {
        "kalshi_resolutions": {"reachable": settled_ok, "history": False,
                               "resolutions": settled_ok,
                               "detail": settled_d},
        "kalshi_probability_history": {"reachable": series_ok,
                                       "history": series_ok,
                                       "resolutions": False,
                                       "detail": series_d},
        "polymarket_history": {"reachable": poly_ok, "history": poly_ok,
                               "resolutions": poly_ok, "detail": poly_d},
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Retrocast source inventory")
    ap.add_argument("--write", choices=("dry_run", "write"),
                    default="dry_run")
    args = ap.parse_args()
    report = classify_sources(probe_live())
    if args.write == "write":
        out = Path("runtime/retrocast_source_inventory.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True),
                       encoding="utf-8")
        md = ["# Retrocast source inventory", ""]
        for leg, v in report["legs"].items():
            md.append(f"- **{leg}**: {v['status']} (weight "
                      f"{v['evidence_weight']}) — {v['detail']}")
        md += ["", f"validation-capable legs: "
               f"{report['validation_capable_legs'] or 'NONE'}",
               f"blocker is source, not code: "
               f"{report['blocker_is_source_not_code']}",
               "", f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
        Path("runtime/retrocast_source_inventory.md").write_text(
            "\n".join(md), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
