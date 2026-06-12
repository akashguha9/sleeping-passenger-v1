"""Full simulator pipeline: payload in, gated advisory decision out.

Runs the complete chain on one candidate payload:

    radar -> narrative -> theme -> exposure -> circuit -> tyres
    -> inflection -> aero -> crash -> triple-blind -> meal box
    -> driver -> cherry-pick -> telemetry

The payload is a plain dict (JSON-friendly) with optional sections;
missing sections fall back to conservative defaults, so the pipeline is
stingy by construction: an empty payload dies on the ladder.
"""

from __future__ import annotations

from typing import Any

from src.simulator import ADVISORY_NOTE, DOCTRINE
from src.simulator.aero_engine import score_aero
from src.simulator.cherry_pick import evaluate_candidate
from src.simulator.circuit_classifier import classify_circuit
from src.simulator.crash_simulator import simulate_crash_cases
from src.simulator.driver_license import score_driver
from src.simulator.meal_box import check_meal_box
from src.simulator.narrative_radar import score_narrative_shock
from src.simulator.narrative_tracker import track_narrative
from src.simulator.signal_tyres import score_signal_tyre
from src.simulator.telemetry import build_decision_telemetry
from src.simulator.theme_mapper import map_theme
from src.simulator.threshold_ladder import score_inflection
from src.simulator.triple_blind import build_triple_blind_review
from src.utils.validation_utils import coerce_float, normalized_score


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}


def evaluate_candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one candidate payload through the full simulator chain.

    Returns a JSON-serializable breakdown: every engine's output, the final
    cherry-pick decision, and the decision telemetry snapshot. ADVISORY_ONLY.
    """
    ticker = str(payload.get("ticker", "UNKNOWN"))
    theme_name = str(payload.get("theme", "unmapped_theme"))

    # 0. Consent bridge (pre-decision): detect consumer evidence, build the
    # consent profile + reliability, and feed business-model fragility into
    # the crash wall automatically. No manual merging.
    from src.consent.pipeline_bridge import prepare_consent_context

    consent_context = prepare_consent_context(payload)
    if consent_context.risk_factors:
        merged_risks = dict(_section(payload, "risk_factors"))
        for name, value in consent_context.risk_factors.items():
            merged_risks[name] = max(coerce_float(merged_risks.get(name)), value)
        payload = {**payload, "risk_factors": merged_risks}

    # 1. Prediction-market radar (optional).
    radar = _section(payload, "prediction_market")
    shock = None
    if radar:
        shock = score_narrative_shock(
            market_name=str(radar.get("market_name", "unnamed_market")),
            probability_before=coerce_float(radar.get("probability_before")),
            probability_after=coerce_float(radar.get("probability_after")),
            velocity=coerce_float(radar.get("velocity")),
            market_importance=coerce_float(radar.get("market_importance")),
            market_liquidity=coerce_float(radar.get("market_liquidity")),
            cross_source_confirmation=coerce_float(
                radar.get("cross_source_confirmation")
            ),
            affected_themes=list(radar.get("affected_themes", []) or []),
            affected_sectors=list(radar.get("affected_sectors", []) or []),
        )

    # 2. Narrative tracking (optional).
    narrative_section = _section(payload, "narrative")
    narrative = track_narrative(
        narrative=str(narrative_section.get("narrative", theme_name)),
        mention_count=int(coerce_float(narrative_section.get("mention_count"))),
        origin_count=int(coerce_float(narrative_section.get("origin_count"))),
        independent_origin_count=int(
            coerce_float(narrative_section.get("independent_origin_count"))
        ),
        source_quality=coerce_float(narrative_section.get("source_quality")),
        narrative_velocity=coerce_float(narrative_section.get("narrative_velocity")),
        narrative_acceleration=coerce_float(
            narrative_section.get("narrative_acceleration")
        ),
        contradiction_count=int(
            coerce_float(narrative_section.get("contradiction_count"))
        ),
    )

    # 3. Theme / track condition.
    theme_section = _section(payload, "theme_assessment")
    theme = map_theme(
        theme=theme_name,
        source_narrative=narrative.narrative,
        policy_fit=coerce_float(theme_section.get("policy_fit")),
        macro_fit=coerce_float(theme_section.get("macro_fit")),
        sector_momentum=coerce_float(theme_section.get("sector_momentum")),
        liquidity_support=coerce_float(theme_section.get("liquidity_support")),
        risk_appetite=coerce_float(theme_section.get("risk_appetite"), 0.5),
        valuation_heat=coerce_float(theme_section.get("valuation_heat")),
        crowding=coerce_float(theme_section.get("crowding")),
        regulatory_friction=coerce_float(theme_section.get("regulatory_friction")),
        candidate_sectors=list(theme_section.get("candidate_sectors", []) or []),
    )

    # 4. Company exposure. When the caller supplies no exposure section,
    # fall back to the deterministic exposure graph (seeded; clearly not a
    # complete real supply-chain dataset) instead of silently scoring zero.
    from src.simulator.exposure_resolver import resolve_exposure

    exposure_section = _section(payload, "exposure")
    graph_resolution: dict[str, Any] | None = None
    if not exposure_section:
        from src.simulator.exposure_graph import build_seed_graph

        graph = build_seed_graph()
        if ticker.upper() in graph.tickers_for_theme(theme_name):
            exposure_section = graph.to_resolver_inputs(theme_name, ticker)
            graph_resolution = graph.resolve(theme_name, ticker).to_dict()
    exposure = resolve_exposure(
        ticker=ticker,
        theme=theme_name,
        revenue_exposure=coerce_float(exposure_section.get("revenue_exposure")),
        margin_sensitivity=coerce_float(exposure_section.get("margin_sensitivity")),
        backlog_linkage=coerce_float(exposure_section.get("backlog_linkage")),
        customer_linkage=coerce_float(exposure_section.get("customer_linkage")),
        geographic_fit=coerce_float(exposure_section.get("geographic_fit")),
        policy_fit=coerce_float(exposure_section.get("policy_fit")),
        supply_chain_position=coerce_float(
            exposure_section.get("supply_chain_position")
        ),
        weak_evidence_penalty=coerce_float(
            exposure_section.get("weak_evidence_penalty")
        ),
    )

    # 5. Circuit classification.
    circuit_section = _section(payload, "circuit")
    circuit = classify_circuit(
        market_cap_usd=coerce_float(circuit_section.get("market_cap_usd")),
        sector=str(circuit_section.get("sector", "")),
        is_biotech_event_driven=bool(circuit_section.get("is_biotech_event_driven", False)),
        annualized_volatility=coerce_float(circuit_section.get("annualized_volatility")),
        policy_dependent=bool(circuit_section.get("policy_dependent", False)),
    )

    # 6. Signal tyres (decayed under this circuit + track condition).
    tyres = [
        score_signal_tyre(
            signal_type=str(s.get("signal_type", "social_spike")),
            raw_strength=coerce_float(s.get("raw_strength")),
            signal_age_hours=coerce_float(s.get("signal_age_hours")),
            reaction_lag_hours=coerce_float(s.get("reaction_lag_hours")),
            source_quality=coerce_float(s.get("source_quality"), 1.0),
            confirmation_multiplier=coerce_float(
                s.get("confirmation_multiplier"), 1.0
            ),
            circuit_decay_multiplier=circuit.profile.half_life_decay_multiplier,
            track_condition_score=theme.track_condition_score,
        )
        for s in payload.get("signals", []) or []
        if isinstance(s, dict)
    ]

    # 7. Inflection.
    inflection_section = _section(payload, "inflection")
    inflection = score_inflection(
        delta_narrative_velocity=coerce_float(
            inflection_section.get("delta_narrative_velocity")
        ),
        delta_source_diversity=coerce_float(
            inflection_section.get("delta_source_diversity")
        ),
        delta_volume_quality=coerce_float(
            inflection_section.get("delta_volume_quality")
        ),
        delta_estimate_revision=coerce_float(
            inflection_section.get("delta_estimate_revision")
        ),
        delta_filing_evidence=coerce_float(
            inflection_section.get("delta_filing_evidence")
        ),
        delta_contradiction_pressure=coerce_float(
            inflection_section.get("delta_contradiction_pressure")
        ),
    )

    # 8. Aero package (origin counts shared with the narrative tracker).
    aero_section = _section(payload, "aero")
    aero = score_aero(
        evidence=_section(aero_section, "evidence"),
        noise_level=coerce_float(aero_section.get("noise_level")),
        contradiction_level=coerce_float(aero_section.get("contradiction_level")),
        duplication_level=coerce_float(aero_section.get("duplication_level")),
        ambiguity_level=coerce_float(aero_section.get("ambiguity_level")),
        promotional_bias=coerce_float(aero_section.get("promotional_bias")),
        independent_origin_count=narrative.independent_origin_count,
        total_source_count=narrative.mention_count,
        sector_momentum=theme.sector_momentum,
        stock_specific_thrust=coerce_float(aero_section.get("stock_specific_thrust")),
        hidden_fundamental_improvement=coerce_float(
            aero_section.get("hidden_fundamental_improvement")
        ),
        narrative_crowding=theme.crowding,
        catalyst_proximity_days=(
            coerce_float(aero_section["catalyst_proximity_days"])
            if aero_section.get("catalyst_proximity_days") is not None
            else None
        ),
        catalyst_confirmed=bool(aero_section.get("catalyst_confirmed", False)),
        regime_shift_level=coerce_float(aero_section.get("regime_shift_level")),
        data_quality=coerce_float(aero_section.get("data_quality"), 1.0),
        score_history=[
            coerce_float(v) for v in aero_section.get("score_history", []) or []
        ],
        bull_force=coerce_float(aero_section.get("bull_force"), 0.5),
        bear_force=coerce_float(aero_section.get("bear_force"), 0.5),
    )

    # 9. Crash permutations.
    crash = simulate_crash_cases(
        {
            str(name): coerce_float(value)
            for name, value in _section(payload, "risk_factors").items()
        }
    )

    # 10. Triple-blind review.
    blind_section = _section(payload, "triple_blind")
    triple_blind = build_triple_blind_review(
        blinded_metrics=_section(blind_section, "blinded_metrics"),
        user_thesis=(
            str(blind_section["user_thesis"])
            if blind_section.get("user_thesis")
            else None
        ),
        optionality_human_found=list(
            blind_section.get("optionality_human_found", []) or []
        ),
    )

    # 11. Meal box.
    meal_section = _section(payload, "meal_box")
    meal_box = check_meal_box(
        thesis=meal_section.get("thesis"),
        evidence=meal_section.get("evidence"),
        catalyst=meal_section.get("catalyst"),
        invalidation=meal_section.get("invalidation"),
    )

    # 12. Driver license.
    driver_section = _section(payload, "driver")
    driver = score_driver(
        license_level=str(driver_section.get("license_level", "learner")),
        violations=[
            v for v in driver_section.get("violations", []) or [] if isinstance(v, dict)
        ],
        thesis_logging_quality=coerce_float(
            driver_section.get("thesis_logging_quality")
        ),
        invalidation_compliance=coerce_float(
            driver_section.get("invalidation_compliance")
        ),
        position_sizing_discipline=coerce_float(
            driver_section.get("position_sizing_discipline")
        ),
        confirmation_patience=coerce_float(
            driver_section.get("confirmation_patience")
        ),
        replay_audit_completion=coerce_float(
            driver_section.get("replay_audit_completion")
        ),
        calibration_honesty=coerce_float(driver_section.get("calibration_honesty")),
        override_abuse_level=coerce_float(driver_section.get("override_abuse_level")),
        revenge_trading_flags=int(
            coerce_float(driver_section.get("revenge_trading_flags"))
        ),
    )

    # 12b. Scrutineering bay: cross-examine the raw payload against the
    # simulator's own physics invariants before any verdict is published.
    from src.simulator.scrutineering import inspect_payload

    scrutineering = inspect_payload(payload)

    # 13. Final cherry-pick decision.
    decision = evaluate_candidate(
        ticker=ticker,
        theme=theme_name,
        opportunity_quality=coerce_float(payload.get("opportunity_quality")),
        track_condition_score=theme.track_condition_score,
        valuation_heat=theme.valuation_heat,
        exposure_score=exposure.exposure_score,
        exposure_class=exposure.exposure_class,
        tyres=tyres,
        hard_evidence_score=coerce_float(payload.get("hard_evidence_score")),
        inflection=inflection,
        aero=aero,
        crash=crash,
        meal_box=meal_box,
        driver=driver,
        circuit=circuit,
        narrative_shock=shock,
        triple_blind=triple_blind,
        scrutineering=scrutineering,
        confirmation_level=normalized_score(payload.get("confirmation_level", 0.0)),
        previous_state=(
            str(payload["previous_state"]) if payload.get("previous_state") else None
        ),
        thesis_damaged=bool(payload.get("thesis_damaged", False)),
    )

    # 14. Consent bridge (post-decision): multipliers, penalties, and
    # severity caps adjust the verdict — and the ledger records every step
    # so there is no hidden magic and no unexplained downgrade.
    from src.consent.pipeline_bridge import apply_consent_adjustment
    from src.simulator.threshold_ladder import LADDER_STATES

    consent_ledger = apply_consent_adjustment(
        context=consent_context,
        score_before=decision.final_candidate_score,
        state_before=decision.final_state,
        ladder_states=LADDER_STATES,
    )
    if consent_context.evidence_present:
        decision.final_candidate_score = consent_ledger.score_after_consent
        if consent_ledger.recommendation_after_consent != decision.final_state:
            decision.final_state = consent_ledger.recommendation_after_consent
            decision.reason_codes.append("CONSENT_CAP_APPLIED")
        if consent_ledger.risk_caps_applied:
            decision.gate_results["consent_gate"] = False
            decision.decision_reason += (
                " Consent gate: "
                + "; ".join(consent_ledger.risk_caps_applied)
                + "."
            )
        else:
            decision.gate_results["consent_gate"] = True
            if consent_ledger.score_after_consent < (
                consent_ledger.score_before_consent - 1e-9
            ):
                decision.decision_reason += (
                    " Consent adjustment applied (see consent_ledger)."
                )
        decision.reason_codes.append("CONSENT_EVIDENCE_EVALUATED")
    else:
        decision.gate_results["consent_gate"] = True
        decision.reason_codes.append("CONSENT_EVIDENCE_ABSENT")

    # 14a. Games layer (optional "games" payload section): classify the
    # decision environment (nested game stack), the dice (uncertainty
    # profiles + loaded-die check), and the reality layer (simulacra +
    # investment-vs-tradeability split). The same signal means different
    # things in different games; the reality gate caps hyperreal,
    # dangerous configurations at watchlist for investment purposes.
    games_result: dict | None = None
    reality_assessment = None
    games_section = payload.get("games")
    if isinstance(games_section, dict) and games_section:
        from src.games.dice_profiles import classify_dice_profile, detect_loaded_die
        from src.games.game_classifier import classify_game_stack
        from src.games.reality_anchor import assess_reality

        game_stack = classify_game_stack(
            dict(games_section.get("layers") or {})
        )
        dice = [
            classify_dice_profile(**{
                k: v for k, v in spec.items()
                if k in classify_dice_profile.__kwdefaults__ or k == "source"
            })
            for spec in games_section.get("dice", []) or []
            if isinstance(spec, dict)
        ]
        loaded_report = None
        observed = games_section.get("observed_outcomes")
        if isinstance(observed, dict) and observed:
            loaded_report = detect_loaded_die(
                observed,
                games_section.get("expected_probabilities"),
            )
        reality_section = games_section.get("reality")
        if isinstance(reality_section, dict) and reality_section:
            reality_assessment = assess_reality(**{
                k: coerce_float(v) for k, v in reality_section.items()
                if k in assess_reality.__kwdefaults__
            })
            if reality_assessment.danger_score >= 5.0:
                decision.gate_results["reality_gate"] = False
                from src.simulator.threshold_ladder import LADDER_STATES

                if decision.final_state in LADDER_STATES and (
                    LADDER_STATES.index(decision.final_state)
                    > LADDER_STATES.index("watchlist")
                ):
                    decision.final_state = "watchlist"
                    decision.reason_codes.append("REALITY_GATE_CAPPED")
                    decision.decision_reason += (
                        " Reality gate: hyperreal/dangerous configuration "
                        f"(danger {reality_assessment.danger_score:.1f}/10) "
                        "caps investment state at watchlist; tradeability "
                        "is reported separately."
                    )
            else:
                decision.gate_results["reality_gate"] = True
        if any(d.profile == "loaded_possible" for d in dice) or (
            loaded_report is not None and loaded_report.loaded
        ):
            decision.reason_codes.append("LOADED_DICE_SUSPECTED")
        games_result = {
            "game_stack": game_stack.to_dict(),
            "dice_profiles": [d.to_dict() for d in dice],
            "loaded_die": loaded_report.to_dict() if loaded_report else None,
            "reality": (
                reality_assessment.to_dict() if reality_assessment else None
            ),
        }

    # 14a-pre. Adaptive opponent model (optional "opponent" section):
    # the mentor's questions — weapon, weak side, niche, market
    # adaptation, blind layer. An exhausted edge or fatal weak side caps
    # the investment state at watchlist: the model must know when its own
    # edge has become predictable.
    opponent_result = None
    opponent_section = payload.get("opponent")
    if isinstance(opponent_section, dict) and opponent_section:
        from src.strategy.adaptive_opponent import assess_adaptive_opponent

        opponent_result = assess_adaptive_opponent(opponent_section)
        adaptation_state = opponent_result["adaptation"]["state"]
        weak_class = opponent_result["weak_side"]["classification"]
        if adaptation_state == "exhausted_edge" or weak_class == "fatal":
            from src.simulator.threshold_ladder import LADDER_STATES

            decision.gate_results["adaptation_gate"] = False
            decision.reason_codes.append(
                "EDGE_EXHAUSTED" if adaptation_state == "exhausted_edge"
                else "FATAL_WEAK_SIDE"
            )
            if decision.final_state in LADDER_STATES and (
                LADDER_STATES.index(decision.final_state)
                > LADDER_STATES.index("watchlist")
            ):
                decision.final_state = "watchlist"
                decision.decision_reason += (
                    " Adaptation gate: the market has adapted to this edge "
                    "(or the weak side is fatal); investment state capped "
                    "at watchlist."
                )
        else:
            decision.gate_results["adaptation_gate"] = True

    # 14a-bis. Tempered Bayesian posterior (optional "bayes" section):
    # prior (typically a prediction-market probability — tradable belief,
    # never truth) updated by evidence items whose likelihood ratios are
    # tempered by trust = reliability x reality x dice x (1 - manipulation).
    bayes_result = None
    bayes_section = payload.get("bayes")
    if isinstance(bayes_section, dict) and bayes_section.get("prior") is not None:
        from src.games.bayesian_update import bayesian_update

        bayes_result = bayesian_update(
            prior=coerce_float(bayes_section.get("prior"), 0.5),
            evidence=[
                e for e in bayes_section.get("evidence", []) or []
                if isinstance(e, dict)
            ],
        )

    # 14a-ter. Dice audits supplied with the payload (from the audit loop):
    # severe statuses on load-bearing sources block investment-grade
    # advisory actions and stamp the decision.
    dice_audit_severe = False
    for audit in payload.get("games", {}).get("dice_audits", []) if isinstance(payload.get("games"), dict) else []:
        if isinstance(audit, dict) and audit.get("calibration_status") in (
            "overconfident", "loaded_suspected",
        ):
            dice_audit_severe = True
            decision.reason_codes.append("DICE_CALIBRATION_RISK")
            break

    # 14b. Strategy section + the Stewards' Room. When the payload carries
    # a "strategy" section, the strategy chain runs inside the pipeline,
    # its self-report is cross-examined against the rest of the payload,
    # and ALL engines are reconciled into one conservative unified verdict
    # with contradictions as first-class cited outputs.
    strategy_result = None
    cross_exam_report = None
    strategy_section = payload.get("strategy")
    if isinstance(strategy_section, dict) and strategy_section:
        from src.strategy.cross_exam import cross_examine_strategy
        from src.strategy.final_decision import evaluate_strategy_payload

        strategy_result = evaluate_strategy_payload(
            {**strategy_section, "ticker": ticker}
        )
        cross_exam_report = cross_examine_strategy(payload)

    from src.simulator.unified_verdict import build_unified_verdict

    unified = build_unified_verdict(
        simulator_state=decision.final_state,
        simulator_score_100=decision.final_candidate_score,
        strategy_result=strategy_result,
        cross_exam=cross_exam_report,
        consent_revenue_label=(
            str((consent_context.profile or {}).get("revenue_quality_label", ""))
            if consent_context.evidence_present
            else ""
        ),
        crash_gate_passed=decision.gate_results.get("crash_gate", True),
    )
    if unified.final_state != decision.final_state:
        decision.final_state = unified.final_state
        decision.reason_codes.append("UNIFIED_CONSERVATIVE_CAP")
        decision.decision_reason += (
            f" Unified verdict: most conservative engine wins "
            f"({unified.state_before_unification} -> {unified.final_state})."
        )
    if unified.contradiction_hold:
        decision.reason_codes.append("CONTRADICTION_HOLD")
        decision.decision_reason += (
            " CONTRADICTION_HOLD: engines disagree materially; human "
            "resolution required."
        )

    # 14c. Staged advisory action: the verdict translated into the
    # journal's action vocabulary (Reject … Exit Candidate), with
    # contradiction holds routing to Research More and the reality split
    # blocking investment-grade actions on tradeable-but-dangerous names.
    from src.games.advisory_router import route_advisory_action

    advisory = route_advisory_action(
        final_state=decision.final_state,
        contradiction_hold=unified.contradiction_hold,
        previous_state=(
            str(payload["previous_state"]) if payload.get("previous_state")
            else None
        ),
        reality=reality_assessment,
        calibration_risk_severe=dice_audit_severe,
    )

    # 15. Telemetry — no candidate is promoted without it. Captures the
    # post-consent, post-unification decision so replay sees what the
    # operator saw.
    telemetry = build_decision_telemetry(
        decision,
        driver_discipline_score=driver.discipline_score,
        expected_time_window_days=coerce_float(
            payload.get("expected_time_window_days"), 90.0
        ),
        predicted_probability=(
            coerce_float(payload["predicted_probability"])
            if payload.get("predicted_probability") is not None
            else (bayes_result.posterior if bayes_result else None)
        ),
        driver_license_level=driver.license_level,
        narrative_state=narrative.narrative_state,
        dominant_game=(
            str((games_result or {}).get("game_stack", {}).get(
                "dominant_game", ""
            ))
            if games_result
            else ""
        ),
        data_source=str(payload.get("data_source", "caller_payload")),
    )

    return {
        "advisory_note": ADVISORY_NOTE,
        "doctrine": list(DOCTRINE),
        "decision": decision.to_dict(),
        "advisory_action": advisory.to_dict(),
        "bayes": bayes_result.to_dict() if bayes_result else None,
        "opponent": opponent_result,
        "games": games_result,
        "consent_ledger": consent_ledger.to_dict(),
        "unified_verdict": unified.to_dict(),
        "strategy": strategy_result,
        "strategy_cross_exam": (
            cross_exam_report.to_dict() if cross_exam_report else None
        ),
        "telemetry": telemetry.to_dict(),
        "breakdown": {
            "narrative_shock": shock.to_dict() if shock else None,
            "narrative": narrative.to_dict(),
            "theme": theme.to_dict(),
            "exposure": exposure.to_dict(),
            "circuit": circuit.to_dict(),
            "tyres": [t.to_dict() for t in tyres],
            "inflection": inflection.to_dict(),
            "aero": aero.to_dict(),
            "crash": {
                # Trim the full permutation list for transport; keep counts.
                **{
                    k: v
                    for k, v in crash.to_dict().items()
                    if k != "tested_combinations"
                },
            },
            "triple_blind": triple_blind.to_dict(),
            "meal_box": meal_box.to_dict(),
            "driver": driver.to_dict(),
            "scrutineering": scrutineering.to_dict(),
            "exposure_graph_resolution": graph_resolution,
        },
    }
