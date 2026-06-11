"""Syndication v2 (Phase 6) + external readiness checker (Phase 7) proofs."""
from __future__ import annotations

from pathlib import Path

from scripts import final_external_readiness_check as ext
from scripts import syndication_detector as syn

WIRE = "ACME Corp wins major defense contract worth $2 billion, sources say"


# ---------------------------------------------------------------------------
# Syndication v2 — beyond-lexical signals
# ---------------------------------------------------------------------------


def test_canonical_url_normalization():
    variants = [
        "https://www.example.com/news/acme-contract/?utm_source=x&utm_medium=y#frag",
        "http://example.com/news/acme-contract",
        "HTTPS://EXAMPLE.COM/news/acme-contract/",
    ]
    canon = {syn.canonical_url(u) for u in variants}
    assert canon == {"example.com/news/acme-contract"}
    # Meaningful params survive, sorted; tracking params die.
    assert syn.canonical_url("example.com/a?b=2&utm_campaign=z&a=1") == "example.com/a?a=1&b=2"
    assert syn.canonical_url(None) == ""


def test_same_canonical_url_collapses_regardless_of_text():
    items = [
        {"claim": "totally different headline wording", "source_name": "a",
         "provenance": "https://www.site.com/story?utm_source=tw"},
        {"claim": "another completely unrelated phrasing", "source_name": "b",
         "provenance": "http://site.com/story"},
    ]
    result = syn.effective_sources(items)
    assert result["effective_count"] == 1
    assert any("canonical URL" in why
               for why in result["clusters"][0]["why_clustered"])


def test_heavy_paraphrase_with_shared_fingerprint_collapses():
    """Beyond-lexical: same entity, same catalyst class, same figure."""
    items = [
        {"claim": "ACME Corp secures defense contract valued at $2 billion",
         "symbol": "ACME", "source_name": "outlet_a"},
        {"claim": "Pentagon hands ACME a deal worth 2 billion dollars",
         "symbol": "ACME", "source_name": "outlet_b"},
    ]
    assert syn.similarity(items[0]["claim"], items[1]["claim"]) < 0.55  # lexically distinct
    result = syn.effective_sources(items)
    assert result["effective_count"] == 1
    assert any("paraphrased duplicate" in why
               for why in result["clusters"][0]["why_clustered"])


def test_same_company_different_catalyst_does_not_collapse():
    items = [
        {"claim": "ACME wins defense contract worth $2 billion",
         "symbol": "ACME", "source_name": "a"},
        {"claim": "ACME CFO resigns from the board effective immediately",
         "symbol": "ACME", "source_name": "b"},
    ]
    assert syn.effective_sources(items)["effective_count"] == 2


def test_same_catalyst_independent_reporting_partially_independent():
    """Different stories on one symbol sharing wire lineage get flagged."""
    items = [
        {"claim": "Reuters: ACME quarterly revenue beats with eps of 4.20",
         "symbol": "ACME", "source_name": "reuters"},
        {"claim": "Reuters exclusive: ACME wins defense contract worth $2 billion",
         "symbol": "ACME", "source_name": "reuters"},
    ]
    result = syn.effective_sources(items)
    assert result["effective_count"] == 2  # genuinely different stories
    assert result["lineage_discounted_count"] == 1  # but one newsroom
    assert any("PARTIAL INDEPENDENCE" in why
               for cluster in result["clusters"]
               for why in cluster["why_clustered"])


def test_stale_repost_detected():
    items = [
        {"claim": WIRE, "symbol": "ACME", "source_name": "a", "freshness_days": 1.0},
        {"claim": WIRE, "symbol": "ACME", "source_name": "b", "freshness_days": 15.0},
    ]
    result = syn.effective_sources(items)
    assert result["effective_count"] == 1
    cluster = result["clusters"][0]
    assert cluster["stale_repost"] is True
    assert any("STALE REPOST" in why for why in cluster["why_clustered"])


def test_wire_lineage_detection_and_shared_lineage_confidence():
    assert syn.wire_lineage({"claim": "X (Reuters) reports"}) == "reuters"
    assert syn.wire_lineage({"source_name": "AP News"}) == "ap"
    assert syn.wire_lineage({"claim": "no agency mentioned"}) is None
    items = [
        {"claim": "Reuters: ACME lands defense contract of $2 billion",
         "symbol": "ACME", "source_name": "paper_a (reuters feed)"},
        {"claim": "ACME bags huge 2 billion defense contract, Reuters reports",
         "symbol": "ACME", "source_name": "paper_b"},
    ]
    result = syn.effective_sources(items)
    assert result["effective_count"] == 1
    assert any("wire" in why and "lineage" in why
               for why in result["clusters"][0]["why_clustered"])


def test_cluster_explanations_are_human_readable():
    items = [{"claim": WIRE, "source_name": "a"},
             {"claim": WIRE, "source_name": "b"}]
    cluster = syn.effective_sources(items)["clusters"][0]
    assert cluster["cluster_confidence"] > 0.5
    assert all(isinstance(w, str) and len(w) > 15
               for w in cluster["why_clustered"])


# ---------------------------------------------------------------------------
# External readiness — never fakes verification
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path, *, markers=(), owner_report: str | None = None,
          e2e=True, env_lines="") -> Path:
    (tmp_path / "reports" / "manual_confirmations").mkdir(parents=True)
    for marker in markers:
        (tmp_path / "reports" / "manual_confirmations" / marker).write_text(
            "# Confirmed by Akash Guha\n", encoding="utf-8")
    if owner_report is not None:
        (tmp_path / "reports" / "github_owner_controls_report.md").write_text(
            owner_report, encoding="utf-8")
    if e2e:
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "e2e.yml").write_text("name: e2e\n", encoding="utf-8")
    if env_lines:
        (tmp_path / ".env").write_text(env_lines, encoding="utf-8")
    return tmp_path


def test_missing_confirmations_are_pending_not_failed(tmp_path):
    repo = _repo(tmp_path)
    outcome = ext.run_checks(repo)
    assert outcome["unsafe"] == 0
    statuses = {r["check"]: r["status"] for r in outcome["results"]}
    assert statuses["github_branch_protection"] == ext.PENDING
    assert statuses["github_security_features"] == ext.PENDING
    assert statuses["e2e_first_green_run"] == ext.PENDING


def test_confirmation_markers_flip_to_verified(tmp_path):
    repo = _repo(tmp_path, markers=(
        "github_branch_protection_confirmed.md",
        "e2e_first_green_run_confirmed.md",
    ))
    statuses = {r["check"]: r["status"] for r in ext.run_checks(repo)["results"]}
    assert statuses["github_branch_protection"] == ext.VERIFIED
    assert statuses["e2e_first_green_run"] == ext.VERIFIED


def test_verified_unsafe_states_fail(tmp_path):
    repo = _repo(tmp_path, owner_report=(
        "# report\n## Verified safe\n- ✅ ok\n## Verified unsafe\n"
        "- ❌ **repo visibility** — NOT private\n## Not verifiable\n"))
    outcome = ext.run_checks(repo)
    assert outcome["unsafe"] >= 1
    missing_e2e = _repo(tmp_path / "x", e2e=False)
    statuses = {r["check"]: r["status"]
                for r in ext.run_checks(missing_e2e)["results"]}
    assert statuses["e2e_first_green_run"] == ext.UNSAFE


def test_plaintext_provider_keys_reported_pending(tmp_path):
    repo = _repo(tmp_path, env_lines="EDINET_API_KEY=actual-value-here\n")
    statuses = {r["check"]: (r["status"], r["detail"])
                for r in ext.run_checks(repo)["results"]}
    status, detail = statuses["env_provider_keys_migrated"]
    assert status == ext.PENDING and "plaintext" in detail
    clean = _repo(tmp_path / "y", env_lines="EDINET_API_KEY=\n")
    statuses = {r["check"]: r["status"]
                for r in ext.run_checks(clean)["results"]}
    assert statuses["env_provider_keys_migrated"] == ext.VERIFIED


def test_checker_never_creates_marker_files(tmp_path):
    repo = _repo(tmp_path)
    ext.run_checks(repo)
    markers = list((repo / "reports" / "manual_confirmations").iterdir())
    assert markers == []  # the script reports; only the owner attests
