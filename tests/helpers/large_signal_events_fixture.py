"""Large ``signal_events`` performance fixture — temp/non-canonical DBs only.

The cockpit stress probe needs to prove its hot paths under a realistic
``signal_events`` row count (~122k).  Polluting the canonical runtime DB
(``runtime/mvp_local.db``) with synthetic fixture rows would corrupt operator
truth, so this helper *refuses* the canonical path and only writes to a
``tmp_path`` or an explicit ``runtime/perf_fixtures/`` DB clearly marked as
non-canonical.

Hard safety rules
-----------------
* The canonical runtime DB path is *refused* — caller gets ``ValueError``.
* Every fixture row carries the advisory safety stamps (``advisory_status``
  ``ADVISORY_ONLY``, ``execution_gate=LOCKED``, ``human_review_required=1``,
  ``ai_execution_count=0``).
* Every fixture row has an ``event_id`` prefixed ``PERF_FIXTURE_`` so the
  runtime truth-purity audit can detect a leak into canonical truth as
  pollution.
* A sidecar ``<db>.meta.json`` documents the role, derivation, and the
  ``safe_to_delete=true`` invariant.
* Inserts are deterministic (fixed seed) and batched (``executemany``) so the
  full 122k generation is fast and bounded.

Nothing here calls a broker, performs execution, or modifies the canonical
runtime DB.  Read-only with respect to operator truth.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_RUNTIME_DB = REPO_ROOT / "runtime" / "mvp_local.db"
PERF_FIXTURE_DIR = REPO_ROOT / "runtime" / "perf_fixtures"

# Hard cap so a typo can never spin up a multi-million-row fixture by accident.
DEFAULT_ROW_COUNT = 122_000
MAX_ROW_COUNT = 250_000
MAX_ROW_COUNT_ALLOW_LARGE = 500_000

# A stable event-id prefix so a leaked synthetic row is obvious if it ever
# turns up in the canonical DB.  The runtime truth-purity audit treats this
# prefix as pollution.
FIXTURE_EVENT_ID_PREFIX = "PERF_FIXTURE_"
FIXTURE_ROLE = "synthetic_performance_fixture"

# Bounded vocabulary for synthetic rows — small enough to stay deterministic,
# wide enough to exercise grouped reads (signal_events_count_by_source) and
# per-source filters (signal_events_by_source).
DEFAULT_SOURCE_NAMES: tuple[str, ...] = (
    "rss", "polymarket", "market_data", "news_filings", "x_stream",
    "filings", "earnings_calendar", "twitter", "discord", "telegram",
)
DEFAULT_TICKERS: tuple[str, ...] = (
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "GOOGL", "AMZN",
    "META", "NFLX", "AVGO", "ORCL", "CRM", "ADBE",
)


class FixtureRefusalError(ValueError):
    """Raised when a fixture helper is asked to touch the canonical runtime DB."""


def _refuse_canonical(db_path: Path) -> None:
    """Hard-stop if ``db_path`` resolves to the canonical runtime DB.

    We resolve both paths to absolute form so a relative ``runtime/mvp_local.db``
    or a symlink cannot sneak through.  This check is the single most important
    safety invariant in this module — without it the fixture could silently
    seed 122k synthetic rows into operator truth.
    """
    try:
        resolved = db_path.expanduser().resolve()
    except OSError:
        resolved = db_path
    try:
        canonical = CANONICAL_RUNTIME_DB.expanduser().resolve()
    except OSError:
        canonical = CANONICAL_RUNTIME_DB
    if resolved == canonical:
        raise FixtureRefusalError(
            f"refuse_to_pollute_canonical_runtime_db: db_path={db_path} "
            f"resolves to the canonical runtime DB ({canonical}). The "
            "large signal_events fixture is non-canonical and must never "
            "seed runtime/mvp_local.db. Use tmp_path or runtime/perf_fixtures/."
        )


def _bound_row_count(row_count: int, *, allow_large_local_test: bool) -> int:
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")
    ceiling = MAX_ROW_COUNT_ALLOW_LARGE if allow_large_local_test else MAX_ROW_COUNT
    if row_count > ceiling:
        raise ValueError(
            f"row_count={row_count} exceeds bound {ceiling} "
            f"(allow_large_local_test={allow_large_local_test})"
        )
    return row_count


def _create_schema(conn: sqlite3.Connection) -> None:
    """Recreate the *canonical* ``signal_events`` schema verbatim.

    Kept in lock-step with ``scripts.persistence.SCHEMA_SQL`` for signal_events.
    Adds the same two indexes that production uses so the probe exercises an
    indexed path.  Also creates a tiny advisory ``_perf_fixture_metadata``
    table so an audit of the fixture DB can see at a glance that it is
    synthetic — this table NEVER appears in the canonical runtime DB.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            source_name TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
            human_review_required INTEGER NOT NULL DEFAULT 1,
            execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
            ai_execution_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS _perf_fixture_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_se_source ON signal_events(source_name);
        CREATE INDEX IF NOT EXISTS idx_se_fetched ON signal_events(fetched_at);
        """
    )


def _row_iter(
    row_count: int,
    tickers: tuple[str, ...],
    source_names: tuple[str, ...],
    seed: int,
):
    """Yield ``(event_id, source_name, raw_payload, fetched_at, …safety)`` tuples.

    Deterministic — same seed produces the same fixture every time.  Timestamps
    are distributed over the last 14 days (1.2s steps so 122k rows span the
    window) so percentile / range queries are realistic.
    """
    rng = random.Random(seed)
    now = int(time.time())
    window_seconds = 14 * 24 * 3600
    step = max(1.0, window_seconds / row_count)
    for i in range(row_count):
        ticker = tickers[i % len(tickers)]
        source = source_names[rng.randrange(len(source_names))]
        # Step backwards through the window with a tiny jitter so multiple rows
        # never share a fetched_at while the overall distribution is dense.
        offset = step * i + rng.uniform(0, step)
        ts = now - int(offset)
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        event_id = f"{FIXTURE_EVENT_ID_PREFIX}{i:07d}_{ticker}"
        # Compact JSON payload — keeps each row small (a few hundred bytes) so
        # the 122k fixture stays around a few tens of MB on disk.
        payload = json.dumps(
            {
                "ticker": ticker,
                "fixture_role": FIXTURE_ROLE,
                "derived_non_canonical": True,
                "i": i,
            },
            separators=(",", ":"),
        )
        yield (event_id, source, payload, fetched_at,
               "ADVISORY_ONLY", 1, "LOCKED", 0)


def _write_sidecar_metadata(
    db_path: Path,
    *,
    row_count: int,
    create_indexes: bool,
    seed: int,
    creation_seconds: float,
) -> Path:
    """Write ``<db_path>.meta.json`` next to the fixture DB.

    The sidecar is the durable evidence that this DB is *non-canonical*; the
    stress probe reads it to surface ``fixture_role``/``derived_non_canonical``
    in its report.  Keys mirror the prompt's required metadata contract.
    """
    meta = {
        "report": "large_signal_events_fixture_metadata",
        "fixture_db_path": str(db_path),
        "fixture_role": FIXTURE_ROLE,
        "schema": "signal_events",
        "row_count": row_count,
        "create_indexes": create_indexes,
        "seed": seed,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "creation_seconds": round(creation_seconds, 3),
        # Hard non-canonical invariants — the audit / probe / release gate all
        # rely on these keys.
        "canonical_truth_source": "sqlite_runtime_not_used",
        "derived_non_canonical": True,
        "safe_to_delete": True,
        "runtime_db_polluted": False,
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
    }
    sidecar = db_path.with_suffix(db_path.suffix + ".meta.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return sidecar


def create_large_signal_events_db(
    db_path: Path,
    *,
    row_count: int = DEFAULT_ROW_COUNT,
    tickers: list[str] | tuple[str, ...] | None = None,
    source_names: list[str] | tuple[str, ...] | None = None,
    create_indexes: bool = True,
    seed: int = 0xC0FFEE,
    batch_size: int = 5_000,
    allow_large_local_test: bool = False,
) -> Path:
    """Create a non-canonical signal_events fixture DB and return its path.

    Refuses the canonical runtime DB.  Bounded row count, batched inserts,
    deterministic content.  Writes a sidecar ``.meta.json`` alongside the DB
    so the non-canonical role is durable and machine-readable.
    """
    db_path = Path(db_path)
    _refuse_canonical(db_path)
    row_count = _bound_row_count(row_count, allow_large_local_test=allow_large_local_test)

    tickers_t = tuple(tickers) if tickers else DEFAULT_TICKERS
    sources_t = tuple(source_names) if source_names else DEFAULT_SOURCE_NAMES
    if not tickers_t:
        raise ValueError("tickers must be non-empty")
    if not sources_t:
        raise ValueError("source_names must be non-empty")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Start clean so re-running the helper is idempotent for tests.
    if db_path.exists():
        db_path.unlink()

    t0 = time.perf_counter()
    conn = sqlite3.connect(str(db_path))
    try:
        # Pragmas only on the fixture DB.  These NEVER touch the canonical
        # runtime DB because we refused that path above.
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        _create_schema(conn)
        # Stamp the in-DB metadata table.  This is what the runtime truth audit
        # uses to immediately recognise a leaked fixture if one ever appeared
        # in the canonical runtime DB.
        conn.executemany(
            "INSERT OR REPLACE INTO _perf_fixture_metadata (key, value) VALUES (?, ?)",
            (
                ("fixture_role", FIXTURE_ROLE),
                ("derived_non_canonical", "true"),
                ("safe_to_delete", "true"),
                ("runtime_db_polluted", "false"),
                ("canonical_truth_source", "sqlite_runtime_not_used"),
                ("schema", "signal_events"),
                ("row_count", str(row_count)),
                ("seed", hex(seed)),
                ("advisory_only", "true"),
                ("execution_gate", _contract.EXECUTION_GATE_LOCKED),
                ("broker_api_called", "false"),
                ("ai_execution_count", str(_contract.AI_EXECUTION_COUNT)),
            ),
        )
        conn.commit()

        # Bulk insert in transaction batches.  ``executemany`` with a single
        # commit per batch is the only way to get 122k rows in under a few
        # seconds on a laptop.
        insert_sql = (
            "INSERT INTO signal_events "
            "(event_id, source_name, raw_payload, fetched_at, "
            " advisory_status, human_review_required, execution_gate, ai_execution_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        batch: list[tuple] = []
        for tup in _row_iter(row_count, tickers_t, sources_t, seed):
            batch.append(tup)
            if len(batch) >= batch_size:
                conn.executemany(insert_sql, batch)
                conn.commit()
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
            conn.commit()

        if create_indexes:
            _create_indexes(conn)
            conn.commit()
        # Bound-check: the row count actually written matches what was asked.
        # A mismatch (e.g. UNIQUE collision) would silently produce a smaller
        # fixture and a misleading "122k proof", so we fail loudly.
        actual = conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
        if actual != row_count:
            raise RuntimeError(
                f"fixture_row_count_mismatch: requested {row_count} but wrote "
                f"{actual} rows — refusing to claim a 122k proof on a smaller "
                "fixture."
            )
    finally:
        conn.close()

    elapsed = time.perf_counter() - t0
    _write_sidecar_metadata(
        db_path,
        row_count=row_count,
        create_indexes=create_indexes,
        seed=seed,
        creation_seconds=elapsed,
    )
    return db_path


def read_sidecar_metadata(db_path: Path) -> dict[str, Any] | None:
    """Return the sidecar metadata, or None if absent / unreadable."""
    sidecar = db_path.with_suffix(db_path.suffix + ".meta.json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


__all__ = [
    "CANONICAL_RUNTIME_DB",
    "PERF_FIXTURE_DIR",
    "DEFAULT_ROW_COUNT",
    "MAX_ROW_COUNT",
    "MAX_ROW_COUNT_ALLOW_LARGE",
    "FIXTURE_EVENT_ID_PREFIX",
    "FIXTURE_ROLE",
    "DEFAULT_SOURCE_NAMES",
    "DEFAULT_TICKERS",
    "FixtureRefusalError",
    "create_large_signal_events_db",
    "read_sidecar_metadata",
]
