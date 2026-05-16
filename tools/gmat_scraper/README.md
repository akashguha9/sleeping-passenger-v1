# GMAT Club scraper

Pulls problems and discussion threads from the public GMAT Club forum and
emits two artifacts:

1. **`data/raw/gmat/<SECTION>.jsonl`** — one Problem per line. Schema:

   ```jsonc
   {
     "url":               "https://gmatclub.com/forum/<topic>.html",
     "title":             "...",                  // null if not parseable
     "section":           "PS|CR|DS|GT|MSR|TPA",  // short code
     "forum_category":    "Critical Reasoning",   // human label, or null
     "question_text":     "...",                  // null if not parseable
     "answer_choices":    {"A": "...", "B": "..."}, // null if none found
     "official_answer":   "B",                    // null if not stated
     "solutions":         [{"author": "...", "body_text": "...", ...}],
     "metadata":          {"n_posts": 7},
     "scrape_timestamp":  "2026-05-16T12:34:56Z", // UTC ISO 8601
     "parser_confidence": 0.8                     // fraction of expected fields hit, in [0,1]
   }
   ```

   Unparseable fields are emitted as JSON `null` — they are never
   fabricated and never silently turned into empty strings.
2. **`data/processed/gmat_frames_<SECTION>.jsonl`** — decision frames the
   trading code can consume as an entry/skip checklist
   (`scripts/gmat_scraper/reasoning_bridge.py`).

## What this module does NOT do

- It does **not** bypass authentication, paywalls, robots.txt, or
  Cloudflare-class anti-bot challenges.
- It does **not** execute trades, place orders, talk to a broker, or
  call any execution API. The `reasoning_bridge` is advisory-only — it
  emits checklist strings the trading code may *display* next to a
  candidate entry.
- It does **not** perform a bulk crawl by default. Every CLI invocation
  is scoped to an explicit section + page range.

## Read this first

- **Terms of Service.** GMAT Club's ToS restrict automated access. Check
  before running. The crawler is rate-limited and resumable by design;
  if you are not the rights holder for the content and you do not have
  permission, do not run it.
- **Anti-bot.** GMAT Club fronts the forum with Cloudflare-class
  protection. A naive run from a datacenter IP returns HTTP 403. You will
  likely need (a) a logged-in session cookie exported from a real browser
  to `cookies.txt` and (b) a residential IP / VPN. Without those, the
  scraper will retry, back off, and ultimately give up — that is the
  intended behavior.
- **Selectors are guesses.** Parsers in `parser.py` are written against
  phpBB v3 default markup. Once you have one real saved HTML page, open
  it next to `SELECTORS` at the top of `parser.py` and adjust any selector
  that returns empty. Tests in `tests/test_gmat_scraper.py` exercise the
  parser against synthetic fixtures, so they will pass even if the real
  selectors are off — treat real-page parsing as a separate
  acceptance step.

## Layout

```
tools/gmat_scraper/
  __init__.py
  sections.py           # PS/CR/DS/GT/MSR/TPA page counts
  http.py               # polite session, retries, cookie jar
  parser.py             # listing + thread parsers (TWEAK SELECTORS HERE)
  store.py              # resumable JSONL writer
  reasoning_bridge.py   # Problem JSONL → DecisionFrame JSONL
  cli.py                # python -m tools.gmat_scraper.cli ...
  README.md
```

> **Quarantine note.** This module is intentionally located under
> `tools/`, not `scripts/`, because it is *outside* the Sleeping Passenger
> private-operator MVP runtime surface (see
> `scripts/private_scope_guard.py`). It must never be imported by code
> under `scripts/` or `src/`. Adding any such import is a scope
> violation and will trip the private-scope-guard tests.

## Usage

```bash
# 1. Smoke test — fetch the first PS listing page, print topic URLs.
python -m tools.gmat_scraper.cli discover --section PS --pages 1

# 2. Small crawl — 3 CR pages, with a cookie jar.
python -m tools.gmat_scraper.cli crawl \
    --section CR --from-page 1 --to-page 3 \
    --delay 4 --cookies ~/gmatclub_cookies.txt

# 3. Resume — re-running the same command picks up where it left off
#    (URLs already in CR.jsonl are skipped).

# 4. Build decision frames for the trading engine.
python -m tools.gmat_scraper.cli bridge \
    --in  data/raw/gmat/CR.jsonl \
    --out data/processed/gmat_frames_CR.jsonl
```

## How the trading engine uses this

`reasoning_bridge.load_frames()` returns a list of `DecisionFrame` records,
and `reasoning_bridge.checklist_for_entry()` collapses them into a short
deduped checklist (default 6 rules, DS/CR prioritized) keyed off the
reasoning patterns the GMAT corpus exercises.

To wire it into a live entry flow, call `checklist_for_entry` next to your
existing entry gate and either log the rules alongside the candidate trade
or require an operator acknowledgement before sizing. This module
deliberately does not auto-block trades — the GMAT corpus does not
predict markets; it teaches *categories of doubt* (sufficiency,
assumption, paradox, etc.) that a disciplined entry has to survive.

## Estimated scale

`sections.total_problems_estimate()` returns ~74,000 problems across all
six sections. At a 4-second polite delay, end-to-end crawl time is on the
order of 80+ hours, plus thread-page requests. Plan to run incrementally
by section and page range, not in one shot.
