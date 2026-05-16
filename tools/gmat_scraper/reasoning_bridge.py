"""Bridge from GMAT problems to trade-decision frames.

The user requirement that justified building this scraper inside a trading
repo: "GMAT teaches reasoning patterns" → translate those patterns into
entry/skip rules the trade engine can consult.

A DecisionFrame is a tiny, opinionated record:

    {
        "problem_id":  "<url>",
        "section":     "CR",
        "frame":       "weaken-thesis",
        "rule":        "Before entry, list 2 things that would invalidate the thesis.",
        "source_url":  "https://gmatclub.com/forum/..."
    }

Trading code can load the JSONL produced by `bridge_jsonl(...)` and use the
`rule` strings as a checklist on every prospective entry. This module makes
no claim that GMAT problems are themselves predictive — only that the
reasoning categories they exercise (sufficiency, assumption, paradox, etc.)
are the same categories a disciplined trade thesis has to survive.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator


# ─────────────────────── Frame catalog ───────────────────────

# Per-section default frames. Each frame is a short imperative the engine
# can show / log next to a candidate entry.
SECTION_DEFAULT_FRAMES: dict[str, list[tuple[str, str]]] = {
    "DS": [
        ("skip-if-insufficient",
         "If the information you have is not strictly sufficient to determine "
         "edge sign and magnitude, SKIP rather than enter."),
        ("data-coverage",
         "Enumerate the minimum data set required for the thesis; flag any "
         "gaps before sizing."),
    ],
    "CR": [
        ("assumption-check",
         "State the load-bearing assumption of the thesis in one sentence. "
         "If it cannot be stated cleanly, the thesis is not ready."),
        ("weaken-thesis",
         "List two distinct facts that, if true, would invalidate the entry. "
         "Pre-commit to exits tied to each."),
        ("paradox-resolve",
         "If price action and thesis disagree, name the mechanism that "
         "reconciles them, or stand down."),
    ],
    "PS": [
        ("constraint-check",
         "Re-derive the numeric edge from first principles (R/R, hit rate, "
         "expectancy) before sizing; do not act on a stale figure."),
    ],
    "GT": [
        ("chart-truth",
         "Read the chart for what it shows, not what you want it to show. "
         "Note the unit, the scale, and the omitted axis before reacting."),
    ],
    "MSR": [
        ("source-synthesis",
         "Cross-check the trade thesis against at least two independent "
         "information surfaces; flag single-source convictions."),
    ],
    "TPA": [
        ("two-part-coherence",
         "If the trade has two coupled legs (e.g., entry + hedge), verify "
         "that the chosen pair is mutually consistent under the same model."),
    ],
}

# Keyword patterns layered on top of section defaults. If a problem's
# question text matches, we attach the named frame in addition.
KEYWORD_FRAMES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bassum(e|es|ed|ption)\b", re.I),
     "assumption-check",
     "Explicitly state every assumption that would have to hold for the "
     "trade to work."),
    (re.compile(r"\bweaken|undermine\b", re.I),
     "weaken-thesis",
     "Identify the single fact that most efficiently invalidates the "
     "entry; tie a stop to it."),
    (re.compile(r"\bstrengthen|support\b", re.I),
     "strengthen-thesis",
     "Identify what new evidence would let you add to the position, and "
     "the exact level at which that evidence would arrive."),
    (re.compile(r"\bparadox|resolve\b", re.I),
     "paradox-resolve",
     "Reconcile the contradiction (e.g., price vs. fundamentals) with a "
     "concrete mechanism before acting."),
    (re.compile(r"\bsufficient|insufficient\b", re.I),
     "skip-if-insufficient",
     "Treat insufficient information as a hard skip, not a soft maybe."),
]


@dataclass(frozen=True)
class DecisionFrame:
    problem_id: str
    section: str
    frame: str
    rule: str
    source_url: str

    def to_jsonable(self) -> dict:
        return asdict(self)


def frames_for_problem(problem: dict) -> list[DecisionFrame]:
    section = problem.get("section", "")
    url = problem.get("url", "")
    text = " ".join([
        problem.get("title", "") or "",
        problem.get("question_text", "") or "",
    ])

    seen: set[str] = set()
    out: list[DecisionFrame] = []

    for frame_name, rule in SECTION_DEFAULT_FRAMES.get(section, []):
        if frame_name in seen:
            continue
        seen.add(frame_name)
        out.append(DecisionFrame(
            problem_id=url, section=section,
            frame=frame_name, rule=rule, source_url=url,
        ))

    for pattern, frame_name, rule in KEYWORD_FRAMES:
        if frame_name in seen:
            continue
        if pattern.search(text):
            seen.add(frame_name)
            out.append(DecisionFrame(
                problem_id=url, section=section,
                frame=frame_name, rule=rule, source_url=url,
            ))

    return out


def iter_problems_jsonl(path: str | Path) -> Iterator[dict]:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def bridge_jsonl(in_path: str | Path, out_path: str | Path) -> int:
    """Read a scraped-problems JSONL, write a decision-frames JSONL.

    Returns the number of frame records written.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for prob in iter_problems_jsonl(in_path):
            for frame in frames_for_problem(prob):
                fh.write(json.dumps(frame.to_jsonable(), ensure_ascii=False))
                fh.write("\n")
                n += 1
    return n


def load_frames(path: str | Path) -> list[DecisionFrame]:
    """Helper for the trading engine: load all frames into memory."""
    out: list[DecisionFrame] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(DecisionFrame(**obj))
    return out


def checklist_for_entry(frames: Iterable[DecisionFrame],
                        section_priority: tuple[str, ...] = ("DS", "CR", "PS", "MSR", "TPA", "GT"),
                        limit: int = 6) -> list[str]:
    """Surface a short, deduped checklist of rules for an entry decision.

    Pulls the highest-priority sections first and stops at `limit` rules.
    Trading code can call this on every candidate entry.
    """
    by_frame: dict[str, str] = {}
    section_order = {s: i for i, s in enumerate(section_priority)}
    sorted_frames = sorted(
        frames,
        key=lambda f: section_order.get(f.section, len(section_priority)),
    )
    for f in sorted_frames:
        if f.frame in by_frame:
            continue
        by_frame[f.frame] = f.rule
        if len(by_frame) >= limit:
            break
    return list(by_frame.values())
