# MICRO_TIMING_LAYER (MTL)
# Module: S35 (decision gate) / S0 (signal intake)
# Added: April 16 2026
# Source: Fabregas/Como timing session
#
# Separates decision quality from timing precision.
# Pipeline knows WHAT to enter (CE) and HOW developed the signal is (PBSC).
# MTL answers: WHEN within a valid window should the trigger fire?
#
# Key insight: decision quality and timing quality are orthogonal variables.
# CVX was a correct directional thesis — wrong temporal window (Day 80 vs Day 5).
# RTX was correct direction AND correct timing (Day 3) -> +3.90% WIN.
#
# MTL_state:
#   EARLY:   t < t_open -> SHADOW_BOOK, not yet
#   OPTIMAL: t in [t_open, t_open + tau_D/3] -> GREEN_LIGHT, execute
#   LATE:    t in [t_open + tau_D/3, t_close] -> CAUTION, apply NLR penalty
#   EXPIRED: t > t_close -> BLOCKED -> LEAVE (TEMPORAL_GRAMMAR = PRESENT_PERFECT)
#
# Retrospective:
#   CVX: PBSC Day 5. Entry Day 80 -> EXPIRED -> LEAVE. -8.82% avoided.
#   RTX: PBSC Day 2. Entry Day 3 -> OPTIMAL -> +3.90% WIN confirmed.
#   XOM: Same signal class as CVX. Entry Day 85 -> EXPIRED -> LEAVE. -6.72% avoided.

MTL_OPTIMAL_FRACTION = 1/3  # first third of window is optimal

def compute_mtl_window(t_pbsc_transition, tau_D_days):
    t_open  = t_pbsc_transition
    t_close = t_pbsc_transition + tau_D_days
    t_optimal_end = t_pbsc_transition + tau_D_days * MTL_OPTIMAL_FRACTION
    return t_open, t_optimal_end, t_close

def get_mtl_state(current_day, t_open, t_optimal_end, t_close):
    if current_day < t_open:
        return 'EARLY'
    elif current_day <= t_optimal_end:
        return 'OPTIMAL'
    elif current_day <= t_close:
        return 'LATE'
    else:
        return 'EXPIRED'

def mtl_gate(mtl_state):
    gates = {
        'EARLY':   ('SHADOW_BOOK', 'Signal developing. Do not enter yet.'),
        'OPTIMAL': ('GREEN_LIGHT', 'Within optimal execution window. Enter.'),
        'LATE':    ('CAUTION',     'Apply NLR_lag penalty to COMPOSITE_EDGE.'),
        'EXPIRED': ('LEAVE',       'Window closed. TEMPORAL_GRAMMAR = PRESENT_PERFECT.'),
    }
    return gates[mtl_state]
