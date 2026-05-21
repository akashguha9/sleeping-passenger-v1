import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests")
    print("Run: python -m pip install requests")
    raise

DEFAULT_ENDPOINTS = [
    "http://127.0.0.1:8000/api/manual-trades",
    "http://127.0.0.1:8000/manual-trades",
    "http://127.0.0.1:8000/api/manual-trade-log",
    "http://127.0.0.1:8000/manual-trade-log",
    "http://127.0.0.1:8000/api/manual_trade_log",
    "http://127.0.0.1:8000/manual_trade_log",
]

FORBIDDEN_MARKERS = [
    "paper",
    "probe",
    "testing",
    "test",
    "fake",
    "dummy",
    "sample",
]

REQUIRED_FIELDS = [
    "signal_event_id",
    "ticker",
    "direction",
    "quantity",
    "price",
    "leverage",
    "currency",
    "thesis",
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "mistake_tags",
    "lesson_takeaway",
    "ai_model_used",
    "notes",
]

def load_entries(path: Path, trade_date: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if trade_date not in data:
        available = ", ".join(sorted(data.keys()))
        raise KeyError(f"No entries found for {trade_date}. Available dates: {available}")
    entries = data[trade_date]
    if not isinstance(entries, list):
        raise ValueError(f"Date block {trade_date} must be a list.")
    return entries

def validate_entry(entry: dict) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in entry]
    if missing:
        raise ValueError(f"{entry.get('ticker', 'UNKNOWN')} missing fields: {missing}")

    joined = json.dumps(entry, ensure_ascii=False).lower()
    hits = []
    for marker in FORBIDDEN_MARKERS:
        if re.search(rf"\b{re.escape(marker)}\b", joined):
            hits.append(marker)
    if hits:
        raise ValueError(
            f"{entry.get('ticker', 'UNKNOWN')} blocked locally. Forbidden marker(s): {hits}"
        )

def endpoint_candidates(user_endpoint: str | None) -> list[str]:
    if user_endpoint:
        return [user_endpoint]
    env_endpoint = os.getenv("MANUAL_TRADE_ENDPOINT")
    if env_endpoint:
        return [env_endpoint]
    return DEFAULT_ENDPOINTS

def submit_one(endpoint: str, entry: dict) -> tuple[bool, str]:
    payload = dict(entry)

    # Backend expects event_id, not signal_event_id
    if "signal_event_id" in payload and "event_id" not in payload:
        payload["event_id"] = payload.pop("signal_event_id")

    try:
        response = requests.post(endpoint, json=payload, timeout=20)
    except requests.RequestException as exc:
        return False, f"REQUEST ERROR: {exc}"

    if 200 <= response.status_code < 300:
        return True, f"{response.status_code}: {response.text[:500]}"

    return False, f"{response.status_code}: {response.text[:1500]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-18")
    parser.add_argument("--file", default="data/manual_trades_by_date.json")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-all-endpoint-tries", action="store_true",
                        help="Try common endpoints until one accepts the first record. Stops after first successful endpoint.")
    args = parser.parse_args()

    entries = load_entries(Path(args.file), args.date)

    print(f"Date: {args.date}")
    print(f"Entries loaded: {len(entries)}")
    print(f"File: {args.file}")
    print(f"Dry run: {args.dry_run}")
    print()

    for entry in entries:
        validate_entry(entry)

    if args.dry_run:
        for entry in entries:
            print(f"DRY RUN OK: {entry['ticker']}")
        print("\nDONE: validation passed for all entries.")
        return 0

    candidates = endpoint_candidates(args.endpoint)
    if not args.allow_all_endpoint_tries and args.endpoint is None and os.getenv("MANUAL_TRADE_ENDPOINT") is None:
        print("No endpoint explicitly supplied.")
        print("Either pass --endpoint or set MANUAL_TRADE_ENDPOINT.")
        print("Example:")
        print('  $env:MANUAL_TRADE_ENDPOINT="http://127.0.0.1:8000/YOUR-ACTUAL-POST-URL"')
        print("  python scripts\\bulk_log_manual_trades.py --date 2026-05-18")
        print()
        print("Or use common endpoint probing:")
        print("  python scripts\\bulk_log_manual_trades.py --date 2026-05-18 --allow-all-endpoint-tries")
        return 2

    chosen_endpoint = None
    if args.allow_all_endpoint_tries and args.endpoint is None and os.getenv("MANUAL_TRADE_ENDPOINT") is None:
        first = entries[0]
        print("Trying common endpoints with FIRST entry only...")
        for candidate in candidates:
            ok, msg = submit_one(candidate, first)
            print(f"{candidate} -> {'OK' if ok else 'FAIL'} {msg[:300]}")
            if ok:
                chosen_endpoint = candidate
                break
        if not chosen_endpoint:
            print("\nNo common endpoint accepted the first entry.")
            print("Use browser F12 > Network > submit one form > copy Request URL, then run with --endpoint.")
            return 1
        remaining_entries = entries[1:]
        successes = 1
        failures = 0
        print(f"\nChosen endpoint: {chosen_endpoint}")
        print(f"First entry already submitted: {first['ticker']}")
    else:
        chosen_endpoint = candidates[0]
        remaining_entries = entries
        successes = 0
        failures = 0
        print(f"Using endpoint: {chosen_endpoint}")

    for entry in remaining_entries:
        ok, msg = submit_one(chosen_endpoint, entry)
        if ok:
            print(f"OK: {entry['ticker']} -> {msg[:300]}")
            successes += 1
        else:
            print(f"FAILED: {entry['ticker']} -> {msg[:500]}")
            failures += 1
        time.sleep(0.25)

    print()
    print("DONE")
    print(f"Successes: {successes}")
    print(f"Failures: {failures}")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())