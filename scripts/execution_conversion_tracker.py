# EXECUTION_CONVERSION_TRACKER (ECT)
# Module: S8 — Population-level conversion across the signal funnel
# Added: April 17-18 2026
# Source: Japanese sake / German schnapps / Turkish raki appetiser / priming session
#
# ECT tracks POPULATION-LEVEL conversion from detected signals to executed trades.
# Distinct from per-trade mechanisms (ZPD, EQS, LPC, IL) which see one signal
# or one trade at a time. ECT is the only mechanism that sees the full
# funnel and can detect systemic selection errors.
#
# The appetite-to-eating insight:
#   Detection without conversion is dead potential.
#   Appetite (detected signal) != Eating (executed trade)
#   A system can detect 100 valid signals and execute 5 correctly OR
#   execute 5 different (lower-quality) signals — per-trade mechanisms
#   cannot tell these apart. ECT can.
#
# ECT is distinct from:
#   ZPD: per-signal gate (binary pass/fail at one signal)
#   EQS: per-trade post-entry fidelity (one trade retrospective)
#   LPC: per-trade luck vs process (one outcome attribution)
#   IL:  per-signal action selection (one signal routing)
#
# ECT asks:
#   'Of all signals that passed pipeline gates, how many became trades?
#    Of trades taken, do they have higher CE than the signals skipped?'
#
# FUNNEL STAGES:
#   S_detected:    total signals entering intake (CFD + SF + NIS)
#   S_zpd_passed:  signals passing ZPD CLEAN_ZONE
#   S_ce_strong:   signals with CE >= 0.70 STRONG_EDGE
#   S_lalo_open:   signals with LALO < 0.35 OPEN_ADOPTION
#   S_executed:    signals that became actual entries
#
# CONVERSION RATES:
#   CR_zpd       = S_zpd_passed / S_detected     (expected 0.15-0.30 strict gates)
#   CR_ce_strong = S_ce_strong  / S_zpd_passed   (expected 0.40-0.60)
#   CR_lalo      = S_lalo_open  / S_ce_strong    (expected 0.60-0.80)
#   CR_execute   = S_executed   / S_lalo_open    (should approach 1.0)
#   CR_total     = S_executed   / S_detected
#
# The critical metric is CR_execute — at this stage the signal has passed
# ALL gates, so CR_execute should be near 1.0. Anything less = leakage.
#
# ECT_STATES (rolling 30-day window on CR_execute):
#   CLEAN_CONVERSION:   CR_execute >= 0.95 -> pipeline converting as designed
#   ACCEPTABLE:         CR_execute 0.80-0.95 -> minor leakage, monitor
#   LEAKAGE_WARNING:    CR_execute 0.60-0.80 -> structural conversion issue
#   CONVERSION_FAILURE: CR_execute < 0.60 -> systemic execution breakdown
#
# Why leakage happens:
#   - Operator hesitation (OSM-borderline but pipeline passed)
#   - Market access issues (fill failure, spread widening)
#   - Size discipline collision (drift_risk_score already at max)
#   - Attention scarcity (multiple simultaneous signals)
#   - CHAOS_ENTRY preference (inverse selection!)
#
# INVERSE SELECTION DETECTION — the critical bug catcher:
#   Per-trade mechanisms CANNOT see if you are skipping high-CE signals
#   while taking low-CE CHAOS_ENTRY positions. ECT makes this visible.
#
#   IS_Score = mean(CE of skipped_gate_passed_signals) - mean(CE of executed_signals)
#
#   IS_Score > +0.10: INVERSE_SELECTION — executed signals lower quality than skipped
#                     This is the CHAOS_ENTRY pattern quantified at the population level
#   IS_Score between -0.10 and +0.10: NEUTRAL_SELECTION
#   IS_Score < -0.10: POSITIVE_SELECTION — you are correctly taking the best signals
#
# Current state (April 17 2026, rolling 90-day):
#   Detected signals: ~120
#   ZPD passed: ~30 (25% CR_zpd)
#   CE STRONG_EDGE: ~15 (50% of ZPD)
#   LALO OPEN_ADOPTION: ~10 (67% of CE)
#   Actually executed: 24 positions (current portfolio size)
#
#   24 executed > 10 gate-passed -> 14 positions executed outside gate pass
#   6 of these are logged CHAOS_ENTRY (JPM, MSFT, EWZ, USO, UNG, FCG)
#   8 are pre-V5.7 grandfathered or gate-borderline
#
#   Mean CE of executed positions: 0.48 (dragged down by CHAOS_ENTRY)
#   Mean CE of ZPD-passed-but-not-executed: 0.72
#   IS_Score = 0.72 - 0.48 = +0.24 INVERSE_SELECTION detected
#
#   This explains consequence_persistence=2.5 DEGRADED state at the
#   population level — the pipeline was finding good signals, but
#   execution happened on different (lower-quality) signals.
#
# ECT FEEDS INTO:
#   Monthly review: CR_execute and IS_Score logged each review cycle
#   BIS update: inverse selection = behavioral integrity degradation
#   consequence_persistence: IS_Score > 0.15 elevates persistence score
#   CHAOS_ENTRY audit: for each CHAOS_ENTRY, identify which gate-passed
#                      signal was skipped in the same window — that is
#                      the true cost
#   Scale-up gate: IS_Score < 0.05 required for capital scale-up
#
# ECT IMPLEMENTATION:
#   Each detected signal gets a snapshot stored:
#     timestamp, ticker, CE, ZPD_gates_passed, LALO_score, LALO_state,
#     was_executed, execution_skip_reason (if applicable)
#
#   ECT runs monthly:
#     1. Compute CR at each funnel stage
#     2. Classify ECT_STATE from CR_execute
#     3. Compute IS_Score = mean(CE_skipped) - mean(CE_executed)
#     4. Flag inverse selection if IS_Score > +0.10
#     5. For each CHAOS_ENTRY: identify skipped higher-CE signal in same window
#     6. Log findings to MOLTBOOK
#
# The appetite-to-eating law:
#   A pipeline that detects 100 signals and executes 5 is not automatically
#   efficient — if the 5 executed were not the best 5, conversion is broken.
#   ECT is the first mechanism that catches this at the population level.
#   
#   Detection without conversion is dead potential.
#   Conversion of wrong signals is worse than no conversion.

ECT_CLEAN_CONVERSION   = 0.95
ECT_ACCEPTABLE         = 0.80
ECT_LEAKAGE_WARNING    = 0.60
# Below ECT_LEAKAGE_WARNING = CONVERSION_FAILURE

ECT_IS_INVERSE         =  0.10
ECT_IS_POSITIVE        = -0.10
# Between these values = NEUTRAL_SELECTION

ECT_SCALEUP_GATE       =  0.05   # IS_Score must be below this for capital scale-up

def compute_conversion_rates(s_detected: int, s_zpd: int, s_ce: int,
                             s_lalo: int, s_executed: int) -> dict:
    def safe_div(a, b):
        return round(a / b, 3) if b > 0 else 0.0
    return {
        'S_detected':    s_detected,
        'S_zpd_passed':  s_zpd,
        'S_ce_strong':   s_ce,
        'S_lalo_open':   s_lalo,
        'S_executed':    s_executed,
        'CR_zpd':        safe_div(s_zpd, s_detected),
        'CR_ce_strong':  safe_div(s_ce, s_zpd),
        'CR_lalo':       safe_div(s_lalo, s_ce),
        'CR_execute':    safe_div(s_executed, s_lalo),
        'CR_total':      safe_div(s_executed, s_detected),
    }

def classify_ect_state(cr_execute: float) -> str:
    if cr_execute >= ECT_CLEAN_CONVERSION:    return 'CLEAN_CONVERSION'
    elif cr_execute >= ECT_ACCEPTABLE:        return 'ACCEPTABLE'
    elif cr_execute >= ECT_LEAKAGE_WARNING:   return 'LEAKAGE_WARNING'
    else:                                     return 'CONVERSION_FAILURE'

def compute_inverse_selection(ce_executed: list, ce_skipped_gate_passed: list) -> dict:
    if len(ce_executed) == 0 or len(ce_skipped_gate_passed) == 0:
        return {'is_score': 0.0, 'is_state': 'INSUFFICIENT_DATA',
                'mean_ce_executed': None, 'mean_ce_skipped': None}
    mean_exec  = sum(ce_executed) / len(ce_executed)
    mean_skip  = sum(ce_skipped_gate_passed) / len(ce_skipped_gate_passed)
    is_score   = round(mean_skip - mean_exec, 3)
    if is_score > ECT_IS_INVERSE:         state = 'INVERSE_SELECTION'
    elif is_score < ECT_IS_POSITIVE:      state = 'POSITIVE_SELECTION'
    else:                                  state = 'NEUTRAL_SELECTION'
    return {
        'is_score':           is_score,
        'is_state':           state,
        'mean_ce_executed':   round(mean_exec, 3),
        'mean_ce_skipped':    round(mean_skip, 3),
        'scaleup_eligible':   is_score < ECT_SCALEUP_GATE,
    }

def run_ect(s_detected: int, s_zpd: int, s_ce: int, s_lalo: int,
            s_executed: int, ce_executed: list,
            ce_skipped_gate_passed: list) -> dict:
    rates = compute_conversion_rates(s_detected, s_zpd, s_ce, s_lalo, s_executed)
    ect_state = classify_ect_state(rates['CR_execute'])
    is_result = compute_inverse_selection(ce_executed, ce_skipped_gate_passed)
    return {
        'funnel':       rates,
        'ect_state':    ect_state,
        'inverse_selection': is_result,
        'alarms': {
            'conversion_failure': ect_state == 'CONVERSION_FAILURE',
            'inverse_selection':  is_result['is_state'] == 'INVERSE_SELECTION',
            'scaleup_blocked':    not is_result.get('scaleup_eligible', False),
        },
        'note': (
            f"ECT_STATE={ect_state}, CR_execute={rates['CR_execute']:.3f}. "
            f"IS_Score={is_result.get('is_score', 0.0):+.3f} "
            f"({is_result.get('is_state', 'N/A')})."
        ),
    }
