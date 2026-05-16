"""HTML parsers for GMAT Club listing and problem pages.

WARNING: written against phpBB v3 default markup (the forum stack GMAT Club
runs on top of). The CSS selectors below are educated guesses. When you have
real HTML access, run the parser against a saved page and adjust the
`SELECTORS` dict at the top of this module if anything turns up empty.

Field policy
------------
- Fields that cannot be parsed are emitted as `None` / `null` in JSONL,
  never fabricated.
- Every problem record includes a `scrape_timestamp` (UTC ISO 8601) and
  a `parser_confidence` float in [0.0, 1.0] reflecting how many expected
  fields were extracted.
- `forum_category` carries the human-readable section label (e.g.
  "Critical Reasoning"), separate from the short `section` code used in
  filenames.

Tested in tests/test_gmat_scraper.py against synthetic fixture HTML so the
parser is at least internally consistent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


# ───────── Selectors (adjust here when you see real HTML) ─────────
SELECTORS = {
    # Listing page
    "topic_row":      "li.row",
    "topic_link":     "a.topictitle",
    "topic_replies":  "dd.posts",
    "topic_views":    "dd.views",
    # Problem (thread) page
    "post_block":     "div.post",
    "post_author":    "p.author",
    "post_body":      ".postbody .content",
    "post_time":      "p.author time",
    "post_anchor":    "h3 a",          # permalink to a specific post
    "thread_title":   "h2.topic-title, h2 a, h1",
    # Answer markers (GMAT Club-specific conventions)
    "official_answer_text": re.compile(
        r"(?:Official Answer|OA(?:\s*is)?|Correct Answer)\s*[:=]?\s*([A-E])",
        re.IGNORECASE,
    ),
    "answer_choice_line": re.compile(
        r"^\s*\(?([A-E])\)?[\.\)\-\s]+(.+)$", re.MULTILINE
    ),
}


# ─────────────────────────── Data shapes ──────────────────────────

@dataclass
class TopicSummary:
    url: str
    title: Optional[str]
    replies: Optional[int] = None
    views: Optional[int] = None


@dataclass
class Post:
    author: Optional[str]
    body_text: Optional[str]
    body_html: Optional[str]
    posted_at: Optional[str] = None
    anchor: Optional[str] = None


@dataclass
class Problem:
    url: str
    title: Optional[str]
    section: str                         # short code: PS / CR / DS / GT / MSR / TPA
    forum_category: Optional[str] = None # human label
    question_text: Optional[str] = None
    answer_choices: Optional[dict[str, str]] = None
    official_answer: Optional[str] = None
    solutions: list[Post] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    scrape_timestamp: Optional[str] = None
    parser_confidence: float = 0.0

    def to_jsonable(self) -> dict:
        return asdict(self)


# ─────────────────────────── Helpers ──────────────────────────────

def _txt(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    s = node.get_text(" ", strip=True)
    return s or None


def _int_or_none(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"\d[\d,]*", s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────── Listing-page parsing ─────────────────────

def parse_listing(html: str, base_url: str) -> list[TopicSummary]:
    """Extract topic summaries from a listing/index page.

    Missing per-row fields are emitted as None (never fabricated).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[TopicSummary] = []
    for row in soup.select(SELECTORS["topic_row"]):
        link = row.select_one(SELECTORS["topic_link"])
        if not link or not link.get("href"):
            continue
        href = urljoin(base_url, link["href"])
        title = _txt(link)
        replies = _int_or_none(_txt(row.select_one(SELECTORS["topic_replies"])))
        views = _int_or_none(_txt(row.select_one(SELECTORS["topic_views"])))
        out.append(TopicSummary(url=href, title=title, replies=replies, views=views))
    return out


# ─────────────────────── Problem-page parsing ─────────────────────

def _extract_answer_choices(text: Optional[str]) -> Optional[dict[str, str]]:
    """Look for lines like 'A) 12' or '(A) 12'. Returns None if no choices
    could be parsed (rather than an empty dict, which would be ambiguous)."""
    if not text:
        return None
    choices: dict[str, str] = {}
    for m in SELECTORS["answer_choice_line"].finditer(text):
        letter = m.group(1).upper()
        body = m.group(2).strip()
        if letter not in choices:
            choices[letter] = body
    return choices or None


def _extract_official_answer(html_or_text: str) -> Optional[str]:
    m = SELECTORS["official_answer_text"].search(html_or_text)
    if m:
        return m.group(1).upper()
    return None


def _parse_post(block: Tag, base_url: str) -> Post:
    author = _txt(block.select_one(SELECTORS["post_author"]))
    body_node = block.select_one(SELECTORS["post_body"])
    body_html = str(body_node) if body_node else None
    # Preserve paragraph structure so the answer-choice regex (which is
    # line-anchored) can find "(A) ..." / "(B) ..." across <p> tags.
    body_text = body_node.get_text("\n", strip=True) if body_node is not None else None
    if body_text == "":
        body_text = None
    time_node = block.select_one(SELECTORS["post_time"])
    posted_at: Optional[str] = None
    if time_node is not None:
        posted_at = time_node.get("datetime") or _txt(time_node)
    anchor_node = block.select_one(SELECTORS["post_anchor"])
    anchor: Optional[str] = None
    if anchor_node is not None and anchor_node.get("href"):
        anchor = urljoin(base_url, anchor_node["href"])
    return Post(
        author=author,
        body_text=body_text,
        body_html=body_html,
        posted_at=posted_at,
        anchor=anchor,
    )


# Fields that count toward parser_confidence on a Problem record.
_CONFIDENCE_FIELDS = (
    "title",
    "question_text",
    "answer_choices",
    "official_answer",
    "solutions_present",
)


def _confidence(problem: "Problem") -> float:
    hits = 0
    if problem.title:
        hits += 1
    if problem.question_text:
        hits += 1
    if problem.answer_choices:
        hits += 1
    if problem.official_answer:
        hits += 1
    if problem.solutions:
        hits += 1
    return round(hits / len(_CONFIDENCE_FIELDS), 3)


def parse_problem(
    html: str,
    url: str,
    section: str,
    title_fallback: Optional[str] = None,
    forum_category: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> Problem:
    """Parse a single problem (thread) page into a Problem record.

    `now_iso` is injectable for deterministic tests; defaults to current UTC.
    """
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one(SELECTORS["thread_title"])
    title = _txt(title_node) or (title_fallback or None)

    blocks = soup.select(SELECTORS["post_block"])
    posts = [_parse_post(b, url) for b in blocks]

    problem = Problem(
        url=url,
        title=title,
        section=section,
        forum_category=forum_category,
        scrape_timestamp=now_iso or _utc_now_iso(),
    )

    if posts:
        first = posts[0]
        problem.question_text = first.body_text
        problem.answer_choices = _extract_answer_choices(first.body_text)
        problem.solutions = posts[1:]

    page_text = soup.get_text("\n", strip=True)
    problem.official_answer = _extract_official_answer(page_text)

    # Optional metadata grab — safe to be empty.
    problem.metadata = {
        "n_posts": len(posts),
    }

    problem.parser_confidence = _confidence(problem)
    return problem
