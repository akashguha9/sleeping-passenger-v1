# TENSION_ACCUMULATION_TRACKER (TAT)
# Module: S35 — Decision Gate
# Added: April 16 2026
# Source: Olise/Timbaland dual session
#
# Tracks the PRESSURE STATE of a thesis — is tension building toward
# payoff, or has it been spent or inverted?
#
# TAT_t = TAT_{t-1} + (PredMkt_momentum_t - Resolution_signal_t)
#
# TAT also makes MTL fully operational:
#   t_open  = when TAT crosses BUILDING threshold (from zero)
#   t_close = when TAT crosses SPENT threshold (back to near zero)
#   t_star  = TAT PEAK state (optimal entry)
#
# TAT states:
#   BUILDING:  TAT increasing. Tension accumulating. Enter valid.
#   PEAK:      TAT at maximum. Optimal entry window. MTL t_star.
#   RELEASING: TAT decreasing but positive. Partial resolution. Caution.
#   SPENT:     TAT near zero. Pressure consumed. MTL t_close. LEAVE.
#   INVERTED:  TAT negative. Thesis resolved in opposite direction. Exit.
#
# Retrospective:
#   CVX: TAT peaked Day 5-15. By Day 80: TAT = SPENT -> LEAVE. -8.82% avoided.
#   GLD: Entry at BUILDING/RELEASING -> +8.17% confirms valid state.
#   ZIM: Iran 64% arrival -> TAT goes INVERTED -> thesis break -> correct exit -2.19%.
#   RTX: Entry Day 3 -> TAT = BUILDING (just triggered) -> full CE -> +3.90% WIN.

TAT_BUILDING_THRESHOLD = 0.15   # TAT above this = BUILDING (entry valid)
TAT_SPENT_THRESHOLD    = 0.10   # TAT below this = SPENT (entry blocked)
TAT_PEAK_LOOKBACK      = 5      # days to check for local maximum

def update_tat(tat_prev, predmkt_momentum, resolution_signal):
    return tat_prev + predmkt_momentum - resolution_signal

def classify_tat_state(tat_current, tat_history):
    if tat_current < 0:
        return 'INVERTED'
    if tat_current < TAT_SPENT_THRESHOLD:
        return 'SPENT'
    if len(tat_history) >= TAT_PEAK_LOOKBACK:
        recent_peak = max(tat_history[-TAT_PEAK_LOOKBACK:])
        if tat_current >= recent_peak * 0.95:
            return 'PEAK'
        elif tat_current < tat_history[-1]:
            return 'RELEASING'
    if tat_current > TAT_BUILDING_THRESHOLD:
        return 'BUILDING'
    return 'BUILDING'

def tat_entry_gate(tat_state):
    entry_valid = {
        'BUILDING':  True,
        'PEAK':      True,
        'RELEASING': True,   # early releasing only; combine with MTL
        'SPENT':     False,
        'INVERTED':  False,
    }
    return entry_valid.get(tat_state, False)

def tat_to_mtl_windows(tat_history_with_dates):
    t_open  = next((d for d, v in tat_history_with_dates if v > TAT_BUILDING_THRESHOLD), None)
    t_close = next((d for d, v in reversed(tat_history_with_dates) if v < TAT_SPENT_THRESHOLD), None)
    t_peak  = max(tat_history_with_dates, key=lambda x: x[1], default=(None, 0))[0]
    return t_open, t_peak, t_close
