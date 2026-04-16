# NARRATIVE_ARCHETYPE_ROUTER (NAR)
# Module: S1 — Belief State
# Added: April 16 2026
# Source: Como/Venezia/football club archetype session
#
# Classifies narrative type BEFORE routing to entry logic.
# REACTION_CLASSIFIER knows HOW a signal moves.
# NAR knows WHAT KIND of narrative it is.
#
# Archetypes:
#   COMPOUNDING: Como — quiet build, earned, structural depth
#     Signals: NLR_lag > 30d, SIS > 0.6, T_n < 0.5
#     Entry: PRE_BURST_COIL -> SNIPER (patient, early)
#
#   ATTENTION: Venezia — hot, manufactured, fast-moving
#     Signals: T_n > 0.7, NLR_lag < 7d, SIS < 0.5
#     Entry: STAND_UP_RUN -> M16 (fast burst, tight exit)
#
#   HYBRID: structure + brand amplification
#     Signals: SIS > 0.5, T_n > 0.4, moderate lag
#     Entry: standard pipeline with SIS discount
#
#   EXTRACTION: high heat, low depth, prior cluster failed
#     Signals: EQS < 0.3, T_n > 0.6, SIS < 0.4
#     Entry: NONE -> SHADOW_BOOK only
#
# Retrospective validation:
#   War/energy cluster (CVX, XOM, USO):
#     T_n=HIGH, NLR_lag=80d, EQS=0.0 after MP+ZIM -> EXTRACTION -> NONE
#     All three entries would have been blocked.
#   RTX:
#     T_n=MODERATE, NLR_lag=3d, SIS=HIGH -> COMPOUNDING -> SNIPER -> +3.90% WIN

COMPOUNDING_THRESHOLDS = {'nlr_lag_min': 30, 'sis_min': 0.6, 'tn_max': 0.5}
ATTENTION_THRESHOLDS   = {'tn_min': 0.7, 'nlr_lag_max': 7, 'sis_max': 0.5}
EXTRACTION_THRESHOLDS  = {'eqs_max': 0.3, 'tn_min': 0.6, 'sis_max': 0.4}

def classify_archetype(nlr_lag_days, sis_score, tn_score, eqs_score):
    if (eqs_score < EXTRACTION_THRESHOLDS['eqs_max'] and
        tn_score > EXTRACTION_THRESHOLDS['tn_min'] and
        sis_score < EXTRACTION_THRESHOLDS['sis_max']):
        return 'EXTRACTION'
    if (nlr_lag_days > COMPOUNDING_THRESHOLDS['nlr_lag_min'] and
        sis_score > COMPOUNDING_THRESHOLDS['sis_min'] and
        tn_score < COMPOUNDING_THRESHOLDS['tn_max']):
        return 'COMPOUNDING'
    if (tn_score > ATTENTION_THRESHOLDS['tn_min'] and
        nlr_lag_days < ATTENTION_THRESHOLDS['nlr_lag_max'] and
        sis_score < ATTENTION_THRESHOLDS['sis_max']):
        return 'ATTENTION'
    return 'HYBRID'

def archetype_to_fire_mode(archetype):
    routing = {
        'COMPOUNDING': 'SNIPER',
        'ATTENTION':   'M16',
        'HYBRID':      'SNIPER_SIS_DISCOUNTED',
        'EXTRACTION':  'NONE',
    }
    return routing[archetype]
