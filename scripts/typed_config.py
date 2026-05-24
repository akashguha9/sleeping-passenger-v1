"""Typed configuration schema for the local advisory MVP (Integrated Sprint — Part 5).

Centralises the growing env surface in one frozen dataclass so the rest of the
codebase reads typed fields instead of scattered ``os.environ.get`` calls with
different defaults.  Safety-breaking config (advisory_only off, execution_gate
unlocked, human-execution-not-required) fails *fast* at construction time with
:class:`ConfigSafetyError` — there is no "soft" mode that disables the safety
invariants.

The schema is layered *on top of* :mod:`scripts.runtime_config` rather than
replacing it: runtime_config remains the single source for the network/SQLite
knobs the API server has always read; this module adds the *new* fields the
integrated sprint introduces (diagnostics tail budget, source SLAs, AI reports
config, etc.) and re-exposes the safety invariants alongside them.

Contract — pure module
----------------------
No DB, no network, no broker calls.  Construction reads ``os.environ`` once;
:func:`load_typed_config` is monkeypatchable by tests via env overrides.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import runtime_config as _runtime_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import runtime_config as _runtime_config  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfigSafetyError(RuntimeError):
    """Raised when a config value would break the advisory-only safety floor."""


# --- env coercion helpers -------------------------------------------------


def _env(name: str, default: str = "") -> str:
    raw = os.environ.get(name, "")
    return raw.strip() if isinstance(raw, str) else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int | None = None,
             maximum: int | None = None) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    if not raw:
        return default
    return Path(raw).expanduser()


def _env_opt_str(name: str) -> str | None:
    raw = _env(name)
    return raw or None


# --- the schema -----------------------------------------------------------


@dataclass(frozen=True)
class TypedConfig:
    """All sprint-relevant config in one typed object.

    Construction validates the advisory-safety floor; a violation raises
    :class:`ConfigSafetyError` rather than returning a "soft" object.
    """

    # Canonical storage.
    canonical_db_path: Path
    runtime_dir: Path

    # Part 1 — diagnostics tail budget.
    diagnostics_snapshot_ttl_seconds: int
    diagnostics_cold_recompute_budget_ms: int
    diagnostics_hot_cache_budget_ms: int
    diagnostics_max_row_scan_on_cold_path: int

    # Part 2 — provider enables + auth.
    yfinance_enabled: bool
    sec_edgar_enabled: bool
    sec_user_agent: str | None
    gdelt_enabled: bool
    newsapi_enabled: bool
    newsapi_key: str | None

    # Part 3 — source freshness SLAs.
    source_price_sla_hours: int
    source_filings_sla_hours: int
    source_news_sla_hours: int
    source_ai_report_sla_hours: int

    # Part 4 — AI report ingestion.
    ai_reports_enabled: bool
    ai_reports_dir: Path
    model_reliability_ledger_path: Path

    # Safety invariants — NEVER overridable to unsafe values.
    advisory_only: bool
    human_execution_required: bool
    execution_gate: str

    # Free-form labels surfaced to release-gate output for traceability.
    environment_tag: str = "local"
    config_schema_version: str = "1.0.0"

    # Computed convenience fields.
    diagnostics_release_dir: Path = field(init=False)
    business_value_summary_path: Path = field(init=False)
    diagnostics_prewarm_summary_path: Path = field(init=False)
    ai_ingestion_summary_path: Path = field(init=False)
    compliance_dir: Path = field(init=False)
    privacy_inventory_path: Path = field(init=False)
    source_license_register_path: Path = field(init=False)

    def __post_init__(self) -> None:
        # Use object.__setattr__ to bypass frozen=True for derived fields.
        release_dir = self.runtime_dir / "release"
        compliance_dir = self.runtime_dir / "compliance"
        object.__setattr__(self, "diagnostics_release_dir", release_dir)
        object.__setattr__(self, "business_value_summary_path",
                           release_dir / "business_value_summary.json")
        object.__setattr__(self, "diagnostics_prewarm_summary_path",
                           release_dir / "diagnostics_prewarm_summary.json")
        object.__setattr__(self, "ai_ingestion_summary_path",
                           release_dir / "ai_ingestion_summary.json")
        object.__setattr__(self, "compliance_dir", compliance_dir)
        object.__setattr__(self, "privacy_inventory_path",
                           compliance_dir / "privacy_inventory.json")
        object.__setattr__(self, "source_license_register_path",
                           compliance_dir / "source_license_register.json")

        self._validate_safety_floor()

    def _validate_safety_floor(self) -> None:
        if not self.advisory_only:
            raise ConfigSafetyError(
                "ADVISORY_ONLY must be true; refusing to load typed config."
            )
        if not self.human_execution_required:
            raise ConfigSafetyError(
                "HUMAN_EXECUTION_REQUIRED must be true; refusing to load typed config."
            )
        if str(self.execution_gate).upper() != "LOCKED":
            raise ConfigSafetyError(
                "EXECUTION_GATE must be LOCKED; "
                f"got {self.execution_gate!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly view (Paths become strings)."""
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, Path):
                out[key] = str(value)
        out.update(_contract.advisory_safety_stamps())
        return out

    def safety_summary(self) -> dict[str, Any]:
        return {
            "advisory_only": self.advisory_only,
            "human_execution_required": self.human_execution_required,
            "execution_gate": str(self.execution_gate).upper(),
            "broker_api_called": False,
            "ai_execution_count": 0,
            "config_schema_version": self.config_schema_version,
        }


# --- loader ---------------------------------------------------------------


_DEFAULT_RUNTIME = REPO_ROOT / "runtime"
_DEFAULT_DB = _DEFAULT_RUNTIME / "mvp_local.db"
_DEFAULT_AI_REPORTS = REPO_ROOT / "data" / "ai_reports"
_DEFAULT_LEDGER = _DEFAULT_RUNTIME / "model_reliability_ledger.json"


def load_typed_config() -> TypedConfig:
    """Build a :class:`TypedConfig` from the current environment.

    Reads ``os.environ`` fresh so tests can monkeypatch env vars and call
    this again.  Safety-breaking values fail fast via :class:`ConfigSafetyError`.
    """
    return TypedConfig(
        canonical_db_path=_env_path("MVP_DB_PATH", _DEFAULT_DB),
        runtime_dir=_env_path("MVP_RUNTIME_DIR", _DEFAULT_RUNTIME),
        diagnostics_snapshot_ttl_seconds=_env_int(
            "DIAGNOSTICS_SNAPSHOT_TTL_SECONDS", 300, minimum=10, maximum=86400),
        diagnostics_cold_recompute_budget_ms=_env_int(
            "DIAGNOSTICS_COLD_RECOMPUTE_BUDGET_MS", 8000, minimum=100, maximum=120000),
        diagnostics_hot_cache_budget_ms=_env_int(
            "DIAGNOSTICS_HOT_CACHE_BUDGET_MS", 750, minimum=50, maximum=10000),
        diagnostics_max_row_scan_on_cold_path=_env_int(
            "DIAGNOSTICS_MAX_ROW_SCAN_ON_COLD_PATH", 25000, minimum=100, maximum=10_000_000),
        yfinance_enabled=_env_bool("YFINANCE_ENABLED", True),
        sec_edgar_enabled=_env_bool("SEC_EDGAR_ENABLED", True),
        sec_user_agent=_env_opt_str("SEC_USER_AGENT"),
        gdelt_enabled=_env_bool("GDELT_ENABLED", True),
        newsapi_enabled=_env_bool("NEWSAPI_ENABLED", False),
        newsapi_key=_env_opt_str("NEWSAPI_KEY"),
        source_price_sla_hours=_env_int("SOURCE_PRICE_SLA_HOURS", 24,
                                        minimum=1, maximum=720),
        source_filings_sla_hours=_env_int("SOURCE_FILINGS_SLA_HOURS", 72,
                                          minimum=1, maximum=720),
        source_news_sla_hours=_env_int("SOURCE_NEWS_SLA_HOURS", 24,
                                       minimum=1, maximum=720),
        source_ai_report_sla_hours=_env_int("SOURCE_AI_REPORT_SLA_HOURS", 24,
                                            minimum=1, maximum=720),
        ai_reports_enabled=_env_bool("AI_REPORTS_ENABLED", True),
        ai_reports_dir=_env_path("AI_REPORTS_DIR", _DEFAULT_AI_REPORTS),
        model_reliability_ledger_path=_env_path("MODEL_RELIABILITY_LEDGER_PATH",
                                                _DEFAULT_LEDGER),
        advisory_only=_env_bool("ADVISORY_ONLY", True),
        human_execution_required=_env_bool("HUMAN_EXECUTION_REQUIRED", True),
        execution_gate=_env("EXECUTION_GATE") or "LOCKED",
        environment_tag=_runtime_config.get_environment_tag(),
    )


def validate_typed_config(cfg: TypedConfig | None = None) -> dict[str, Any]:
    """Validate typed config and report the result as a dict.

    Used by :mod:`scripts.release_gate` so the gate can surface a single
    ``typed_config_ok`` field plus reasons if the schema rejects.
    """
    try:
        config = cfg if cfg is not None else load_typed_config()
    except ConfigSafetyError as exc:
        return {
            "typed_config_ok": False,
            "reason": str(exc),
            "advisory_only": False,
            **_contract.execution_lock_stamp(),
        }
    return {
        "typed_config_ok": True,
        "reason": "ok",
        "config_schema_version": config.config_schema_version,
        "environment_tag": config.environment_tag,
        **config.safety_summary(),
        **_contract.execution_lock_stamp(),
    }


# --- CLI ------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="typed_config.py",
        description=(
            "Validate and dump the typed configuration schema for the local "
            "advisory MVP. Read-only; no broker calls; no execution."
        ),
    )
    p.add_argument("--validate", action="store_true",
                   help="exit non-zero on safety-floor violation")
    p.add_argument("--json", action="store_true", help="emit JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        cfg = load_typed_config()
    except ConfigSafetyError as exc:
        msg = {"typed_config_ok": False, "reason": str(exc)}
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            print(f"CONFIG REJECTED: {exc}")
        return 2 if args.validate else 1
    payload = cfg.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("Typed Config (advisory-only, read-only)")
        print("=======================================")
        for key in ("canonical_db_path", "runtime_dir",
                    "diagnostics_snapshot_ttl_seconds",
                    "diagnostics_cold_recompute_budget_ms",
                    "diagnostics_hot_cache_budget_ms",
                    "yfinance_enabled", "sec_edgar_enabled", "gdelt_enabled",
                    "source_price_sla_hours", "source_filings_sla_hours",
                    "source_news_sla_hours", "source_ai_report_sla_hours",
                    "ai_reports_enabled",
                    "advisory_only", "human_execution_required",
                    "execution_gate"):
            print(f"  {key:<42} : {payload.get(key)}")
    return 0


__all__ = [
    "TypedConfig",
    "ConfigSafetyError",
    "load_typed_config",
    "validate_typed_config",
]


if __name__ == "__main__":
    raise SystemExit(main())
