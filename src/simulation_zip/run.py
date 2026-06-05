"""CLI: safely ingest a local zip corpus and emit SIMULATION_ONLY reports.

Usage::

    python -m src.simulation_zip.run --zip "C:\\Users\\akash\\Downloads\\hackathon_scraper.zip"

Or set ``SIMULATION_ZIP_PATH`` and run ``python -m src.simulation_zip.run``.

Fail-closed: a missing / corrupted / oversized / path-unsafe archive yields a
BLOCKED report (exit code 2) with NO_DATA metrics — never fabricated numbers.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
from pathlib import Path

from src.simulation_zip.harness import run_zip_simulation
from src.simulation_zip.reports import (
    render_integration_markdown,
    render_summary_markdown,
    write_json,
)
from src.simulation_zip.safety import SafetyConfig


def _timestamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.simulation_zip.run",
        description="Safe zip simulation corpus ingestion (advisory-only, "
        "fail-closed). All outputs are SIMULATION_ONLY.",
    )
    p.add_argument(
        "--zip",
        default=os.environ.get("SIMULATION_ZIP_PATH", ""),
        help="Path to the local .zip corpus (or set SIMULATION_ZIP_PATH).",
    )
    p.add_argument(
        "--out-dir",
        default="runtime/reports",
        help="Directory for generated reports (default: runtime/reports).",
    )
    p.add_argument("--corpus-label", default="OPERATOR_ZIP")
    p.add_argument(
        "--tests-pass",
        dest="tests_pass",
        action="store_true",
        default=True,
        help="Assert the suite passes (default). Gates the after<=60 cap.",
    )
    p.add_argument("--no-tests-pass", dest="tests_pass", action="store_false")
    p.add_argument(
        "--guardrails-ok",
        dest="guardrails_ok",
        action="store_true",
        default=True,
    )
    p.add_argument("--no-guardrails-ok", dest="guardrails_ok", action="store_false")
    p.add_argument("--max-member-mb", type=int, default=50)
    return p


def run(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.zip:
        print(
            "ERROR: no zip path. Pass --zip or set SIMULATION_ZIP_PATH.\n"
            "This is fail-closed: nothing is parsed without an explicit path."
        )
        return 2

    config = SafetyConfig(
        max_member_uncompressed_bytes=args.max_member_mb * 1024 * 1024
    )
    report = run_zip_simulation(
        args.zip,
        config=config,
        tests_pass=args.tests_pass,
        guardrails_ok=args.guardrails_ok,
        corpus_label=args.corpus_label,
    )

    ts = _timestamp()
    out = Path(args.out_dir)
    inventory = {
        "schema_version": "1.0.0",
        "generated_at": report.get("generated_at"),
        "labels": report.get("labels"),
        "zip_path": report.get("zip_path"),
        "safety": report.get("safety"),
        "manifest": report.get("manifest"),
    }
    paths = {
        "inventory": write_json(out / f"zip_simulation_inventory_{ts}.json", inventory),
        "run": write_json(out / f"zip_simulation_run_{ts}.json", report),
        "scores": write_json(out / f"zip_simulation_scores_{ts}.json", report.get("scores")),
    }
    summary_path = out / f"zip_simulation_summary_{ts}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(render_summary_markdown(report), encoding="utf-8")
    integration_path = out / f"zip_simulation_integration_{ts}.md"
    integration_path.write_text(render_integration_markdown(report), encoding="utf-8")

    status = report.get("status")
    print(f"[{status}] {report.get('zip_path')}")
    print(f"  archive_safety = {report['safety']['archive_status']} "
          f"({report['safety']['reason']})")
    print(f"  usable_records = {report['diagnostics'].get('usable_records')}, "
          f"families_parsed = {report['diagnostics'].get('families_parsed')}")
    overall = report["scores"]["overall"]
    print(f"  overall before/after = {overall['overall_before']} -> "
          f"{overall['overall_after']} (Δ {overall['overall_delta']}, "
          f"{overall['overall_relative_lift_pct']}%)  [SIMULATION_ONLY]")
    for k, v in paths.items():
        print(f"  wrote {k}: {v}")
    print(f"  wrote summary: {summary_path}")
    print(f"  wrote integration: {integration_path}")
    if status == "BLOCKED":
        print("  FAIL-CLOSED: archive blocked; no simulation records produced.")
        return 2
    return 0


def main() -> None:  # pragma: no cover - thin wrapper
    raise SystemExit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
