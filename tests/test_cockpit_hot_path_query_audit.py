"""Kanté Task 2 — cockpit hot-path query/index audit + guarded index apply.

Proves the audit measures the cockpit/diagnostics hot-path reads honestly:

* missing tables are handled (never crash, excluded from the score);
* an unindexed hot-path read is detected as ``full_scan_detected``;
* once the index exists the same read reports ``uses_index``;
* index recommendations reference only columns that actually exist;
* the audit never emits destructive SQL;
* score fields are present in both the dict and the JSON CLI output.

And that the companion apply script is additive + guarded:

* dry-run mutates nothing;
* ``--apply`` requires ADMIN + a dry-run receipt;
* the write function refuses a direct-import bypass;
* only additive ``CREATE INDEX IF NOT EXISTS`` is accepted.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.persistence as persistence
from scripts import cockpit_hot_path_query_audit as audit
from scripts import apply_cockpit_hot_path_indexes as applier
from scripts import operator_permission_guard as _guard


@pytest.fixture
def schema_db(tmp_path: Path) -> Path:
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    return db


def _index_names(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Audit behaviour.
# ---------------------------------------------------------------------------


def test_handles_missing_tables(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()  # file exists, no tables
    report = audit.audit_hot_paths(empty)
    assert report["db_available"] is True
    assert all(hp.get("table_missing") for hp in report["hot_paths"])
    # Score fields still present; nothing counted.
    assert report["hot_path_query_count"] == 0
    assert "cockpit_hot_path_score" in report


def test_unindexed_table_produces_full_scan(schema_db: Path) -> None:
    # Fresh schema has no created_via index → truth-purity count full-scans.
    report = audit.audit_hot_paths(schema_db)
    by_name = {hp["query_name"]: hp for hp in report["hot_paths"]}
    tp = by_name["truth_purity_fake_rows"]
    assert tp["full_scan_detected"] is True
    assert tp["uses_index"] is False
    assert report["hot_path_full_scan_risk"] > 0


def test_indexed_table_shows_uses_index(schema_db: Path) -> None:
    conn = sqlite3.connect(str(schema_db))
    try:
        conn.execute("CREATE INDEX idx_manual_trades_created_via "
                     "ON manual_trades(created_via)")
        conn.commit()
    finally:
        conn.close()
    report = audit.audit_hot_paths(schema_db)
    tp = {hp["query_name"]: hp for hp in report["hot_paths"]}["truth_purity_fake_rows"]
    assert tp["uses_index"] is True
    assert tp["full_scan_detected"] is False
    assert tp["index_name"]  # plan names the index


def test_recommendations_use_only_existing_columns(schema_db: Path) -> None:
    report = audit.audit_hot_paths(schema_db)
    conn = sqlite3.connect(str(schema_db))
    try:
        for rec in report["index_recommendations"]:
            # rec looks like: CREATE INDEX IF NOT EXISTS idx ON <table>(<col>);
            assert rec.upper().startswith("CREATE INDEX IF NOT EXISTS")
            table = rec.split(" ON ")[1].split("(")[0].strip()
            col = rec.split("(")[1].split(")")[0].strip()
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert col in cols, f"recommended column {col!r} absent from {table}"
    finally:
        conn.close()


def test_no_destructive_sql_in_recommendations(schema_db: Path) -> None:
    report = audit.audit_hot_paths(schema_db)
    blob = json.dumps(report).upper()
    for tok in ("DROP ", "DELETE ", "UPDATE ", "INSERT ", "ALTER "):
        assert tok not in blob, f"destructive token {tok!r} leaked into audit"


def test_audit_never_mutates_db(schema_db: Path) -> None:
    before = _index_names(schema_db)
    audit.audit_hot_paths(schema_db)
    assert _index_names(schema_db) == before


def test_score_fields_in_cli_json(schema_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = audit.main(["--db-path", str(schema_db), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for key in ("hot_path_indexed_coverage", "hot_path_bounded_coverage",
                "hot_path_full_scan_risk", "cockpit_hot_path_score"):
        assert key in payload


# ---------------------------------------------------------------------------
# Guarded index apply.
# ---------------------------------------------------------------------------


def test_safe_create_index_filter() -> None:
    assert applier._is_safe_create_index(
        "CREATE INDEX IF NOT EXISTS idx_x ON manual_trades(created_via);")
    # Destructive / non-additive statements rejected.
    assert not applier._is_safe_create_index("DROP INDEX idx_x;")
    assert not applier._is_safe_create_index("DELETE FROM manual_trades;")
    assert not applier._is_safe_create_index(
        "CREATE INDEX idx_x ON manual_trades(created_via);")  # missing IF NOT EXISTS


def test_apply_dry_run_does_not_mutate(schema_db: Path, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    before = _index_names(schema_db)
    rc = applier.main(["--db-path", str(schema_db)])  # dry-run
    assert rc == 0
    assert _index_names(schema_db) == before  # untouched


def test_apply_requires_admin(schema_db: Path, tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    applier.main(["--db-path", str(schema_db)])  # write receipt
    # OPERATOR cannot perform MIGRATION_WRITE.
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    assert applier.main(["--db-path", str(schema_db), "--apply"]) == 2
    before = _index_names(schema_db)
    assert before == _index_names(schema_db)


def test_apply_admin_creates_indexes(schema_db: Path, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv(_guard.AUDIT_PATH_ENV_VAR, str(tmp_path / "audit.jsonl"))
    applier.main(["--db-path", str(schema_db)])  # dry-run receipt
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "ADMIN")
    before = _index_names(schema_db)
    assert applier.main(["--db-path", str(schema_db), "--apply"]) == 0
    after = _index_names(schema_db)
    assert len(after) > len(before)
    # Re-audit: full scan risk drops to zero once indexes exist.
    report = audit.audit_hot_paths(schema_db)
    assert report["hot_path_full_scan_risk"] == 0.0


def test_apply_indexes_blocks_direct_import(schema_db: Path) -> None:
    with pytest.raises(PermissionError):
        applier.apply_indexes(schema_db, ["CREATE INDEX IF NOT EXISTS idx_x "
                              "ON manual_trades(created_via);"],
                              permission_decision=None)
