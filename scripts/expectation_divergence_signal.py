# EXPECTATION_DIVERGENCE_SIGNAL (EDS)
# Module: S1 — Belief State
# Added: April 16 2026
# Source: Dylan / We Are the World session
#
# The Dylan Detector formalised.
# EDS = narrative_implied_direction - observed_market_direction
#
# Pipeline has SSSC BOUNDARY_TENSION (flows conflict), NIS (momentum fraction),
# TAT (pressure state). None computes: narrative says direction X, market does Y.
#
# EDS_states:
#   CONFIRMING:     EDS near 0 -> narrative and reality aligned -> full CE
#   MILD_DIVERGE:   EDS 0.2-0.5 -> watch closely, NLR check
#   STRONG_DIVERGE: EDS > 0.5 -> HIGH PRIORITY anomaly
#     sub-classify:
#       REVERSAL_SIGNAL:     narrative (+1), observed (-1) -> story says up, mkt says down
#       HIDDEN_ACCUMULATION: narrative (+1), volume spike, price flat
#       FAKE_MOVE:           narrative confirmed by price, NOT by Polymarket odds
#   INVERTED:       EDS > 0.8 -> extreme divergence, treat as thesis inversion, exit
#
# Inputs:
#   narrative_implied_dir: sign(COMPOSITE_EDGE - 0.5) * narrative_strength_t
#   observed_market_dir:   sign(price_return_7d) * volume_confirmation
#   polymarket_dir:        sign(delta_odds_7d) * market_liquidity
#
# CE adjustment:
#   CONFIRMING:     CE_eds = CE_raw (full weight)
#   MILD_DIVERGE:   CE_eds = CE_raw * 0.75
#   STRONG_DIVERGE: CE_eds = CE_raw * 0.30 (near block)
#   INVERTED:       CE_eds = 0 (thesis break, exit signal)
#
# Portfolio retrospectives:
#   ZIM: war narrative (+), Iran 64% Polymarket declining (-) -> INVERTED -> exit -2.19% correct
#   CVX Day 30+: war narrative (+), CVX price declining (-) -> REVERSAL_SIGNAL -> LEAVE (-8.82% avoided)
#   RTX: narrative (+), price (+), Polymarket (+) -> CONFIRMING -> full CE -> +3.90% WIN
#
# "Trade the contradiction, not the chorus."

EDS_MILD_THRESHOLD   = 0.2
EDS_STRONG_THRESHOLD = 0.5
EDS_INVERTED_THRESHOLD = 0.8

CE_WEIGHT_CONFIRMING    = 1.00
CE_WEIGHT_MILD          = 0.75
CE_WEIGHT_STRONG        = 0.30
CE_WEIGHT_INVERTED      = 0.00

def compute_eds_score(narrative_dir, observed_dir, polymarket_dir,
                      narrative_weight=0.4, price_weight=0.3, poly_weight=0.3):
    raw = (narrative_dir * narrative_weight +
           observed_dir  * price_weight +
           polymarket_dir * poly_weight)
    divergence = abs(narrative_dir - (observed_dir * price_weight + polymarket_dir * poly_weight))
    return divergence

def classify_eds_state(eds_score):
    if eds_score >= EDS_INVERTED_THRESHOLD:
        return 'INVERTED'
    elif eds_score >= EDS_STRONG_THRESHOLD:
        return 'STRONG_DIVERGE'
    elif eds_score >= EDS_MILD_THRESHOLD:
        return 'MILD_DIVERGE'
    else:
        return 'CONFIRMING'

def classify_divergence_type(narrative_dir, observed_dir, polymarket_dir, volume_spike):
    if narrative_dir > 0 and observed_dir < 0:
        return 'REVERSAL_SIGNAL'
    elif narrative_dir > 0 and volume_spike and abs(observed_dir) < 0.1:
        return 'HIDDEN_ACCUMULATION'
    elif narrative_dir * observed_dir > 0 and narrative_dir * polymarket_dir < 0:
        return 'FAKE_MOVE'
    return 'UNCLASSIFIED'

def apply_eds_adjustment(ce_raw, eds_state):
    weights = {
        'CONFIRMING':    CE_WEIGHT_CONFIRMING,
        'MILD_DIVERGE':  CE_WEIGHT_MILD,
        'STRONG_DIVERGE': CE_WEIGHT_STRONG,
        'INVERTED':      CE_WEIGHT_INVERTED,
    }
    return ce_raw * weights.get(eds_state, 1.0)

def eds_full_check(ce_raw, narrative_dir, price_return_7d, volume_conf,
                   delta_odds_7d, liquidity, volume_spike=False):
    observed_dir = (1 if price_return_7d > 0 else -1) * volume_conf
    poly_dir     = (1 if delta_odds_7d > 0 else -1) * liquidity
    score = compute_eds_score(narrative_dir, observed_dir, poly_dir)
    state = classify_eds_state(score)
    dtype = classify_divergence_type(narrative_dir, observed_dir, poly_dir, volume_spike)
    ce_adj = apply_eds_adjustment(ce_raw, state)
    return {
        'eds_score':        round(score, 3),
        'eds_state':        state,
        'divergence_type':  dtype if state in ('STRONG_DIVERGE', 'INVERTED') else None,
        'ce_adjusted':      round(ce_adj, 3),
        'action':           'THESIS_BREAK_EXIT' if state == 'INVERTED' else 'STANDARD',
    }
