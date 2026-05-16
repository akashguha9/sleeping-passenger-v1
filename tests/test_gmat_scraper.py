"""Tests for the GMAT scraper module.

The scraper is intentionally *out of MVP scope* and lives under
``tools/gmat_scraper/`` (see ``scripts/private_scope_guard.py``). The
tests here exist purely to keep the quarantined module honest —
parser invariants, advisory-only / no-broker guarantees — and to lock
in that the package cannot be re-imported under ``scripts/`` without
also tripping the scope-guard tests.

NOTE: parser tests use synthetic fixture HTML modeled on phpBB v3
default markup. Passing these tests does NOT guarantee the parser
works against the real GMAT Club site — it only verifies the parser's
internal contract. Real-site selectors live in
``tools.gmat_scraper.parser.SELECTORS`` and may need adjustment when
you have a saved real-page HTML.

All tests are offline; no test issues a network request.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

bs4 = pytest.importorskip("bs4")

from tools.gmat_scraper import parser, reasoning_bridge, sections, store
from tools.gmat_scraper import cli as scraper_cli
from tools.gmat_scraper import http as scraper_http

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ─────────────────────── sections / URL generation ───────────────────────

def test_section_urls_PS_page1_has_no_index():
    s = sections.SECTIONS["PS"]
    assert s.index_url(1) == "https://gmatclub.com/forum/problem-solving-ps-140/"


def test_section_urls_PS_pageN_uses_index_50_step():
    s = sections.SECTIONS["PS"]
    assert s.index_url(2)   == "https://gmatclub.com/forum/problem-solving-ps-140/index-50.html"
    assert s.index_url(3)   == "https://gmatclub.com/forum/problem-solving-ps-140/index-100.html"
    assert s.index_url(820) == "https://gmatclub.com/forum/problem-solving-ps-140/index-40950.html"


def test_section_urls_CR_pages():
    s = sections.SECTIONS["CR"]
    assert s.index_url(1)   == "https://gmatclub.com/forum/critical-reasoning-cr-139/"
    assert s.index_url(2)   == "https://gmatclub.com/forum/critical-reasoning-cr-139/index-50.html"
    assert s.index_url(262) == "https://gmatclub.com/forum/critical-reasoning-cr-139/index-13050.html"


def test_total_problems_estimate_in_range():
    # User-supplied snapshot: PS 820 + CR 262 + DS 361 + GT 19 + MSR 4 + TPA 17,
    # page_size 50 → ~74,150. Allow drift; just sanity-check magnitude.
    n = sections.total_problems_estimate()
    assert 60_000 < n < 90_000


# ─────────────────────── listing parser ───────────────────────

def test_parse_listing_extracts_all_rows():
    html = _read("gmat_listing.html")
    topics = parser.parse_listing(
        html, base_url="https://gmatclub.com/forum/problem-solving-ps-140/"
    )
    assert len(topics) == 3
    assert topics[0].title.startswith("If x is positive integer")
    assert topics[0].url.endswith("/forum/sample-problem-one-12345.html")
    assert topics[0].replies == 12
    assert topics[0].views == 3450


def test_parse_listing_handles_absolute_url():
    html = _read("gmat_listing.html")
    topics = parser.parse_listing(
        html, base_url="https://gmatclub.com/forum/problem-solving-ps-140/"
    )
    assert topics[2].url == "https://gmatclub.com/forum/full-url-problem-11111.html"


def test_parse_listing_empty_html_yields_empty_list():
    topics = parser.parse_listing("<html><body></body></html>", base_url="https://x/")
    assert topics == []


# ─────────────────────── problem parser ───────────────────────

def test_parse_problem_pulls_question_and_choices():
    html = _read("gmat_problem.html")
    p = parser.parse_problem(
        html,
        url="https://gmatclub.com/forum/weakens.html",
        section="CR",
        forum_category="Critical Reasoning",
        now_iso="2026-05-16T00:00:00Z",
    )
    assert p.section == "CR"
    assert p.forum_category == "Critical Reasoning"
    assert p.url == "https://gmatclub.com/forum/weakens.html"
    assert "congestion charge" in p.question_text
    assert p.answer_choices["A"].startswith("The charge is collected")
    assert p.answer_choices["B"].startswith("Most downtown drivers")
    assert set(p.answer_choices) == {"A", "B", "C", "D", "E"}


def test_parse_problem_finds_official_answer():
    html = _read("gmat_problem.html")
    p = parser.parse_problem(html, url="x", section="CR")
    assert p.official_answer == "B"


def test_parse_problem_collects_solutions():
    html = _read("gmat_problem.html")
    p = parser.parse_problem(html, url="x", section="CR")
    assert len(p.solutions) == 2
    assert "attack the assumption" in p.solutions[0].body_text


def test_parse_problem_emits_timestamp_and_confidence():
    html = _read("gmat_problem.html")
    p = parser.parse_problem(
        html, url="x", section="CR",
        now_iso="2026-05-16T12:34:56Z",
    )
    assert p.scrape_timestamp == "2026-05-16T12:34:56Z"
    assert 0.0 < p.parser_confidence <= 1.0


def test_parse_problem_unparseable_fields_emit_null():
    """An empty page must yield nulls, not fabricated empty strings."""
    p = parser.parse_problem(
        "<html><body></body></html>",
        url="https://gmatclub.com/forum/empty.html",
        section="PS",
        now_iso="2026-05-16T00:00:00Z",
    )
    j = p.to_jsonable()
    assert j["title"] is None
    assert j["question_text"] is None
    assert j["answer_choices"] is None
    assert j["official_answer"] is None
    assert j["solutions"] == []
    assert j["parser_confidence"] == 0.0


def test_parse_problem_jsonable_is_serialisable():
    html = _read("gmat_problem.html")
    p = parser.parse_problem(html, url="x", section="CR",
                             now_iso="2026-05-16T00:00:00Z")
    # Must roundtrip through JSON without errors and preserve None.
    encoded = json.dumps(p.to_jsonable())
    decoded = json.loads(encoded)
    assert decoded["section"] == "CR"
    assert decoded["scrape_timestamp"] == "2026-05-16T00:00:00Z"


# ─────────────────────── store / resume ───────────────────────

def test_store_append_and_known_urls_roundtrip(scratch_path):
    path = scratch_path / "ps.jsonl"
    s = store.JsonlStore(path)
    assert s.known_urls() == set()
    s.append({"url": "https://a.example/p1", "title": "p1"})
    s.append({"url": "https://a.example/p2", "title": "p2"})
    # Reopen to confirm persistence + dedup-key semantics
    s2 = store.JsonlStore(path)
    assert s2.known_urls() == {"https://a.example/p1", "https://a.example/p2"}


def test_store_ignores_malformed_lines(scratch_path):
    path = scratch_path / "ps.jsonl"
    path.write_text(
        '{"url":"https://a.example/p1"}\nNOT JSON\n{"url":"https://a.example/p2"}\n'
    )
    s = store.JsonlStore(path)
    assert s.known_urls() == {"https://a.example/p1", "https://a.example/p2"}


def test_store_resume_skip_logic_simulation(scratch_path):
    """End-to-end check: a 'resume' caller should not re-emit known URLs."""
    path = scratch_path / "cr.jsonl"
    s = store.JsonlStore(path)
    s.append({"url": "u1"})
    seen = s.known_urls()
    new_topics = [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}]
    written = 0
    for t in new_topics:
        if t["url"] in seen:
            continue
        s.append(t)
        seen.add(t["url"])
        written += 1
    assert written == 2
    assert s.known_urls() == {"u1", "u2", "u3"}


# ─────────────────────── reasoning bridge ───────────────────────

def test_default_frames_attached_per_section_DS():
    p = {"url": "u", "section": "DS", "title": "t", "question_text": "anything"}
    names = {f.frame for f in reasoning_bridge.frames_for_problem(p)}
    assert "skip-if-insufficient" in names
    assert "data-coverage" in names


def test_keyword_layered_frames_CR_assumption():
    p = {"url": "u", "section": "CR",
         "title": "Which assumption is required?",
         "question_text": "Find the assumption."}
    names = {f.frame for f in reasoning_bridge.frames_for_problem(p)}
    assert "assumption-check" in names


def test_bridge_jsonl_writes_records(scratch_path):
    in_path = scratch_path / "CR.jsonl"
    out_path = scratch_path / "frames.jsonl"
    in_path.write_text(json.dumps({
        "url": "https://gmatclub.com/forum/x",
        "title": "Which most weakens the argument?",
        "section": "CR",
        "question_text": "We assume the policy will reduce traffic.",
    }) + "\n")
    n = reasoning_bridge.bridge_jsonl(in_path, out_path)
    assert n > 0
    lines = [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
    assert all(rec["section"] == "CR" for rec in lines)
    assert any(rec["frame"] == "weaken-thesis" for rec in lines)


def test_checklist_for_entry_dedups_and_caps():
    p_ds = {"url": "u1", "section": "DS", "title": "t",
            "question_text": "is information sufficient"}
    p_cr = {"url": "u2", "section": "CR", "title": "what assumption",
            "question_text": "weaken the conclusion"}
    frames = (reasoning_bridge.frames_for_problem(p_ds)
              + reasoning_bridge.frames_for_problem(p_cr))
    rules = reasoning_bridge.checklist_for_entry(frames, limit=4)
    assert 1 <= len(rules) <= 4
    assert len(rules) == len(set(rules))  # deduped


def test_bridge_is_deterministic():
    """Same input must yield identical frames across runs."""
    p = {"url": "u", "section": "CR",
         "title": "weaken this", "question_text": "assume X holds"}
    a = [f.to_jsonable() for f in reasoning_bridge.frames_for_problem(p)]
    b = [f.to_jsonable() for f in reasoning_bridge.frames_for_problem(p)]
    assert a == b


# ─────────────────────── safety guardrails ───────────────────────

# Words that, if present in the scraper or bridge code, would indicate the
# module is doing something it must NOT do per the spec (sending orders,
# touching brokers, executing trades).
_FORBIDDEN_PATTERNS = [
    r"\bplace_order\b",
    r"\bsubmit_order\b",
    r"\bexecute_trade\b",
    r"\bbroker[._]",
    r"\balpaca\b",
    r"\bibkr\b",
    r"\binteractive[\s_-]?brokers\b",
    r"\btd[\s_-]?ameritrade\b",
    r"\bschwab[\s_-]?api\b",
    r"\boanda\b",
    r"\border[\s_-]?id\b",
]


@pytest.mark.parametrize("mod", [parser, reasoning_bridge, sections,
                                  store, scraper_cli, scraper_http])
def test_no_broker_or_execution_language_in_scraper(mod):
    src = inspect.getsource(mod)
    for pat in _FORBIDDEN_PATTERNS:
        assert re.search(pat, src, flags=re.IGNORECASE) is None, (
            f"forbidden pattern {pat!r} found in {mod.__name__}"
        )


def test_reasoning_bridge_is_advisory_only():
    """Bridge must produce checklist strings, never callables or side effects."""
    p = {"url": "u", "section": "CR", "title": "weaken", "question_text": "assume"}
    frames = reasoning_bridge.frames_for_problem(p)
    # Every frame must be a plain DecisionFrame with string fields.
    for f in frames:
        assert isinstance(f.rule, str)
        assert isinstance(f.frame, str)
        # No callable smuggled in.
        assert not callable(f.rule)
