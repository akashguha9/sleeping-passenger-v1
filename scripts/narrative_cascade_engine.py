"""Narrative Cascade engine — upstream information → downstream candidates.

The orchestrator for the full chain:

    signal_events → normalized observations → dedup/independence
      → narrative clusters + states (+ prediction-market impulses)
      → trigger-keyword event activation → curated causal graph propagation
      → security exposures (depth, direction, lag, strongest path)
      → narrative recognition (mentions, independent sources, attention,
        price recognition when OHLCV exists)
      → Narrative Pre-Alpha Gap  NPAG = |latent impact| − recognition
      → market titration state + market PAG for the same ticker
      → combined PAG (configurable weights)
      → narrative×titration interaction priority
      → operator candidate with counterfactuals + invalidation

Honesty contract
----------------
* Latent causal impact flows through CURATED transmission priors — every
  candidate carries its full assumption path and validation status.
* Recognition components list what is missing; NPAG confidence is LOW
  when price recognition is unavailable.
* Counterfactual paths (bull/bear/null) are labelled HYPOTHESIS.
* Nothing here is a probability; nothing authorizes a trade; candidates
  end in operator actions (IGNORE/WATCH/RESEARCH/PRIORITIZE/NO_EDGE) that
  are prioritization labels, not instructions.
* Extraction is deterministic-lexical (extraction_method recorded); no
  LLM calls are made by this engine.

Reads the local DB via lazy persistence accessors; results are cached by
the API layer.  Advisory-only.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import persistence
    from scripts.causal_event_graph import (
        event_nodes_with_triggers,
        load_causal_graph,
        propagate_shock,
    )
    from scripts.market_titration_engine import evaluate_market_titration
    from scripts.narrative_observation import build_observations_from_events
    from scripts.narrative_state_engine import (
        build_narrative_state,
        cluster_observations_into_narratives,
    )
    from scripts.prediction_market_impulse import compute_impulses_by_market
    from scripts.signal_inbox_bridge import _ticker_for_event
    from scripts.titration_runtime_store import recognition_inputs_for
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence  # type: ignore[no-redef]
    from causal_event_graph import (  # type: ignore[no-redef]
        event_nodes_with_triggers, load_causal_graph, propagate_shock,
    )
    from market_titration_engine import evaluate_market_titration  # type: ignore[no-redef]
    from narrative_observation import build_observations_from_events  # type: ignore[no-redef]
    from narrative_state_engine import (  # type: ignore[no-redef]
        build_narrative_state, cluster_observations_into_narratives,
    )
    from prediction_market_impulse import compute_impulses_by_market  # type: ignore[no-redef]
    from signal_inbox_bridge import _ticker_for_event  # type: ignore[no-redef]
    from titration_runtime_store import recognition_inputs_for  # type: ignore[no-redef]

CASCADE_ENGINE_VERSION = "narrative_cascade_v1"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "human_review_required": True,
}

# Configurable combined-PAG weights (operator priors).
COMBINED_PAG_WEIGHTS = {"market": 0.5, "narrative": 0.5}

OPERATOR_ACTIONS: tuple[str, ...] = (
    "IGNORE", "WATCH", "RESEARCH", "PRIORITIZE", "NO_EDGE",
)

MIN_SHOCK_FOR_CANDIDATES = 0.10


def _interaction_priority(
    narrative_state: str, titration_state: str,
    narrative_temperature: float | None, ftr_triggered: bool,
) -> tuple[str, str]:
    """(interaction label, operator action).  Prioritization, never a trade."""
    if ftr_triggered or (
        isinstance(narrative_temperature, (int, float)) and narrative_temperature > 0.85
    ):
        return "NO_EDGE_WAIT_HEAT", "NO_EDGE"
    pairs = {
        ("BREAKING", "ENDPOINT_CROSSING"): ("REACTION_IN_PROGRESS", "RESEARCH"),
        ("ACCELERATING", "BUFFER_DEPLETING"): ("HIGH_PRIORITY_PRE_ALPHA", "PRIORITIZE"),
        ("ACCELERATING", "PRIMED"): ("HIGH_PRIORITY_PRE_ALPHA", "PRIORITIZE"),
        ("BREAKING", "PRIMED"): ("REACTION_IN_PROGRESS", "RESEARCH"),
        ("DOMINANT", "CROWDED"): ("LATE_RECOGNIZED", "IGNORE"),
        ("DECAYING", "EXHAUSTING"): ("THESIS_DECAY", "IGNORE"),
    }
    hit = pairs.get((narrative_state, titration_state))
    if hit:
        return hit
    if narrative_state in ("EMERGING", "ACCUMULATING") and titration_state in (
        "LOADING", "PRE_ALPHA_WATCH", "INERT", "INSUFFICIENT_DATA",
    ):
        return "EARLY_WATCH", "WATCH"
    if narrative_state in ("ACCELERATING", "BREAKING"):
        return "NARRATIVE_MOVING", "RESEARCH"
    if narrative_state == "CONTESTED":
        return "CONTESTED_OPTIONALITY", "WATCH"
    if narrative_state == "DECAYING":
        return "NARRATIVE_FADING", "IGNORE"
    return "UNMAPPED_COMBINATION", "WATCH"


def _match_event_nodes(
    narrative: dict[str, Any], triggers: dict[str, list[str]]
) -> list[str]:
    """Deterministic keyword activation of curated event nodes.

    Single-word keywords match on WORD BOUNDARIES ("war" must not match
    "warned"); multi-word keywords match as phrases."""
    import re as _re

    text = (
        narrative.get("canonical_topic", "")
        + " "
        + " ".join((m.get("raw_title") or "") for m in narrative.get("members", []))
    ).lower()
    matched = []
    for node, keywords in triggers.items():
        for keyword in keywords:
            if " " in keyword:
                if keyword in text:
                    matched.append(node)
                    break
            elif _re.search(rf"\b{_re.escape(keyword)}\b", text):
                matched.append(node)
                break
    return matched


def _narrative_shock(state: dict[str, Any]) -> float:
    """Event shock magnitude from narrative evidence (bounded heuristic)."""
    strength = min(1.0, float(state.get("narrative_strength", 0.0) or 0.0) / 3.0)
    impulse = min(1.0, abs(float(state.get("prediction_market_impulse", 0.0) or 0.0)))
    certainty = max(0.0, float(state.get("certainty", 0.0) or 0.0))
    return round(min(1.0, 0.4 * strength + 0.4 * impulse + 0.2 * certainty), 6)


def _events_for_ticker(ticker: str, event_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Minimal titration item from the ticker's own evidence events."""
    timestamps, sources = [], []
    for row in event_rows:
        payload = row.get("raw_payload")
        if not isinstance(payload, dict):
            continue
        source = str(row.get("source_name", "") or "")
        if source == "market_data":
            continue
        try:
            mapped = str(_ticker_for_event(source, payload) or "").upper()
        except Exception:
            continue
        if mapped == ticker.upper():
            timestamps.append(str(row.get("fetched_at", "") or ""))
            sources.append(source)
    if not timestamps:
        return None
    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    return {
        "ticker": ticker.upper(),
        "event_timestamps": [timestamps[i] for i in order][:50],
        "event_sources": [sources[i] for i in order][:50],
        "event_count": len(timestamps),
        "cross_source_support_count": len(set(sources)),
        "duplicate_suppressed_count": 0,
        "observed_at": max(timestamps),
    }


def _recognition_for_ticker(
    ticker: str,
    company_name: str | None,
    observations: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Narrative recognition NR: mentions + independent sources + attention
    velocity + price recognition (OHLCV) — components listed, missing
    listed, syndication never counted as independence."""
    t_upper = ticker.upper().split(".")[0]
    name_lower = (company_name or "").lower()
    mention_obs = []
    for obs in observations:
        text = ((obs.get("raw_title") or "") + " " + (obs.get("raw_text") or "")).lower()
        if (len(t_upper) >= 3 and t_upper.lower() in text.split()) or (
            name_lower and len(name_lower) >= 5 and name_lower in text
        ):
            mention_obs.append(obs)
    explicit_mentions = len(mention_obs)
    independent = sum(float(o.get("independence_weight", 1.0) or 1.0) for o in mention_obs)
    recent = [
        o for o in mention_obs
        if (o.get("retrieved_at_utc") or "") >= (now - timedelta(hours=48)).isoformat()
    ]
    attention_velocity = min(1.0, len(recent) / 6.0)

    price_recognition = None
    try:
        rec = recognition_inputs_for(ticker)
        if rec is not None:
            price_recognition = rec.get("price_recognition")
    except Exception:
        price_recognition = None

    components = {
        "explicit_mentions": explicit_mentions,
        "independent_mention_mass": round(independent, 3),
        "attention_velocity": round(attention_velocity, 6),
        "price_recognition": price_recognition,
    }
    available = [
        min(1.0, explicit_mentions / 5.0),
        min(1.0, independent / 3.0),
        attention_velocity,
    ]
    missing = ["analyst_attention", "search_interest", "options_activity"]
    if price_recognition is not None:
        available.append(float(price_recognition))
        confidence = "MODERATE"
    else:
        missing.append("price_recognition_ohlcv")
        confidence = "LOW"
    score = round(sum(available) / len(available), 6)
    return {
        "score": score,
        "confidence": confidence,
        "components": components,
        "missing_components": missing,
        "overlap_note": (
            "attention velocity shares the evidence stream with narrative "
            "strength; treat NPAG confidence accordingly"
        ),
        "model_version": CASCADE_ENGINE_VERSION,
    }


def build_cascade_report(
    db_path: Path | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    now_dt = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    kwargs: dict[str, Any] = {"limit": 5000}
    if db_path is not None:
        kwargs["db_path"] = db_path
    try:
        event_rows = persistence.get_signal_events(**kwargs)
    except Exception:
        event_rows = []
    snap_kwargs: dict[str, Any] = {}
    if db_path is not None:
        snap_kwargs["db_path"] = db_path
    try:
        snapshots = persistence.get_probability_snapshots(**snap_kwargs)
    except Exception:
        snapshots = []

    obs_result = build_observations_from_events(event_rows)
    observations = obs_result["observations"]
    impulses = compute_impulses_by_market(snapshots)

    clusters = cluster_observations_into_narratives(observations)
    narrative_states: list[dict[str, Any]] = []
    for cluster in clusters:
        market_impulse = None
        for member in cluster["members"]:
            market_id = member.get("prediction_market_id")
            if market_id and market_id in impulses and impulses[market_id].get("impulse_available"):
                candidate = impulses[market_id]["log_odds_change"]
                if market_impulse is None or abs(candidate) > abs(market_impulse):
                    market_impulse = candidate
        state = build_narrative_state(
            cluster, now=now_dt, all_narratives=clusters, market_impulse=market_impulse,
        )
        state["_members"] = cluster["members"]
        state["_tokens"] = cluster["tokens"]
        narrative_states.append(state)

    graph = load_causal_graph()
    triggers = event_nodes_with_triggers(graph)

    candidates: dict[str, dict[str, Any]] = {}
    total_paths = 0
    for state in narrative_states:
        if state["state"] == "INSUFFICIENT_DATA":
            continue
        cluster_view = {
            "canonical_topic": state.get("canonical_topic", ""),
            "members": state.get("_members", []),
        }
        matched_nodes = _match_event_nodes(cluster_view, triggers)
        shock = _narrative_shock(state)
        if not matched_nodes or shock < MIN_SHOCK_FOR_CANDIDATES:
            continue
        for node in matched_nodes:
            result = propagate_shock(graph, node, shock)
            total_paths += result.get("path_count", 0)
            for exposure in result.get("security_exposures", []):
                ticker = exposure["ticker"]
                existing = candidates.get(ticker)
                if existing is not None and abs(existing["latent_causal_impact"]) >= abs(
                    exposure["latent_impact"]
                ):
                    existing["dominant_narratives"].append(state["narrative_id"])
                    continue
                candidates[ticker] = {
                    "ticker": ticker,
                    "discovery_origin": (
                        "prediction_market_probability_shift"
                        if state.get("prediction_market_impulse")
                        else "narrative_cluster"
                    ),
                    "upstream_event_node": node,
                    "upstream_event_label": (graph["nodes"].get(node) or {}).get("label", node),
                    "source_narrative_id": state["narrative_id"],
                    "source_narrative_topic": state["canonical_topic"],
                    "narrative_state": state["state"],
                    "narrative_temperature": state.get("narrative_temperature"),
                    "linguistic_inflection": (state.get("linguistic_inflection") or {}).get("labels"),
                    "log_odds_impulse": state.get("prediction_market_impulse"),
                    "shock": shock,
                    "latent_causal_impact": exposure["latent_impact"],
                    "expected_direction": exposure["direction"],
                    "depth_class": exposure["depth_class"],
                    "causal_depth": exposure["depth"],
                    "upstream_score": exposure["upstream_score"],
                    "strongest_path": exposure["strongest_path"],
                    "strongest_path_relations": exposure["strongest_path_relations"],
                    "expected_propagation": exposure["lag_description"],
                    "lag_class": exposure["lag_class"],
                    "path_count": exposure["path_count"],
                    "path_assumptions": exposure["assumptions"],
                    "contradiction_band": state.get("contradiction_band"),
                    "dominant_narratives": [state["narrative_id"]],
                }

    # Recognition + NPAG + titration integration per candidate.
    candidate_rows: list[dict[str, Any]] = []
    for ticker, cand in sorted(candidates.items()):
        recognition = _recognition_for_ticker(ticker, None, observations, now_dt)
        latent = abs(float(cand["latent_causal_impact"]))
        npag = round(latent - float(recognition["score"]), 6)

        titration_item = _events_for_ticker(ticker, event_rows)
        market_pag = None
        titration_state = "INSUFFICIENT_DATA"
        ftr_triggered = False
        if titration_item is not None:
            try:
                titr = evaluate_market_titration(titration_item, now=now_dt)
                titration_state = str(titr.get("titration_state") or "INSUFFICIENT_DATA")
                market_pag = titr.get("pre_alpha_gap_adjusted")
                ftr_triggered = bool(
                    (titr.get("false_transition_risk") or {}).get("triggered")
                )
            except Exception:
                pass
        if market_pag is not None:
            combined = round(
                COMBINED_PAG_WEIGHTS["market"] * float(market_pag)
                + COMBINED_PAG_WEIGHTS["narrative"] * npag,
                6,
            )
        else:
            combined = round(COMBINED_PAG_WEIGHTS["narrative"] * npag, 6)

        interaction, action = _interaction_priority(
            cand["narrative_state"], titration_state,
            cand.get("narrative_temperature"), ftr_triggered,
        )
        sign = 1 if cand["expected_direction"] == "POSITIVE" else -1
        counterfactuals = {
            "base_thesis": (
                f"{cand['upstream_event_label']} propagates via "
                f"{' -> '.join(cand['strongest_path'])}"
            ),
            "bull_path": "transmission completes at curated strength (HYPOTHESIS)",
            "bear_path": (
                "input-cost / constraint channel dominates and reverses the sign"
                " (HYPOTHESIS)" if sign > 0 else
                "substitution or policy offset neutralizes the harm (HYPOTHESIS)"
            ),
            "null_path": "consequence already priced; recognition rises without response (HYPOTHESIS)",
            "alternative_explanation": "narrative is syndication-driven attention without economic transmission (HYPOTHESIS)",
        }
        confidence = (
            "MEDIUM" if recognition["confidence"] == "MODERATE" and cand["path_count"] > 1
            else "LOW"
        )
        candidate_rows.append({
            **{k: v for k, v in cand.items() if not k.startswith("_")},
            "narrative_recognition": recognition,
            "narrative_pre_alpha_gap": npag,
            "market_pre_alpha_gap": market_pag,
            "combined_pre_alpha_gap": combined,
            "combined_pag_weights": dict(COMBINED_PAG_WEIGHTS),
            "titration_state": titration_state,
            "interaction": interaction,
            "operator_action": action,
            "counterfactuals": counterfactuals,
            "confidence": confidence,
            "invalidation_conditions": [
                "narrative decays past its half-life without corroboration",
                "recognition rises above latent impact (gap closes)",
                f"contradiction band worsens beyond {cand.get('contradiction_band')}",
                "curated path assumption rejected on operator review",
            ],
            "status": f"{action} — HUMAN REVIEW REQUIRED",
        })
    candidate_rows.sort(key=lambda c: -abs(c["combined_pre_alpha_gap"]))

    narrative_public = [
        {k: v for k, v in s.items() if not k.startswith("_")}
        for s in narrative_states
    ]
    impulse_summary = {
        market_id: imp for market_id, imp in impulses.items()
        if imp.get("impulse_available") or imp.get("usable_snapshot_count")
    }

    return {
        "engine_version": CASCADE_ENGINE_VERSION,
        "generated_at": now_dt.isoformat(),
        "graph_version": graph.get("graph_version"),
        "graph_status": graph.get("status"),
        "observation_summary": {
            "raw_event_count": obs_result["raw_event_count"],
            "observation_count": obs_result["observation_count"],
            "duplicate_cluster_count": obs_result["duplicate_cluster_count"],
            "duplicates_collapsed": obs_result["duplicates_collapsed"],
        },
        "probability_snapshot_count": len(snapshots),
        "market_impulses": impulse_summary,
        "narrative_count": len(narrative_public),
        "narratives": narrative_public[:50],
        "causal_path_count": total_paths,
        "candidate_count": len(candidate_rows),
        "candidates": candidate_rows[:25],
        "extraction_method": "deterministic_lexical_v1",
        "non_claims": [
            "no_probability_claimed",
            "curated_paths_are_priors_not_proven_causation",
            "linguistic_framing_features_are_unvalidated_heuristics",
            "candidates_are_prioritization_not_trade_instructions",
        ],
        **SAFETY_STAMPS,
    }


_report_cache: dict[str, Any] = {"at": 0.0, "report": None}
CASCADE_CACHE_TTL_S = 60.0


def get_cached_cascade_report() -> dict[str, Any]:
    """TTL-cached report for the API layer (explicit invalidation via TTL)."""
    now = time.monotonic()
    if (
        _report_cache["report"] is not None
        and now - _report_cache["at"] < CASCADE_CACHE_TTL_S
    ):
        return {**_report_cache["report"], "cache_hit": True}
    report = build_cascade_report()
    _report_cache.update({"at": now, "report": report})
    return {**report, "cache_hit": False}


__all__ = [
    "CASCADE_ENGINE_VERSION",
    "COMBINED_PAG_WEIGHTS",
    "OPERATOR_ACTIONS",
    "build_cascade_report",
    "get_cached_cascade_report",
]
