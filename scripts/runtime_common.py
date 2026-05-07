from __future__ import annotations

import json
import os
import sys
import time
import uuid
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Runtime artifact coherence layer
# ---------------------------------------------------------------------------
# All runtime/*.json artifacts written in a single pipeline run share a common
# run_id and source_mode. This prevents contradictions like one artifact
# reporting LIVE_ETIL while another reports SYNTHETIC_RUNTIME_FALLBACK.
#
# Design:
#   * RUN_ID is generated once per process. Child processes inherit via env.
#   * _source_mode is a module global, defaulting to SYNTHETIC_RUNTIME_FALLBACK.
#   * stamp_payload() stamps a dict with run_id/source_mode/timestamps.
#   * write_json_atomic() auto-stamps dict payloads; non-dict payloads pass
#     through unchanged (backwards compatible).
#   * append_jsonl() auto-stamps each row.
#
# A downstream coherence test asserts every runtime/*.json shares run_id and
# source_mode after a single pipeline run.

VALID_SOURCE_MODES = {"LIVE_ETIL", "SYNTHETIC_RUNTIME_FALLBACK", "REPLAY"}
VALID_OPERATING_MODES = {"seeded", "hybrid", "live_prepared", "paper_prepared"}
VALID_TRUTH_ORIGIN_TAGS = {
    "seeded",
    "synthetic",
    "placeholder",
    "passive",
    "external",
    "live_ready",
}
VALID_BRIDGE_MODES = {
    "seeded",
    "hybrid_observation",
    "external_candidate_validation",
    "unavailable",
}
TRUTH_ORIGIN_TAG_ORDER = (
    "seeded",
    "synthetic",
    "placeholder",
    "passive",
    "external",
    "live_ready",
)
EXTERNAL_OBSERVATION_FRESHNESS_SECONDS = 6 * 60 * 60

# NOTE: source_mode and run_id are stored in os.environ rather than as simple
# module globals because both `scripts.runtime_common` and `runtime_common`
# can be loaded as distinct module instances in the same process (each has
# its own globals) — see the dual-import fallback in action_engine.py et al.
# Using env vars gives us ONE source of truth shared across all instances.

RUN_ID: str = os.environ.get("PIPELINE_RUN_ID") or uuid.uuid4().hex[:12]
os.environ["PIPELINE_RUN_ID"] = RUN_ID  # propagate to child processes

RUN_STARTED_AT: str = os.environ.get("PIPELINE_RUN_STARTED_AT") or (
    datetime.now(timezone.utc).replace(microsecond=0).isoformat()
)
os.environ["PIPELINE_RUN_STARTED_AT"] = RUN_STARTED_AT

# Initialize env source_mode if unset. Real value is established per-run by
# resolve_source_mode().
if os.environ.get("PIPELINE_SOURCE_MODE") not in VALID_SOURCE_MODES:
    os.environ["PIPELINE_SOURCE_MODE"] = "SYNTHETIC_RUNTIME_FALLBACK"


def set_source_mode(mode: str) -> None:
    """Set the process-wide source_mode. Must be one of VALID_SOURCE_MODES."""
    if mode not in VALID_SOURCE_MODES:
        raise ValueError(
            f"invalid source_mode {mode!r}; must be one of {sorted(VALID_SOURCE_MODES)}"
        )
    os.environ["PIPELINE_SOURCE_MODE"] = mode


def get_source_mode() -> str:
    mode = os.environ.get("PIPELINE_SOURCE_MODE", "SYNTHETIC_RUNTIME_FALLBACK")
    if mode not in VALID_SOURCE_MODES:
        mode = "SYNTHETIC_RUNTIME_FALLBACK"
    return mode


def get_run_id() -> str:
    rid = os.environ.get("PIPELINE_RUN_ID")
    return rid if rid else RUN_ID


def get_run_started_at() -> str:
    return os.environ.get("PIPELINE_RUN_STARTED_AT", RUN_STARTED_AT)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _detect_git_commit_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "--no-pager", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


_GIT_COMMIT_HASH = _detect_git_commit_hash()


def get_git_commit_hash() -> str | None:
    return _GIT_COMMIT_HASH


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _external_observation_state(
    runtime_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = runtime_payload if isinstance(runtime_payload, dict) else {}
    explicit_active = bool(payload.get("external_observation_active", False))
    explicit_source = str(
        payload.get("external_observation_source") or "yahoo_finance"
    ).strip() or "yahoo_finance"
    explicit_fetched_at = (
        payload.get("external_observation_fetched_at")
        or payload.get("fetched_at")
        or payload.get("artifact_written_at")
    )
    if explicit_active:
        observed_at = _parse_iso_timestamp(explicit_fetched_at)
        return {
            "active": True,
            "provider": explicit_source,
            "resolved_provider": explicit_source,
            "observed_at": observed_at.isoformat() if observed_at else explicit_fetched_at,
            "staleness_classification": "fresh" if observed_at else "unknown",
        }
    return {
        "active": False,
        "provider": "yahoo",
        "resolved_provider": "yahoo_placeholder",
        "observed_at": None,
        "staleness_classification": "inactive_until_explicit_runtime_attachment",
    }


def _quote_provider_state(runtime_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    external_state = _external_observation_state(runtime_payload)
    if external_state["active"]:
        requested_provider = str(external_state["provider"]).strip().lower()
        resolved_provider = str(external_state["resolved_provider"]).strip().lower()
        return {
            "requested_provider": requested_provider,
            "resolved_provider": resolved_provider,
            "live_quotes_available": True,
            "contract_state": "external_observation",
        }

    try:
        from scripts.market_data_adapter import describe_market_data_adapter
    except ModuleNotFoundError:
        try:
            from market_data_adapter import describe_market_data_adapter
        except ModuleNotFoundError:
            describe_market_data_adapter = None

    provider = os.environ.get("PIPELINE_QUOTE_PROVIDER")
    if describe_market_data_adapter is None:
        requested_provider = (provider or "yahoo").strip().lower()
        return {
            "requested_provider": requested_provider,
            "resolved_provider": f"{requested_provider}_placeholder",
            "live_quotes_available": False,
            "contract_state": "placeholder",
        }

    description = describe_market_data_adapter(provider)
    if not isinstance(description, dict):
        description = {}
    requested_provider = str(description.get("requested_provider") or provider or "yahoo").strip().lower()
    resolved_provider = str(
        description.get("resolved_provider") or f"{requested_provider}_placeholder"
    ).strip()
    live_quotes_available = bool(description.get("live_quotes_available", False))
    contract_state = str(description.get("contract_state") or "").strip().lower()
    if not contract_state:
        contract_state = "live_ready" if live_quotes_available else "placeholder"
    return {
        "requested_provider": requested_provider,
        "resolved_provider": resolved_provider,
        "live_quotes_available": live_quotes_available,
        "contract_state": contract_state,
    }


def build_deployment_permissions(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = payload
    paper_execution_enabled = _env_flag("PIPELINE_ENABLE_PAPER_EXECUTION", default=False)
    live_execution_enabled = _env_flag("PIPELINE_ENABLE_LIVE_EXECUTION", default=False)
    return {
        "paper_execution_enabled": paper_execution_enabled,
        "live_execution_enabled": live_execution_enabled,
        "can_emit_paper_actions": paper_execution_enabled,
        "can_emit_live_actions": live_execution_enabled,
    }


def classify_operating_mode(payload: dict[str, Any] | None = None) -> str:
    runtime_payload = payload if isinstance(payload, dict) else {}
    source_mode = str(runtime_payload.get("source_mode") or get_source_mode()).upper()
    quote_state = _quote_provider_state(runtime_payload)
    deployment = build_deployment_permissions(runtime_payload)
    external_observation_active = bool(quote_state["live_quotes_available"]) or source_mode == "LIVE_ETIL"

    if deployment["live_execution_enabled"] and external_observation_active:
        return "live_prepared"
    if external_observation_active:
        return "hybrid"
    if deployment["paper_execution_enabled"]:
        return "paper_prepared"
    return "seeded"


def build_truth_context(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_payload = payload if isinstance(payload, dict) else {}
    simulation_context = runtime_payload.get("simulation_context", {})
    if not isinstance(simulation_context, dict):
        simulation_context = {}
    source_mode = str(runtime_payload.get("source_mode") or get_source_mode()).upper()
    quote_state = _quote_provider_state(runtime_payload)
    deployment = build_deployment_permissions(runtime_payload)
    operating_mode = classify_operating_mode(runtime_payload)

    tags: list[str] = []
    truth_origin = "seeded"

    if source_mode == "REPLAY" or str(runtime_payload.get("source") or "").lower() == "runtime_files":
        tags.append("passive")
    if simulation_context.get("is_simulated"):
        truth_origin = "synthetic"
        tags.append("synthetic")
    elif deployment["live_execution_enabled"] and (
        quote_state["live_quotes_available"] or source_mode == "LIVE_ETIL"
    ):
        truth_origin = "live_ready"
        tags.extend(["external", "live_ready"])
    elif quote_state["live_quotes_available"] or source_mode == "LIVE_ETIL":
        truth_origin = "external"
        tags.append("external")
    else:
        truth_origin = "seeded"
        tags.append("seeded")

    if quote_state["contract_state"] == "placeholder":
        tags.append("placeholder")

    ordered_tags = [
        tag for tag in TRUTH_ORIGIN_TAG_ORDER
        if tag in set(tags) and tag in VALID_TRUTH_ORIGIN_TAGS
    ]
    return {
        "operating_mode": operating_mode,
        "truth_origin": truth_origin,
        "truth_origin_tags": ordered_tags,
        "source_mode": source_mode,
        "quote_provider": quote_state["requested_provider"],
        "quote_provider_state": quote_state["contract_state"],
        "live_quotes_available": quote_state["live_quotes_available"],
    }


def resolve_bridge_mode(
    *,
    include_external_observations: bool,
    external_candidate_bridge_enabled: bool,
    external_observation_active: bool,
    external_observation_valid_count: int,
    external_candidate_count: int,
    scm_external_row_count: int,
    paper_candidate_count: int,
    provider_error_count: int,
) -> dict[str, Any]:
    """Resolve the bounded external-bridge runtime mode.

    Contract:
      * seeded: no external observation mode requested
      * hybrid_observation: external observations active, but no SCM
        candidate admission
      * external_candidate_validation: valid external observations admitted
        into SCM candidate rows and paper-safe candidates
      * unavailable: external mode requested but no valid external
        observations survived provider/data-quality checks
    """
    valid_count = max(int(external_observation_valid_count or 0), 0)
    candidate_count = max(int(external_candidate_count or 0), 0)
    external_rows = max(int(scm_external_row_count or 0), 0)
    paper_candidates = max(int(paper_candidate_count or 0), 0)
    errors = max(int(provider_error_count or 0), 0)

    if not include_external_observations:
        return {
            "bridge_mode": "seeded",
            "bridge_mode_reason": "no external observation mode requested",
            "bridge_mode_safety_state": "paper_safe_only",
        }

    if valid_count <= 0 or not external_observation_active:
        return {
            "bridge_mode": "unavailable",
            "bridge_mode_reason": (
                "external mode requested but provider returned zero valid observations"
            ),
            "bridge_mode_safety_state": "fail_closed",
        }

    if (
        external_candidate_bridge_enabled
        and candidate_count > 0
        and external_rows > 0
    ):
        return {
            "bridge_mode": "external_candidate_validation",
            "bridge_mode_reason": (
                "valid external observations admitted as SCM candidate rows"
            ),
            "bridge_mode_safety_state": "paper_safe_only",
        }

    if errors > 0 and valid_count <= 0:
        return {
            "bridge_mode": "unavailable",
            "bridge_mode_reason": (
                "external mode requested but provider returned zero valid observations"
            ),
            "bridge_mode_safety_state": "fail_closed",
        }

    return {
        "bridge_mode": "hybrid_observation",
        "bridge_mode_reason": (
            "external observations active but no external candidates admitted into SCM"
        ),
        "bridge_mode_safety_state": "paper_safe_only",
    }


def compute_config_fingerprint(config_paths: list[Path] | None = None) -> str:
    paths = config_paths or [
        SIGNAL_REFINERY_CONFIG_PATH,
        PERCEPTION_CONTROL_CONFIG_PATH,
        BLOCKER_WEIGHTS_PATH,
        EXECUTION_GOVERNANCE_CONFIG_PATH,
        EXPERIENCE_MODE_CONFIG_PATH,
        ENVIRONMENT_FIT_CONFIG_PATH,
        OPERATOR_CONTROL_CONFIG_PATH,
        STRUCTURAL_COVER_MAP_PATH,
        ARCHETYPE_REGISTRY_PATH,
        EXTERNAL_DATA_CONFIG_PATH,
        LLM_PROVIDER_CONFIG_PATH,
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(repo_relative(path).encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    for key in (
        "PIPELINE_QUOTE_PROVIDER",
        "PIPELINE_ENABLE_PAPER_EXECUTION",
        "PIPELINE_ENABLE_LIVE_EXECUTION",
    ):
        digest.update(key.encode("utf-8"))
        digest.update(b"=")
        digest.update(os.environ.get(key, "").encode("utf-8"))
    return digest.hexdigest()[:12]


def resolve_source_mode(
    etil_input_path: Path | None = None,
    freshness_seconds: int = 900,
) -> str:
    """Determine source_mode from presence/freshness of the ETIL input file.

    LIVE_ETIL only when the file exists, is fresh, and contains at least one
    signal input row. Empty ETIL payloads are treated as synthetic fallback so
    stale/placeholder artifacts do not silently flip the repo into external mode.
    """
    if etil_input_path is None:
        etil_input_path = SIGNAL_VOCODER_ETIL_INPUTS_PATH
    try:
        if etil_input_path.exists():
            age = time.time() - etil_input_path.stat().st_mtime
            if age <= freshness_seconds:
                payload = load_json_file(etil_input_path, default={}) or {}
                signal_rows = []
                if isinstance(payload, dict):
                    candidate_rows = payload.get("signal_inputs")
                    if isinstance(candidate_rows, list):
                        signal_rows = candidate_rows
                elif isinstance(payload, list):
                    signal_rows = payload
                has_signal_rows = any(
                    isinstance(row, dict)
                    and str(
                        row.get("ticker")
                        or row.get("symbol")
                        or row.get("signal_id")
                        or ""
                    ).strip()
                    for row in signal_rows
                )
                mode = "LIVE_ETIL" if has_signal_rows else "SYNTHETIC_RUNTIME_FALLBACK"
            else:
                mode = "SYNTHETIC_RUNTIME_FALLBACK"
        else:
            mode = "SYNTHETIC_RUNTIME_FALLBACK"
    except OSError:
        mode = "SYNTHETIC_RUNTIME_FALLBACK"
    set_source_mode(mode)
    return mode


def stamp_payload(
    payload: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp a runtime artifact payload with run_id/source_mode/timestamps.

    Caller-supplied run_id/source_mode are overwritten — those are authoritative
    from this process. Other keys are preserved. Reads run_id/source_mode from
    os.environ so dual-imported module instances stay coherent.
    """
    stamped = dict(payload)
    metadata_context = runtime_state if isinstance(runtime_state, dict) else stamped
    truth_context = build_truth_context(metadata_context)
    stamped["run_id"] = get_run_id()
    stamped["source_mode"] = get_source_mode()
    stamped.setdefault("run_started_at", get_run_started_at())
    stamped["artifact_written_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    stamped["operating_mode"] = truth_context["operating_mode"]
    stamped["truth_origin"] = truth_context["truth_origin"]
    stamped["truth_origin_tags"] = truth_context["truth_origin_tags"]
    stamped["commit_hash"] = get_git_commit_hash()
    stamped["config_fingerprint"] = compute_config_fingerprint()
    return stamped

MOLTBOOK_DIR = REPO_ROOT / "moltbook"
OPEN_POSITIONS_PATH = MOLTBOOK_DIR / "open_positions.json"
SIGNAL_LEDGER_PATH = MOLTBOOK_DIR / "signal_ledger.json"

LOG_DIR = REPO_ROOT / "logs"
SNAPSHOT_LOG_PATH = LOG_DIR / "system_snapshots.jsonl"

RUNTIME_DIR = REPO_ROOT / "runtime"
SCM_REPORT_PATH = RUNTIME_DIR / "scm_report.json"
DERIVED_GATE_STATES_PATH = RUNTIME_DIR / "derived_gate_states.json"
EXECUTION_POLICY_PATH = RUNTIME_DIR / "execution_policy.json"
PER_SIGNAL_ATTRIBUTION_PATH = RUNTIME_DIR / "per_signal_attribution.json"
ACTION_REPORT_PATH = RUNTIME_DIR / "action_report.json"
GOVERNANCE_FEEDBACK_REPORT_PATH = RUNTIME_DIR / "governance_feedback_report.json"
BLOCKER_COST_REPORT_PATH = RUNTIME_DIR / "blocker_cost_report.json"
TREND_REPORT_PATH = RUNTIME_DIR / "trend_report.json"
HEALTH_REPORT_PATH = RUNTIME_DIR / "pipeline_health_report.json"
FOOTBALL_PORTFOLIO_ARCHETYPE_REPORT_PATH = RUNTIME_DIR / "football_portfolio_archetype_report.json"
FIELD_DYNAMICS_REPORT_PATH = RUNTIME_DIR / "field_dynamics_report.json"
SIGNAL_METABOLISM_REPORT_PATH = RUNTIME_DIR / "signal_metabolism_report.json"
FALSE_NEGATIVE_CASINO_MONOPOLY_REPORT_PATH = (
    RUNTIME_DIR / "false_negative_casino_monopoly_layer_report.json"
)
STRUCTURAL_DESIGN_REPORT_PATH = RUNTIME_DIR / "structural_design_report.json"
STRUCTURAL_ADMISSION_REPORT_PATH = RUNTIME_DIR / "structural_admission_report.json"
LATENT_SIGNAL_RELEASE_REPORT_PATH = RUNTIME_DIR / "latent_signal_release_report.json"
SIGNAL_TEXTURE_REPORT_PATH = RUNTIME_DIR / "signal_texture_report.json"
OPPORTUNITY_HALF_LIFE_REPORT_PATH = RUNTIME_DIR / "opportunity_half_life_report.json"
VALIDATION_BUFFER_REPORT_PATH = RUNTIME_DIR / "validation_buffer_report.json"
SIGNAL_ZETA_REPORT_PATH = RUNTIME_DIR / "signal_zeta_report.json"
FALSE_CONVICTION_REPORT_PATH = RUNTIME_DIR / "false_conviction_report.json"
COLLAPSE_ANALYSIS_REPORT_PATH = RUNTIME_DIR / "collapse_analysis_report.json"
MURCIELAGO_DURABILITY_REPORT_PATH = RUNTIME_DIR / "murcielago_durability_report.json"
AVENTADOR_PROMOTION_REPORT_PATH = RUNTIME_DIR / "aventador_promotion_report.json"
GALLARDO_EXECUTION_REPORT_PATH = RUNTIME_DIR / "gallardo_execution_report.json"
BULL_STATE_REPORT_PATH = RUNTIME_DIR / "bull_state_report.json"
BULL_TRANSITION_LOG_PATH = RUNTIME_DIR / "bull_transition_log.json"
ARCHETYPE_PROFILE_REPORT_PATH = RUNTIME_DIR / "archetype_profile_report.json"
CLOSURE_DEFICIT_REPORT_PATH = RUNTIME_DIR / "closure_deficit_report.json"
EXPERIENCE_MODE_REPORT_PATH = RUNTIME_DIR / "experience_mode_report.json"
ENVIRONMENT_FIT_REPORT_PATH = RUNTIME_DIR / "environment_fit_report.json"
COMPLEXITY_LADDER_CONTROLLER_PATH = RUNTIME_DIR / "complexity_ladder_controller.json"
SIGNAL_REFINERY_REPORT_PATH = RUNTIME_DIR / "signal_refinery_report.json"
PERCEPTION_CONTROL_REPORT_PATH = RUNTIME_DIR / "perception_control_report.json"
ATTENTION_PROXY_REPORT_PATH = RUNTIME_DIR / "attention_proxy_report.json"
MOLTBOOK_FEEDBACK_SUMMARY_PATH = RUNTIME_DIR / "moltbook_feedback_summary.json"
SIGNAL_GATE_SUMMARY_PATH = RUNTIME_DIR / "signal_gate_summary.json"
EXTREME_STATE_REPORT_PATH = RUNTIME_DIR / "extreme_state_report.json"
OPERATOR_STATE_PATH = RUNTIME_DIR / "operator_state.json"
ACTIVE_WORK_BLOCK_PATH = RUNTIME_DIR / "active_work_block.json"
OPERATOR_PHASE_BALANCE_PATH = RUNTIME_DIR / "operator_phase_balance.json"
OPERATOR_PHASE_REPORT_PATH = RUNTIME_DIR / "operator_phase_report.json"
PAPER_POSITIONS_PATH = RUNTIME_DIR / "paper_positions.json"
EXTERNAL_MARKS_PATH = RUNTIME_DIR / "external_market_marks.json"
PAPER_RETIREMENT_REPORT_PATH = RUNTIME_DIR / "paper_retirement_report.json"
MODEL_UPGRADE_REPORT_PATH = RUNTIME_DIR / "model_upgrade_report.json"
PAPER_RECONCILIATION_REPORT_PATH = RUNTIME_DIR / "paper_reconciliation_report.json"
PAPER_RECONCILIATION_SUMMARY_PATH = RUNTIME_DIR / "paper_reconciliation_summary.json"
POLYMARKET_GAMMA_REPORT_PATH = RUNTIME_DIR / "polymarket_gamma_report.json"
POLYMARKET_DATA_REPORT_PATH = RUNTIME_DIR / "polymarket_data_report.json"
POLYMARKET_CLOB_REPORT_PATH = RUNTIME_DIR / "polymarket_clob_report.json"
BLOCKSCOUT_REPORT_PATH = RUNTIME_DIR / "blockscout_report.json"
EXTERNAL_DATA_REPORT_PATH = RUNTIME_DIR / "external_data_report.json"
GROK_XAI_REPORT_PATH = RUNTIME_DIR / "grok_xai_report.json"
SIGNAL_VOCODER_ETIL_INPUTS_PATH = RUNTIME_DIR / "signal_vocoder_etil_inputs.json"
QUOTE_CACHE_DIR = RUNTIME_DIR / "quote_cache"

PAPER_DECISION_LEDGER_PATH = LOG_DIR / "paper_decisions.jsonl"
PAPER_ORDER_LEDGER_PATH = LOG_DIR / "paper_orders.jsonl"
PAPER_FILL_LEDGER_PATH = LOG_DIR / "paper_fills.jsonl"
PAPER_CLOSE_LEDGER_PATH = LOG_DIR / "paper_closes.jsonl"
OPERATOR_OVERRIDE_LEDGER_PATH = LOG_DIR / "operator_overrides.jsonl"
OPERATOR_FEEDBACK_LEDGER_PATH = LOG_DIR / "operator_quality_feedback.jsonl"
MODEL_FEEDBACK_LEDGER_PATH = LOG_DIR / "model_quality_feedback.jsonl"
INTERACTION_FEEDBACK_LEDGER_PATH = LOG_DIR / "interaction_quality_feedback.jsonl"
POST_TRADE_FEEDBACK_PATH = LOG_DIR / "post_trade_feedback.jsonl"
PAPER_RECONCILIATION_HISTORY_PATH = LOG_DIR / "paper_reconciliation_history.jsonl"
MOLTBOOK_FEEDBACK_CASES_PATH = RUNTIME_DIR / "moltbook_feedback_cases.jsonl"
SIGNAL_KILL_LOG_PATH = LOG_DIR / "signal_kill_log.jsonl"
OPERATOR_BLOCK_EVENTS_PATH = LOG_DIR / "operator_block_events.jsonl"

CONFIG_DIR = REPO_ROOT / "config"
BLOCKER_WEIGHTS_PATH = CONFIG_DIR / "blocker_weights.json"
SIGNAL_REFINERY_CONFIG_PATH = CONFIG_DIR / "signal_refinery_config.json"
PERCEPTION_CONTROL_CONFIG_PATH = CONFIG_DIR / "perception_control_config.json"
EXECUTION_GOVERNANCE_CONFIG_PATH = CONFIG_DIR / "execution_governance_config.json"
EXPERIENCE_MODE_CONFIG_PATH = CONFIG_DIR / "experience_mode_config.json"
ENVIRONMENT_FIT_CONFIG_PATH = CONFIG_DIR / "environment_fit_config.json"
OPERATOR_CONTROL_CONFIG_PATH = CONFIG_DIR / "operator_control_config.json"
STRUCTURAL_COVER_MAP_PATH = CONFIG_DIR / "structural_cover_map.json"
ARCHETYPE_REGISTRY_PATH = CONFIG_DIR / "archetype_registry.json"
EXTERNAL_DATA_CONFIG_PATH = CONFIG_DIR / "external_data_config.json"
LLM_PROVIDER_CONFIG_PATH = CONFIG_DIR / "llm_provider_config.json"

OPEN_POSITION_REQUIRED_KEYS = {
    "ticker",
    "entry_price",
    "current_price",
    "pnl_pct",
    "position_size",
    "state",
    "chaos_flag",
    "entry_type",
    "thesis_cluster",
    "stop_loss",
    "take_profit",
    "time_in_trade",
    "priority_score",
}
OPEN_POSITION_STATES = {"OPEN", "REDUCED", "EXIT_PENDING", "CLOSED"}
OPEN_POSITION_ENTRY_TYPES = {"CLEAN", "CHAOS"}

POLICY_STATE_RANK = {
    "BLOCKED": 0,
    "DO_NOT_DEPLOY": 0,
    "RESTRICTED": 1,
    "NOT_READY": 1,
    "LIMITED_DEPLOY": 2,
    "PARTIAL": 2,
    "REVIEW_READY": 2,
    "NORMAL": 3,
    "UNRESTRICTED": 3,
    "READY": 3,
}
PERMISSIVE_POLICY_STATES = {
    "READY",
    "UNRESTRICTED",
    "NORMAL",
    "LIMITED_DEPLOY",
    "REVIEW_READY",
}


def repo_relative(path: Path) -> str:
    """Return a repo-relative, POSIX-separator-normalized path string.

    POSIX form (forward slashes) keeps runtime artifacts and diagnostic
    messages byte-identical across Windows and Linux, so pytest assertions
    and generated JSON don't need platform-specific branches.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return default
    return json.loads(raw)


def write_json_atomic(path: Path, payload: Any, stamp: bool = True) -> None:
    """Write payload to path atomically.

    When payload is a dict and stamp is True (default), run_id/source_mode/
    timestamps are stamped onto it via stamp_payload() to enforce runtime
    artifact coherence. Non-dict payloads are written as-is for backwards
    compatibility.
    """
    ensure_directory(path.parent)
    effective_payload = (
        stamp_payload(payload) if stamp and isinstance(payload, dict) else payload
    )
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(effective_payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def write_runtime_artifact(path: Path, payload: dict[str, Any]) -> None:
    """Preferred public API: atomic dict write with coherence stamping.

    Thin wrapper around write_json_atomic(..., stamp=True) to make intent
    explicit at call sites.
    """
    if not isinstance(payload, dict):
        raise TypeError("write_runtime_artifact requires a dict payload")
    write_json_atomic(path, payload, stamp=True)


def append_jsonl(path: Path, row: dict[str, Any], stamp: bool = True) -> None:
    """Append one JSON row to a .jsonl file.

    When stamp is True (default), run_id/source_mode/timestamps are added to
    the row so snapshot/log streams are coherent with other runtime artifacts.
    """
    ensure_directory(path.parent)
    effective_row = stamp_payload(row) if stamp and isinstance(row, dict) else row
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(effective_row, separators=(",", ":")) + "\n")


def _coerce_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def normalize_active_blockers(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return sorted({_text(item) for item in payload if _text(item)})
    if isinstance(payload, dict):
        if isinstance(payload.get("active_blockers"), list):
            return normalize_active_blockers(payload["active_blockers"])
        blockers = []
        for key, value in payload.items():
            if isinstance(value, bool) and value:
                blockers.append(str(key))
        return sorted(set(blockers))
    return []


def normalize_gate_state_map(payload: Any) -> dict[str, bool]:
    blockers = normalize_active_blockers(payload)
    if isinstance(payload, dict) and "active_blockers" not in payload:
        result = {}
        for key, value in payload.items():
            if isinstance(value, bool):
                result[str(key)] = value
        for blocker in blockers:
            result[blocker] = True
        return result
    return {blocker: True for blocker in blockers}


def normalize_execution_policy(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("execution_policy"), dict):
        payload = payload["execution_policy"]
    if isinstance(payload, dict):
        raw_state = (
            payload.get("policy_state")
            or payload.get("state")
            or payload.get("execution_policy")
            or "UNKNOWN"
        )
        policy_state = _text(raw_state, "UNKNOWN").upper()
        allow_new_risk = payload.get("allow_new_risk")
        if allow_new_risk is None:
            allow_new_risk = policy_state in PERMISSIVE_POLICY_STATES
        allow_clean_entries = payload.get("allow_clean_entries")
        if allow_clean_entries is None:
            allow_clean_entries = _coerce_bool(allow_new_risk, False)
        allow_chaos_entries = payload.get("allow_chaos_entries")
        if allow_chaos_entries is None:
            allow_chaos_entries = _coerce_bool(allow_new_risk, False)
        return {
            "policy_state": policy_state,
            "position_sizing_cap": _text(payload.get("position_sizing_cap"), "SYSTEM_DEFAULT"),
            "allow_clean_entries": _coerce_bool(allow_clean_entries, False),
            "allow_chaos_entries": _coerce_bool(allow_chaos_entries, False),
            "allow_new_risk": _coerce_bool(allow_new_risk, False),
            "allow_only_exits_and_reductions": _coerce_bool(
                payload.get("allow_only_exits_and_reductions"),
                policy_state in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"},
            ),
            "retain_watchlist_names": _coerce_bool(payload.get("retain_watchlist_names"), False),
            "chaos_entries_forbidden": _coerce_bool(
                payload.get("chaos_entries_forbidden"),
                not _coerce_bool(allow_chaos_entries, False),
            ),
            "watchlist_action": _text(payload.get("watchlist_action"), "MONITOR"),
            "required_clearance_gates": [
                _text(item)
                for item in payload.get("required_clearance_gates", [])
                if _text(item)
            ],
            "blocked_entry_states": [
                _text(item)
                for item in payload.get("blocked_entry_states", [])
                if _text(item)
            ],
            "next_priority_action": _text(
                payload.get("next_priority_action"), "MONITOR_CONVERSION"
            ),
            "minimum_conditions_to_improve": [
                _text(item)
                for item in payload.get("minimum_conditions_to_improve", [])
                if _text(item)
            ],
            "rationale": [
                _text(item)
                for item in payload.get("rationale", [])
                if _text(item)
            ],
        }
    if isinstance(payload, str):
        return normalize_execution_policy({"policy_state": payload})
    return normalize_execution_policy({"policy_state": "UNKNOWN"})


def _infer_entry_type(row: dict[str, Any]) -> str:
    explicit = _text(row.get("entry_type")).upper()
    if explicit in OPEN_POSITION_ENTRY_TYPES:
        return explicit
    status = _text(row.get("status")).upper()
    state = _text(row.get("state")).upper()
    conversion_state = _text(row.get("conversion_state")).upper()
    if "CHAOS" in explicit or "CHAOS" in status or "CHAOS" in state or "CHAOS" in conversion_state:
        return "CHAOS"
    if "CLEAN" in explicit or "CLEAN" in status or "CLEAN" in state or "CLEAN" in conversion_state:
        return "CLEAN"
    return "UNKNOWN"


def _infer_signal_state(row: dict[str, Any]) -> str:
    for key in ("signal_state", "state", "status", "conversion_state"):
        value = _text(row.get(key)).upper()
        if not value:
            continue
        if value in {"WATCHLIST", "NOT_EXECUTED"}:
            return "WATCHLIST"
        if value in {"EXECUTED_CLEAN", "EXECUTED_CHAOS", "ACTIVE", "CLEAN_ENTRY", "CHAOS_ENTRY"}:
            return "ACTIVE"
        if value == "REJECTED":
            return "REJECTED"
        return value
    return "UNKNOWN"


def _extract_watchlist_diagnostics_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}

    diagnostics = payload.get("watchlist_diagnostics")
    if not isinstance(diagnostics, dict):
        return {}

    watchlist_rows = diagnostics.get("watchlist_signals")
    if not isinstance(watchlist_rows, list):
        return {}

    diagnostics_map: dict[str, dict[str, Any]] = {}
    for row in watchlist_rows:
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker")).upper()
        if signal_id:
            diagnostics_map[signal_id] = row
        if ticker:
            diagnostics_map[ticker] = row
    return diagnostics_map


def normalize_per_signal_rows(payload: Any) -> list[dict[str, Any]]:
    rows_payload = payload
    watchlist_diagnostics_map = _extract_watchlist_diagnostics_map(payload)
    if isinstance(payload, dict):
        for key in ("per_signal_attribution", "signals", "rows"):
            if isinstance(payload.get(key), list):
                rows_payload = payload[key]
                break
    if not isinstance(rows_payload, list):
        return []

    rows: list[dict[str, Any]] = []
    for row in rows_payload:
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker") or row.get("symbol")).upper()
        if not ticker:
            continue

        blocker = _text(row.get("blocker_attribution"), "NONE").upper()
        signal_state = _infer_signal_state(row)
        entry_type = _infer_entry_type(row)
        watchlist_diagnostics = (
            watchlist_diagnostics_map.get(signal_id)
            or watchlist_diagnostics_map.get(ticker)
            or {}
        )
        explicit_watchlist_tier = _text(
            row.get("watchlist_tier"),
            _text(watchlist_diagnostics.get("watchlist_tier")),
        ).upper()
        explicit_candidate_conversion_state = _text(
            row.get("candidate_conversion_state"),
            _text(watchlist_diagnostics.get("candidate_conversion_state")),
        ).upper()
        explicit_pre_entry_state = _text(
            row.get("pre_entry_state"),
            _text(watchlist_diagnostics.get("pre_entry_state")),
        ).upper()
        if (
            blocker == "NONE"
            and signal_state == "WATCHLIST"
            and not explicit_watchlist_tier
            and not explicit_candidate_conversion_state
            and not explicit_pre_entry_state
        ):
            blocker = "GSCE_PHASE_LOCK"

        promotable_clean_candidate = _coerce_bool(
            row.get("promotable_clean_candidate"),
            _coerce_bool(watchlist_diagnostics.get("promotable_clean_candidate"), False),
        )
        watchlist_tier = _text(
            row.get("watchlist_tier"),
            explicit_watchlist_tier,
        ).upper()
        candidate_conversion_state = _text(
            row.get("candidate_conversion_state"),
            explicit_candidate_conversion_state,
        ).upper()
        pre_entry_state = _text(
            row.get("pre_entry_state"),
            explicit_pre_entry_state or "NONE",
        ).upper()

        if signal_state == "WATCHLIST":
            if not watchlist_tier:
                watchlist_tier = "PROMOTABLE" if promotable_clean_candidate else "STANDARD"
            if not candidate_conversion_state:
                candidate_conversion_state = (
                    "PROMOTABLE_WATCHLIST" if promotable_clean_candidate else "NOT_EXECUTED"
                )
            if not pre_entry_state or pre_entry_state == "NONE":
                if promotable_clean_candidate and blocker == "GSCE_PHASE_LOCK":
                    pre_entry_state = "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
                else:
                    pre_entry_state = "NONE"
        else:
            if not watchlist_tier:
                watchlist_tier = "NONE"
            if not candidate_conversion_state:
                candidate_conversion_state = _text(row.get("conversion_state"), signal_state).upper()
            if not pre_entry_state:
                pre_entry_state = "NONE"

        rows.append(
            {
                "signal_id": signal_id,
                "ticker": ticker,
                "entry_type": entry_type,
                "signal_state": signal_state,
                "status": _text(
                    row.get("status") or row.get("state") or row.get("conversion_state"),
                    signal_state,
                ).upper(),
                "blocker_attribution": blocker,
                "priority_score": _coerce_number(
                    row.get("priority_score", row.get("ce_score", row.get("priority", 0.0)))
                ),
                "ce_score": _coerce_number(
                    row.get("ce_score", row.get("priority_score", 0.0))
                ),
                "promotable_clean_candidate": promotable_clean_candidate,
                "watchlist_tier": watchlist_tier,
                "candidate_conversion_state": candidate_conversion_state,
                "pre_entry_state": pre_entry_state,
                "source_name": _text(row.get("source_name") or row.get("source")),
                "signal_origin": _text(row.get("signal_origin")),
                "origin_label": _text(row.get("origin_label")),
                "condition_id": _text(row.get("condition_id") or row.get("conditionId")),
                "question": _text(row.get("question")),
            }
        )
    rows.sort(key=lambda item: (item["ticker"], -item["priority_score"], item["signal_id"]))
    return rows


def build_signal_summary_from_rows(
    rows: list[dict[str, Any]],
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    seed = seed or {}
    status_counts: dict[str, int] = {}
    qualifying_ids = []
    for row in rows:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if row["signal_id"]:
            qualifying_ids.append(row["signal_id"])
    summary = {
        "signal_count_total": int(seed.get("signal_count_total", len(rows))),
        "signals_above_ce_threshold": int(seed.get("signals_above_ce_threshold", len(rows))),
        "qualifying_signal_ids": seed.get("qualifying_signal_ids", qualifying_ids),
        "status_counts_above_threshold": seed.get("status_counts_above_threshold", status_counts),
        "qualifying_signals": seed.get("qualifying_signals", rows),
    }
    if summary["signal_count_total"] < summary["signals_above_ce_threshold"]:
        summary["signal_count_total"] = summary["signals_above_ce_threshold"]
    return summary


def normalize_scm_review(
    payload: Any, active_blockers: list[str] | None = None
) -> dict[str, Any]:
    active_blockers = active_blockers or []
    review_source = payload
    if isinstance(payload, dict) and isinstance(payload.get("scm_review"), dict):
        review_source = payload["scm_review"]
    if isinstance(review_source, dict):
        diagnosis = review_source.get("diagnosis")
        if diagnosis is None and active_blockers:
            diagnosis = active_blockers
        elif isinstance(diagnosis, str):
            diagnosis = [diagnosis]
        elif not isinstance(diagnosis, list):
            diagnosis = []
        return {
            "scm_rate": round(_coerce_number(review_source.get("scm_rate"), 0.0), 3),
            "scm_state": _text(review_source.get("scm_state"), "UNKNOWN").upper(),
            "diagnosis": [_text(item).upper() for item in diagnosis if _text(item)],
            "gap_type": _text(review_source.get("gap_type"), "UNKNOWN"),
        }
    return {
        "scm_rate": 0.0,
        "scm_state": "UNKNOWN",
        "diagnosis": active_blockers,
        "gap_type": "UNKNOWN",
    }


def load_open_positions_payload(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_json_file(path or OPEN_POSITIONS_PATH, default=[])
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("open_positions.json must contain a top-level JSON array")
    return payload


def validate_open_positions_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return ["open_positions.json must contain a top-level JSON array"]
    price_fields = {
        "entry_price",
        "current_price",
        "pnl_pct",
        "stop_loss",
        "take_profit",
        "priority_score",
    }
    for index, item in enumerate(payload):
        context = f"open_positions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{context} must be an object")
            continue
        missing = sorted(OPEN_POSITION_REQUIRED_KEYS - set(item.keys()))
        if missing:
            errors.append(f"{context} missing keys: {missing}")
            continue
        ticker = _text(item.get("ticker")).upper()
        if not ticker:
            errors.append(f"{context}.ticker must be a non-empty string")
        if _text(item.get("state")).upper() not in OPEN_POSITION_STATES:
            errors.append(
                f"{context}.state must be one of {sorted(OPEN_POSITION_STATES)}"
            )
        if _text(item.get("entry_type")).upper() not in OPEN_POSITION_ENTRY_TYPES:
            errors.append(
                f"{context}.entry_type must be one of {sorted(OPEN_POSITION_ENTRY_TYPES)}"
            )
        if not isinstance(item.get("chaos_flag"), bool):
            errors.append(f"{context}.chaos_flag must be boolean")
        if not isinstance(item.get("time_in_trade"), str) or not item["time_in_trade"].strip():
            errors.append(f"{context}.time_in_trade must be a non-empty string")
        if not isinstance(item.get("position_size"), str) or not item["position_size"].strip():
            errors.append(f"{context}.position_size must be a non-empty string")
        if (
            not isinstance(item.get("thesis_cluster"), str)
            or not item["thesis_cluster"].strip()
        ):
            errors.append(f"{context}.thesis_cluster must be a non-empty string")
        for field in price_fields:
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{context}.{field} must be numeric")
    return errors


def load_open_positions(
    path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = path or OPEN_POSITIONS_PATH
    if not target.exists():
        summary = {
            "path": repo_relative(target),
            "file_exists": False,
            "valid": False,
            "position_count": 0,
            "states": {},
            "errors": [f"Missing open positions file: {repo_relative(target)}"],
        }
        return [], summary
    payload = load_json_file(target, default=[])
    errors = validate_open_positions_payload(payload)
    positions: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            position = dict(item)
            position["ticker"] = _text(position.get("ticker")).upper()
            position["state"] = _text(position.get("state")).upper()
            position["entry_type"] = _text(position.get("entry_type")).upper()
            positions.append(position)
    state_counts: dict[str, int] = {}
    for position in positions:
        state = position["state"]
        state_counts[state] = state_counts.get(state, 0) + 1
    summary = {
        "path": repo_relative(target),
        "file_exists": True,
        "valid": len(errors) == 0,
        "position_count": len(positions),
        "states": state_counts,
        "errors": errors,
    }
    return positions, summary


def _load_live_scm_report() -> dict[str, Any] | None:
    try:
        from scripts.signal_conversion_monitor import build_signal_conversion_report
    except ModuleNotFoundError:
        try:
            from signal_conversion_monitor import build_signal_conversion_report
        except ModuleNotFoundError:
            return None
    try:
        return build_signal_conversion_report()
    except Exception:
        return None


def _load_live_moltbook_summary() -> dict[str, Any]:
    # PATCHED: explicit ModuleNotFoundError guard makes this function self-contained.
    # Previously the double-import fallback could propagate ModuleNotFoundError
    # if both 'scripts.moltbook_loader' and 'moltbook_loader' were absent,
    # relying entirely on the call-site try/except Exception in
    # _load_state_from_runtime_files(). This patch mirrors the pattern used
    # by _load_live_scm_report() and eliminates the hidden dependency.
    try:
        from scripts.moltbook_loader import summarize_moltbook
    except ModuleNotFoundError:
        try:
            from moltbook_loader import summarize_moltbook
        except ModuleNotFoundError:
            return {}
    try:
        return summarize_moltbook()
    except Exception:
        return {}


def _build_state_from_live_report(report: dict[str, Any]) -> dict[str, Any]:
    per_signal_rows = normalize_per_signal_rows(report)
    gate_states = normalize_gate_state_map(report.get("derived_gate_states"))
    active_blockers = normalize_active_blockers(gate_states)
    signal_summary = build_signal_summary_from_rows(
        per_signal_rows, report.get("signal_summary")
    )
    return {
        "source": "live_builder",
        "moltbook_summary": report.get("moltbook_summary", {}),
        "signal_summary": signal_summary,
        "per_signal_attribution": per_signal_rows,
        "watchlist_diagnostics": report.get("watchlist_diagnostics", {}),
        "derived_gate_states": gate_states,
        "active_blockers": active_blockers,
        "execution_policy": normalize_execution_policy(report.get("execution_policy")),
        "scm_review": normalize_scm_review(report, active_blockers=active_blockers),
        "simulation_context": report.get("simulation_context", {}),
        "note": report.get("note", ""),
    }


def _load_state_from_runtime_files() -> dict[str, Any]:
    scm_payload = load_json_file(SCM_REPORT_PATH, default={}) or {}
    derived_payload = load_json_file(DERIVED_GATE_STATES_PATH, default={})
    execution_payload = load_json_file(EXECUTION_POLICY_PATH, default={})
    per_signal_payload = load_json_file(PER_SIGNAL_ATTRIBUTION_PATH, default=[])

    normalized_per_signal_payload: dict[str, Any] = {
        "watchlist_diagnostics": scm_payload.get("watchlist_diagnostics", {}),
    }
    if isinstance(per_signal_payload, dict):
        normalized_per_signal_payload.update(per_signal_payload)
    else:
        normalized_per_signal_payload["per_signal_attribution"] = per_signal_payload

    per_signal_rows = normalize_per_signal_rows(normalized_per_signal_payload)
    gate_states = normalize_gate_state_map(
        derived_payload or scm_payload.get("derived_gate_states")
    )
    active_blockers = normalize_active_blockers(gate_states)

    signal_summary_seed = {}
    if isinstance(scm_payload, dict):
        signal_summary_seed = scm_payload.get("signal_summary", {})
        if not isinstance(signal_summary_seed, dict):
            signal_summary_seed = {}
        if (
            "signals_above_threshold" in scm_payload
            and "signals_above_ce_threshold" not in signal_summary_seed
        ):
            signal_summary_seed["signals_above_ce_threshold"] = scm_payload[
                "signals_above_threshold"
            ]
    signal_summary = build_signal_summary_from_rows(per_signal_rows, signal_summary_seed)

    try:
        moltbook_summary = _load_live_moltbook_summary()
    except Exception:
        moltbook_summary = {}

    return {
        "source": "runtime_files",
        "moltbook_summary": moltbook_summary,
        "signal_summary": signal_summary,
        "per_signal_attribution": per_signal_rows,
        "watchlist_diagnostics": scm_payload.get("watchlist_diagnostics", {}),
        "derived_gate_states": gate_states,
        "active_blockers": active_blockers,
        "execution_policy": normalize_execution_policy(
            execution_payload or scm_payload
        ),
        "scm_review": normalize_scm_review(scm_payload, active_blockers=active_blockers),
        "simulation_context": scm_payload.get("simulation_context", {}),
        "signal_refinery": load_json_file(SIGNAL_REFINERY_REPORT_PATH, default={}) or {},
        "perception_control": load_json_file(PERCEPTION_CONTROL_REPORT_PATH, default={}) or {},
        "note": _text(
            scm_payload.get("note"), "Loaded from normalized runtime files."
        ),
    }


def persist_current_runtime_state(state: dict[str, Any]) -> None:
    scm_payload = {
        "scm_rate": state["scm_review"]["scm_rate"],
        "scm_state": state["scm_review"]["scm_state"],
        "diagnosis": state["scm_review"].get("diagnosis", []),
        "gap_type": state["scm_review"].get("gap_type", "UNKNOWN"),
        "signals_above_threshold": state["signal_summary"].get(
            "signals_above_ce_threshold", 0
        ),
        "signal_summary": state["signal_summary"],
        "moltbook_summary": state["moltbook_summary"],
        "watchlist_diagnostics": state.get("watchlist_diagnostics", {}),
        "derived_gate_states": state["derived_gate_states"],
        "execution_policy": state["execution_policy"],
        "note": state.get("note", ""),
    }
    write_json_atomic(SCM_REPORT_PATH, scm_payload)
    write_json_atomic(DERIVED_GATE_STATES_PATH, state["derived_gate_states"])
    write_json_atomic(EXECUTION_POLICY_PATH, state["execution_policy"])
    write_json_atomic(
        PER_SIGNAL_ATTRIBUTION_PATH,
        {"per_signal_attribution": state["per_signal_attribution"]},
    )


def load_current_pipeline_state(prefer_runtime_files: bool = False) -> dict[str, Any]:
    if prefer_runtime_files:
        runtime_state = _load_state_from_runtime_files()
        if (
            runtime_state["per_signal_attribution"]
            or runtime_state["scm_review"]["scm_state"] != "UNKNOWN"
        ):
            return runtime_state
    live_report = _load_live_scm_report()
    if live_report is not None:
        return _build_state_from_live_report(live_report)
    return _load_state_from_runtime_files()


def build_runtime_state_from_scm_report_payload(scm_report: dict[str, Any]) -> dict[str, Any]:
    derived_gate_states = scm_report.get("derived_gate_states", {})
    return {
        "source": "scm_report",
        "moltbook_summary": scm_report.get("moltbook_summary", {}),
        "signal_summary": scm_report.get("signal_summary", {}),
        "per_signal_attribution": normalize_per_signal_rows(scm_report),
        "watchlist_diagnostics": scm_report.get("watchlist_diagnostics", {}),
        "derived_gate_states": derived_gate_states,
        "active_blockers": normalize_active_blockers(derived_gate_states),
        "execution_policy": scm_report.get("execution_policy", {}),
        "scm_review": scm_report.get("scm_review", {}),
        "scm_input_origin": scm_report.get("scm_input_origin", "seeded"),
        "scm_external_row_count": int(scm_report.get("scm_external_row_count", 0) or 0),
        "scm_seeded_row_count": int(scm_report.get("scm_seeded_row_count", 0) or 0),
        "simulation_context": scm_report.get("simulation_context", {}),
        "signal_refinery": scm_report.get("signal_refinery", {}) or {},
        "perception_control": scm_report.get("perception_control", {}) or {},
        "note": scm_report.get("note", ""),
    }


def policy_state_score(policy_state: str) -> int:
    return POLICY_STATE_RANK.get(_text(policy_state).upper(), 0)
