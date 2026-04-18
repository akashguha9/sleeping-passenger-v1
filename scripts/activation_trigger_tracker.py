# ACTIVATION_TRIGGER_TRACKER (ATT)
# Module: S3B — External prerequisite gate, dormant-vs-active classifier
# Added: April 17-18 2026
# Source: India women's reservation bill / delayed-execution signal session
#
# ATT tracks EXTERNAL PREREQUISITE EVENTS required to activate a signal
# that has already passed internal pipeline gates but remains blocked
# by external world events (census, delimitation, FDA decision, Fed
# meeting, earnings release, regulatory approval, court ruling).
#
# ATT is distinct from:
#   MTL:  intra-stage timing (within a single SLT stage)
#   SLT:  signal lifecycle stage (internal narrative progression)
#   LALO: late-adoption saturation (crowd state)
#   PSE:  propagation probability (will it spread forward)
#   NDI:  post-circulation narrative distortion
#   ZPD:  6-gate simultaneous pass check
#
# ATT answers: 'given this signal is structurally valid (NSD clean, CE
# would be STRONG_EDGE, NDI UNDERREPORTED, LALO OPEN_ADOPTION),
# what EXTERNAL world events must happen before execution is possible,
# and when?'
#
# THE INDIA RESERVATION BILL ARCHETYPE:
#   - Signal: 33% women's quota in legislature. Structurally sound thesis.
#   - Passes NSD (SS high, moral + structural grounding)
#   - NDI UNDERREPORTED (less visible than eventual impact)
#   - CE would be STRONG_EDGE
#   - BUT blocked on external prerequisites:
#     1. Census 2027 completion (p=0.90)
#     2. Delimitation exercise ~2028 (p=0.65, politically contested)
#     3. Rotation rule specification ~2029 (p=0.50, incumbent-displacement)
#   - Joint p_activation = 0.29 over 3-year lag
#   - Signal is VALID but DORMANT — cannot deploy capital
#
# ATT FORMALISES:
#
# Each signal carries external_prerequisites list:
#   [
#     {name, expected_completion_date, p_on_time, critical, dependency_type},
#     ...
#   ]
#
# where dependency_type in:
#   LEGAL          - statutory requirement (passed bill, treaty ratification)
#   REGULATORY     - regulator decision (FDA, FCC, SEC approval)
#   SCHEDULED      - known-date event (Fed meeting, earnings, elections)
#   CONTINGENT     - conditional on prior event (post-census delimitation)
#   POLITICAL      - requires political alignment (incumbent consent)
#
# COMPUTATION:
#
#   # activation probability: product over CRITICAL prerequisites
#   p_activation_by_T = prod(p_on_time_i for prereq_i if prereq_i.critical)
#
#   # non-critical prereqs reduce confidence but don't block activation
#   # expected activation date: weighted average of critical prereq dates
#   expected_activation_date = max(critical prereq completion dates)
#
#   # lag in years from today
#   activation_lag_years = (expected_activation_date - today).days / 365
#
#   # time decay factor: 15% annual decay on dormant signals
#   time_decay_factor = exp(-LAMBDA * activation_lag_years)
#   where LAMBDA = 0.15
#
#   # CE adjustment
#   CE_final = CE_raw * time_decay_factor
#
# DECAY EXAMPLES (LAMBDA = 0.15):
#   lag 1 year:  exp(-0.15)   = 0.861
#   lag 2 years: exp(-0.30)   = 0.741
#   lag 3 years: exp(-0.45)   = 0.638
#   lag 5 years: exp(-0.75)   = 0.472
#   lag 10 yrs:  exp(-1.50)   = 0.223
#
# ATT STATES:
#
# ACTIVE: activation_lag < 30 days AND p_activation > 0.70
#   -> Full pipeline. Normal processing. RTX Day 3 archetype.
#
# NEAR_ACTIVATION: activation_lag 30-180 days AND p_activation > 0.60
#   -> Watchlist + pre-positioning authorized at EIGHTH_UNIT
#   -> Monitor prerequisite probabilities daily
#   -> FDA decision date known archetype
#
# DORMANT_VALID: activation_lag 180-1460 days (6mo-4y) AND p_activation > 0.40
#   -> Watchlist only. NO CAPITAL DEPLOYED.
#   -> Signal quality preserved. Timing blocked.
#   -> Refresh prereq probabilities monthly.
#   -> Reservation bill archetype.
#
# FAR_DORMANT: activation_lag > 1460 days OR p_activation < 0.40
#   -> Demote from watchlist. Edge decayed below useful threshold.
#
# BROKEN_CHAIN: any critical prerequisite becomes impossible (p = 0)
#   -> Signal invalidated. Remove from all queues.
#
# ATT FEEDS INTO:
#
#   CE COMPOSITE_EDGE:
#     CE_final = CE_raw * time_decay_factor
#     Large activation_lag -> substantial CE reduction
#
#   IL action selection:
#     ACTIVE:          full IL space
#     NEAR_ACTIVATION: max IL = STAGGER (pre-position only)
#     DORMANT_VALID:   max IL = WATCHLIST (no capital)
#     FAR_DORMANT:     REMOVE
#     BROKEN_CHAIN:    INVALIDATE
#
#   Watchlist-queue isolation:
#     DORMANT_VALID signals live in separate queue from ACTIVE pipeline.
#     Watchlist queue does NOT consume drift_risk budget.
#     This prevents dormant signals from crowding out active capacity.
#
#   MOLTBOOK logging:
#     ATT state at entry recorded per trade.
#     Post-trade: did the trade enter during ACTIVE or was a prereq rushed?
#     Rushed-prereq entries flagged as ATT_VIOLATION.
#
# PORTFOLIO RETROSPECTIVES:
#
#   Women's reservation bill:
#     prereqs = [
#       (census_2027, p=0.90, critical=True),
#       (delimitation_2028, p=0.65, critical=True),
#       (rotation_spec_2029, p=0.50, critical=True)
#     ]
#     p_activation = 0.90 * 0.65 * 0.50 = 0.293
#     expected_activation_date = 2029-Q1 (~3 years from April 2026)
#     activation_lag_years = 3.0
#     time_decay_factor = exp(-0.45) = 0.638
#     
#     ATT state: DORMANT_VALID
#     Action: watchlist only. No capital deployed.
#     Even if CE would be 0.80 STRONG_EDGE at activation, current CE_final
#     = 0.80 * 0.638 = 0.510 GOOD_EDGE range... BUT DORMANT_VALID state
#     forces WATCHLIST action regardless of CE level.
#
#   RTX Day 3 (Iran-war defense):
#     prereqs = [
#       (iran_tension_event, p=1.0, critical=True, already_fired=True),
#       (procurement_cycle_accel, p=0.85, critical=False, in_progress=True)
#     ]
#     p_activation = 1.0 (critical prereqs all fired)
#     activation_lag_years = 0
#     time_decay_factor = 1.0
#     
#     ATT state: ACTIVE
#     Normal processing. Full CE preserved. +3.90% WIN.
#
#   Hypothetical FDA approval play:
#     prereqs = [
#       (FDA_decision_2026_06_15, p=0.95, critical=True, scheduled=True)
#     ]
#     p_activation = 0.95
#     activation_lag_years = 60/365 = 0.164
#     time_decay_factor = exp(-0.0246) = 0.976
#     
#     ATT state: NEAR_ACTIVATION
#     Action: watchlist + EIGHTH_UNIT pre-position authorized.
#     Full sizing only after FDA decision fires.
#
# THE INDIA RESERVATION LAW:
#   A signal can be structurally valid without being tradable.
#   ATT is the gatekeeper between 'this is real' and 'this is live'.
#   Structural validity + LALO OPEN_ADOPTION + NDI UNDERREPORTED + NSD
#   UNDERVALUED + CE STRONG_EDGE does NOT guarantee executability.
#   External world events remain the final gate.

import math
from datetime import date

ATT_LAMBDA                  = 0.15    # annual decay constant

ATT_ACTIVE_LAG_DAYS         = 30
ATT_NEAR_ACTIVATION_LAG_DAYS = 180
ATT_DORMANT_LAG_DAYS        = 1460    # 4 years

ATT_ACTIVE_MIN_P            = 0.70
ATT_NEAR_MIN_P              = 0.60
ATT_DORMANT_MIN_P           = 0.40

def compute_p_activation(prereqs: list) -> float:
    critical = [p for p in prereqs if p.get('critical', True)]
    if not critical:
        return 1.0
    p = 1.0
    for prereq in critical:
        p *= prereq.get('p_on_time', 0.0)
    return round(p, 4)

def compute_activation_lag_years(prereqs: list, today: date) -> float:
    critical_dates = [
        p['expected_completion_date']
        for p in prereqs
        if p.get('critical', True) and not p.get('already_fired', False)
    ]
    if not critical_dates:
        return 0.0
    latest = max(critical_dates)
    lag_days = (latest - today).days
    return round(lag_days / 365.0, 3)

def compute_time_decay(lag_years: float) -> float:
    return round(math.exp(-ATT_LAMBDA * max(0, lag_years)), 4)

def classify_att_state(lag_days: float, p_activation: float,
                       has_broken_chain: bool = False) -> str:
    if has_broken_chain: return 'BROKEN_CHAIN'
    if lag_days < ATT_ACTIVE_LAG_DAYS and p_activation >= ATT_ACTIVE_MIN_P:
        return 'ACTIVE'
    elif (lag_days < ATT_NEAR_ACTIVATION_LAG_DAYS 
          and p_activation >= ATT_NEAR_MIN_P):
        return 'NEAR_ACTIVATION'
    elif (lag_days < ATT_DORMANT_LAG_DAYS 
          and p_activation >= ATT_DORMANT_MIN_P):
        return 'DORMANT_VALID'
    else:
        return 'FAR_DORMANT'

def att_effects(att_state: str) -> dict:
    effects_map = {
        'ACTIVE':          {'max_il_action': 'FIRE_MODE_ELIGIBLE',
                            'consumes_drift_budget': True,
                            'watchlist_only': False,
                            'note': 'Signal live. Normal pipeline processing.'},
        'NEAR_ACTIVATION': {'max_il_action': 'STAGGER',
                            'consumes_drift_budget': True,
                            'watchlist_only': False,
                            'note': 'Pre-position EIGHTH_UNIT. Monitor prereqs daily.'},
        'DORMANT_VALID':   {'max_il_action': 'WATCHLIST',
                            'consumes_drift_budget': False,
                            'watchlist_only': True,
                            'note': 'Watchlist only. No capital. Refresh prereqs monthly.'},
        'FAR_DORMANT':     {'max_il_action': 'REMOVE',
                            'consumes_drift_budget': False,
                            'watchlist_only': False,
                            'note': 'Edge decayed. Demote from watchlist.'},
        'BROKEN_CHAIN':    {'max_il_action': 'INVALIDATE',
                            'consumes_drift_budget': False,
                            'watchlist_only': False,
                            'note': 'Critical prereq impossible. Signal dead.'},
    }
    return effects_map.get(att_state, effects_map['FAR_DORMANT'])

def compute_att(prereqs: list, today: date = None,
                ce_raw: float = None) -> dict:
    if today is None:
        today = date.today()
    has_broken = any(p.get('p_on_time', 0.0) <= 0.0 and p.get('critical', True)
                     for p in prereqs)
    p_activation = compute_p_activation(prereqs) if not has_broken else 0.0
    lag_years    = compute_activation_lag_years(prereqs, today)
    lag_days     = lag_years * 365
    time_decay   = compute_time_decay(lag_years)
    state        = classify_att_state(lag_days, p_activation, has_broken)
    effects      = att_effects(state)
    result = {
        'att_state':            state,
        'p_activation':         p_activation,
        'activation_lag_years': lag_years,
        'activation_lag_days':  round(lag_days, 1),
        'time_decay_factor':    time_decay,
        'effects':              effects,
        'prereqs_summary':      [
            {'name': p.get('name', 'unnamed'),
             'p_on_time': p.get('p_on_time', 0.0),
             'critical':  p.get('critical', True)}
            for p in prereqs
        ],
    }
    if ce_raw is not None:
        result['ce_raw']   = ce_raw
        result['ce_final'] = round(ce_raw * time_decay, 3)
    return result
