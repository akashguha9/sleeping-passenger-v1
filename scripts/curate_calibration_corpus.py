"""Curate the calibration corpus.

Calibration Corpus + Hosted Canary sprint, Phase 1.

Purpose
-------
Build a provenance-valid, deduplicated JSON corpus of closed outcome
records so the calibration gate (``scripts.calibration_report``) can run
on real evidence rather than fabricated samples.  When real evidence is
insufficient the corpus is still emitted truthfully so the gate reports
``INSUFFICIENT_EVIDENCE`` rather than silently faking a number.

Sources, in priority order
~~~~~~~~~~~~~~~~~~~~~~~~~~

A. Existing closed manual / paper trades in ``runtime/mvp_local.db``
   joined to ``reconciliation_results``.  Only rows whose
   ``created_via`` is not ``quarantined_fake_manual_trade`` and whose
   reconciliation ``outcome_status`` is ``WIN`` or ``LOSS`` are
   considered.  These trades carry no historical
   ``model_probability``: they are recorded as ``source=manual_trade``
   provenance-truthful records that DO NOT count toward calibration
   math (``model_probability`` is omitted).  They are useful evidence
   for the corpus, but the calibration gate only uses records that
   carry both a ``model_probability`` and an ``outcome_label``.

B. Public, read-only Polymarket closed markets, ONLY when the
   ``--include-polymarket-closed`` flag is set.  The pre-resolution
   ``last_trade_price`` serves as the implied ``model_probability`` and
   the resolved outcome supplies ``outcome_label``.  GET-only, no
   credentials, hard short timeout, redaction on logs.

C. Test fixtures (``--from-fixture <path>``) labelled
   ``source=fixture_test_only``.  These NEVER count toward ``N_real``.

What is NEVER produced here
~~~~~~~~~~~~~~~~~~~~~~~~~~~
* No broker / order / fill / position / execution row.
* No mock or fallback row is silently promoted: every record carries a
  truthful ``provenance.mock_fallback`` / ``provenance.fallback_used``
  flag.
* No fabricated outcome.  If a row's outcome is unknown it is dropped.

Hard safety
~~~~~~~~~~~
* Advisory-only stamps on every record.
* ``execution_gate=LOCKED``, ``broker_api_called=False``,
  ``ai_execution_count=0``.
* External requests are GET-only with an 8-second timeout and a
  redaction filter on every logged URL / error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

CORPUS_SOURCES: tuple[str, ...] = (
    "manual_trade",
    "paper_trade",
    "polymarket_closed",
    "kalshi_closed",
    "fixture_test_only",
)

_HTTP_TIMEOUT_SEC = 8
_USER_AGENT = "sleeping-passenger-mvp/corpus (advisory-only)"
_POLYMARKET_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


@dataclass
class CorpusRecord:
    record_id: str
    source: str
    source_record_id: str
    asset_or_market: str
    signal_timestamp_utc: str
    outcome_timestamp_utc: str
    horizon_days: float
    score_snapshot: dict[str, Any] = field(default_factory=dict)
    outcome_label: int = 0
    outcome_definition: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "record_id": self.record_id,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "asset_or_market": self.asset_or_market,
            "signal_timestamp_utc": self.signal_timestamp_utc,
            "outcome_timestamp_utc": self.outcome_timestamp_utc,
            "horizon_days": float(self.horizon_days),
            "score_snapshot": dict(self.score_snapshot),
            "outcome_label": int(self.outcome_label),
            "outcome_definition": str(self.outcome_definition),
            "provenance": dict(self.provenance),
        }
        out.update(SAFETY_STAMPS)
        return out


def stable_dedupe_key(record: dict[str, Any]) -> str:
    """Compute the stable SHA-256 dedupe key documented in the sprint spec.

    ``sha256(source | source_record_id | asset_or_market |
    signal_timestamp_utc | outcome_timestamp_utc | outcome_definition)``
    with each component lower-cased where the spec says so.
    """
    parts = [
        str(record.get("source", "")).strip().lower(),
        str(record.get("source_record_id", "")).strip().lower(),
        str(record.get("asset_or_market", "")).strip().lower(),
        str(record.get("signal_timestamp_utc", "")).strip(),
        str(record.get("outcome_timestamp_utc", "")).strip(),
        str(record.get("outcome_definition", "")).strip().lower(),
    ]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\b[A-Za-z0-9_\-]{16,}\b", "<redacted>", text)


# ---------------------------------------------------------------------------
# Validity helpers
# ---------------------------------------------------------------------------


def _is_real_source(rec: dict[str, Any]) -> bool:
    source = str(rec.get("source", "")).strip().lower()
    if source == "fixture_test_only":
        return False
    prov = rec.get("provenance", {}) or {}
    if prov.get("mock_fallback") or prov.get("fallback_used"):
        return False
    return True


def _has_valid_probability(rec: dict[str, Any]) -> bool:
    snap = rec.get("score_snapshot", {}) or {}
    if "model_probability" not in snap:
        return False
    p = snap.get("model_probability")
    try:
        p = float(p)
    except (TypeError, ValueError):
        return False
    if p != p:  # NaN
        return False
    if p == float("inf") or p == float("-inf"):
        return False
    return 0.0 <= p <= 1.0


def _has_valid_outcome(rec: dict[str, Any]) -> bool:
    return rec.get("outcome_label") in (0, 1)


def _has_p_and_y(rec: dict[str, Any]) -> bool:
    return _has_valid_probability(rec) and _has_valid_outcome(rec) and _is_real_source(rec)


def validate_corpus(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute the spec mathematics for a corpus collection.

    Returns the n_total / n_real / n_fixture / n_mock / n_valid_p /
    n_valid_y / n_deduped scalars plus the derived
    ``corpus_validity``, ``corpus_coverage_score``, ``evidence_status``
    fields.  Also reports ``n_pairs`` (records with both ``p_i`` and
    ``y_i`` from a real source), ``base_rate``, ``class_imbalance``, and
    a string ``class_balance_warning`` consumed by the calibration gate.
    Pure function — no I/O.
    """
    records_list = list(records)
    n_total = len(records_list)
    n_fixture = sum(1 for r in records_list if str(r.get("source", "")).lower() == "fixture_test_only")
    n_mock = sum(
        1
        for r in records_list
        if (r.get("provenance", {}) or {}).get("mock_fallback")
        or (r.get("provenance", {}) or {}).get("fallback_used")
    )
    n_real = sum(1 for r in records_list if _is_real_source(r))
    n_valid_p = sum(1 for r in records_list if _has_valid_probability(r))
    n_valid_y = sum(1 for r in records_list if _has_valid_outcome(r))
    n_deduped = len({stable_dedupe_key(r) for r in records_list})
    n_pairs = sum(1 for r in records_list if _has_p_and_y(r))

    # Class balance computed over real (p, y) pairs only.  Without pairs
    # the metric is undefined; emit None rather than fabricate.
    if n_pairs > 0:
        positives = sum(
            1
            for r in records_list
            if _has_p_and_y(r) and int(r.get("outcome_label", 0)) == 1
        )
        base_rate = positives / float(n_pairs)
        class_imbalance = abs(base_rate - (1.0 - base_rate))
        if class_imbalance > 0.7:
            class_balance_warning = "HIGH_CLASS_IMBALANCE"
        else:
            class_balance_warning = "OK"
    else:
        base_rate = None
        class_imbalance = None
        class_balance_warning = "NO_PAIRS"

    n_min = 200
    validity = (
        n_real >= n_min
        and n_mock == 0
        and n_valid_p == n_total
        and n_valid_y == n_total
        and n_deduped == n_total
    )
    coverage_score = min(10.0, 10.0 * n_real / float(n_min))
    evidence_status = "MEASURABLE" if n_real >= n_min else "INSUFFICIENT_EVIDENCE"

    return {
        "n_total": n_total,
        "n_real": n_real,
        "n_fixture": n_fixture,
        "n_mock": n_mock,
        "n_valid_p": n_valid_p,
        "n_valid_y": n_valid_y,
        "n_deduped": n_deduped,
        "n_pairs": n_pairs,
        "n_min": n_min,
        "corpus_validity": bool(validity),
        "corpus_coverage_score": round(coverage_score, 6),
        "evidence_status": evidence_status,
        "base_rate": (round(base_rate, 6) if base_rate is not None else None),
        "class_imbalance": (
            round(class_imbalance, 6) if class_imbalance is not None else None
        ),
        "class_balance_warning": class_balance_warning,
    }


def dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate records, keeping the first occurrence of each
    stable key.  Preserves ordering.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for rec in records:
        key = stable_dedupe_key(rec)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Source A — local SQLite manual trades + reconciliations
# ---------------------------------------------------------------------------


def _outcome_label_from_status(status: str) -> int | None:
    s = str(status or "").strip().upper()
    if s == "WIN":
        return 1
    if s == "LOSS":
        return 0
    return None


def _fetch_probability_snapshots(
    cur: Any,
) -> dict[str, dict[str, Any]]:
    """Return ``{event_id: snapshot_dict}`` from the probability_snapshots
    table if it exists.  Empty mapping when the table is absent.
    """
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='probability_snapshots'"
        )
        if cur.fetchone() is None:
            return {}
        cur.execute(
            "SELECT signal_id, model_probability, EMS, EQS, DS, LS, EFS, APS, "
            "raw_score, chaos_risk, staleness_penalty, mock_penalty, "
            "probability_formula_version, generated_at_utc "
            "FROM probability_snapshots"
        )
        out: dict[str, dict[str, Any]] = {}
        for row in cur.fetchall():
            (
                signal_id,
                p,
                ems,
                eqs,
                ds,
                ls,
                efs,
                aps,
                raw_score,
                chaos,
                stale,
                mock,
                version,
                generated_at,
            ) = row
            out[str(signal_id)] = {
                "model_probability": float(p) if p is not None else None,
                "EMS": float(ems) if ems is not None else None,
                "EQS": float(eqs) if eqs is not None else None,
                "DS": float(ds) if ds is not None else None,
                "LS": float(ls) if ls is not None else None,
                "EFS": float(efs) if efs is not None else None,
                "APS": float(aps) if aps is not None else None,
                "raw_score": float(raw_score) if raw_score is not None else None,
                "chaos_risk": float(chaos) if chaos is not None else None,
                "staleness_penalty": float(stale) if stale is not None else None,
                "mock_penalty": float(mock) if mock is not None else None,
                "probability_formula_version": str(version or ""),
                "generated_at_utc": str(generated_at or ""),
            }
        return out
    except Exception:  # pragma: no cover — defensive against schema drift
        return {}


def gather_from_sqlite(db_path: Path) -> list[dict[str, Any]]:
    """Pull closed manual trades + reconciliations from SQLite.

    Filters
    -------
    * ``manual_trades.created_via`` MUST NOT be
      ``"quarantined_fake_manual_trade"``.
    * ``reconciliation_results.outcome_status`` MUST be ``WIN`` or
      ``LOSS``.

    Emits ``source="manual_trade"`` records.  When a matching
    ``probability_snapshots`` row exists for ``manual_trades.event_id``,
    the snapshot's ``model_probability`` is attached and the trade
    becomes a calibration pair (``p_i``, ``y_i``).  Trades without a
    matching snapshot are still emitted for provenance but carry no
    ``model_probability`` — the calibration gate's math layer excludes
    them automatically.
    """
    import sqlite3

    db = Path(db_path)
    if not db.exists():
        return []
    out: list[dict[str, Any]] = []
    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        snapshots = _fetch_probability_snapshots(cur)
        cur.execute(
            """
            SELECT mt.trade_id, mt.event_id, mt.ticker, mt.executed_at,
                   mt.created_via, rr.outcome_status, rr.reconciled_at
            FROM manual_trades mt
            JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id
            WHERE mt.created_via != 'quarantined_fake_manual_trade'
              AND rr.outcome_status IN ('WIN', 'LOSS')
            """
        )
        rows = cur.fetchall()
    finally:
        con.close()

    for row in rows:
        trade_id, event_id, ticker, executed_at, created_via, status, reconciled_at = row
        label = _outcome_label_from_status(status)
        if label is None:
            continue
        signal_ts = str(executed_at or "")
        outcome_ts = str(reconciled_at or signal_ts or "")
        try:
            sdt = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
            odt = datetime.fromisoformat(outcome_ts.replace("Z", "+00:00"))
            horizon = max(0.0, (odt - sdt).total_seconds() / 86400.0)
        except Exception:
            horizon = 0.0
        # Bridge: when probability_snapshots has a row for this signal,
        # attach the snapshot so the trade becomes a calibration pair.
        snap = snapshots.get(str(event_id) or "")
        if snap is None:
            snap = {}
        score_snapshot: dict[str, Any] = {
            "EMS": snap.get("EMS"),
            "EQS": snap.get("EQS"),
            "DS": snap.get("DS"),
            "LS": snap.get("LS"),
            "EFS": snap.get("EFS"),
            "APS": snap.get("APS"),
        }
        if snap.get("model_probability") is not None:
            p_val = snap["model_probability"]
            try:
                p_float = float(p_val)
            except (TypeError, ValueError):
                p_float = None
            if (
                p_float is not None
                and not math_is_invalid(p_float)
                and 0.0 <= p_float <= 1.0
            ):
                score_snapshot["model_probability"] = round(p_float, 6)
        provenance = {
            "truth_source": "sqlite",
            "canonical": True,
            "mock_fallback": False,
            "fallback_used": False,
            "url_or_source_hint_redacted": "runtime/mvp_local.db:manual_trades+reconciliation_results",
            "collected_at_utc": _utc_now_iso(),
            "created_via": str(created_via or ""),
        }
        if snap:
            provenance["bridged_from_probability_snapshot"] = True
            provenance["probability_formula_version"] = snap.get(
                "probability_formula_version", ""
            )
            provenance["snapshot_generated_at_utc"] = snap.get(
                "generated_at_utc", ""
            )
        rec = CorpusRecord(
            record_id=f"mt:{trade_id}",
            source="manual_trade",
            source_record_id=str(trade_id),
            asset_or_market=str(ticker or event_id or ""),
            signal_timestamp_utc=signal_ts,
            outcome_timestamp_utc=outcome_ts,
            horizon_days=round(horizon, 4),
            score_snapshot=score_snapshot,
            outcome_label=int(label),
            outcome_definition="manual_trade_reconciliation_win_loss",
            provenance=provenance,
        )
        out.append(rec.to_dict())
    return out


def math_is_invalid(value: float) -> bool:
    """True when ``value`` is NaN or infinite."""
    import math

    return math.isnan(value) or math.isinf(value)


# ---------------------------------------------------------------------------
# Source B — Polymarket public closed markets (opt-in only)
# ---------------------------------------------------------------------------


def _fetch_polymarket_closed_page(limit: int, offset: int) -> list[dict[str, Any]]:
    try:
        import requests  # noqa: WPS433 — lazy import
    except ImportError:  # pragma: no cover — env-dependent
        return []
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    params = {
        "closed": "true",
        "limit": str(int(limit)),
        "offset": str(int(offset)),
        "order": "endDate",
        "ascending": "false",
    }
    try:
        resp = requests.get(
            _POLYMARKET_MARKETS_URL,
            headers=headers,
            params=params,
            timeout=_HTTP_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(_redact(f"polymarket fetch error: {type(exc).__name__}\n"))
        return []
    if resp.status_code not in (200, 204):
        sys.stderr.write(_redact(f"polymarket http status={resp.status_code}\n"))
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    if isinstance(body, list):
        return [m for m in body if isinstance(m, dict)]
    return []


def gather_from_polymarket_closed(max_records: int) -> list[dict[str, Any]]:
    """Public read-only Polymarket closed markets.

    Only called when the operator explicitly opts in.  GET-only, no
    credentials, no order/balance/fills calls.  Returns at most
    ``max_records`` records.  Any single failed page returns an empty
    list rather than raising — the curate run still emits whatever has
    been collected so far.
    """
    collected: list[dict[str, Any]] = []
    page_size = min(100, max(10, int(max_records)))
    offset = 0
    seen_ids: set[str] = set()
    while len(collected) < max_records:
        page = _fetch_polymarket_closed_page(page_size, offset)
        if not page:
            break
        progressed = False
        for market in page:
            market_id = str(market.get("id") or market.get("conditionId") or "").strip()
            if not market_id or market_id in seen_ids:
                continue
            seen_ids.add(market_id)
            rec = _polymarket_market_to_record(market)
            if rec is None:
                continue
            collected.append(rec)
            progressed = True
            if len(collected) >= max_records:
                break
        offset += len(page)
        if not progressed:
            break
    return collected


def _polymarket_market_to_record(market: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a Polymarket closed-market dict into a CorpusRecord-shaped dict.

    Skips markets that are non-binary, lack a resolved outcome, or lack
    an implied probability we can use as ``model_probability``.
    """
    market_id = str(market.get("id") or market.get("conditionId") or "").strip()
    if not market_id:
        return None

    # Outcome label — the resolved binary outcome.
    raw_outcome = (
        market.get("outcomePrices")
        or market.get("outcome_prices")
        or market.get("outcomes")
        or []
    )
    label: int | None = None
    if isinstance(raw_outcome, list) and len(raw_outcome) == 2:
        try:
            first = float(raw_outcome[0])
            second = float(raw_outcome[1])
            if (first, second) == (1.0, 0.0):
                label = 1
            elif (first, second) == (0.0, 1.0):
                label = 0
        except (TypeError, ValueError):
            label = None
    if label is None:
        return None

    # Implied probability — last_trade_price for the YES outcome.
    p_raw = (
        market.get("lastTradePrice")
        or market.get("last_trade_price")
        or market.get("yesPrice")
        or market.get("clobPrice")
    )
    try:
        p_val = float(p_raw)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p_val <= 1.0):
        return None

    signal_ts = str(market.get("createdAt") or market.get("startDate") or "")
    outcome_ts = str(market.get("endDate") or market.get("end_date") or "")
    try:
        sdt = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
        odt = datetime.fromisoformat(outcome_ts.replace("Z", "+00:00"))
        horizon = max(0.0, (odt - sdt).total_seconds() / 86400.0)
    except Exception:
        horizon = 0.0

    question = str(market.get("question") or market.get("slug") or market_id)
    rec = CorpusRecord(
        record_id=f"poly:{market_id}",
        source="polymarket_closed",
        source_record_id=market_id,
        asset_or_market=question[:240],
        signal_timestamp_utc=signal_ts,
        outcome_timestamp_utc=outcome_ts,
        horizon_days=round(horizon, 4),
        score_snapshot={
            "EMS": None,
            "EQS": None,
            "DS": None,
            "LS": None,
            "EFS": None,
            "APS": None,
            "model_probability": round(p_val, 6),
        },
        outcome_label=int(label),
        outcome_definition="polymarket_binary_yes_resolved",
        provenance={
            "truth_source": "public_api",
            "canonical": False,
            "mock_fallback": False,
            "fallback_used": False,
            "url_or_source_hint_redacted": "gamma-api.polymarket.com/markets?closed=true",
            "collected_at_utc": _utc_now_iso(),
        },
    )
    return rec.to_dict()


# ---------------------------------------------------------------------------
# Source C — fixtures (test-only)
# ---------------------------------------------------------------------------


def load_fixture_records(fixture_path: Path) -> list[dict[str, Any]]:
    """Load a JSON list of pre-built corpus records and mark each as
    ``source="fixture_test_only"``.  Used by tests and never counted as
    real evidence in the math layer.
    """
    p = Path(fixture_path)
    if not p.exists():
        return []
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(body, list):
        return []
    out: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        rec = dict(item)
        rec["source"] = "fixture_test_only"
        rec.setdefault("provenance", {})
        rec["provenance"]["truth_source"] = "test_fixture"
        rec["provenance"].setdefault("mock_fallback", False)
        rec["provenance"].setdefault("fallback_used", False)
        rec.update(SAFETY_STAMPS)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Build pipeline + CLI
# ---------------------------------------------------------------------------


def build_corpus(
    *,
    from_sqlite: Path | None,
    include_polymarket_closed: bool,
    from_fixture: Path | None,
    max_records: int,
) -> dict[str, Any]:
    """Run the curation pipeline.  Returns the corpus envelope dict.

    Caller decides whether to write the envelope; pure function w.r.t.
    side effects (the requests path is gated by
    ``include_polymarket_closed``).
    """
    pulled: list[dict[str, Any]] = []
    sources_used: list[str] = []
    if from_sqlite is not None:
        rows = gather_from_sqlite(from_sqlite)
        if rows:
            sources_used.append(f"sqlite:{from_sqlite}")
        pulled.extend(rows)
    if include_polymarket_closed:
        rows = gather_from_polymarket_closed(max_records=max_records)
        if rows:
            sources_used.append("polymarket_closed_public")
        pulled.extend(rows)
    if from_fixture is not None:
        rows = load_fixture_records(from_fixture)
        if rows:
            sources_used.append(f"fixture:{from_fixture}")
        pulled.extend(rows)

    # Enforce dedupe at the corpus level so the math layer can assume it.
    deduped = dedupe_records(pulled)
    if len(deduped) > max_records:
        deduped = deduped[:max_records]

    metrics = validate_corpus(deduped)
    envelope: dict[str, Any] = {
        "script": "curate_calibration_corpus.py",
        "generated_at_utc": _utc_now_iso(),
        "sources_used": sources_used,
        "metrics": metrics,
        "records": deduped,
    }
    envelope.update(SAFETY_STAMPS)
    return envelope


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Curate the calibration corpus from local SQLite, optional "
            "public Polymarket closed markets, and/or a test fixture.  "
            "Advisory-only.  GET-only on external sources.  No fabrication."
        )
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Default.  Build the envelope in memory but do not write.")
    parser.add_argument("--write", action="store_true",
                        help="Persist the envelope to --output (overrides --dry-run).")
    parser.add_argument(
        "--from-sqlite",
        type=Path,
        default=None,
        help="Path to SQLite DB.  Typical: runtime/mvp_local.db.",
    )
    parser.add_argument(
        "--include-polymarket-closed",
        action="store_true",
        help="Opt in to fetching public Polymarket closed markets (GET-only).",
    )
    parser.add_argument(
        "--from-fixture",
        type=Path,
        default=None,
        help="Optional JSON file of test fixture records (counted as fixture_test_only).",
    )
    parser.add_argument("--max-records", type=int, default=250)
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "runtime" / "release" / "calibration_corpus.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    envelope = build_corpus(
        from_sqlite=args.from_sqlite,
        include_polymarket_closed=bool(args.include_polymarket_closed),
        from_fixture=args.from_fixture,
        max_records=int(args.max_records),
    )

    metrics = envelope["metrics"]
    sys.stdout.write(
        f"calibration corpus: n_total={metrics['n_total']} n_real={metrics['n_real']} "
        f"n_fixture={metrics['n_fixture']} n_mock={metrics['n_mock']} "
        f"evidence_status={metrics['evidence_status']} "
        f"corpus_validity={metrics['corpus_validity']}\n"
    )

    if args.write:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(envelope, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            sys.stdout.write(f"wrote {out}\n")
        except OSError as exc:  # pragma: no cover — disk full / read-only
            sys.stderr.write(_redact(f"could not write corpus: {type(exc).__name__}\n"))
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
