# CYCLE_CLARITY_SCORE (CCS) + CHAOS_INTENSITY_SCORE (CIS)
# Module: S35 / CAL
# Added: April 16 2026
# Source: OODA / The Doors / CCS-CIS session
#
# Two-axis deployment gate. The formal operationalisation of:
# 'Best trades when you see the pattern and others see fog.'
#
# Deploy ONLY when CCS >= 7 AND CIS >= 7 -> EDGE_ZONE
#
# Pipeline has NAR, EDS, TAT, GSCE, SDI, REALM — each scores one dimension.
# None combined them into a single two-variable gate until now.
#
# Decision matrix:
#   CCS >= 7 AND CIS >= 7:  EDGE_ZONE -> deploy capital (FIRE_MODE permitted)
#   CCS >= 7 AND CIS < 4:   CROWDED_TREND -> crowd also sees it, SHADOW_BOOK only
#   CCS < 4 AND CIS >= 7:   CHAOS_TRAP -> confusion without structure, NO ENTRY
#   CCS < 4 AND CIS < 4:    DEAD_ZONE -> nothing happening, WAIT
#   CCS 4-7 AND CIS 4-7:    TRANSITIONAL -> monitor, do not deploy
#
# CCS components (each 0-2, total 0-10):
#   1. pattern_recognition:      NAR archetype confidence * SIS depth
#      COMPOUNDING=2, HYBRID=1.5, ATTENTION=1, EXTRACTION=0
#   2. historical_analog_match:  HPS persistence * NLR_lag_fit
#      strong analog right timing=2, partial=1, none=0
#   3. narrative_familiarity:    NIS SIGNAL_DOMINANT * maturity_stage
#      PRE_BURST_COIL + SIGNAL_DOMINANT=2, late=0
#   4. behavioral_predictability: TAT BUILDING/PEAK * EDS CONFIRMING
#      both positive=2, one=1, neither=0
#   5. timing_structure:         MTL OPTIMAL * GSCE FINAL_THIRD
#      both=2, one=1, neither=0
#
# CIS components (each 0-2, total 0-10):
#   1. signal_noise:             SDI_environment * SOURCE_BUBBLE_echo_density
#      both HIGH=2, one=1, low=0
#   2. emotional_extremes:       THREE_POISONS_bias_total (crowd, not operator)
#      HIGH crowd bias=2, moderate=1, low=0
#   3. volatility:               T_n narrative temperature
#      T_n > 0.7=2, 0.4-0.7=1, < 0.4=0
#   4. narrative_fragmentation:  EDS state
#      INVERTED=2, STRONG_DIVERGE=1.5, MILD_DIVERGE=0.5, CONFIRMING=0
#   5. reference_loss:           TAT SPENT/INVERTED or NIS NARRATIVE_DECAY
#      INVERTED=2, SPENT=1.5, MOMENTUM_DOMINANT=1, SIGNAL_DOMINANT=0
#
# Portfolio retrospectives:
#   RTX Day 3:   CCS=10 (all 5 factors max), CIS=6 -> EDGE_ZONE -> +3.90% WIN
#   CVX Day 80:  CCS=0.5 (all factors fail) -> DEAD_ZONE/CHAOS_TRAP -> blocked -> -8.82% avoided
#   GLD entry:   CCS=10, CIS=6 -> EDGE_ZONE -> +8.17% confirms

CCS_EDGE_THRESHOLD = 7.0
CIS_EDGE_THRESHOLD = 7.0

NAR_PATTERN_SCORES = {
    'COMPOUNDING':  2.0,
    'HYBRID':       1.5,
    'ATTENTION':    1.0,
    'EXTRACTION':   0.0,
}

EDS_FRAGMENTATION_SCORES = {
    'INVERTED':       2.0,
    'STRONG_DIVERGE': 1.5,
    'MILD_DIVERGE':   0.5,
    'CONFIRMING':     0.0,
}

TAT_REFERENCE_SCORES = {
    'INVERTED':           2.0,
    'SPENT':              1.5,
    'MOMENTUM_DOMINANT':  1.0,
    'SIGNAL_DOMINANT':    0.0,
}

def compute_ccs(nar_archetype, sis_score, hps_match, nlr_fit,
                nis_state, maturity_score, tat_state, eds_state,
                mtl_state, gsce_phase):
    c1 = NAR_PATTERN_SCORES.get(nar_archetype, 0) * sis_score
    c2 = hps_match * nlr_fit
    c3 = (2.0 if nis_state == 'SIGNAL_DOMINANT' else 0.5) * maturity_score
    c4_tat = 1 if tat_state in ('BUILDING', 'PEAK') else 0
    c4_eds = 1 if eds_state == 'CONFIRMING' else 0
    c4 = c4_tat + c4_eds
    c5_mtl = 1 if mtl_state == 'OPTIMAL' else 0
    c5_gsce = 1 if gsce_phase == 'FINAL_THIRD' else 0
    c5 = c5_mtl + c5_gsce
    return min(c1 + c2 + c3 + c4 + c5, 10.0)

def compute_cis(sdi_env_score, echo_density, crowd_bias_total,
                t_n_score, eds_state, tat_state, nis_state):
    z1 = min(sdi_env_score + echo_density, 2.0)
    z2 = 2.0 if crowd_bias_total > 0.6 else (1.0 if crowd_bias_total > 0.3 else 0.0)
    z3 = 2.0 if t_n_score > 0.7 else (1.0 if t_n_score > 0.4 else 0.0)
    z4 = EDS_FRAGMENTATION_SCORES.get(eds_state, 0.0)
    z5 = TAT_REFERENCE_SCORES.get(tat_state, TAT_REFERENCE_SCORES.get(nis_state, 0.0))
    return min(z1 + z2 + z3 + z4 + z5, 10.0)

def classify_decision_zone(ccs, cis):
    if ccs >= CCS_EDGE_THRESHOLD and cis >= CIS_EDGE_THRESHOLD:
        return 'EDGE_ZONE'
    elif ccs >= CCS_EDGE_THRESHOLD and cis < 4.0:
        return 'CROWDED_TREND'
    elif ccs < 4.0 and cis >= CIS_EDGE_THRESHOLD:
        return 'CHAOS_TRAP'
    elif ccs < 4.0 and cis < 4.0:
        return 'DEAD_ZONE'
    else:
        return 'TRANSITIONAL'

def ccs_cis_gate(ccs, cis):
    zone = classify_decision_zone(ccs, cis)
    action = 'DEPLOY' if zone == 'EDGE_ZONE' else (
             'SHADOW_BOOK' if zone == 'CROWDED_TREND' else (
             'NO_ENTRY' if zone == 'CHAOS_TRAP' else (
             'WAIT' if zone == 'DEAD_ZONE' else 'MONITOR')))
    return {
        'ccs':    round(ccs, 2),
        'cis':    round(cis, 2),
        'zone':   zone,
        'action': action,
        'fire_mode_permitted': zone == 'EDGE_ZONE',
    }
