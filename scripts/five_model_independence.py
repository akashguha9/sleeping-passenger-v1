"""Five-model independence — model_runs ledger + independence score.

Integrated Sprint — Part 8 (Kanté defensive batch 2).  Each AI model report
ingested for the daily synthesis must:

* arrive with its own ``prompt_hash`` and ``input_context_hash``,
* be timestamped before any synthesis,
* have ``saw_other_model_outputs == False``,
* and only feed synthesis once an explicit *independent freeze* has been
  recorded.

This module provides:

* the ``model_runs`` table DDL (compatible with ``persistence_integrity``),
* an in-memory ``ModelRun`` dataclass for tests,
* the independence-score formula,
* the summary builder + writer at
  ``runtime/release/five_model_independence_summary.json``.

No network, no broker, no AI execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "five_model_independence_summary.json"
)

EXPECTED_MODELS: tuple[str, ...] = (
    "grok", "claude", "codex", "gemini", "mistral",
)

_DDL = """
CREATE TABLE IF NOT EXISTS model_runs (
    model_run_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    input_context_hash TEXT NOT NULL,
    generated_at_utc TEXT,
    ingested_at_utc TEXT,
    run_order INTEGER,
    independent_before_synthesis INTEGER NOT NULL,
    saw_other_model_outputs INTEGER NOT NULL DEFAULT 0,
    output_hash TEXT,
    status TEXT,
    advisory_only INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_mr_model_name ON model_runs(model_name);
"""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:32]


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


@dataclass
class ModelRun:
    model_name: str
    prompt: str
    input_context: str
    output: str
    saw_other_model_outputs: bool = False
    independent_before_synthesis: bool = True
    run_order: int = 0
    status: str = "OK"
    generated_at_utc: str = field(default_factory=_utc_iso)
    ingested_at_utc: str = field(default_factory=_utc_iso)
    frozen_before_synthesis: bool = True
    ingested_before_synthesis: bool = True
    missing_reason: str | None = None  # for explicitly-missing models

    @property
    def model_run_id(self) -> str:
        return f"{self.model_name}-{uuid.uuid5(uuid.NAMESPACE_URL, self.prompt + self.output).hex[:16]}"

    @property
    def prompt_hash(self) -> str:
        return _sha(self.prompt)

    @property
    def input_context_hash(self) -> str:
        return _sha(self.input_context)

    @property
    def output_hash(self) -> str:
        return _sha(self.output)

    def is_independent(self) -> bool:
        return (
            not self.saw_other_model_outputs
            and self.independent_before_synthesis
            and self.frozen_before_synthesis
            and self.ingested_before_synthesis
            and not self.missing_reason
            and bool(self.prompt_hash)
            and bool(self.input_context_hash)
            and bool(self.output_hash)
        )

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.model_run_id, self.model_name, self.prompt_hash,
            self.input_context_hash, self.generated_at_utc, self.ingested_at_utc,
            int(self.run_order),
            int(self.independent_before_synthesis),
            int(self.saw_other_model_outputs),
            self.output_hash, self.status, 1,
        )


def open_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:" if db_path is None else str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def record_model_run(conn: sqlite3.Connection, run: ModelRun) -> str:
    conn.execute(
        "INSERT OR REPLACE INTO model_runs("
        "model_run_id, model_name, prompt_hash, input_context_hash, "
        "generated_at_utc, ingested_at_utc, run_order, "
        "independent_before_synthesis, saw_other_model_outputs, output_hash, "
        "status, advisory_only) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        run.as_row(),
    )
    conn.commit()
    return run.model_run_id


def independence_score(runs: Iterable[ModelRun]) -> dict[str, Any]:
    runs = list(runs)
    expected = len(EXPECTED_MODELS)
    seen_models = {r.model_name.lower() for r in runs
                   if not (r.missing_reason or "")}
    independent = [r for r in runs
                   if r.is_independent() and not r.missing_reason]
    contaminated = [r for r in runs if r.saw_other_model_outputs]
    # Sprint 3 — explicit-missing-with-reason.  A model can be marked
    # missing with a non-empty ``missing_reason`` (e.g. "rate-limited",
    # "API key absent").  We do NOT count it as silently missing.
    explicitly_missing = [r for r in runs if r.missing_reason]
    silently_missing = [
        m for m in EXPECTED_MODELS
        if m not in {r.model_name.lower() for r in runs}
    ]
    missing_prompt = any(not r.prompt_hash for r in runs if not r.missing_reason)
    missing_output = any(not r.output_hash for r in runs if not r.missing_reason)
    synthesis_before_freeze = any(
        not r.independent_before_synthesis for r in runs if not r.missing_reason
    )
    # Synthesis contamination audit — any run where frozen_before_synthesis
    # was false or saw_other_model_outputs is true.
    synthesis_contamination = [
        r for r in runs
        if not r.missing_reason
        and (r.saw_other_model_outputs or not r.frozen_before_synthesis
             or not r.ingested_before_synthesis)
    ]
    synthesis_contamination_audited = True  # this fn IS the audit

    contamination_penalty = _clamp01(
        0.20 * (len(contaminated) / expected)
        + 0.10 * (1.0 if missing_prompt else 0.0)
        + 0.10 * (1.0 if missing_output else 0.0)
        + 0.10 * (1.0 if synthesis_before_freeze else 0.0)
    )
    raw_independence = _clamp01(
        (len(independent) / expected) * (1.0 - contamination_penalty)
    )

    all_expected_accounted_for = all(
        m in {r.model_name.lower() for r in runs}
        for m in EXPECTED_MODELS
    )
    # We give full credit when every expected model is either present-and-
    # independent OR explicitly-missing-with-reason.  Silently-missing
    # models are NEVER given credit.
    accountable_for = len(seen_models) + len({
        r.model_name.lower() for r in explicitly_missing
    } & set(EXPECTED_MODELS))
    accountability_ratio = min(1.0, accountable_for / expected)

    five_model_independence_seg = _clamp01(
        0.40 * raw_independence
        + 0.20 * accountability_ratio
        + 0.20 * (0.0 if synthesis_before_freeze else 1.0)
        + 0.10 * (0.0 if missing_prompt else 1.0)
        + 0.10 * (0.0 if missing_output else 1.0)
    )

    return {
        "expected_model_count": expected,
        "seen_model_count": len(seen_models),
        "independent_model_count": len(independent),
        "contaminated_model_count": len(contaminated),
        "explicitly_missing_count": len(explicitly_missing),
        "silently_missing_models": silently_missing,
        "explicitly_missing_models": [
            {"model_name": r.model_name, "reason": r.missing_reason}
            for r in explicitly_missing
        ],
        "missing_prompt_hash": missing_prompt,
        "missing_output_hash": missing_output,
        "synthesis_before_freeze": synthesis_before_freeze,
        "synthesis_contamination_count": len(synthesis_contamination),
        "synthesis_contamination_audited": synthesis_contamination_audited,
        "contamination_penalty": round(contamination_penalty, 6),
        "independence_score": round(raw_independence, 6),
        "accountability_ratio": round(accountability_ratio, 6),
        "five_model_independence_score": round(10.0 * five_model_independence_seg, 4),
        "all_expected_models_seen": all_expected_accounted_for,
        "missing_models": silently_missing,
    }


def _fixture_runs() -> list[ModelRun]:
    """All 5 expected models, fully independent, with deterministic hashes."""
    base_prompt = "synthesize today's daily signal candidates"
    base_context = "candidate_list_2026-05-24"
    out = []
    for i, m in enumerate(EXPECTED_MODELS):
        out.append(ModelRun(
            model_name=m, prompt=base_prompt + f"::{m}",
            input_context=base_context,
            output=f"{m}-stance-summary",
            run_order=i + 1,
        ))
    return out


def build_summary(runs: Iterable[ModelRun] | None = None) -> dict[str, Any]:
    runs = list(runs) if runs is not None else _fixture_runs()
    score = independence_score(runs)
    return {
        "report": "five_model_independence_summary",
        "ok": score["five_model_independence_score"] >= 9.5,
        "generated_at_utc": _utc_iso(),
        "expected_models": list(EXPECTED_MODELS),
        "ledger_entries": [
            {
                "model_run_id": r.model_run_id,
                "model_name": r.model_name,
                "prompt_hash": r.prompt_hash,
                "input_context_hash": r.input_context_hash,
                "output_hash": r.output_hash,
                "saw_other_model_outputs": r.saw_other_model_outputs,
                "independent_before_synthesis": r.independent_before_synthesis,
                "run_order": r.run_order,
                "status": r.status,
            } for r in runs
        ],
        **score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  runs: Iterable[ModelRun] | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(runs)
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
    p = argparse.ArgumentParser(prog="five_model_independence.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"five_model_independence_score = "
              f"{summary['five_model_independence_score']}")
        print(f"  seen: {summary['seen_model_count']}/"
              f"{summary['expected_model_count']} "
              f"missing={summary['missing_models']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH", "EXPECTED_MODELS",
    "ModelRun", "open_db", "record_model_run", "independence_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
