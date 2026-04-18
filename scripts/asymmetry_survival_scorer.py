# ASYMMETRY_SURVIVAL_SCORER (ASS)
# Module: S35 — Trade-level quality gate
# Added: April 17 2026
# Source: "The optimist gave flight, the pessimist gave parachutes" session
#
# Q = O × S
# The parachute check: after SBE confirms a signal floats, ASS asks whether
# the TRADE is of high quality — both opportunity AND survivability.
#
# SBE says: 'the signal floats' (the wings work)
# ASS says: 'AND the parachute is attached' (Q = O × S)
#
# A signal can have B = STRONG_FLOAT (SBE) but still have low S:
#   -> Q = O(high) * S(low) = LOW quality trade despite floating signal
#   -> This is the CVX Day 80 pattern: signal seemed fine but no parachute
#
# O (Opportunity Score): computed by ASYMMETRY ENGINE (optimist)
#   What could pay? Upside quality: asymmetry, timing, catalyst, pre-narrative edge.
#   o1 (30%): asymmetry_ratio = normalised(potential_upside / potential_downside)
#   o2 (25%): timing_score = SLT_stage_scores:
#              IGNITION=0.7, VALIDATION=0.8, EXPANSION=1.0, CROWDING=0.4,
#              EXHAUSTION=0.1, CLOSURE=0.0
#   o3 (25%): catalyst_clarity = CIS2_score / 10
#   o4 (20%): pre_narrative_edge = 1 - (SLT_stage_ordinal / 6)
#
# S (Survival Score): computed by SURVIVAL ENGINE (pessimist)
#   What could kill this? Downside quality: invalidation, exit, loss bound, decay.
#   s1 (30%): invalidation_clarity = 0.0 (not defined), 0.4 (defined), 0.8 (measurable)
#   s2 (25%): exit_clarity = SLT_stage exits: IGNITION/VALIDATION=0.9, EXPANSION=0.7,
#              CROWDING=0.4, EXHAUSTION=0.3, CLOSURE=0.0
#   s3 (30%): loss_bound = 1.0 if hard_stop_defined (10% rule), 0.5 if partial, 0.0 if none
#   s4 (15%): decay_resistance = SF_persistence_score / 10
#
# Q = O * S     range: 0 to 1
#
# Q thresholds:
#   HIGH:     Q >= 0.64 -> enter QUARTER_UNIT
#   MODERATE: Q 0.36-0.64 -> reduce size or watchlist
#   LOW:      Q 0.16-0.36 -> skip
#   REJECT:   Q < 0.16  -> hard reject regardless of SBE state
#
# GOVERNANCE SPLIT:
#   O: Asymmetry Engine (optimist) computes opportunity
#   S: Survival Engine (pessimist) computes survivability
#   Q = O * S: neither engine alone approves
#   HARD VETO: if S < 0.30 -> trade blocked regardless of O
#     The parachute check is a hard gate, not a scoring softener
#
# Portfolio retrospectives:
#   RTX Day 3:   O=0.88, S=0.88 -> Q=0.77 HIGH QUALITY -> ENTER -> +3.90% WIN
#   CVX Day 80:  O=0.14, S=0.27 -> Q=0.04 REJECT -> -8.82% avoided
#   GLD current: O=0.75, S=0.80 -> Q=0.60 MODERATE -> QUARTER_UNIT -> +8.17% holds
#
# The parachute law:
#   SBE confirms the signal floats. ASS confirms the parachute is attached.
#   Build like an optimist. Execute like a pessimist.
#   The engine that enters should not be the engine that invalidates.

Q_HIGH_THRESHOLD     = 0.64
Q_MODERATE_THRESHOLD = 0.36
Q_LOW_THRESHOLD      = 0.16
S_VETO_THRESHOLD     = 0.30   # hard veto: if S < 0.30, reject regardless of O

SLT_TIMING_SCORES = {
    'IGNITION':   0.70,
    'VALIDATION': 0.80,
    'EXPANSION':  1.00,
    'CROWDING':   0.40,
    'EXHAUSTION': 0.10,
    'CLOSURE':    0.00,
}
SLT_EXIT_CLARITY = {
    'IGNITION':   0.90,
    'VALIDATION': 0.90,
    'EXPANSION':  0.70,
    'CROWDING':   0.40,
    'EXHAUSTION': 0.30,
    'CLOSURE':    0.00,
}
SLT_STAGE_ORDINAL = {
    'IGNITION': 0, 'VALIDATION': 1, 'EXPANSION': 2,
    'CROWDING': 3, 'EXHAUSTION': 4, 'CLOSURE': 5,
}

def compute_opportunity_score(asymmetry_ratio: float, slt_stage: str,
                               cis2_score: float) -> dict:
    o1 = max(0.0, min(1.0, asymmetry_ratio))
    o2 = SLT_TIMING_SCORES.get(slt_stage, 0.5)
    o3 = min(cis2_score / 10.0, 1.0)
    stage_ord = SLT_STAGE_ORDINAL.get(slt_stage, 3)
    o4 = max(0.0, 1.0 - (stage_ord / 6.0))
    O = 0.30*o1 + 0.25*o2 + 0.25*o3 + 0.20*o4
    return {
        'O': round(O, 3),
        'components': {
            'asymmetry_ratio': round(o1, 3),
            'timing_score':    round(o2, 3),
            'catalyst_clarity':round(o3, 3),
            'pre_narrative_edge': round(o4, 3),
        }
    }

def compute_survival_score(invalidation_clarity: float, slt_stage: str,
                            hard_stop_defined: bool, sf_persistence_score: float) -> dict:
    s1 = max(0.0, min(1.0, invalidation_clarity))  # 0.0/0.4/0.8
    s2 = SLT_EXIT_CLARITY.get(slt_stage, 0.5)
    s3 = 1.0 if hard_stop_defined else 0.0
    s4 = min(sf_persistence_score / 10.0, 1.0)
    S = 0.30*s1 + 0.25*s2 + 0.30*s3 + 0.15*s4
    return {
        'S': round(S, 3),
        'components': {
            'invalidation_clarity': round(s1, 3),
            'exit_clarity':         round(s2, 3),
            'loss_bound':           round(s3, 3),
            'decay_resistance':     round(s4, 3),
        }
    }

def classify_q(q_score: float, s_score: float) -> str:
    if s_score < S_VETO_THRESHOLD:
        return 'VETO_S'   # parachute not attached
    if q_score >= Q_HIGH_THRESHOLD:     return 'HIGH'
    elif q_score >= Q_MODERATE_THRESHOLD: return 'MODERATE'
    elif q_score >= Q_LOW_THRESHOLD:    return 'LOW'
    else:                               return 'REJECT'

def ass_gate(q_state: str, q_score: float) -> dict:
    gates = {
        'HIGH':     {'action': 'ENTER',         'size': 'QUARTER_UNIT',
                     'note': f'Q={q_score:.2f} HIGH. Both wings and parachute.'},
        'MODERATE': {'action': 'ENTER_REDUCED', 'size': 'HALF_QUARTER_UNIT',
                     'note': f'Q={q_score:.2f} MODERATE. One dimension weak. Reduce size.'},
        'LOW':      {'action': 'WATCHLIST',     'size': 'NO_ENTRY',
                     'note': f'Q={q_score:.2f} LOW. Skip or watchlist only.'},
        'REJECT':   {'action': 'REJECT',        'size': 'NO_ENTRY',
                     'note': f'Q={q_score:.2f} REJECT. CVX Day 80 pattern.'},
        'VETO_S':   {'action': 'VETO',          'size': 'NO_ENTRY',
                     'note': f'S < {S_VETO_THRESHOLD}. HARD VETO. No parachute. Block regardless of O.'},
    }
    return gates.get(q_state, {'action': 'REJECT', 'size': 'NO_ENTRY'})

def ass_full_check(asymmetry_ratio: float, slt_stage: str, cis2_score: float,
                   invalidation_clarity: float, hard_stop_defined: bool,
                   sf_persistence_score: float) -> dict:
    opp    = compute_opportunity_score(asymmetry_ratio, slt_stage, cis2_score)
    surv   = compute_survival_score(invalidation_clarity, slt_stage,
                                    hard_stop_defined, sf_persistence_score)
    O, S   = opp['O'], surv['S']
    Q      = round(O * S, 3)
    state  = classify_q(Q, S)
    gate   = ass_gate(state, Q)
    return {
        'Q':             Q,
        'O':             O,
        'S':             S,
        'q_state':       state,
        'gate':          gate,
        'O_components':  opp['components'],
        'S_components':  surv['components'],
        'veto_applied':  (S < S_VETO_THRESHOLD),
    }
