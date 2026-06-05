"""Conservative dataset-family classification for zip members.

We never assume market relevance.  Classification combines five binary
features with fixed weights (sum to 1.0):

    raw_score_i = w_ext*ext + w_hdr*hdr + w_kw*kw + w_schema*schema + w_path*path
    confidence_i = min(1, raw_score_i)

    w_extension=0.25  w_header=0.30  w_keyword=0.20  w_schema=0.20  w_path=0.05

The family with the highest raw score wins; ties and sub-0.25 scores fall back
to ``unknown``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

W_EXTENSION = 0.25
W_HEADER = 0.30
W_KEYWORD = 0.20
W_SCHEMA = 0.20
W_PATH = 0.05


class DatasetFamily(str, Enum):
    CHESS_PGN = "chess_pgn"
    HACKATHON_PROJECT = "hackathon_project"
    SCRAPED_TEXT = "scraped_text"
    MARKET_OR_FINANCE_DATA = "market_or_finance_data"
    CODE_CORPUS = "code_corpus"
    UNKNOWN = "unknown"


class ConfidenceClass(str, Enum):
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    MEDIUM_CONFIDENCE = "MEDIUM_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNKNOWN = "UNKNOWN"


# Per-family detection profiles.  ``schema`` keys are CSV-style column tokens.
_PROFILES: dict[DatasetFamily, dict[str, tuple[str, ...]]] = {
    DatasetFamily.CHESS_PGN: {
        "ext": (".pgn",),
        "header": ("[event ", "[site ", "[white ", "[black ", "[result "),
        "keyword": ("eco", "whiteelo", "blackelo", "timecontrol", "1. e4", "1.d4"),
        "schema": (),
        "path": ("chess", "pgn", "lichess", "game"),
    },
    DatasetFamily.MARKET_OR_FINANCE_DATA: {
        "ext": (".csv", ".tsv", ".xlsx", ".parquet", ".json"),
        "header": (),
        "keyword": ("ticker", "open,high,low,close", "ohlc", "pnl", "sharpe"),
        "schema": (
            "ticker", "symbol", "date", "datetime", "open", "high", "low",
            "close", "price", "volume", "signal", "return", "pnl", "outcome",
        ),
        "path": ("market", "finance", "ohlcv", "price", "trades", "stock"),
    },
    DatasetFamily.HACKATHON_PROJECT: {
        "ext": (".md", ".txt", ".json", ".ipynb", ".py", ".js", ".html"),
        "header": ("# ", "## ", "problem statement", "## inspiration"),
        "keyword": (
            "hackathon", "prototype", "mvp", "pitch", "demo", "judging",
            "submission", "devpost", "team", "sponsor",
        ),
        "schema": (),
        "path": ("hackathon", "pitch", "demo", "submission", "project"),
    },
    DatasetFamily.SCRAPED_TEXT: {
        "ext": (".txt", ".md", ".html", ".htm", ".json", ".csv"),
        "header": ("<html", "<!doctype html", "http://", "https://"),
        "keyword": (
            "scraped", "crawler", "webpage", "reddit", "twitter", "linkedin",
            "youtube", "article", "comment", "upvotes", "permalink",
        ),
        "schema": ("url", "title", "author", "timestamp", "body", "source"),
        "path": ("scrape", "crawl", "reddit", "twitter", "news", "web"),
    },
    DatasetFamily.CODE_CORPUS: {
        "ext": (".py", ".js", ".ts", ".tsx", ".jsx", ".ipynb"),
        "header": ("import ", "from ", "def ", "class ", "function ", "const "),
        "keyword": (
            "requirements.txt", "package.json", "npm", "def ", "class ",
            "import ", "module.exports",
        ),
        "schema": (),
        "path": ("src", "lib", "code", "notebook", "scripts"),
    },
}


@dataclass(slots=True)
class FamilyScore:
    family: DatasetFamily
    raw_score: float
    confidence: float
    features: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ClassificationResult:
    family: DatasetFamily
    confidence: float
    confidence_class: ConfidenceClass
    features: dict[str, int]
    all_scores: dict[str, float]
    content_type_guess: str
    parser_candidate: str


_CONTENT_TYPE_BY_EXT = {
    ".pgn": "text/x-chess-pgn",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".html": "text/html",
    ".htm": "text/html",
    ".py": "text/x-python",
    ".ipynb": "application/x-ipynb+json",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".parquet": "application/vnd.apache.parquet",
    ".xlsx": "application/vnd.openxmlformats",
}

_PARSER_BY_FAMILY = {
    DatasetFamily.CHESS_PGN: "pgn_parser",
    DatasetFamily.HACKATHON_PROJECT: "hackathon_parser",
    DatasetFamily.SCRAPED_TEXT: "scraped_text_parser",
    DatasetFamily.MARKET_OR_FINANCE_DATA: "market_parser",
    DatasetFamily.CODE_CORPUS: "code_corpus_indexer",
    DatasetFamily.UNKNOWN: "none",
}


class DatasetClassifier:
    """Classifies a member from its name + a decoded content sample."""

    def confidence_class(self, confidence: float) -> ConfidenceClass:
        if confidence >= 0.75:
            return ConfidenceClass.HIGH_CONFIDENCE
        if confidence >= 0.50:
            return ConfidenceClass.MEDIUM_CONFIDENCE
        if confidence >= 0.25:
            return ConfidenceClass.LOW_CONFIDENCE
        return ConfidenceClass.UNKNOWN

    def _schema_tokens(self, sample_lower: str) -> set[str]:
        """First non-empty line's comma/tab tokens (CSV header heuristic)."""
        for line in sample_lower.splitlines():
            line = line.strip()
            if line:
                seps = "\t" if "\t" in line else ","
                return {t.strip().strip('"') for t in line.split(seps)}
        return set()

    def score_family(
        self, family: DatasetFamily, ext: str, sample_lower: str,
        path_lower: str, header_tokens: set[str],
    ) -> FamilyScore:
        prof = _PROFILES[family]
        ext_match = 1 if ext in prof["ext"] else 0
        header_match = 1 if any(h in sample_lower for h in prof["header"]) else 0
        keyword_match = 1 if any(k in sample_lower for k in prof["keyword"]) else 0
        schema_match = 0
        if prof["schema"]:
            overlap = header_tokens & set(prof["schema"])
            # Require >= 2 schema columns to count, to avoid a stray "date".
            schema_match = 1 if len(overlap) >= 2 else 0
        path_match = 1 if any(p in path_lower for p in prof["path"]) else 0
        features = {
            "extension_match": ext_match,
            "header_match": header_match,
            "keyword_match": keyword_match,
            "schema_match": schema_match,
            "path_match": path_match,
        }
        raw = (
            W_EXTENSION * ext_match + W_HEADER * header_match
            + W_KEYWORD * keyword_match + W_SCHEMA * schema_match
            + W_PATH * path_match
        )
        return FamilyScore(family, raw, min(1.0, raw), features)

    def classify(self, archive_path: str, sample: bytes) -> ClassificationResult:
        ext = os.path.splitext(archive_path)[1].lower()
        path_lower = archive_path.replace("\\", "/").lower()
        try:
            text = sample.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - decode is defensive
            text = ""
        sample_lower = text.lower()
        header_tokens = self._schema_tokens(sample_lower)

        scores: dict[DatasetFamily, FamilyScore] = {}
        for fam in _PROFILES:
            scores[fam] = self.score_family(
                fam, ext, sample_lower, path_lower, header_tokens
            )
        # Pick the best by raw score; deterministic tie-break by family order.
        best = max(
            scores.values(),
            key=lambda s: (s.raw_score, -list(DatasetFamily).index(s.family)),
        )
        if best.raw_score < 0.25:
            family = DatasetFamily.UNKNOWN
            confidence = best.confidence
            features = best.features
        else:
            family = best.family
            confidence = best.confidence
            features = best.features
        return ClassificationResult(
            family=family,
            confidence=round(confidence, 6),
            confidence_class=self.confidence_class(confidence),
            features=features,
            all_scores={f.value: round(s.raw_score, 6) for f, s in scores.items()},
            content_type_guess=_CONTENT_TYPE_BY_EXT.get(ext, "application/octet-stream"),
            parser_candidate=_PARSER_BY_FAMILY[family],
        )


__all__ = [
    "DatasetFamily",
    "ConfidenceClass",
    "DatasetClassifier",
    "ClassificationResult",
    "FamilyScore",
    "W_EXTENSION",
    "W_HEADER",
    "W_KEYWORD",
    "W_SCHEMA",
    "W_PATH",
]
