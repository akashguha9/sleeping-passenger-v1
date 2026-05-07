"""Run deterministic scoring and classification for the signal refinery MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models.market import MarketSnapshot
from src.models.signal import SignalScore
from src.scoring.attention_cluster import maybe_build_attention_cluster, score_attention_cluster
from src.scoring.durability_validator import score_durability
from src.scoring.engagement_intent_engine import score_engagement_manipulation
from src.scoring.evidence_quality_layer import score_evidence_quality
from src.scoring.execution_friction import score_execution_friction
from src.scoring.liquidity_score import score_liquidity
from src.scoring.llm_explanation_adapter import ExplanationAdapter
from src.scoring.net_signal_value import score_net_signal_value
from src.scoring.state_classifier import classify_state
from src.storage.csv_store import write_csv_rows
from src.storage.sqlite_store import SQLiteStore
from src.utils.logging_utils import get_logger, log_event
from src.utils.time_utils import utc_now_iso

LOGGER = get_logger("run_scoring")


def build_signal_score(snapshot: MarketSnapshot) -> tuple[SignalScore, object | None]:
    ems = score_engagement_manipulation(snapshot)
    eqs = score_evidence_quality(snapshot)
    ds = score_durability(snapshot)
    ls = score_liquidity(snapshot)
    efs = score_execution_friction(snapshot, liquidity_score=ls.score)
    net = score_net_signal_value(
        evidence_quality_score=eqs.score,
        durability_score=ds.score,
        liquidity_score=ls.score,
        engagement_manipulation_score=ems.score,
        execution_friction_score=efs.score,
        market_implied_probability=snapshot.implied_probability,
    )
    decision = classify_state(
        ems=ems.score,
        eqs=eqs.score,
        ds=ds.score,
        ls=ls.score,
        efs=efs.score,
        aps=net["admission_priority_score"].score,  # type: ignore[index]
    )
    score = SignalScore(
        market_id=snapshot.market_id,
        engagement_manipulation_score=ems.score,
        evidence_quality_score=eqs.score,
        durability_score=ds.score,
        liquidity_score=ls.score,
        execution_friction_score=efs.score,
        market_mispricing_estimate=float(net["market_mispricing_estimate"]),
        model_probability=float(net["model_probability"]),
        net_signal_value=net["net_signal_value"].score,  # type: ignore[index]
        admission_priority_score=net["admission_priority_score"].score,  # type: ignore[index]
        state=decision.state,
        reason_codes=[
            *ems.reason_codes,
            *eqs.reason_codes,
            *ds.reason_codes,
            *ls.reason_codes,
            *efs.reason_codes,
            *decision.reason_codes,
        ],
        explanation="",
        scored_at=utc_now_iso(),
    )
    score.explanation = ExplanationAdapter.explain_signal(snapshot, score)
    attention_score = score_attention_cluster(
        {
            "virality_proxy": snapshot.virality_spike,
            "emotional_intensity": snapshot.emotional_intensity,
            "narrative_recycling": snapshot.narrative_recycling,
            "topic_frequency": min(1.0, snapshot.volume / 50000.0),
            "spread_velocity": min(1.0, snapshot.spread / 0.10),
        }
    )
    attention_cluster = maybe_build_attention_cluster(
        market_id=snapshot.market_id,
        topic=snapshot.category,
        entities=snapshot.entities,
        narrative_type=snapshot.narrative_type,
        emotional_category="high_emotion" if snapshot.emotional_intensity >= 0.60 else "measured",
        source=snapshot.source,
        engagement_manipulation_score=ems.score,
        evidence_quality_score=eqs.score,
        attention_score=attention_score,
    )
    return score, attention_cluster


def main() -> None:
    parser = argparse.ArgumentParser(description="Run signal scoring on latest market snapshots.")
    parser.add_argument("--summary", action="store_true", help="Print a concise summary.")
    args = parser.parse_args()

    store = SQLiteStore()
    snapshot_rows = store.read_latest_market_snapshots()
    snapshots = [MarketSnapshot(**row) for row in snapshot_rows]
    scores: list[SignalScore] = []
    clusters = []
    for snapshot in snapshots:
        score, cluster = build_signal_score(snapshot)
        scores.append(score)
        if cluster is not None:
            clusters.append(cluster)
        if score.state == "IGNORE":
            store.write_rejected_signal(score)
            log_event(LOGGER, "signal_rejected", module="run_scoring", market_id=score.market_id, state=score.state, reason_codes=score.reason_codes)
        else:
            log_event(LOGGER, "signal_admitted", module="run_scoring", market_id=score.market_id, state=score.state, reason_codes=score.reason_codes)
    store.write_signal_scores(scores)
    if clusters:
        store.write_attention_clusters(clusters)
    processed_path = Path("data/processed/latest_signal_scores.json")
    processed_path.write_text(json.dumps([score.to_dict() for score in scores], indent=2, sort_keys=True), encoding="utf-8")
    write_csv_rows("data/processed/latest_signal_scores.csv", [score.to_dict() for score in scores])
    if args.summary:
        print("Signal Refinery Scoring")
        print(f"signals_scored={len(scores)}")
        print(f"ignored={sum(1 for row in scores if row.state == 'IGNORE')}")
        print(f"watch={sum(1 for row in scores if row.state == 'WATCH')}")
        print(f"validate={sum(1 for row in scores if row.state == 'VALIDATE')}")
        print(f"paper_trade={sum(1 for row in scores if row.state == 'PAPER_TRADE')}")
        print(f"attention_clusters={len(clusters)}")
        print(f"processed_scores_path={processed_path}")


if __name__ == "__main__":
    main()
