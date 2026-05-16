"""Command-line entry point for the GMAT Club scraper.

Examples
--------

    # Smoke run — fetch just the first listing page of Problem Solving
    # and dump the topic summaries to stdout. Does NOT visit threads.
    python -m tools.gmat_scraper.cli discover --section PS --pages 1

    # Crawl a small page range, saving full problems to JSONL.
    python -m tools.gmat_scraper.cli crawl \\
        --section CR --from-page 1 --to-page 3 \\
        --delay 4 --cookies ~/gmatclub_cookies.txt

    # Build decision frames from a scraped JSONL.
    python -m tools.gmat_scraper.cli bridge \\
        --in data/raw/gmat/CR.jsonl \\
        --out data/processed/gmat_frames_CR.jsonl
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .http import PoliteClient, FetchError
from .parser import parse_listing, parse_problem
from .reasoning_bridge import bridge_jsonl
from .sections import SECTIONS
from .store import JsonlStore

log = logging.getLogger("gmat_scraper")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "raw" / "gmat"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _client_from_args(args: argparse.Namespace) -> PoliteClient:
    return PoliteClient(
        delay=args.delay,
        jitter=args.jitter,
        max_retries=args.retries,
        cookies_path=args.cookies,
    )


# ─────────────────────── Commands ───────────────────────

def cmd_discover(args: argparse.Namespace) -> int:
    section = SECTIONS[args.section]
    client = _client_from_args(args)
    pages = args.pages or 1
    for page in range(1, pages + 1):
        url = section.index_url(page)
        try:
            html = client.get_html(url)
        except FetchError as exc:
            log.error("fetch failed: %s", exc)
            return 2
        topics = parse_listing(html, url)
        log.info("page %d  %d topics", page, len(topics))
        for t in topics:
            print(f"{t.url}\t{t.title}")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    section = SECTIONS[args.section]
    client = _client_from_args(args)
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_DIR
    out_path = out_dir / f"{section.code}.jsonl"
    store = JsonlStore(out_path)
    seen = store.known_urls()
    log.info("resume: %d already-stored URLs in %s", len(seen), out_path)

    to_page = args.to_page or section.last_page
    from_page = args.from_page or 1
    if to_page > section.last_page:
        log.warning("--to-page %d > section.last_page %d, clamping",
                    to_page, section.last_page)
        to_page = section.last_page

    n_problems = 0
    for page in range(from_page, to_page + 1):
        listing_url = section.index_url(page)
        try:
            listing_html = client.get_html(listing_url)
        except FetchError as exc:
            log.error("listing fetch failed at page %d: %s — stopping", page, exc)
            break
        topics = parse_listing(listing_html, listing_url)
        log.info("page %d/%d  %d topics", page, to_page, len(topics))

        for t in topics:
            if t.url in seen:
                continue
            try:
                thread_html = client.get_html(t.url)
            except FetchError as exc:
                log.warning("skip %s — %s", t.url, exc)
                continue
            problem = parse_problem(
                thread_html, t.url, section.code,
                title_fallback=t.title,
                forum_category=section.name,
            )
            store.append(problem.to_jsonable())
            seen.add(t.url)
            n_problems += 1
            if args.max_problems and n_problems >= args.max_problems:
                log.info("hit --max-problems %d, stopping", args.max_problems)
                return 0
    log.info("done — %d new problems appended to %s", n_problems, out_path)
    return 0


def cmd_bridge(args: argparse.Namespace) -> int:
    n = bridge_jsonl(args.in_path, args.out_path)
    log.info("wrote %d decision frames to %s", n, args.out_path)
    return 0


# ─────────────────────── Argparse ───────────────────────

def _add_client_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--delay", type=float, default=3.0,
                   help="seconds between requests (default 3.0)")
    p.add_argument("--jitter", type=float, default=1.0,
                   help="random +/- on delay (default 1.0)")
    p.add_argument("--retries", type=int, default=4,
                   help="max HTTP retries (default 4)")
    p.add_argument("--cookies", type=str, default=None,
                   help="path to Netscape cookies.txt with a logged-in session")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gmat_scraper")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="list topics on a listing page")
    d.add_argument("--section", choices=list(SECTIONS), required=True)
    d.add_argument("--pages", type=int, default=1,
                   help="number of listing pages from page 1 to print")
    _add_client_args(d)
    d.set_defaults(func=cmd_discover)

    c = sub.add_parser("crawl", help="fetch and save full problems")
    c.add_argument("--section", choices=list(SECTIONS), required=True)
    c.add_argument("--from-page", type=int, default=1)
    c.add_argument("--to-page", type=int, default=None,
                   help="defaults to the section's last page")
    c.add_argument("--out-dir", type=str, default=None,
                   help=f"defaults to {DEFAULT_OUT_DIR}")
    c.add_argument("--max-problems", type=int, default=None,
                   help="cap total new problems for this run (safety)")
    _add_client_args(c)
    c.set_defaults(func=cmd_crawl)

    b = sub.add_parser("bridge", help="convert scraped JSONL → decision frames JSONL")
    b.add_argument("--in", dest="in_path", required=True)
    b.add_argument("--out", dest="out_path", required=True)
    b.set_defaults(func=cmd_bridge)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
