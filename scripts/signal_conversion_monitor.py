# SIGNAL_CONVERSION_MONITOR (SCM)
# Module: CAL — Calibration
# Added: April 16 2026
# Source: Railway campus / conversion failure session
#
# Meta-diagnostic: what fraction of the operator's identified edge is
# successfully converting into clean pipeline entries?
#
# SCM_rate = clean_SYSTEM_entries / total_signals_above_CE_threshold
#
# CEE detects overload (too much entering at once — April 4 CHAOS cluster).
# SCM detects conversion failure (too little entering cleanly — T=6 vs 9.57 arch).
# They are opposite failure modes. GSCE manages the balance between them.
#
# Current state (T=6, April 16 2026):
#   clean_SYSTEM_entries = 2 (RTX WIN + ZIM correct thesis-break exit)
#   total_signals_above_threshold approx 12
#   SCM_rate approx 0.17 -> LOW_CONVERSION
#
# This explains the architecture-vs-results gap precisely:
#   Pipeline score 9.57/9.76 = high latent edge
#   T=6, epsilon=1.0 = low expressed output
#   Gap = conversion friction, not trait deficit
#
# SCM states:
#   HIGH_CONVERSION:     rate > 0.60 -> operator expressing edge cleanly
#   PARTIAL_CONVERSION:  rate 0.30-0.60 -> some signals converting
#   LOW_CONVERSION:      rate 0.10-0.30 -> most edge not making it through
#   CONVERSION_FAILURE:  rate < 0.10 -> operator has edge but not expressing it
#
# When LOW_CONVERSION detected, SCM routes diagnosis to blocking gates in order:
#   1. GSCE phase lock (most common — S4 firing in BUILD_UP)
#   2. CEE overload (SESSION_LOCK still active)
#   3. MTL timing (EARLY or EXPIRED state)
#   4. NAR archetype (EXTRACTION classification)
#   5. TAT pressure state (SPENT or INVERTED)
#   6. REALM + BIS (operator state blocking)
#
# SCM_rate target progression:
#   Current:  0.17 (LOW_CONVERSION)
#   T=10:     0.25+ (PARTIAL as 4 more clean closes added)
#   S9 live:  0.35+ (PARTIAL with Polymarket data)
#   Real cap: 0.50+ (HIGH_CONVERSION target)

SCM_HIGH_CONVERSION     = 0.60
SCM_PARTIAL_CONVERSION  = 0.30
SCM_LOW_CONVERSION      = 0.10

DIAGNOSTIC_ROUTING_ORDER = [
    'GSCE_PHASE_LOCK',
    'CEE_OVERLOAD',
    'MTL_TIMING',
    'NAR_ARCHETYPE',
    'TAT_PRESSURE_STATE',
    'REALM_BIS',
]

def compute_scm_rate(clean_system_entries, total_signals_above_threshold):
    if total_signals_above_threshold == 0:
        return 0.0
    return clean_system_entries / total_signals_above_threshold

def classify_scm_state(scm_rate):
    if scm_rate >= SCM_HIGH_CONVERSION:
        return 'HIGH_CONVERSION'
    elif scm_rate >= SCM_PARTIAL_CONVERSION:
        return 'PARTIAL_CONVERSION'
    elif scm_rate >= SCM_LOW_CONVERSION:
        return 'LOW_CONVERSION'
    else:
        return 'CONVERSION_FAILURE'

def scm_diagnostic_route(scm_state, gate_states):
    if scm_state in ('HIGH_CONVERSION', 'PARTIAL_CONVERSION'):
        return None
    blocking_gates = []
    for gate in DIAGNOSTIC_ROUTING_ORDER:
        if gate_states.get(gate, False):
            blocking_gates.append(gate)
    return blocking_gates if blocking_gates else ['UNKNOWN_BLOCKER']

def scm_review(clean_entries, total_signals, gate_states):
    rate  = compute_scm_rate(clean_entries, total_signals)
    state = classify_scm_state(rate)
    diagnosis = scm_diagnostic_route(state, gate_states)
    return {
        'scm_rate':   round(rate, 3),
        'scm_state':  state,
        'diagnosis':  diagnosis,
        'gap_type':   'CONVERSION_FRICTION' if state != 'HIGH_CONVERSION' else 'NONE',
    }
