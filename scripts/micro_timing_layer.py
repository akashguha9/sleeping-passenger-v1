# MICRO_TIMING_LAYER (MTL)
# Module: S35 — Intra-stage timing precision
# Added: April 17-18 2026
# Source: RVP / Jonty Rhodes / chess / table tennis / snap-window session
#
# V(t) = V0 * exp(-lambda * t)
# Opportunity value decays exponentially within a stage window.
# SLT says which stage. MTL says where within that stage you are right now.
#
# The distinction:
#   SLT = EXPANSION means you are in the optimal entry stage.
#   MTL = OPENING vs CLOSING distinguishes Day 1 from Day 34 of EXPANSION.
#   SLT cannot make this distinction. MTL can.
#
# time_fraction = time_elapsed_since_stage_entry / stage_estimated_duration
#   0.0 = just entered this stage
#   1.0 = about to leave this stage
#   >1.0 = stage window expired
#
# MTL states:
#   OPENING:  time_fraction < 0.25  -> most of window remains
#             -> IL STAGGER tranche_1 timing
#             -> maximum snap_window_score, enter first tranche
#
#   BUILDING: time_fraction 0.25-0.50 -> momentum phase
#             -> IL STAGGER tranche_2 timing
#             -> GLD current (Day 13 / 35 = 0.37) = BUILDING
#
#   PEAK:     time_fraction 0.50-0.75 -> highest quality window
#             -> FIRE_MODE if ZPD CLEAN_ZONE simultaneously
#             -> IL STAGGER tranche_3 timing
#             -> ZPD HALF_UNIT only fires at MTL PEAK (not CLOSING)
#
#   CLOSING:  time_fraction 0.75-1.0 -> value decaying, urgency rising
#             -> IL PROBE only, no FIRE_MODE
#             -> window closing, do not enter full size
#
#   EXPIRED:  time_fraction > 1.0 -> window closed
#             -> LEAVE or check if SLT has advanced to next stage
#             -> CVX Day 80 = EXPIRED
#
# Snap-window score:
#   V(t) = V0 * exp(-lambda * time_fraction)
#   V0 = ASS Q score at stage entry (the quality of the setup when it was fresh)
#   lambda = decay_rate (default 0.5, calibrate on T=10+ closed trades)
#   This replaces ASS timing_score's coarse stage-to-float mapping with
#   a continuous exponential decay score within the stage.
#
# Stage duration estimates (heuristic until empirically calibrated):
#   IGNITION:   7-14 days  (pre-narrative forms quickly)
#   VALIDATION: 7-21 days  (can persist if narrative stays clean)
#   EXPANSION:  14-35 days (prime entry window, widest range)
#   CROWDING:   7-21 days  (shortens as saturation accelerates)
#   EXHAUSTION: 3-14 days  (often fast, do not re-enter)
#   CLOSURE:    3-7 days   (exit quickly, lock profits or cut losses)
#
# MTL feeds into downstream mechanisms:
#   1. IL STAGGER tranche timing:
#      tranche_1: fires when MTL state = OPENING
#      tranche_2: fires when MTL state = BUILDING or PEAK
#      tranche_3: fires when MTL state = PEAK (and SBE -> STRONG_FLOAT)
#      Replaces vague 'when CFD CONVERGING' with precise stage position.
#
#   2. ASS timing_score refinement:
#      snap_window_score = V(t) replaces coarse SLT_TIMING_SCORES dict
#      More precise: exponential decay within stage vs stage-level constant
#
#   3. ZPD CLEAN_ZONE size upgrade:
#      HALF_UNIT upgrade should only fire at MTL PEAK, not MTL CLOSING
#      MTL gates the size upgrade to the optimal intra-stage window
#
# The snap-window law from sport:
#   RVP:         saw cross early (CFD CONVERGING), committed at MTL PEAK, not first sight
#   Jonty Rhodes: anticipated early (SF PRISTINE), launched at precise MTL CLOSING urgency
#   Table tennis:  read wrist/shoulders early, force MTL delay to BUILDING/PEAK
#                  not at OPENING (early read ≠ early action)
#   Chess:         sees position early (ZPD CLEAN_ZONE), plays at MTL PEAK when decisive
#
# The deepest law from this session:
#   See early (CFD CONVERGING + SF PRISTINE)
#   Wait properly (MTL OPENING -> BUILDING -> PEAK)
#   Strike cleaner (FIRE_MODE + ZPD CLEAN_ZONE at MTL PEAK)
#   NOT at first sight.
#
# Portfolio retrospectives:
#   RTX Day 3:
#     Stage: VALIDATION (entered Day 1, now Day 3, estimated 14 days)
#     time_fraction = 3/14 = 0.21 -> MTL OPENING
#     V(0.21) = 0.88 * exp(-0.5 * 0.21) = 0.88 * 0.90 = 0.80
#     MTL OPENING -> tranche_1 justified, most of window remains
#     Outcome: +3.90% WIN. Confirmed OPENING entry was correct.
#
#   CVX Day 80:
#     Stage: EXHAUSTION (far into window, time_fraction >> 1.0)
#     V(1.0+) = 0.14 * exp(-0.5 * 1.0+) ≈ 0.08 -> EXPIRED
#     MTL EXPIRED -> LEAVE -> confirms SBE TRAP + RTT HOSTILE
#     Outcome: -8.82% avoided. EXPIRED correctly blocked.
#
#   GLD current:
#     Stage: EXPANSION (entered ~April 5, now April 18 = Day 13)
#     Stage estimated duration: 35 days
#     time_fraction = 13/35 = 0.37 -> MTL BUILDING
#     V(0.37) = 0.60 * exp(-0.5 * 0.37) = 0.60 * 0.83 = 0.50
#     MTL BUILDING -> tranche_2 continuation -> +8.17% holds

import math

MTL_OPENING_THRESHOLD  = 0.25
MTL_BUILDING_THRESHOLD = 0.50
MTL_PEAK_THRESHOLD     = 0.75
MTL_LAMBDA_DEFAULT     = 0.50   # decay rate — calibrate on T=10+

STAGE_DURATION_ESTIMATES = {
    'IGNITION':   10,    # days
    'VALIDATION': 14,
    'EXPANSION':  28,
    'CROWDING':   14,
    'EXHAUSTION': 7,
    'CLOSURE':    5,
}

def compute_time_fraction(days_elapsed: float, slt_stage: str) -> float:
    estimated_duration = STAGE_DURATION_ESTIMATES.get(slt_stage, 14)
    return days_elapsed / max(estimated_duration, 1)

def classify_mtl_state(time_fraction: float) -> str:
    if time_fraction > 1.0:             return 'EXPIRED'
    elif time_fraction >= MTL_PEAK_THRESHOLD:    return 'CLOSING'
    elif time_fraction >= MTL_BUILDING_THRESHOLD:return 'PEAK'
    elif time_fraction >= MTL_OPENING_THRESHOLD: return 'BUILDING'
    else:                               return 'OPENING'

def snap_window_score(v0: float, time_fraction: float,
                      lambda_rate: float = MTL_LAMBDA_DEFAULT) -> float:
    if time_fraction > 1.0:
        return 0.0
    return round(v0 * math.exp(-lambda_rate * time_fraction), 3)

def mtl_action_guidance(mtl_state: str, zpd_zone_state: str = None) -> dict:
    guidance = {
        'OPENING':  {'il_tranche': 1, 'fire_mode_allowed': False,
                     'note': 'tranche_1. Most of window remains. Enter conservatively.'},
        'BUILDING': {'il_tranche': 2, 'fire_mode_allowed': False,
                     'note': 'tranche_2. Momentum phase. Add to position if conditions hold.'},
        'PEAK':     {'il_tranche': 3,
                     'fire_mode_allowed': zpd_zone_state == 'CLEAN_ZONE',
                     'note': 'tranche_3. Optimal window. FIRE_MODE if ZPD CLEAN_ZONE.'},
        'CLOSING':  {'il_tranche': None, 'fire_mode_allowed': False,
                     'note': 'IL PROBE only. Value decaying. Do not enter full size.'},
        'EXPIRED':  {'il_tranche': None, 'fire_mode_allowed': False,
                     'note': 'Window closed. LEAVE or check SLT stage advance.'},
    }
    return guidance.get(mtl_state, {'il_tranche': None, 'fire_mode_allowed': False})

def mtl_full_check(days_elapsed: float, slt_stage: str, ass_q_at_entry: float,
                   zpd_zone_state: str = None,
                   lambda_rate: float = MTL_LAMBDA_DEFAULT) -> dict:
    time_fraction = compute_time_fraction(days_elapsed, slt_stage)
    mtl_state     = classify_mtl_state(time_fraction)
    sws           = snap_window_score(ass_q_at_entry, time_fraction, lambda_rate)
    guidance      = mtl_action_guidance(mtl_state, zpd_zone_state)
    return {
        'mtl_state':          mtl_state,
        'time_fraction':      round(time_fraction, 3),
        'days_elapsed':       days_elapsed,
        'stage_duration_est': STAGE_DURATION_ESTIMATES.get(slt_stage, 14),
        'snap_window_score':  sws,
        'il_tranche':         guidance['il_tranche'],
        'fire_mode_allowed':  guidance['fire_mode_allowed'],
        'note':               guidance['note'],
    }
