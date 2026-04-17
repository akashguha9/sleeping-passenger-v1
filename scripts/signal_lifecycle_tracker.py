# SIGNAL_LIFECYCLE_TRACKER (SLT)
# Module: S35 — Decision Gate
# Added: April 17 2026
# Source: Russia / architecture / cinema session
#
# Synthesises TAT, GSCE, NIS, NII, EDS, and TEMPORAL_GRAMMAR into a single
# stage label per thesis with stage-specific decision rules.
#
# The Trans-Siberian insight: sequence creates insight that a snapshot cannot.
# WHERE are you on the journey? Not just what does the signal look like now.
#
# Pipeline has TAT (pressure state), GSCE (execution phase), NIS (momentum
# fraction), NARRATIVE_MATURITY (development stage). None synthesises these
# into a single STAGE label with stage-specific entry/sizing/exit rules.
#
# SLT stages:
#   IGNITION:   Day 0-5. Fresh signal, HWE building, TAT BUILDING, CIS2 strong.
#               Enter if HWE>=0.80 + RTT=PORTABLE + CCS>=7.
#   VALIDATION: Day 5-15. Signal confirmed, NIS SIGNAL_DOMINANT, ODM SATURATING.
#               Hold. Monitor EDS for MILD_DIVERGE.
#   EXPANSION:  Day 15-30. TAT PEAK, NIS SIGNAL_DOMINANT, EDS CONFIRMING, NDM GROUNDED.
#               Maximum sizing. Tighten stop progressively.
#   CROWDING:   Day 30-60. T_n HIGH, echo_density HIGH, SDI_env inflating, NII EXTENDED.
#               Reduce size. RTT checks MODERATE tier.
#   EXHAUSTION: Day 60+. NIS MOMENTUM_DOMINANT, TAT SPENT, NII INFLATED, CIS2 declining.
#               Exit preparation. No new entries in this stage.
#   CLOSURE:    Final. TAT SPENT/INVERTED, EDS INVERTED, hard stop hit.
#               Exit or already exited. Log to CAL.
#
# Stage transition triggers:
#   IGNITION -> VALIDATION:   first price/odds confirmation in signal direction
#   VALIDATION -> EXPANSION:  TAT = PEAK AND NIS = SIGNAL_DOMINANT
#   EXPANSION -> CROWDING:    T_n > 0.7 OR echo_density > 0.6
#   CROWDING -> EXHAUSTION:   NIS = MOMENTUM_DOMINANT OR NII = INFLATED
#   EXHAUSTION -> CLOSURE:    TAT = SPENT OR EDS = INVERTED OR CIS2 < 4
#   Any -> CLOSURE:           10% hard stop hit OR thesis break
#
# Portfolio retrospectives:
#   RTX Day 3:   SLT=IGNITION. HWE 0.85, CIS2=10, TAT BUILDING. Enter. WIN.
#   CVX Day 80:  SLT=EXHAUSTION. NIS MOMENTUM, TAT SPENT, NII HYPER. Block. -8.82% avoided.
#   GLD current: SLT=EXPANSION. TAT BUILDING, NIS SIGNAL_DOMINANT. Hold. +8.17%.
#   TLT/TIP:     SLT=CLOSURE. EXIT NOW confirmed. T=7, T=8 when closed.
#
# SLT is distinct from:
#   TAT: pressure state (BUILDING/PEAK/RELEASING/SPENT/INVERTED) - point in time
#   GSCE: execution phase (BUILD_UP/PROGRESSION/FINAL_THIRD/TRANSITION) - action mode
#   NIS: momentum fraction (SIGNAL_DOMINANT/MOMENTUM_DOMINANT) - single dimension
#   SLT: full journey stage - synthesises ALL mechanisms into one operational label
#
# Architecture mapping (Trans-Siberian = SLT):
#   Saint Basil's = hub-and-spoke SANGAM SSSC CONFLUENCE
#   Moscow Metro = SNC routing table
#   Lake Baikal = WMBRL deep memory vault
#   Trans-Siberian = SLT sequential stage tracker
#   Wes Anderson = structured NDM GROUNDED state
#   Satyajit Ray = SNC raw observation before scoring
#   Scorsese = GSCE FINAL_THIRD stress mode

SLT_STAGES = ['IGNITION', 'VALIDATION', 'EXPANSION', 'CROWDING', 'EXHAUSTION', 'CLOSURE']

# Stage-specific rules
SLT_ENTRY_RULE = {
    'IGNITION':   'ENTER if HWE_committed AND RTT_portable AND CCS>=7',
    'VALIDATION': 'HOLD only. No new entry in this thesis.',
    'EXPANSION':  'HOLD. Max sizing. Tighten stop progressively.',
    'CROWDING':   'REDUCE size. RTT check MODERATE tier.',
    'EXHAUSTION': 'NO ENTRY. Exit preparation only.',
    'CLOSURE':    'EXIT or already exited. Log to CAL.',
}

SLT_SIZING_MULTIPLIER = {
    'IGNITION':   1.0,    # QUARTER_UNIT baseline
    'VALIDATION': 1.0,    # maintain
    'EXPANSION':  1.0,    # maintain (at current drift_risk=8 cap)
    'CROWDING':   0.5,    # reduce
    'EXHAUSTION': 0.0,    # exit only
    'CLOSURE':    0.0,    # closed
}

def classify_slt_stage(days_in_thesis: int, tat_state: str, nis_state: str,
                        nii_state: str, eds_state: str, t_n_score: float,
                        echo_density: float, cis2_score: float,
                        hard_stop_hit: bool = False) -> str:
    if hard_stop_hit or eds_state == 'INVERTED' or tat_state == 'INVERTED':
        return 'CLOSURE'
    if tat_state == 'SPENT' and nis_state in ('MOMENTUM_DOMINANT', 'NARRATIVE_DECAY'):
        if cis2_score < 4.0:
            return 'CLOSURE'
        return 'EXHAUSTION'
    if (nis_state == 'MOMENTUM_DOMINANT' or nii_state in ('INFLATED', 'HYPER')
            or days_in_thesis > 60):
        return 'EXHAUSTION'
    if (t_n_score > 0.7 or echo_density > 0.6) and days_in_thesis > 30:
        return 'CROWDING'
    if (tat_state == 'PEAK' and nis_state == 'SIGNAL_DOMINANT'
            and eds_state == 'CONFIRMING'):
        return 'EXPANSION'
    if days_in_thesis >= 5 and nis_state == 'SIGNAL_DOMINANT':
        return 'VALIDATION'
    return 'IGNITION'

def slt_gate(slt_stage: str, hwe_committed: bool = False,
             rtt_portable: bool = False, ccs_score: float = 0.0) -> dict:
    if slt_stage == 'IGNITION':
        if hwe_committed and rtt_portable and ccs_score >= 7.0:
            return {'action': 'ENTER', 'size_multiplier': SLT_SIZING_MULTIPLIER['IGNITION'],
                    'rule': SLT_ENTRY_RULE['IGNITION']}
        return {'action': 'WAIT', 'size_multiplier': 0.0,
                'rule': 'IGNITION conditions not met. Wait for HWE+RTT+CCS.'}
    return {
        'action':          'HOLD' if slt_stage in ('VALIDATION', 'EXPANSION') else (
                           'REDUCE' if slt_stage == 'CROWDING' else 'EXIT'),
        'size_multiplier': SLT_SIZING_MULTIPLIER.get(slt_stage, 0.0),
        'rule':            SLT_ENTRY_RULE.get(slt_stage, ''),
    }

def slt_full_check(days_in_thesis, tat_state, nis_state, nii_state, eds_state,
                   t_n_score, echo_density, cis2_score, hard_stop_hit=False,
                   hwe_committed=False, rtt_portable=False, ccs_score=0.0):
    stage = classify_slt_stage(days_in_thesis, tat_state, nis_state,
                                nii_state, eds_state, t_n_score,
                                echo_density, cis2_score, hard_stop_hit)
    gate  = slt_gate(stage, hwe_committed, rtt_portable, ccs_score)
    return {
        'slt_stage':        stage,
        'days_in_thesis':   days_in_thesis,
        'gate':             gate,
        'entry_rule':       SLT_ENTRY_RULE.get(stage, ''),
        'size_multiplier':  SLT_SIZING_MULTIPLIER.get(stage, 0.0),
    }
