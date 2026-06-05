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
    # Sprint 2 v2 enrichment (additive; core fields above are unchanged).
    refined_family: str = "unknown"
    refined_confidence: float = 0.0
    refined_confidence_class: str = "UNKNOWN"
    metadata_match: int = 0
    v2_features: dict[str, int] = field(default_factory=dict)


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

# --------------------------------------------------------------------------- #
# Sprint 2 v2 classifier: 6-feature weighting + extended refined families.    #
# Additive — the core 5-feature classify() above is preserved unchanged so    #
# Sprint 1 behaviour/tests stay stable.  The refined family is reported       #
# alongside the core family for richer inventory diagnostics.                 #
# --------------------------------------------------------------------------- #
W2_EXTENSION = 0.20
W2_HEADER = 0.25
W2_KEYWORD = 0.20
W2_SCHEMA = 0.20
W2_PATH = 0.10
W2_METADATA = 0.05

# Extended refined families -> parent core family (for diagnostics rollup).
EXTENDED_TO_PARENT: dict[str, str] = {
    "chess_pgn": "chess_pgn",
    "notebook_corpus": "code_corpus",
    "code_corpus": "code_corpus",
    "spreadsheet_corpus": "market_or_finance_data",
    "json_api_dump": "scraped_text",
    "html_scrape": "scraped_text",
    "social_media_scrape": "scraped_text",
    "scraped_text": "scraped_text",
    "market_or_finance_data": "market_or_finance_data",
    "resume_or_profile_data": "hackathon_project",
    "pitch_deck_or_business_doc": "hackathon_project",
    "hackathon_project": "hackathon_project",
    "image_or_media_metadata": "unknown",
    "compressed_nested_archive": "unknown",
    "logs_or_runtime_artifacts": "unknown",
    "unknown": "unknown",
}

# Refined profiles: ext / header / keyword / schema / path / meta(basename).
_EXTENDED_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "chess_pgn": {
        "ext": (".pgn",), "header": ("[event ", "[white ", "[result "),
        "keyword": ("whiteelo", "eco", "timecontrol"), "schema": (),
        "path": ("chess", "pgn", "lichess"), "meta": ("game", "chesscom", "lichess"),
    },
    "notebook_corpus": {
        "ext": (".ipynb",), "header": ('"cells"', '"nbformat"'),
        "keyword": ("nbformat", "cell_type", "execution_count"), "schema": (),
        "path": ("notebook", "nb"), "meta": ("notebook",),
    },
    "spreadsheet_corpus": {
        "ext": (".xlsx", ".xls", ".ods"), "header": (),
        "keyword": ("sheet", "workbook"), "schema": (),
        "path": ("sheet", "excel", "xls"), "meta": ("sheet", "book"),
    },
    "json_api_dump": {
        "ext": (".json",), "header": ('{"', '[{'),
        "keyword": ('"data"', '"results"', '"items"', "endpoint", "api"),
        "schema": (), "path": ("api", "dump", "json"), "meta": ("api", "dump"),
    },
    "html_scrape": {
        "ext": (".html", ".htm"), "header": ("<html", "<!doctype html", "<head"),
        "keyword": ("<div", "<span", "href="), "schema": (),
        "path": ("html", "scrape", "web"), "meta": ("page", "index"),
    },
    "social_media_scrape": {
        "ext": (".json", ".csv", ".txt"), "header": (),
        "keyword": ("reddit", "twitter", "tweet", "upvotes", "subreddit", "linkedin"),
        "schema": ("author", "permalink", "subreddit", "likes"),
        "path": ("reddit", "twitter", "social", "tweets"),
        "meta": ("reddit", "tweet", "social"),
    },
    "market_or_finance_data": {
        "ext": (".csv", ".parquet", ".json"), "header": (),
        "keyword": ("ticker", "ohlc", "close", "pnl"),
        "schema": ("ticker", "symbol", "close", "open", "high", "low", "volume"),
        "path": ("market", "ohlcv", "price", "stock", "finance"),
        "meta": ("ohlcv", "prices", "quotes"),
    },
    "resume_or_profile_data": {
        "ext": (".pdf", ".docx", ".txt", ".json"), "header": (),
        "keyword": ("experience", "education", "skills", "resume", "curriculum"),
        "schema": (), "path": ("resume", "cv", "profile"),
        "meta": ("resume", "cv", "profile"),
    },
    "pitch_deck_or_business_doc": {
        "ext": (".md", ".pdf", ".pptx", ".txt"), "header": ("# ", "## "),
        "keyword": ("pitch", "market size", "revenue", "business model", "go-to-market"),
        "schema": (), "path": ("pitch", "deck", "business"),
        "meta": ("pitch", "deck", "slides"),
    },
    "image_or_media_metadata": {
        "ext": (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".exif", ".webp"),
        "header": (), "keyword": ("exif", "width", "height", "camera"),
        "schema": (), "path": ("img", "image", "media", "photo"),
        "meta": ("img", "photo", "thumb"),
    },
    "compressed_nested_archive": {
        "ext": (".zip", ".tar", ".gz", ".7z", ".rar"), "header": (),
        "keyword": (), "schema": (), "path": ("archive", "nested"),
        "meta": ("backup", "archive"),
    },
    "logs_or_runtime_artifacts": {
        "ext": (".log", ".out", ".err"), "header": (),
        "keyword": ("traceback", "error", "warning", "info ", "debug "),
        "schema": (), "path": ("log", "logs", "runtime"), "meta": ("log",),
    },
    "hackathon_project": {
        "ext": (".md", ".txt"), "header": ("# ", "## ", "## inspiration"),
        "keyword": ("hackathon", "devpost", "prototype", "demo", "judging", "submission"),
        "schema": (), "path": ("hackathon", "submission", "project"),
        "meta": ("readme", "submission"),
    },
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

    def _score_refined(
        self, fam: str, ext: str, sample_lower: str, path_lower: str,
        header_tokens: set[str], meta_tokens: set[str],
    ) -> tuple[float, dict[str, int]]:
        prof = _EXTENDED_PROFILES[fam]
        ext_m = 1 if ext in prof["ext"] else 0
        hdr_m = 1 if any(h in sample_lower for h in prof["header"]) else 0
        kw_m = 1 if any(k in sample_lower for k in prof["keyword"]) else 0
        sch_m = 0
        if prof["schema"]:
            sch_m = 1 if len(header_tokens & set(prof["schema"])) >= 2 else 0
        path_m = 1 if any(p in path_lower for p in prof["path"]) else 0
        meta_m = 1 if any(m in meta_tokens for m in prof["meta"]) else 0
        raw = (
            W2_EXTENSION * ext_m + W2_HEADER * hdr_m + W2_KEYWORD * kw_m
            + W2_SCHEMA * sch_m + W2_PATH * path_m + W2_METADATA * meta_m
        )
        return raw, {
            "extension_match": ext_m, "header_match": hdr_m,
            "keyword_match": kw_m, "schema_match": sch_m,
            "path_match": path_m, "metadata_match": meta_m,
        }

    def classify_refined(
        self, archive_path: str, sample_lower: str, header_tokens: set[str]
    ) -> tuple[str, float, dict[str, int]]:
        ext = os.path.splitext(archive_path)[1].lower()
        path_lower = archive_path.replace("\\", "/").lower()
        base = os.path.basename(path_lower)
        import re as _re

        meta_tokens = set(_re.split(r"[^a-z0-9]+", base)) - {""}
        best_fam, best_raw, best_feat = "unknown", 0.0, {}
        for fam in _EXTENDED_PROFILES:
            raw, feat = self._score_refined(
                fam, ext, sample_lower, path_lower, header_tokens, meta_tokens
            )
            if raw > best_raw:
                best_fam, best_raw, best_feat = fam, raw, feat
        if best_raw < 0.25:
            best_fam = "unknown"
        return best_fam, min(1.0, best_raw), best_feat

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

        refined_fam, refined_conf, v2_feat = self.classify_refined(
            archive_path, sample_lower, header_tokens
        )
        return ClassificationResult(
            family=family,
            confidence=round(confidence, 6),
            confidence_class=self.confidence_class(confidence),
            features=features,
            all_scores={f.value: round(s.raw_score, 6) for f, s in scores.items()},
            content_type_guess=_CONTENT_TYPE_BY_EXT.get(ext, "application/octet-stream"),
            parser_candidate=_PARSER_BY_FAMILY[family],
            refined_family=refined_fam,
            refined_confidence=round(refined_conf, 6),
            refined_confidence_class=self.confidence_class(refined_conf).value,
            metadata_match=v2_feat.get("metadata_match", 0),
            v2_features=v2_feat,
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
    "W2_EXTENSION",
    "W2_HEADER",
    "W2_KEYWORD",
    "W2_SCHEMA",
    "W2_PATH",
    "W2_METADATA",
    "EXTENDED_TO_PARENT",
]
