"""Parsers that turn useful zip members into structured SIMULATION records.

Each parser is defensive: malformed input yields an empty/NO_DATA result, not
an exception that crashes the harness.  No parser claims market relevance for
non-market data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass, field

from src.simulation_zip import metrics
from src.simulation_zip.labels import PARSER_VERSION

# Minimum data thresholds for honest market metrics (else NO_DATA).
MIN_MARKET_ROWS = 100
MIN_CLOSED_OUTCOMES = 30
MIN_PROBABILITY_PREDICTIONS = 50

_TAG_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]\s*$')


# --------------------------------------------------------------------------- #
# Parser 1 — chess.com / lichess PGN                                          #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ChessGame:
    game_id: str
    event: str
    site: str
    date: str
    white: str
    black: str
    result: str
    white_elo: int | None
    black_elo: int | None
    time_control: str
    termination: str
    eco: str
    opening: str
    moves_count: int
    delta_elo: float | None
    expected_white: float | None
    actual_white: float | None
    surprise: float | None
    upset: int
    draw: int
    timeout_flag: int
    abandoned_flag: int
    resignation_flag: int
    provenance_id: str
    raw_headers: dict[str, str] = field(default_factory=dict)


def _split_pgn_games(text: str) -> list[tuple[dict[str, str], str]]:
    """Split a PGN file into (headers, movetext) tuples."""
    games: list[tuple[dict[str, str], str]] = []
    headers: dict[str, str] = {}
    moves: list[str] = []
    in_moves = False
    for line in text.splitlines():
        m = _TAG_RE.match(line.strip())
        if m:
            if in_moves and (headers or moves):
                games.append((headers, " ".join(moves).strip()))
                headers, moves, in_moves = {}, [], False
            headers[m.group(1)] = m.group(2)
        elif line.strip() == "":
            if headers or moves:
                in_moves = True if not in_moves and headers else in_moves
                if in_moves:
                    pass
            in_moves = bool(headers)
        else:
            in_moves = True
            moves.append(line.strip())
    if headers or moves:
        games.append((headers, " ".join(moves).strip()))
    return [g for g in games if g[0]]


def _count_plies(movetext: str) -> int:
    if not movetext:
        return 0
    cleaned = re.sub(r"\{[^}]*\}", " ", movetext)  # strip comments
    cleaned = re.sub(r"\d+\.(\.\.)?", " ", cleaned)  # strip move numbers
    cleaned = re.sub(r"\$\d+", " ", cleaned)  # strip NAGs
    tokens = [
        t for t in cleaned.split()
        if t not in ("1-0", "0-1", "1/2-1/2", "*") and t not in ("", "...")
    ]
    return len(tokens)


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class PgnParser:
    version = PARSER_VERSION

    def parse(self, text: str, provenance_id: str) -> list[ChessGame]:
        out: list[ChessGame] = []
        for idx, (headers, movetext) in enumerate(_split_pgn_games(text)):
            h = {k: v for k, v in headers.items()}
            result = h.get("Result", "*")
            white_elo = _to_int(h.get("WhiteElo"))
            black_elo = _to_int(h.get("BlackElo"))
            termination = h.get("Termination", "")
            term_l = termination.lower()
            if result == "1-0":
                actual = 1.0
            elif result == "0-1":
                actual = 0.0
            elif result == "1/2-1/2":
                actual = 0.5
            else:
                actual = None
            delta = expected = surprise = None
            upset = 0
            if white_elo is not None and black_elo is not None:
                delta = float(white_elo - black_elo)
                expected = metrics.elo_expected_white(delta)
                if actual is not None:
                    surprise = abs(actual - expected)
                    if (expected >= 0.65 and actual == 0) or (
                        expected <= 0.35 and actual == 1
                    ):
                        upset = 1
            out.append(
                ChessGame(
                    game_id=f"{provenance_id[:12]}-g{idx}",
                    event=h.get("Event", ""),
                    site=h.get("Site", ""),
                    date=h.get("Date", h.get("UTCDate", "")),
                    white=h.get("White", ""),
                    black=h.get("Black", ""),
                    result=result,
                    white_elo=white_elo,
                    black_elo=black_elo,
                    time_control=h.get("TimeControl", ""),
                    termination=termination,
                    eco=h.get("ECO", ""),
                    opening=h.get("Opening", ""),
                    moves_count=_count_plies(movetext),
                    delta_elo=delta,
                    expected_white=expected,
                    actual_white=actual,
                    surprise=surprise,
                    upset=upset,
                    draw=1 if result == "1/2-1/2" else 0,
                    timeout_flag=1 if ("time" in term_l or "timeout" in term_l) else 0,
                    abandoned_flag=1 if "abandon" in term_l else 0,
                    resignation_flag=1 if ("resign" in term_l) else 0,
                    provenance_id=provenance_id,
                    raw_headers=h,
                )
            )
        return out


# --------------------------------------------------------------------------- #
# Parser 2 — hackathon project corpus                                         #
# --------------------------------------------------------------------------- #
_HACK_KEYWORDS = {
    "problem_clarity": (["problem", "pain", "challenge", "user", "need", "why"], 6),
    "solution_specificity": (
        ["solution", "build", "prototype", "feature", "architecture", "workflow"], 6,
    ),
    "evidence_depth": (
        ["data", "result", "metric", "benchmark", "experiment", "evaluation"], 6,
    ),
    "demo_readiness": (["demo", "screenshot", "video", "live", "deploy", "run"], 6),
    "risk_disclosure": (
        ["risk", "limitation", "caveat", "assumption", "tradeoff", "threat"], 6,
    ),
    "reproducibility": (
        ["reproduce", "install", "setup", "requirements", "readme", "command"], 6,
    ),
    "external_judge_alignment": (
        ["judging", "criteria", "score", "rubric", "evaluation", "impact"], 6,
    ),
}


@dataclass(slots=True)
class HackathonProject:
    project_id: str
    title: str
    text_length: int
    problem_clarity: float
    solution_specificity: float
    evidence_depth: float
    demo_readiness: float
    risk_disclosure: float
    reproducibility: float
    external_judge_alignment: float
    heuristic_explanation: dict[str, str]
    provenance_id: str


class HackathonParser:
    version = PARSER_VERSION

    def parse(self, text: str, provenance_id: str) -> HackathonProject:
        low = text.lower()
        title = ""
        for line in text.splitlines():
            s = line.strip().lstrip("#").strip()
            if s:
                title = s[:120]
                break
        scores: dict[str, float] = {}
        explain: dict[str, str] = {}
        for name, (kws, k) in _HACK_KEYWORDS.items():
            hits = sum(1 for kw in kws if kw in low)
            scores[name] = min(1.0, hits / k)
            explain[name] = f"min(1, {hits}/{k}) over {kws}"
        return HackathonProject(
            project_id=provenance_id[:16],
            title=title,
            text_length=len(text),
            problem_clarity=scores["problem_clarity"],
            solution_specificity=scores["solution_specificity"],
            evidence_depth=scores["evidence_depth"],
            demo_readiness=scores["demo_readiness"],
            risk_disclosure=scores["risk_disclosure"],
            reproducibility=scores["reproducibility"],
            external_judge_alignment=scores["external_judge_alignment"],
            heuristic_explanation=explain,
            provenance_id=provenance_id,
        )


# --------------------------------------------------------------------------- #
# Parser 3 — scraped noisy text                                               #
# --------------------------------------------------------------------------- #
_PLATFORMS = (
    "reddit", "twitter", "x.com", "linkedin", "youtube", "github",
    "medium", "substack", "hackernews", "ycombinator",
)
_URL_RE = re.compile(r"https?://([^/\s\"']+)")


@dataclass(slots=True)
class ScrapedDoc:
    doc_id: str
    source: str
    title: str
    url: str
    text_length: int
    topic_keywords: list[str]
    normalized_hash: str
    provenance_id: str


class ScrapedTextParser:
    version = PARSER_VERSION

    def _infer_source(self, text: str, archive_path: str) -> tuple[str, str]:
        hay = (archive_path + " " + text[:2000]).lower()
        for p in _PLATFORMS:
            if p in hay:
                return p, ""
        m = _URL_RE.search(text)
        if m:
            return m.group(1).lower(), m.group(0)
        return "unknown", ""

    def parse(self, text: str, provenance_id: str, archive_path: str) -> ScrapedDoc:
        source, url = self._infer_source(text, archive_path)
        title = ""
        for line in text.splitlines():
            if line.strip():
                title = line.strip()[:120]
                break
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        freq: dict[str, int] = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        topics = [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        nhash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return ScrapedDoc(
            doc_id=provenance_id[:16],
            source=source,
            title=title,
            url=url,
            text_length=len(text),
            topic_keywords=topics,
            normalized_hash=nhash,
            provenance_id=provenance_id,
        )


def scraped_corpus_stats(docs: list[ScrapedDoc]) -> dict[str, object]:
    if not docs:
        return {
            "documents": 0, "unique_sources": 0, "source_diversity": 0.0,
            "duplicate_ratio": 0.0, "sources": {},
        }
    source_counts: dict[str, int] = {}
    seen: set[str] = set()
    duplicates = 0
    for d in docs:
        source_counts[d.source] = source_counts.get(d.source, 0) + 1
        if d.normalized_hash in seen:
            duplicates += 1
        else:
            seen.add(d.normalized_hash)
    div = metrics.shannon_diversity(source_counts)
    return {
        "documents": len(docs),
        "unique_sources": div["unique_sources"],
        "source_entropy": round(div["entropy"], 6),
        "source_diversity": round(div["normalized_diversity"], 6),
        "duplicate_ratio": round(metrics.duplicate_ratio(len(docs), duplicates), 6),
        "duplicate_count": duplicates,
        "sources": dict(sorted(source_counts.items())),
    }


# --------------------------------------------------------------------------- #
# Parser 4 — market / finance structured data (strict, fail-closed)          #
# --------------------------------------------------------------------------- #
_MARKET_PRICE_COLS = ("close", "price", "adj_close", "adjclose")
_MARKET_REQUIRED_ANY = (
    ("ticker", "symbol"),
    ("date", "datetime", "timestamp"),
)


class MarketParser:
    version = PARSER_VERSION

    def _detect_schema(self, header: list[str]) -> dict[str, str | None]:
        cols = {c.strip().lower(): c for c in header}
        def pick(*names: str) -> str | None:
            for n in names:
                if n in cols:
                    return n
            return None
        return {
            "ticker": pick("ticker", "symbol"),
            "date": pick("date", "datetime", "timestamp"),
            "price": pick("close", "price", "adj_close", "adjclose"),
            "volume": pick("volume", "vol"),
            "signal": pick("signal", "position"),
            "return": pick("return", "ret"),
            "pnl": pick("pnl", "profit"),
            "outcome": pick("outcome", "win", "label"),
            "probability": pick("probability", "prob", "p", "pred_proba"),
        }

    def parse(self, text: str, provenance_id: str, archive_path: str) -> dict[str, object]:
        """Parse a CSV-like member.  Returns a strict, honest result dict.

        ``status`` is NO_DATA unless real, dated, tickered, priced rows clear
        the minimum thresholds.  Calibration/outcome metrics are only added
        when their own thresholds are met.
        """
        result: dict[str, object] = {
            "provenance_id": provenance_id,
            "archive_path": archive_path,
            "status": "NO_DATA",
            "reason": "",
            "rows_parsed": 0,
            "valid_price_rows": 0,
            "schema": {},
            "metrics": {},
        }
        try:
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
        except (csv.Error, ValueError):
            result["reason"] = "csv_parse_error"
            return result
        if len(rows) < 2:
            result["reason"] = "too_few_rows"
            return result
        header = rows[0]
        schema = self._detect_schema(header)
        result["schema"] = schema
        if not schema["price"] or not (schema["ticker"] and schema["date"]):
            result["reason"] = "missing_ticker_date_or_price_schema"
            return result
        idx = {k: header.index(v) for k, v in schema.items() if v is not None}
        # Group prices per ticker preserving row order.
        per_ticker: dict[str, list[float]] = {}
        signals: dict[str, list[float]] = {}
        prob_pairs: list[tuple[float, float]] = []
        valid = 0
        for r in rows[1:]:
            if len(r) <= max(idx.values()):
                continue
            tkr = r[idx["ticker"]].strip()
            try:
                price = float(r[idx["price"]])
            except (ValueError, IndexError):
                continue
            per_ticker.setdefault(tkr, []).append(price)
            if "signal" in idx:
                try:
                    signals.setdefault(tkr, []).append(float(r[idx["signal"]]))
                except ValueError:
                    signals.setdefault(tkr, []).append(0.0)
            if "probability" in idx and "outcome" in idx:
                try:
                    p = float(r[idx["probability"]])
                    y = float(r[idx["outcome"]])
                    if 0.0 <= p <= 1.0 and y in (0.0, 1.0):
                        prob_pairs.append((p, y))
                except (ValueError, IndexError):
                    pass
            valid += 1
        result["rows_parsed"] = len(rows) - 1
        result["valid_price_rows"] = valid
        if valid < MIN_MARKET_ROWS:
            result["reason"] = (
                f"valid_rows_{valid}_below_min_{MIN_MARKET_ROWS}"
            )
            return result

        # Build strategy returns: position_{t-1} * r_t per ticker.
        strat: list[float] = []
        for tkr, prices in per_ticker.items():
            rets = metrics.simple_returns(prices)
            sig = signals.get(tkr)
            for i, r in enumerate(rets):
                pos = sig[i] if sig and i < len(sig) else 1.0
                strat.append(pos * r)
        m: dict[str, object] = {
            "cumulative_return": metrics.cumulative_return(strat),
            "sharpe": metrics.sharpe_ratio(strat),
            "max_drawdown": metrics.max_drawdown(strat),
            "n_strategy_returns": len(strat),
        }
        # Sortino with MAR=0.
        downside = [min(0.0, x) for x in strat]
        dd = math.sqrt(sum(x * x for x in downside) / len(downside)) if downside else 0.0
        if dd > metrics.EPS and strat:
            mean = sum(strat) / len(strat)
            m["sortino"] = (mean / dd) * math.sqrt(len(strat))
        else:
            m["sortino"] = None

        calibration: dict[str, object] = {"status": "NO_DATA"}
        if len(prob_pairs) >= MIN_PROBABILITY_PREDICTIONS:
            calibration = {
                "status": "OK",
                "n": len(prob_pairs),
                "brier": metrics.brier_score(prob_pairs),
                "log_loss": metrics.log_loss(prob_pairs),
                "ece": metrics.expected_calibration_error(prob_pairs),
                "reliability": metrics.reliability_decomposition(prob_pairs),
            }
        m["calibration"] = calibration
        result["metrics"] = m
        result["status"] = "OK"
        result["reason"] = "ok"
        return result


__all__ = [
    "PgnParser", "ChessGame",
    "HackathonParser", "HackathonProject",
    "ScrapedTextParser", "ScrapedDoc", "scraped_corpus_stats",
    "MarketParser",
    "MIN_MARKET_ROWS", "MIN_CLOSED_OUTCOMES", "MIN_PROBABILITY_PREDICTIONS",
]
