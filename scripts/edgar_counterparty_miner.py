"""EDGAR full-text counterparty miner — HARD_FILING evidence for embedded
infrastructure relationships.

Searches SEC EDGAR full-text search (efts.sec.gov) for infrastructure
provider names inside OTHER companies' filings. A client 10-K naming a
provider is a disclosed embedded relationship with an accession number —
provenance-grade evidence, unlike blogposts.

Fail-closed rules:
  * SEC_USER_AGENT missing/empty  -> exit nonzero, no request sent
  * network/HTTP failure          -> exit nonzero, exact blocker reported
  * no silent fixture fallback — fixture mode is a separate explicit flag

Read-only public data. ADVISORY_ONLY; no broker, no execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

_REPO_ROOT = Path(__file__).resolve().parents[1]
FTS_BASE = "https://efts.sec.gov/LATEST/search-index"
FORMS = "10-K,10-Q,8-K,20-F,S-1"
ADMISSIBLE_FLOOR = 0.5

SEED_PROVIDERS: dict[str, list[str]] = {
    "Wise": ['"Wise plc"', '"Wise Payments"', '"TransferWise"'],
    "Microsoft Azure": ['"Microsoft Azure"'],
    "Amazon Web Services": ['"Amazon Web Services"'],
    "Visa": ['"Visa Inc"'],
    "Adyen": ['"Adyen"'],
    "Mastercard": ['"Mastercard Incorporated"'],
    "PayPal": ['"PayPal Holdings"'],
    "Cloudflare": ['"Cloudflare"'],
    "Snowflake": ['"Snowflake Inc"'],
    "Datadog": ['"Datadog"'],
}


class LiveSourceError(RuntimeError):
    pass


# --- edge classification (self-filings must never count as counterparty) ------
SELF_FILING = "SELF_FILING"
COUNTERPARTY_FILING = "COUNTERPARTY_FILING"
CLIENT_DEPENDENCY = "CLIENT_DEPENDENCY"
PARTNER_DISCLOSURE = "PARTNER_DISCLOSURE"
BOILERPLATE = "BOILERPLATE"
UNKNOWN = "UNKNOWN"

EDGE_TYPE_WEIGHT = {SELF_FILING: 0.0, BOILERPLATE: 0.2, UNKNOWN: 0.4,
                    COUNTERPARTY_FILING: 0.7, PARTNER_DISCLOSURE: 0.85,
                    CLIENT_DEPENDENCY: 1.0}
ADMISSIBLE_EDGE_TYPES = frozenset({COUNTERPARTY_FILING, PARTNER_DISCLOSURE,
                                   CLIENT_DEPENDENCY})

# Issuer aliases: if the FILER is the provider itself, the filing is
# SELF_FILING — a primary source about the provider, but NOT counterparty
# evidence of embedded relationships.
PROVIDER_SELF_ALIASES: dict[str, tuple[str, ...]] = {
    "Wise": ("wise group", "wise plc", "wise payments", "transferwise"),
    "Microsoft Azure": ("microsoft corp",),
    "Amazon Web Services": ("amazon.com", "amazon com"),
    "Visa": ("visa inc",),
    "Adyen": ("adyen",),
    "Mastercard": ("mastercard",),
    "PayPal": ("paypal",),
    "Cloudflare": ("cloudflare",),
    "Snowflake": ("snowflake",),
    "Datadog": ("datadog",),
}

_DEPENDENCY_TERMS = ("depend", "processing agreement", "settlement",
                     "cloud infrastructure", "payment processing",
                     "hosted on", "material vendor", "api ",
                     "infrastructure provider", "compliance provider")
_PARTNER_TERMS = ("partnership", "integration", "powered by", "platform",
                  "strategic agreement", "reseller",
                  "distribution agreement", "service agreement")
_BOILERPLATE_TERMS = ("competitors include", "such as", "among others",
                      "compared to", "peer group")


def classify_edge(provider_name: str, filer_name: str,
                  snippet: str = "") -> str:
    filer = filer_name.lower()
    for alias in PROVIDER_SELF_ALIASES.get(provider_name, ()):
        if alias in filer:
            return SELF_FILING
    text = snippet.lower()
    if not text:
        # FTS gives no snippet: a different filer is at least a
        # counterparty filing; context beyond that is unknowable here.
        return COUNTERPARTY_FILING
    if any(t in text for t in _DEPENDENCY_TERMS):
        return CLIENT_DEPENDENCY
    if any(t in text for t in _PARTNER_TERMS):
        return PARTNER_DISCLOSURE
    if any(t in text for t in _BOILERPLATE_TERMS):
        return BOILERPLATE
    return UNKNOWN


def resolve_sec_user_agent(root: Path = _REPO_ROOT) -> str:
    """os.environ first, then .env (value used for the header only — never
    logged, never written into reports)."""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if ua:
        return ua
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("SEC_USER_AGENT="):
                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                if candidate:
                    return candidate
    raise LiveSourceError(
        "SEC_USER_AGENT_MISSING_FAIL_CLOSED: set SEC_USER_AGENT (identity "
        "header required by SEC fair-access policy); no request was sent.")


# --- snippet-level context upgrade ---------------------------------------------
_SNIPPET_DEPENDENCY_TERMS = (
    "critical to operations", "relies on", "depends on",
    "payment processing", "settlement", "cloud infrastructure",
    "platform provider", "merchant acquiring", "foreign exchange",
    "cross-border payments", "api integration", "material vendor",
    "service agreement", "processing agreement")
_SNIPPET_PARTNER_TERMS = (
    "partner", "partnership", "integration", "powered by",
    "strategic agreement", "reseller", "distribution agreement",
    "platform integration")
_SNIPPET_BOILERPLATE_TERMS = (
    "competitor", "industry participants", "may use", "could use",
    "general market", "example of")


def classify_snippet(text: str) -> dict[str, Any]:
    """Keyword classification of a filing snippet around a provider match.
    ContextConfidence = min(1, keyword_hits / 3)."""
    t = text.lower()
    dep = sum(1 for k in _SNIPPET_DEPENDENCY_TERMS if k in t)
    par = sum(1 for k in _SNIPPET_PARTNER_TERMS if k in t)
    boil = sum(1 for k in _SNIPPET_BOILERPLATE_TERMS if k in t)
    if dep > 0:
        etype, hits = CLIENT_DEPENDENCY, dep
    elif par > 0:
        etype, hits = PARTNER_DISCLOSURE, par
    elif boil > 0:
        etype, hits = BOILERPLATE, boil
    else:
        etype, hits = UNKNOWN, 0
    return {"edge_type": etype, "keyword_hits": hits,
            "context_confidence": round(min(1.0, hits / 3.0), 3)}


def upgrade_edge_with_snippet(edge: dict[str, Any], snippet: str,
                              today: date) -> dict[str, Any]:
    """Apply snippet classification to an existing COUNTERPARTY edge.
    SELF_FILING can never be upgraded into counterparty evidence."""
    if edge.get("edge_type") == SELF_FILING:
        return edge
    cls = classify_snippet(snippet)
    new_type = cls["edge_type"]
    if new_type == UNKNOWN:
        new_type = edge.get("edge_type", COUNTERPARTY_FILING)
    m = _materiality(edge.get("form_type", ""), edge.get("filing_date", ""),
                     match_count=max(1, cls["keyword_hits"]), today=today,
                     edge_type=new_type)
    # snippet evidence raises context weight honestly
    m["context_weight"] = max(0.3, cls["context_confidence"])
    m["materiality_score"] = round(
        0.25 * m["section_weight"] + 0.15 * m["frequency_weight"]
        + 0.15 * m["recency_weight"] + 0.25 * m["context_weight"]
        + 0.20 * m["edge_type_weight"], 4)
    edge = dict(edge)
    edge.update(m)
    edge["edge_type"] = new_type
    edge["matched_text_snippet"] = snippet[:800]
    edge["section_context"] = "SNIPPET_KEYWORD_CONTEXT"
    edge["context_confidence"] = cls["context_confidence"]
    edge["hard_filing_admissible"] = edge_admissible(
        new_type, edge.get("accession_number", ""), m["materiality_score"])
    return edge


def fetch_filing_snippet(edge: dict[str, Any], ua: str, provider_terms:
                         list[str], window: int = 400) -> str:
    """Fetch the primary filing document and extract +/-window chars around
    the first provider-term match. Raises LiveSourceError on any failure —
    callers queue the edge instead of guessing."""
    import re as _re
    cik = str(edge.get("client_cik", "")).lstrip("0")
    accession = edge.get("accession_number", "").replace("-", "")
    if not cik or not accession:
        raise LiveSourceError("SNIPPET_MISSING_CIK_OR_ACCESSION")
    index_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                 f"{accession}/index.json")
    req = urllib.request.Request(index_url, headers={"User-Agent": ua})
    try:
        idx = json.loads(urllib.request.urlopen(req, timeout=25).read())
        items = idx["directory"]["item"]
    except Exception as exc:
        raise LiveSourceError(
            f"SNIPPET_INDEX_FETCH_FAILED: {type(exc).__name__}") from exc
    docs = [i["name"] for i in items
            if str(i.get("name", "")).lower().endswith((".htm", ".txt"))]
    for name in docs[:4]:
        doc_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                   f"{accession}/{name}")
        req = urllib.request.Request(doc_url, headers={"User-Agent": ua})
        try:
            raw = urllib.request.urlopen(req, timeout=25).read()
        except Exception:
            continue
        text = _re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore"))
        text = _re.sub(r"\s+", " ", text)
        low = text.lower()
        for term in provider_terms:
            pos = low.find(term.strip('"').lower())
            if pos >= 0:
                return text[max(0, pos - window):pos + window]
        time.sleep(0.4)
    raise LiveSourceError("SNIPPET_TERM_NOT_FOUND_IN_DOCUMENTS")


def _fts_query(term: str, ua: str, forms: str = FORMS,
               retries: int = 3) -> dict[str, Any]:
    url = f"{FTS_BASE}?q={urllib.parse.quote(term)}&forms={urllib.parse.quote(forms)}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        try:
            raw = urllib.request.urlopen(req, timeout=25).read()
            return {"raw": raw, "data": json.loads(raw), "request_url": url}
        except Exception as exc:   # EFTS throws intermittent 500s; back off
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise LiveSourceError(
        f"EDGAR_FTS_FETCH_FAILED after {retries} attempts: "
        f"{type(last_exc).__name__}: {last_exc}") from last_exc


def _materiality(form_type: str, file_date: str, match_count: int,
                 today: date, edge_type: str = UNKNOWN) -> dict[str, float]:
    # FTS gives no section context; conservative Notes/Exhibits weight, with
    # the limitation recorded honestly on every edge.
    section_weight = 0.6
    frequency_weight = min(match_count / 5.0, 1.0)
    try:
        age_days = max(0, (today - date.fromisoformat(file_date)).days)
    except ValueError:
        age_days = 3650
    recency_weight = math.exp(-age_days / 730.0)
    context_weight = 0.3  # no snippet from FTS; cannot claim dependency terms
    type_weight = EDGE_TYPE_WEIGHT.get(edge_type, 0.4)
    score = (0.25 * section_weight + 0.15 * frequency_weight
             + 0.15 * recency_weight + 0.25 * context_weight
             + 0.20 * type_weight)
    return {"section_weight": section_weight,
            "frequency_weight": round(frequency_weight, 4),
            "recency_weight": round(recency_weight, 4),
            "context_weight": context_weight,
            "edge_type_weight": type_weight,
            "materiality_score": round(score, 4)}


def edge_admissible(edge_type: str, accession: str, score: float) -> bool:
    return bool(accession and edge_type in ADMISSIBLE_EDGE_TYPES
                and score >= ADMISSIBLE_FLOOR)


def mine_providers(providers: dict[str, list[str]], *, ua: str,
                   adapter_run_id: str, today: date,
                   sleep_seconds: float = 0.7) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    provider_summaries: dict[str, Any] = {}
    for provider, terms in providers.items():
        provider_hits = 0
        for term in terms:
            result = _fts_query(term, ua)
            time.sleep(sleep_seconds)  # SEC fair-access pacing
            payload = result["data"]
            hits = payload.get("hits", {}).get("hits", [])
            total = payload.get("hits", {}).get("total", {}).get("value", 0)
            provider_hits += int(total or 0)
            source_hash = hashlib.sha256(result["raw"]).hexdigest()[:32]
            for h in hits:
                src = h.get("_source", {})
                accession = str(h.get("_id", "")).split(":", 1)[0]
                filers = src.get("display_names") or ["UNKNOWN_FILER"]
                ciks = src.get("ciks") or [""]
                file_date = str(src.get("file_date", ""))
                form_type = str(src.get("file_type", src.get("root_form", "")))
                edge_type = classify_edge(provider, str(filers[0]))
                m = _materiality(form_type, file_date,
                                 match_count=int(total or 1), today=today,
                                 edge_type=edge_type)
                edge_id = hashlib.sha256(
                    f"{provider}|{accession}|{filers[0]}".encode()
                ).hexdigest()[:16]
                edges.append({
                    "edge_id": edge_id, "provider_name": provider,
                    "search_term": term,
                    "client_filer_name": str(filers[0]),
                    "client_cik": str(ciks[0]),
                    "form_type": form_type, "filing_date": file_date,
                    "accession_number": accession,
                    "filing_url": ("https://www.sec.gov/cgi-bin/browse-edgar"
                                   f"?action=getcompany&CIK={ciks[0]}"),
                    "section_context": "FTS_NO_SECTION_CONTEXT",
                    "matched_text_snippet": "",
                    "edge_type": edge_type,
                    **m,
                    "hard_filing_admissible": edge_admissible(
                        edge_type, accession, m["materiality_score"]),
                    "source_mode": "HARD_FILING",
                    "source_hash": source_hash,
                    "adapter_name": "edgar_fts_counterparty",
                    "adapter_run_id": adapter_run_id,
                    "request_url": result["request_url"],
                    "SEC_USER_AGENT_used": True,
                })
        provider_summaries[provider] = {"total_fts_hits": provider_hits}
    return {"edges": edges, "provider_summaries": provider_summaries,
            "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY}


def write_outputs(result: dict[str, Any], *, edges_path: Path,
                  report_path: Path, adapter_run_id: str,
                  fetch_timestamp: str) -> dict[str, Any]:
    existing: set[str] = set()
    if edges_path.exists():
        for line in edges_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line).get("edge_id", ""))
    fresh = [e for e in result["edges"] if e["edge_id"] not in existing]
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    with edges_path.open("a", encoding="utf-8") as fh:
        for e in fresh:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    admissible = [e for e in result["edges"] if e["hard_filing_admissible"]]
    by_type: dict[str, int] = {}
    for e in result["edges"]:
        by_type[e.get("edge_type", UNKNOWN)] = by_type.get(
            e.get("edge_type", UNKNOWN), 0) + 1
    report = {
        "adapter_run_id": adapter_run_id, "fetch_timestamp": fetch_timestamp,
        "total_edges": len(result["edges"]),
        "edges_found": len(result["edges"]), "edges_written_new": len(fresh),
        "self_filing_count": by_type.get(SELF_FILING, 0),
        "boilerplate_count": by_type.get(BOILERPLATE, 0),
        "unknown_count": by_type.get(UNKNOWN, 0),
        "counterparty_count": by_type.get(COUNTERPARTY_FILING, 0),
        "partner_disclosure_count": by_type.get(PARTNER_DISCLOSURE, 0),
        "client_dependency_count": by_type.get(CLIENT_DEPENDENCY, 0),
        "hard_admissible_count": len(admissible),
        "providers": result["provider_summaries"],
        "materiality_note": "FTS returns no section context or snippet; "
                            "section/context weights use conservative "
                            "defaults and are labeled per edge.",
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True),
                           encoding="utf-8")
    return report


def reclassify_edges(edges_path: Path, report_path: Path,
                     today: date) -> dict[str, Any]:
    """Offline reclassification of already-fetched edges (no network):
    recompute edge_type, materiality, and admissibility in place."""
    edges = [json.loads(line) for line in
             edges_path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    for e in edges:
        edge_type = classify_edge(e["provider_name"],
                                  e.get("client_filer_name", ""),
                                  e.get("matched_text_snippet", ""))
        m = _materiality(e.get("form_type", ""), e.get("filing_date", ""),
                         match_count=max(1, int(5 * float(
                             e.get("frequency_weight", 0.2)))),
                         today=today, edge_type=edge_type)
        e.update(m)
        e["edge_type"] = edge_type
        e["hard_filing_admissible"] = edge_admissible(
            edge_type, e.get("accession_number", ""), m["materiality_score"])
    with edges_path.open("w", encoding="utf-8") as fh:
        for e in edges:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    by_type: dict[str, int] = {}
    for e in edges:
        by_type[e["edge_type"]] = by_type.get(e["edge_type"], 0) + 1
    report = {
        "adapter_run_id": "reclassify-offline",
        "fetch_timestamp": f"{today.isoformat()}T00:00:00Z",
        "total_edges": len(edges), "edges_found": len(edges),
        "edges_written_new": 0,
        "self_filing_count": by_type.get(SELF_FILING, 0),
        "boilerplate_count": by_type.get(BOILERPLATE, 0),
        "unknown_count": by_type.get(UNKNOWN, 0),
        "counterparty_count": by_type.get(COUNTERPARTY_FILING, 0),
        "partner_disclosure_count": by_type.get(PARTNER_DISCLOSURE, 0),
        "client_dependency_count": by_type.get(CLIENT_DEPENDENCY, 0),
        "hard_admissible_count": sum(
            1 for e in edges if e["hard_filing_admissible"]),
        "materiality_note": "offline reclassification; FTS has no snippets, "
                            "so non-self edges default to "
                            "COUNTERPARTY_FILING pending snippet capture",
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True),
                           encoding="utf-8")
    return report


def _main() -> int:
    ap = argparse.ArgumentParser(description="EDGAR counterparty miner "
                                             "(read-only, fail-closed)")
    ap.add_argument("--providers", nargs="*", default=None,
                    help="subset of seed provider names")
    ap.add_argument("--reclassify", action="store_true",
                    help="offline: reclassify existing edges file, no fetch")
    ap.add_argument("--snippets", action="store_true",
                    help="fetch filing snippets for top counterparty edges "
                         "and upgrade dependency typing (fail-closed queue)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--edges-out", type=Path,
                    default=Path("data/evidence/edgar_counterparty_edges.jsonl"))
    ap.add_argument("--report-out", type=Path,
                    default=Path("runtime/edgar_counterparty_report.json"))
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    if args.reclassify:
        from datetime import datetime, timezone
        report = reclassify_edges(args.edges_out, args.report_out,
                                  datetime.now(timezone.utc).date())
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.snippets:
        from datetime import datetime, timezone
        try:
            ua = resolve_sec_user_agent()
        except LiveSourceError as exc:
            print(json.dumps({"status": "BLOCKED_MISSING_ENV",
                              "blocker": str(exc)}))
            return 2
        today = datetime.now(timezone.utc).date()
        edges = [json.loads(line) for line in
                 args.edges_out.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        wanted = set(args.providers or [])
        targets = [e for e in edges
                   if e.get("edge_type") == COUNTERPARTY_FILING
                   and (not wanted or e["provider_name"] in wanted)]
        targets.sort(key=lambda e: -float(e.get("materiality_score", 0)))
        targets = targets[:args.top]
        upgraded, queued = [], []
        by_id = {e["edge_id"]: e for e in edges}
        for e in targets:
            terms = [t for t in SEED_PROVIDERS.get(e["provider_name"], [])]
            try:
                snippet = fetch_filing_snippet(e, ua, terms)
                new_edge = upgrade_edge_with_snippet(e, snippet, today)
                by_id[e["edge_id"]] = new_edge
                upgraded.append({"edge_id": e["edge_id"],
                                 "from": e["edge_type"],
                                 "to": new_edge["edge_type"],
                                 "context_confidence":
                                     new_edge.get("context_confidence")})
            except LiveSourceError as exc:
                queued.append({"edge_id": e["edge_id"],
                               "provider": e["provider_name"],
                               "blocker": str(exc)})
            time.sleep(0.6)
        with args.edges_out.open("w", encoding="utf-8") as fh:
            for e in by_id.values():
                fh.write(json.dumps(e, sort_keys=True) + "\n")
        snip_report = {"attempted": len(targets), "upgraded": upgraded,
                       "queued": queued,
                       "status": ("OK" if upgraded else
                                  ("DEGRADED" if queued else "NO_TARGETS")),
                       "advisory_status": ADVISORY_STATUS}
        Path("runtime/edgar_snippet_report.json").write_text(
            json.dumps(snip_report, indent=2, sort_keys=True),
            encoding="utf-8")
        Path("runtime/edgar_snippet_queue.json").write_text(
            json.dumps({"queued": queued}, indent=2, sort_keys=True),
            encoding="utf-8")
        Path("runtime/edgar_snippet_report.md").write_text(
            "# EDGAR snippet report\n\n"
            + f"attempted: {len(targets)} · upgraded: {len(upgraded)} · "
              f"queued: {len(queued)} · status: {snip_report['status']}\n",
            encoding="utf-8")
        print(json.dumps(snip_report, indent=2, sort_keys=True))
        return 0
    try:
        ua = resolve_sec_user_agent()
    except LiveSourceError as exc:
        print(json.dumps({"status": "BLOCKED_MISSING_ENV",
                          "blocker": str(exc)}))
        return 2
    providers = SEED_PROVIDERS
    if args.providers:
        providers = {k: v for k, v in SEED_PROVIDERS.items()
                     if k in set(args.providers)}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    run_id = args.run_id or f"edgar-{now.strftime('%Y%m%dT%H%M%SZ')}"
    try:
        result = mine_providers(providers, ua=ua, adapter_run_id=run_id,
                                today=now.date())
    except LiveSourceError as exc:
        print(json.dumps({"status": "BLOCKED_ADAPTER_LIMITATION",
                          "blocker": str(exc)}))
        return 3
    report = write_outputs(result, edges_path=args.edges_out,
                           report_path=args.report_out,
                           adapter_run_id=run_id,
                           fetch_timestamp=now.isoformat())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
