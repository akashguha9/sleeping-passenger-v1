# NARRATIVE_INERTIA_SCORE (NIS)
# Module: S2 — Narrative Engine
# Added: April 16 2026
# Source: Olise/Timbaland dual session
#
# Tracks what fraction of current narrative strength is signal-driven
# vs momentum-driven. Pipeline has TEMPORAL_GRAMMAR (tense classification)
# and NLR (timing) but NOT a continuous signal-vs-momentum fraction.
#
# The hook keeps looping after the original trigger weakened.
# N_{t+1} = rho * N_t + eta_t
#
# NIS states:
#   SIGNAL_DOMINANT:   fresh_signal high, NIS rising -> full CE weight
#   MOMENTUM_DOMINANT: fresh_signal low, NIS persisting -> MOMENTUM_DISCOUNT
#   NARRATIVE_DECAY:   NIS dropping, fresh_signal near zero -> SHADOW_BOOK
#
# Retrospective:
#   CVX Day 0-5: SIGNAL_DOMINANT. Full CE. Entry would have been correct.
#   CVX Day 80:  fresh_signal approx 0, NIS persisting on rho decay only.
#                MOMENTUM_DOMINANT -> MOMENTUM_DISCOUNT -> CE below threshold -> LEAVE
#   RTX Day 3:   SIGNAL_DOMINANT (defence signal just fired). Full CE -> WIN.
#
# MOMENTUM_DISCOUNT applied to COMPOSITE_EDGE when MOMENTUM_DOMINANT:
#   CE_adjusted = CE * MOMENTUM_DISCOUNT_FACTOR

NIS_DECAY_RATE = 0.92        # rho: narrative persistence per day
MOMENTUM_DISCOUNT_FACTOR = 0.65  # CE multiplier when MOMENTUM_DOMINANT
SIGNAL_DOMINANT_THRESHOLD  = 0.40  # fresh_signal above this = SIGNAL_DOMINANT
MOMENTUM_DOMINANT_THRESHOLD = 0.15 # fresh_signal below this = MOMENTUM_DOMINANT

def update_nis(nis_prev, fresh_signal_strength):
    return NIS_DECAY_RATE * nis_prev + (1 - NIS_DECAY_RATE) * fresh_signal_strength

def classify_nis_state(nis_score, fresh_signal_strength):
    if fresh_signal_strength > SIGNAL_DOMINANT_THRESHOLD:
        return 'SIGNAL_DOMINANT'
    elif fresh_signal_strength < MOMENTUM_DOMINANT_THRESHOLD:
        if nis_score > 0.3:
            return 'MOMENTUM_DOMINANT'
        else:
            return 'NARRATIVE_DECAY'
    else:
        return 'TRANSITIONAL'

def apply_nis_discount(composite_edge, nis_state):
    if nis_state == 'SIGNAL_DOMINANT':
        return composite_edge
    elif nis_state == 'MOMENTUM_DOMINANT':
        return composite_edge * MOMENTUM_DISCOUNT_FACTOR
    elif nis_state == 'NARRATIVE_DECAY':
        return composite_edge * 0.40
    else:
        return composite_edge * 0.80
