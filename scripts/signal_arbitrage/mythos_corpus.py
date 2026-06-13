"""Real-corpus backfill + live calibration engine for the Mythos->Fable loop.

This converts the "no real corpus" gap from a vague weakness into a precise,
testable data pipeline:

  * a durable calibration-record SCHEMA (identity + Mythos + aggregation +
    Fable + ledger + outcome features),
  * a BACKFILL pipeline that turns historical thesis/trade records into
    feature-bearing calibration records (dry-run by default; never fabricates
    an outcome — unknowns become INCONCLUSIVE),
  * a real CALIBRATION runner that refuses to fit below evidence thresholds and
    reports separation / AUC / trap precision-recall / action accuracy / Brier
    / ECE / utility-by-action when enough labelled records exist.

Honesty contract (reused from scripts.outcome_evidence): SYNTHETIC_FIXTURE rows
are NEVER calibration-eligible.  Only REAL_MANUAL_TRADE / PAPER_TRADE /
IMPORTED_BACKTEST resolved outcomes count toward calibration thresholds.

Pure + deterministic (integer/string timestamps in, no wall clock).  No network.
ADVISORY_ONLY; never fits in a way that violates a fraud/spine invariant.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import clamp, r3, mean
from .mythos import MythosObservation, run_mythos, source_to_ecology
from .mythos_aggregator import aggregate_cluster, run_aggregated_pipeline, dedup_observations
from .strategist import strategize_signal
from .opportunity import score_opportunity
from .mythos_ledger import MythosLedgerStore

# --- outcome enum (calibration-record level) ---
WIN = "WIN"
LOSS = "LOSS"
BREAKEVEN = "BREAKEVEN"
AVOIDED_TRAP = "AVOIDED_TRAP"
MISSED_WINNER = "MISSED_WINNER"
FALSE_POSITIVE = "FALSE_POSITIVE"
FALSE_NEGATIVE = "FALSE_NEGATIVE"
INCONCLUSIVE = "INCONCLUSIVE"
_RESOLVED = {WIN, LOSS, BREAKEVEN, AVOIDED_TRAP, MISSED_WINNER, FALSE_POSITIVE, FALSE_NEGATIVE}

# Calibration-eligible source types (mirror scripts.outcome_evidence contract).
REAL_MANUAL_TRADE = "REAL_MANUAL_TRADE"
PAPER_TRADE = "PAPER_TRADE"
IMPORTED_BACKTEST = "IMPORTED_BACKTEST"
SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
ELIGIBLE_SOURCE_TYPES = frozenset({REAL_MANUAL_TRADE, PAPER_TRADE, IMPORTED_BACKTEST})

_EPS = 0.001

# Status ladders.
NO_CORPUS_FOUND = "NO_CORPUS_FOUND"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
PARTIAL_BACKFILL = "PARTIAL_BACKFILL"
READY_FOR_CALIBRATION = "READY_FOR_CALIBRATION"

PROVISIONAL_DIAGNOSTIC = "PROVISIONAL_DIAGNOSTIC"
FIRST_PASS_CALIBRATION = "FIRST_PASS_CALIBRATION"
STRONGER_CALIBRATION_READY = "STRONGER_CALIBRATION_READY"

MIN_PROVISIONAL = 10
MIN_FIRST_PASS = 30
MIN_STRONGER = 100

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Required schema (used by tests to assert completeness).
SCHEMA: dict[str, tuple[str, ...]] = {
    "identity": ("record_id", "entity", "ticker", "claim", "thesis_id",
                 "opened_at", "closed_at", "horizon_days", "source_records", "claim_type"),
    "mythos": ("observation_quality_score", "governance_trust_score",
               "interpretation_confidence", "interpretation_gap_score",
               "reality_check_score", "economic_reality_score", "narrative_belief_score",
               "reality_narrative_divergence", "divergence_type",
               "food_chain_capture_score", "value_capture_role", "casino_odds_integrity",
               "timing_integrity", "layer_integrity_score", "strategy_eligibility_score",
               "final_mythos_confidence", "recommended_next_module", "claim_status",
               "confidence_cap"),
    "aggregation": ("n_observations", "n_sources", "n_distinct_ecologies",
                    "distinct_ecologies", "corroboration_score",
                    "same_source_duplicate_count", "governance_weighted_reality",
                    "governance_weighted_narrative", "directional_agreement_score",
                    "source_independence_score", "cross_platform_migration_score"),
    "fable": ("legacy_baseline", "raw_merit", "investable_score", "research_ceiling_score",
              "decay_adjusted_ceiling", "crowding_adjusted_ceiling", "upgrade_delta",
              "ceiling_delta", "risk_detection_delta", "gate_haircut",
              "trap_suppression_score", "confidence_score", "confidence_label",
              "expected_value_of_waiting", "expected_value_of_acting_now",
              "recommended_action", "decision", "ceiling_decision", "binding_bottleneck",
              "binding_gate", "vitality", "timing_edge", "interpretation_gap",
              "synthetic_contamination", "reality_purity", "final_opportunity_score"),
    "ledger": ("survival_count", "contradiction_count", "next_reality_check",
               "validation_window_days", "claim_status_at_entry", "claim_status_at_exit",
               "evidence_events", "chain_valid"),
    "outcome": ("outcome_label", "realized_return", "max_drawdown", "max_runup",
                "hit_target", "hit_stop", "thesis_confirmed", "thesis_disconfirmed",
                "time_to_confirmation", "time_to_failure", "final_outcome_status"),
}


# ==========================================================================
# Outcome labelling (never fabricated)
# ==========================================================================
def label_from_return(realized_return: float | None, *, eps: float = _EPS) -> str:
    if realized_return is None:
        return INCONCLUSIVE
    if realized_return > eps:
        return WIN
    if realized_return < -eps:
        return LOSS
    return BREAKEVEN


# ==========================================================================
# Calibration record
# ==========================================================================
@dataclass
class CalibrationRecord:
    record_id: str
    source_type: str
    identity: dict[str, Any]
    mythos: dict[str, Any]
    aggregation: dict[str, Any]
    fable: dict[str, Any]
    ledger: dict[str, Any]
    outcome: dict[str, Any]
    feature_bearing: bool
    calibratable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id, "source_type": self.source_type,
            "identity": self.identity, "mythos": self.mythos,
            "aggregation": self.aggregation, "fable": self.fable,
            "ledger": self.ledger, "outcome": self.outcome,
            "feature_bearing": self.feature_bearing, "calibratable": self.calibratable,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CalibrationRecord":
        return cls(
            record_id=d["record_id"], source_type=d.get("source_type", SYNTHETIC_FIXTURE),
            identity=d.get("identity", {}), mythos=d.get("mythos", {}),
            aggregation=d.get("aggregation", {}), fable=d.get("fable", {}),
            ledger=d.get("ledger", {}), outcome=d.get("outcome", {}),
            feature_bearing=d.get("feature_bearing", False),
            calibratable=d.get("calibratable", False))


def _obs_from_dict(d: dict[str, Any]) -> MythosObservation:
    """Reconstruct a MythosObservation from a corpus observation dict."""
    fields = {f for f in MythosObservation.__dataclass_fields__}
    kw = {k: v for k, v in d.items() if k in fields and k != "evidence_events"}
    ev = d.get("evidence_events")
    if ev:
        kw["evidence_events"] = tuple(ev)
    return MythosObservation(**kw)


def _directional_agreement(per_source: list[dict[str, Any]]) -> float:
    if not per_source:
        return 0.0
    signs = [1 if p["economic_reality_score"] >= p["narrative_belief_score"] else -1
             for p in per_source]
    consensus = 1 if sum(signs) >= 0 else -1
    return clamp(sum(1 for s in signs if s == consensus) / len(signs))


def build_calibration_record(
    *, cluster: list[MythosObservation], record_id: str, ticker: str,
    opened_at: str = "", closed_at: str = "", horizon_days: int = 0,
    source_type: str = SYNTHETIC_FIXTURE, realized_return: float | None = None,
    outcome_override: str | None = None, outcome_extra: dict[str, Any] | None = None,
) -> CalibrationRecord:
    """Turn one resolved thesis cluster into a feature-bearing calibration record.

    Outcome is derived from realized_return (or override) — NEVER guessed. If no
    return and no override, outcome_label = INCONCLUSIVE.
    """
    raw_n = len(cluster)
    deduped = dedup_observations(cluster)
    agg = aggregate_cluster(cluster)

    # Representative Mythos snapshot = highest-governance-trust observation.
    reps = [(run_mythos(o)) for o in deduped] or [None]
    rep = max([m for m in reps if m], key=lambda m: m["governance_trust_score"], default=None)

    pipe = run_aggregated_pipeline(cluster)

    # Fable features: score the aggregated dossier through the strategist.
    fable_feat: dict[str, Any] = {}
    if agg.dossier is not None:
        strat = strategize_signal(agg.dossier)
        ss = score_opportunity(agg.dossier)["segment_scores"]
        fable_feat = {
            "legacy_baseline": strat["legacy_baseline"], "raw_merit": strat["raw_merit"],
            "investable_score": strat["investable_score"],
            "research_ceiling_score": strat["research_ceiling_score"],
            "decay_adjusted_ceiling": strat["decay_adjusted_ceiling"],
            "crowding_adjusted_ceiling": strat["crowding_adjusted_ceiling"],
            "upgrade_delta": strat["upgrade_delta"], "ceiling_delta": strat["ceiling_delta"],
            "risk_detection_delta": strat["risk_detection_delta"],
            "gate_haircut": strat["gate_haircut"],
            "trap_suppression_score": strat["trap_suppression_score"],
            "confidence_score": strat["confidence_score"],
            "confidence_label": strat["confidence_label"],
            "expected_value_of_waiting": strat["expected_value_of_waiting"],
            "expected_value_of_acting_now": strat["expected_value_of_acting_now"],
            "recommended_action": strat["recommended_action"],
            "decision": strat["decision"], "ceiling_decision": strat["ceiling_decision"],
            "binding_bottleneck": strat["binding_bottleneck"],
            "binding_gate": strat["binding_gate"],
            "vitality": ss["vitality"], "timing_edge": ss["timing_edge"],
            "interpretation_gap": ss["interpretation_gap"],
            "synthetic_contamination": ss["synthetic_contamination"],
            "reality_purity": ss["reality_purity"],
            "final_opportunity_score": ss["final_opportunity"],
        }

    # Ledger features via an ephemeral in-memory store.
    led = MythosLedgerStore(None)
    run_aggregated_pipeline(cluster, ledger=led, current_day=horizon_days)
    claims = led.all_claims()
    crec = claims[0] if claims else None
    ledger_feat = {
        "survival_count": crec.survival_count if crec else 0,
        "contradiction_count": crec.contradiction_count if crec else 0,
        "next_reality_check": crec.expected_check_day if crec else 0,
        "validation_window_days": crec.validation_window if crec else 0,
        "claim_status_at_entry": agg.claim_status,
        "claim_status_at_exit": crec.status if crec else agg.claim_status,
        "evidence_events": (crec.events if crec else []),
        "chain_valid": crec.chain_valid() if crec else True,
    }

    # Outcome (never fabricated).
    label = outcome_override or label_from_return(realized_return)
    extra = outcome_extra or {}
    outcome = {
        "outcome_label": label, "realized_return": realized_return,
        "max_drawdown": extra.get("max_drawdown"), "max_runup": extra.get("max_runup"),
        "hit_target": extra.get("hit_target"), "hit_stop": extra.get("hit_stop"),
        "thesis_confirmed": label in (WIN,) or extra.get("thesis_confirmed", False),
        "thesis_disconfirmed": label in (LOSS, FALSE_POSITIVE) or extra.get("thesis_disconfirmed", False),
        "time_to_confirmation": extra.get("time_to_confirmation"),
        "time_to_failure": extra.get("time_to_failure"),
        "final_outcome_status": label,
    }

    mythos_feat = {
        "observation_quality_score": rep["observation_quality_score"] if rep else 0.0,
        "governance_trust_score": rep["governance_trust_score"] if rep else 0.0,
        "interpretation_confidence": rep["interpretation_confidence"] if rep else 0.0,
        "interpretation_gap_score": rep["interpretation_gap_score"] if rep else 0.0,
        "reality_check_score": rep["reality_check_score"] if rep else 0.0,
        "economic_reality_score": agg.economic_reality_score,
        "narrative_belief_score": agg.narrative_belief_score,
        "reality_narrative_divergence": r3(agg.economic_reality_score - agg.narrative_belief_score),
        "divergence_type": rep["divergence_type"] if rep else "NO_EDGE",
        "food_chain_capture_score": rep["food_chain"]["food_chain_capture_score"] if rep else 0.0,
        "value_capture_role": rep["food_chain"]["value_capture_role"] if rep else "UNDIFFERENTIATED",
        "casino_odds_integrity": rep["casino"]["casino_odds_integrity"] if rep else 0.0,
        "timing_integrity": rep["eta"]["timing_integrity"] if rep else 0.0,
        "layer_integrity_score": rep["layer_integrity_score"] if rep else 0.0,
        "strategy_eligibility_score": rep["strategy_eligibility_score"] if rep else 0.0,
        "final_mythos_confidence": rep["final_mythos_confidence"] if rep else 0.0,
        "recommended_next_module": pipe["pre_scoring_decision"],
        "claim_status": agg.claim_status, "confidence_cap": agg.confidence_cap,
    }

    n_distinct_sources = len({o.source.strip().lower() for o in deduped})
    base_corro = agg.corroboration
    dir_agree = _directional_agreement(agg.per_source)
    source_independence = clamp(n_distinct_sources / max(1, len(deduped)))
    corro_adjusted = r3(base_corro * dir_agree * source_independence)
    agg_feat = {
        "n_observations": agg.n_observations, "n_sources": agg.n_sources,
        "n_distinct_ecologies": agg.n_distinct_ecologies,
        "distinct_ecologies": agg.distinct_ecologies,
        "corroboration_score": corro_adjusted,
        "same_source_duplicate_count": raw_n - len(deduped),
        "governance_weighted_reality": agg.economic_reality_score,
        "governance_weighted_narrative": agg.narrative_belief_score,
        "directional_agreement_score": r3(dir_agree),
        "source_independence_score": r3(source_independence),
        "cross_platform_migration_score": r3(base_corro),
    }

    identity = {
        "record_id": record_id, "entity": agg.entity, "ticker": ticker,
        "claim": agg.claim, "thesis_id": f"{agg.entity}:{ticker}",
        "opened_at": opened_at, "closed_at": closed_at, "horizon_days": horizon_days,
        "source_records": [p["source"] for p in agg.per_source],
        "claim_type": deduped[0].claim_type if deduped else "generic",
    }

    feature_bearing = bool(agg.dossier is not None and rep is not None)
    calibratable = bool(feature_bearing and label in _RESOLVED
                        and source_type in ELIGIBLE_SOURCE_TYPES)

    return CalibrationRecord(
        record_id=record_id, source_type=source_type, identity=identity,
        mythos=mythos_feat, aggregation=agg_feat, fable=fable_feat,
        ledger=ledger_feat, outcome=outcome,
        feature_bearing=feature_bearing, calibratable=calibratable)


# ==========================================================================
# Backfill pipeline
# ==========================================================================
@dataclass
class BackfillReport:
    status: str
    total_input_records: int
    parsed: int
    with_entity: int
    with_claim: int
    with_outcome: int
    feature_bearing: int
    calibratable: int
    inconclusive: int
    missing_field_counts: dict[str, int]
    example_missing: list[dict[str, Any]]
    output_path: str | None
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "status", "total_input_records", "parsed", "with_entity", "with_claim",
            "with_outcome", "feature_bearing", "calibratable", "inconclusive",
            "missing_field_counts", "example_missing", "output_path", "advisory_status")}


def _load_source(path: Path) -> list[dict[str, Any]]:
    """Load a corpus file into a list of raw thesis dicts (best-effort)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []
    if isinstance(data, dict):
        # cluster-corpus format {records:[...]} or holdings {positions:[...]}
        if "records" in data:
            return list(data["records"])
        if "positions" in data:
            return [{"ticker": p.get("ticker"), "entity": p.get("normalized_ticker") or p.get("ticker"),
                     "status": p.get("status"), "closed_at": p.get("closed_at"),
                     "observations": [], "realized_return": None} for p in data["positions"]]
        return [data]
    if isinstance(data, list):
        return list(data)
    return []


def backfill_calibration_records(
    source_paths: list[str], output_path: str | None = None, mode: str = "dry_run",
) -> BackfillReport:
    """Backfill historical thesis/trade records into calibration records.

    dry_run (default) never writes.  Records without reconstructable
    observations remain identity-only and INCONCLUSIVE; outcomes are never
    fabricated.
    """
    raw: list[dict[str, Any]] = []
    for sp in source_paths:
        raw.extend(_load_source(Path(sp)))

    if not raw:
        return BackfillReport(
            status=NO_CORPUS_FOUND, total_input_records=0, parsed=0, with_entity=0,
            with_claim=0, with_outcome=0, feature_bearing=0, calibratable=0,
            inconclusive=0, missing_field_counts={}, example_missing=[],
            output_path=None)

    records: list[CalibrationRecord] = []
    missing: dict[str, int] = {"observations": 0, "claim": 0, "realized_return": 0,
                               "entity": 0, "ticker": 0}
    examples: list[dict[str, Any]] = []
    with_entity = with_claim = with_outcome = 0

    for i, rec in enumerate(raw):
        ticker = rec.get("ticker") or ""
        entity = rec.get("entity") or ticker
        claim = rec.get("claim") or ""
        obs_dicts = rec.get("observations") or []
        realized = rec.get("realized_return")
        if entity:
            with_entity += 1
        else:
            missing["entity"] += 1
        if claim:
            with_claim += 1
        else:
            missing["claim"] += 1
        if realized is not None or rec.get("outcome_override"):
            with_outcome += 1
        else:
            missing["realized_return"] += 1
        if not obs_dicts:
            missing["observations"] += 1
        if not ticker:
            missing["ticker"] += 1

        if not obs_dicts:
            # identity-only stub: cannot reconstruct features -> INCONCLUSIVE.
            cr = CalibrationRecord(
                record_id=rec.get("record_id") or f"bf-{i}",
                source_type=rec.get("source_type", SYNTHETIC_FIXTURE),
                identity={"record_id": rec.get("record_id") or f"bf-{i}", "entity": entity,
                          "ticker": ticker, "claim": claim, "thesis_id": f"{entity}:{ticker}",
                          "opened_at": rec.get("opened_at", ""), "closed_at": rec.get("closed_at", ""),
                          "horizon_days": rec.get("horizon_days", 0), "source_records": [],
                          "claim_type": rec.get("claim_type", "generic")},
                mythos={}, aggregation={}, fable={},
                ledger={}, outcome={"outcome_label": INCONCLUSIVE, "realized_return": None,
                                    "final_outcome_status": INCONCLUSIVE},
                feature_bearing=False, calibratable=False)
            if len(examples) < 5:
                examples.append({"record_id": cr.record_id, "missing": "observations"})
            records.append(cr)
            continue

        cluster = [_obs_from_dict(o) for o in obs_dicts]
        cr = build_calibration_record(
            cluster=cluster, record_id=rec.get("record_id") or f"bf-{i}", ticker=ticker,
            opened_at=rec.get("opened_at", ""), closed_at=rec.get("closed_at", ""),
            horizon_days=rec.get("horizon_days", 0),
            source_type=rec.get("source_type", SYNTHETIC_FIXTURE),
            realized_return=realized, outcome_override=rec.get("outcome_override"),
            outcome_extra=rec.get("outcome_extra"))
        records.append(cr)

    feature_bearing = sum(1 for r in records if r.feature_bearing)
    calibratable = sum(1 for r in records if r.calibratable)
    inconclusive = sum(1 for r in records if r.outcome.get("outcome_label") == INCONCLUSIVE)

    written = None
    if mode == "write" and output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r.to_dict(), sort_keys=True) + "\n")
        written = str(p)

    if calibratable >= MIN_PROVISIONAL:
        status = READY_FOR_CALIBRATION
    elif feature_bearing > 0:
        status = PARTIAL_BACKFILL
    else:
        status = INSUFFICIENT_EVIDENCE

    return BackfillReport(
        status=status, total_input_records=len(raw), parsed=len(records),
        with_entity=with_entity, with_claim=with_claim, with_outcome=with_outcome,
        feature_bearing=feature_bearing, calibratable=calibratable,
        inconclusive=inconclusive, missing_field_counts=missing,
        example_missing=examples, output_path=written)


# ==========================================================================
# Real calibration runner
# ==========================================================================
def prediction_score(rec: CalibrationRecord) -> float:
    """Deterministic, FIXED (un-fitted) win-likelihood proxy in [0,1].

    Fraud-gated: multiplied by reality_purity so a perception-dependent record
    cannot score as a likely win."""
    f = rec.fable
    if not f:
        return 0.0
    inv = f.get("investable_score", 0.0)
    ceil = f.get("research_ceiling_score", 0.0)
    conf = f.get("confidence_score", 0.0)
    ev_act = max(0.0, f.get("expected_value_of_acting_now", 0.0))
    corro = rec.aggregation.get("corroboration_score", 0.0)
    purity = f.get("reality_purity", 0.0)
    s = 0.35 * inv + 0.20 * ceil + 0.15 * conf + 0.15 * corro + 0.15 * ev_act
    return clamp(s * purity)


def _auc(scores_labels: list[tuple[float, int]]) -> float | None:
    pos = [s for s, y in scores_labels if y == 1]
    neg = [s for s, y in scores_labels if y == 0]
    if not pos or not neg:
        return None
    wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
    return r3(wins / (len(pos) * len(neg)))


def _predicted_trap(rec: CalibrationRecord) -> bool:
    f = rec.fable
    if not f:
        return True
    return (f.get("decision") in ("NARRATIVE_TRAP", "AVOID")
            or f.get("recommended_action") in ("AVOID_TRAP", "REJECT_UNTIL_FRAUD_RESOLVED",
                                               "EXIT_OR_IGNORE")
            or rec.mythos.get("recommended_next_module") in ("REJECTED_PRE_SCORING",
                                                             "ROUTE_TO_REALITY_CHECK"))


def _action_correct(rec: CalibrationRecord) -> bool:
    label = rec.outcome.get("outcome_label")
    routed_act = rec.fable.get("recommended_action") if rec.fable else None
    trap_flag = _predicted_trap(rec)
    if label == WIN:
        return not trap_flag and routed_act in ("ACT_NOW", "COLLECT_SPECIFIC_EVIDENCE",
                                                "WAIT_FOR_CONFIRMATION", "SHORTLIST_ONLY")
    if label in (LOSS, FALSE_POSITIVE, AVOIDED_TRAP):
        return trap_flag
    return False


def run_real_calibration(records_path: str | None = None, *,
                         records: list[CalibrationRecord] | None = None,
                         allow_source_types: frozenset[str] = ELIGIBLE_SOURCE_TYPES,
                         ) -> dict[str, Any]:
    """Load calibration records, gate by evidence thresholds, compute metrics.

    Refuses to fit/grade below MIN_PROVISIONAL.  Synthetic rows are excluded
    unless their source_type is in ``allow_source_types``."""
    if records is None:
        records = []
        if records_path is not None and Path(records_path).exists():
            for line in Path(records_path).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    records.append(CalibrationRecord.from_dict(json.loads(line)))

    eligible = [r for r in records
                if r.calibratable and r.source_type in allow_source_types
                and r.outcome.get("outcome_label") in _RESOLVED]
    n = len(eligible)

    base = {
        "n_total_records": len(records), "n_eligible_labelled": n,
        "min_provisional": MIN_PROVISIONAL, "min_first_pass": MIN_FIRST_PASS,
        "advisory_status": "ADVISORY_ONLY", "weights_fitted": False,
        "weight_change_status": "NO_WEIGHT_CHANGES_INSUFFICIENT_EVIDENCE",
    }
    if n < MIN_PROVISIONAL:
        base.update({"status": INSUFFICIENT_EVIDENCE,
                     "reason": f"only {n} eligible labelled records; need >= {MIN_PROVISIONAL}",
                     "records_needed": MIN_PROVISIONAL - n})
        return base

    # Metrics.
    scored = [(prediction_score(r), r) for r in eligible]
    wins = [s for s, r in scored if r.outcome["outcome_label"] == WIN]
    losses = [s for s, r in scored if r.outcome["outcome_label"] in (LOSS, FALSE_POSITIVE)]
    separation = r3((mean(wins) if wins else 0.0) - (mean(losses) if losses else 0.0))
    auc = _auc([(s, 1 if r.outcome["outcome_label"] == WIN else 0)
                for s, r in scored if r.outcome["outcome_label"] in (WIN, LOSS, FALSE_POSITIVE)])

    actual_traps = [r for r in eligible if r.outcome["outcome_label"] in (LOSS, FALSE_POSITIVE, AVOIDED_TRAP)]
    predicted_traps = [r for r in eligible if _predicted_trap(r)]
    correct_traps = [r for r in predicted_traps if r.outcome["outcome_label"] in (LOSS, FALSE_POSITIVE, AVOIDED_TRAP)]
    trap_precision = r3(len(correct_traps) / len(predicted_traps)) if predicted_traps else None
    trap_recall = r3(len(correct_traps) / len(actual_traps)) if actual_traps else None

    action_accuracy = r3(sum(1 for r in eligible if _action_correct(r)) / n)

    # Brier + ECE over WIN/LOSS subset.
    wl = [(prediction_score(r), 1 if r.outcome["outcome_label"] == WIN else 0)
          for r in eligible if r.outcome["outcome_label"] in (WIN, LOSS, FALSE_POSITIVE)]
    brier = r3(mean([(p - y) ** 2 for p, y in wl])) if wl else None
    ece = None
    if wl:
        bins = 5
        total = len(wl)
        acc = 0.0
        for k in range(bins):
            lo, hi = k / bins, (k + 1) / bins
            grp = [(p, y) for p, y in wl if (lo <= p < hi or (k == bins - 1 and p == 1.0))]
            if grp:
                conf = mean([p for p, _ in grp])
                accuracy = mean([y for _, y in grp])
                acc += (len(grp) / total) * abs(accuracy - conf)
        ece = r3(acc)

    # Utility by action.
    util: dict[str, float] = {}
    by_action: dict[str, list[float]] = {}
    for r in eligible:
        act = (r.fable.get("recommended_action") if r.fable else None) or "NONE"
        rr = r.outcome.get("realized_return")
        dd = r.outcome.get("max_drawdown") or 0.0
        u = (rr if rr is not None else 0.0) - 0.5 * dd
        if r.outcome["outcome_label"] in (LOSS, FALSE_POSITIVE) and not _predicted_trap(r):
            u -= 0.25  # false-positive penalty
        if r.outcome["outcome_label"] in (AVOIDED_TRAP,) and _predicted_trap(r):
            u += 0.25  # avoided-trap credit
        by_action.setdefault(act, []).append(u)
    for act, us in by_action.items():
        util[act] = r3(mean(us))

    if n >= MIN_STRONGER:
        status = STRONGER_CALIBRATION_READY
    elif n >= MIN_FIRST_PASS:
        status = FIRST_PASS_CALIBRATION
    else:
        status = PROVISIONAL_DIAGNOSTIC

    base.update({
        "status": status,
        "separation": separation, "auc_rank_separation": auc,
        "trap_precision": trap_precision, "trap_recall": trap_recall,
        "action_accuracy": action_accuracy, "brier_score": brier, "ece": ece,
        "utility_by_action": util,
        "n_wins": sum(1 for r in eligible if r.outcome["outcome_label"] == WIN),
        "n_losses": len(losses),
        "false_positives": sum(1 for r in eligible if r.outcome["outcome_label"] == FALSE_POSITIVE),
        "false_negatives": sum(1 for r in eligible if r.outcome["outcome_label"] == FALSE_NEGATIVE),
        "missed_winners": sum(1 for r in eligible if r.outcome["outcome_label"] == MISSED_WINNER),
        "avoided_traps": sum(1 for r in eligible if r.outcome["outcome_label"] == AVOIDED_TRAP),
    })
    return base


def real_corpus_backfill_readiness() -> dict[str, Any]:
    """Honest assessment of the live data files for backfill."""
    paths = [
        _REPO_ROOT / "data" / "daily_payload" / "closed_positions.json",
        _REPO_ROOT / "data" / "paper_trades" / "latest_paper_trades.json",
    ]
    report = backfill_calibration_records([str(p) for p in paths], mode="dry_run")
    out = report.to_dict()
    out["calibration"] = run_real_calibration(records=[])  # 0 eligible -> INSUFFICIENT
    return out


__all__ = [
    "CalibrationRecord", "BackfillReport", "SCHEMA",
    "build_calibration_record", "backfill_calibration_records",
    "run_real_calibration", "real_corpus_backfill_readiness", "prediction_score",
    "label_from_return",
    "WIN", "LOSS", "BREAKEVEN", "AVOIDED_TRAP", "MISSED_WINNER", "FALSE_POSITIVE",
    "FALSE_NEGATIVE", "INCONCLUSIVE",
    "REAL_MANUAL_TRADE", "PAPER_TRADE", "IMPORTED_BACKTEST", "SYNTHETIC_FIXTURE",
    "NO_CORPUS_FOUND", "INSUFFICIENT_EVIDENCE", "PARTIAL_BACKFILL",
    "READY_FOR_CALIBRATION", "PROVISIONAL_DIAGNOSTIC", "FIRST_PASS_CALIBRATION",
    "STRONGER_CALIBRATION_READY",
]
