"""Evidence reliability (Upgrade C), offline ingestion (D), German lexicon
(B), and anti-gaming rules (F) tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.consent.anti_gaming import analyze_positive_evidence, apply_refutations
from src.consent.evidence import detect_topics, extract_evidence, normalize_text
from src.consent.evidence_reliability import (
    deduplicate_records,
    coerce_records,
    score_evidence_reliability,
)
from src.consent.ingestion import (
    ingest_csv_file,
    ingest_json_file,
    ingest_raw_texts,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "consent_evidence"
AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Upgrade B — German-English lexicon
# ---------------------------------------------------------------------------


def test_german_cancellation_billing_text_triggers_layers() -> None:
    hits = extract_evidence(
        ["Trotz Kündigung weiter abgebucht, dann Mahngebühr und Inkasso"]
    )
    assert hits["charged_after_cancellation"].count >= 1
    assert hits["hidden_fees"].count >= 2
    assert "mahngebuhr" in hits["hidden_fees"].matched_terms
    assert "inkasso" in hits["hidden_fees"].matched_terms


def test_german_insurance_text_triggers_claims_risk() -> None:
    hits = extract_evidence(
        ["Erstattungsantrag abgelehnt, Unterlagen fehlen, keine Rückerstattung"]
    )
    assert hits["claims_non_payment"].count >= 2


def test_umlaut_and_digraph_variants_match() -> None:
    assert normalize_text("Kündigung") == normalize_text("Kuendigung")
    for spelling in ("Mahngebühr fällig", "Mahngebuehr faellig"):
        assert extract_evidence([spelling])["hidden_fees"].count == 1


def test_mixed_german_english_text_scores_both() -> None:
    hits = extract_evidence(
        ["Stilllegung nur schriftlich, reply took a week, still charged"]
    )
    assert hits["pause_friction"].count >= 1
    assert hits["email_only_relief"].count >= 1
    assert hits["processing_delay"].count >= 2


def test_neutral_german_contract_text_is_not_harm() -> None:
    hits = extract_evidence(
        ["Mein Vertrag und die Mitgliedschaft laufen über SEPA Lastschrift"]
    )
    assert sum(h.count for h in hits.values()) == 0
    topics = detect_topics(
        ["Mein Vertrag und die Mitgliedschaft laufen über SEPA Lastschrift"]
    )
    assert "contract" in topics and "billing" in topics


def test_german_terms_surface_in_evidence_terms() -> None:
    hits = extract_evidence(["Stilllegung nur per E-Mail, Warteschleife ewig"])
    assert "stilllegung" in hits["pause_friction"].matched_terms
    assert "warteschleife" in hits["bot_only_support"].matched_terms


# ---------------------------------------------------------------------------
# Upgrade C — evidence reliability
# ---------------------------------------------------------------------------


def test_single_vague_complaint_is_low_reliability() -> None:
    report = score_evidence_reliability(
        ["terrible scam company, worst ever, never again"], as_of=AS_OF
    )
    assert report.band == "low"
    assert report.score < 3.5
    assert any("single anecdote" in w for w in report.missing_data_warnings)


def test_specific_independent_complaints_raise_reliability() -> None:
    one = score_evidence_reliability(
        [{"text": "charged 9.90 after cancel on 2026-03-01",
          "source": "a", "source_type": "verified_review", "date": "2026-03-01"}],
        as_of=AS_OF,
    )
    five = score_evidence_reliability(
        [
            {"text": f"charged {i}.90 euro after cancel, hidden fee on invoice {i}",
             "source": f"portal_{i}", "source_type": "verified_review",
             "date": f"2026-0{i}-01"}
            for i in range(1, 6)
        ],
        as_of=AS_OF,
    )
    assert five.score > one.score
    assert five.independent_sources == 5


def test_regulator_source_outweighs_anonymous_text() -> None:
    anonymous = score_evidence_reliability(
        [{"text": "claim denied without explanation, 89 euro premium",
          "source_type": "anonymous"}],
        as_of=AS_OF,
    )
    regulator = score_evidence_reliability(
        [{"text": "regulator inquiry into claim denied without explanation, 89 euro",
          "source_type": "regulator_action", "source": "bafin",
          "date": "2026-05-01"}],
        as_of=AS_OF,
    )
    assert regulator.score > anonymous.score
    assert regulator.best_source_type == "regulator_action"


def test_duplicates_are_collapsed_not_corroborating() -> None:
    records = coerce_records(
        [
            "charged after cancel was confirmed, hidden fee of 9.90 added",
            "charged after cancel was confirmed, hidden fee of 9.90 added!",
            "Charged after cancel was confirmed - hidden fee of 9.90 added",
        ]
    )
    unique, duplicates = deduplicate_records(records)
    assert len(unique) == 1
    assert duplicates == 2

    echoed = score_evidence_reliability(
        ["charged after cancel, hidden fee of 9.90"] * 5, as_of=AS_OF
    )
    independent = score_evidence_reliability(
        [
            "charged after cancel on march 1, fee 9.90",
            "billed after cancellation in april, 12 euro fee",
            "kept charging me for 2 months after i cancelled",
        ],
        as_of=AS_OF,
    )
    assert independent.score > echoed.score
    assert echoed.duplicate_count == 4


def test_empty_evidence_is_band_none() -> None:
    report = score_evidence_reliability([], as_of=AS_OF)
    assert report.band == "none"
    assert report.score == 0.0


# ---------------------------------------------------------------------------
# Upgrade D — offline ingestion
# ---------------------------------------------------------------------------


def test_json_ingestion_offline(tmp_path) -> None:
    bundle = ingest_json_file(FIXTURES / "gym_mixed_evidence.json")
    assert bundle.unique_count == 5
    assert "de" in bundle.languages_detected
    assert "charged_after_cancellation" in bundle.categories_detected
    assert bundle.reliability is not None
    assert bundle.reliability.score > 0


def test_csv_ingestion_offline() -> None:
    bundle = ingest_csv_file(FIXTURES / "insurer_evidence.csv")
    assert bundle.unique_count == 4
    assert "claims_non_payment" in bundle.categories_detected
    assert bundle.reliability.best_source_type == "regulator_action"


def test_raw_text_ingestion_offline() -> None:
    bundle = ingest_raw_texts(
        ["cannot cancel, email only", "hidden fee on final invoice"]
    )
    assert bundle.unique_count == 2
    assert "cannot_cancel" in bundle.categories_detected


def test_duplicate_fixture_does_not_inflate() -> None:
    bundle = ingest_json_file(FIXTURES / "duplicated_evidence.json")
    assert bundle.record_count == 5
    assert bundle.unique_count == 1
    assert bundle.duplicate_count == 4
    assert any("duplicate" in w for w in bundle.warnings)


def test_mixed_language_routes_to_correct_layers() -> None:
    bundle = ingest_json_file(FIXTURES / "gym_mixed_evidence.json")
    assert {"de", "en"} & set(bundle.languages_detected)
    assert "pause_friction" in bundle.categories_detected
    assert "hidden_fees" in bundle.categories_detected
    assert "cancellation" in bundle.topics_detected or (
        "pause" in bundle.topics_detected
    )


# ---------------------------------------------------------------------------
# Upgrade F — anti-gaming
# ---------------------------------------------------------------------------


def test_generic_praise_does_not_refute_anything() -> None:
    report = analyze_positive_evidence(
        ["friendly staff and great equipment", "love this place"]
    )
    assert report.refutations_by_category == {}
    assert report.generic_praise_ignored >= 1


def test_marketing_language_is_flagged_not_counted() -> None:
    report = analyze_positive_evidence(
        ["we pride ourselves on an award-winning premium experience"]
    )
    assert report.marketing_flagged >= 1
    assert report.refutations_by_category == {}


def test_specific_refutation_reduces_only_its_category() -> None:
    report = analyze_positive_evidence(
        ["refund received within 24 hours", "cancelled in app with confirmation"]
    )
    layers = {"claims_non_payment": 8.0, "subscription_extraction": 8.0,
              "friction_tax": 8.0}
    category_map = {
        "claims_non_payment": ["claims_non_payment"],
        "subscription_extraction": ["cannot_cancel"],
        "friction_tax": ["processing_delay"],
    }
    adjusted = apply_refutations(layers, category_map, report)
    # cancellation + delay refuted; claims untouched.
    assert adjusted["subscription_extraction"] < 8.0
    assert adjusted["friction_tax"] < 8.0
    assert adjusted["claims_non_payment"] == pytest.approx(8.0)


def test_resolution_evidence_reduces_severity_globally() -> None:
    report = analyze_positive_evidence(
        ["issue was resolved, refunded after i complained"]
    )
    assert report.resolution_relief > 0
    adjusted = apply_refutations(
        {"claims_non_payment": 8.0}, {"claims_non_payment": ["claims_non_payment"]},
        report,
    )
    assert adjusted["claims_non_payment"] < 8.0


# ---------------------------------------------------------------------------
# CI hermeticity guard
# ---------------------------------------------------------------------------


def test_consent_fixtures_are_git_tracked() -> None:
    """Every offline test must bring its own committed fixture.

    The blanket ``*.csv`` gitignore has silently swallowed test fixtures
    twice (templates/outcome_import_template.csv historically, then
    insurer_evidence.csv -> FileNotFoundError only on a clean CI
    checkout while passing locally). This guard fails fast, at the
    source, with an actionable message if any consent fixture present on
    disk is not tracked by git.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not available (e.g. tarball checkout)")
    repo_root = FIXTURES.parents[2]
    if not (repo_root / ".git").exists():
        pytest.skip("not a git checkout")

    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--", "tests/fixtures/consent_evidence"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    )
    on_disk = {
        str(path.relative_to(repo_root)).replace("\\", "/")
        for path in FIXTURES.iterdir()
        if path.is_file()
    }
    untracked = sorted(on_disk - tracked)
    assert not untracked, (
        "consent fixture(s) exist on disk but are NOT committed — a clean "
        f"CI checkout will fail with FileNotFoundError: {untracked}. "
        "Run `git add` (the .gitignore negates *.csv under tests/fixtures/)."
    )
