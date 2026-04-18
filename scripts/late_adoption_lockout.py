# LATE_ADOPTION_LOCKOUT (LALO)
# Module: S4 — Execution-gate late-adoption detector
# Added: April 17-18 2026
# Source: Parrots / chillies / AI mimicry / MVP mapping session
#
# LALO = mean(crowd_density, velocity_decay, momentum_dominance,
#             echo_saturation, stage_maturity)
#
# The parrot ceiling insight: copying consensus reaches a ceiling.
# Even if a signal is still alive (SLT not CLOSURE, MTL not EXPIRED,
# SBE STRONG_FLOAT), the ADOPTION window may have closed — the edge is
# exhausted because you'd be entering as a late parrot copying what the
# crowd already owns.
#
# LALO asks: 'has the adoption window already saturated such that entering
# is pure mimicry with no price-setting power?'
#
# LALO is distinct from:
#   MTL: where am I within the current stage? (time position within stage)
#   PSE: will this signal spread? (pre-propagation)
#   NSD: is narrative ahead of structure? (pre-entry quality gap)
#   NDI: how distorted is the circulating narrative? (distortion score)
#   SLT: which lifecycle stage? (stage label, not saturation state)
#
# 5 LALO components (each 0-1):
#
# c1: CROWD_DENSITY (0-1)
#   = CFD CS_score if CFD_state == 'LOCKED' else CFD CS_score * 0.5
#   High LOCKED CFD = maximum crowd density = late adoption territory
#   The crowd has fully formed consensus = nothing new to add to price
#
# c2: ADOPTION_VELOCITY_DECAY (0-1)
#   = 1 - (dCS/dt_current / dCS/dt_peak)
#   Has consensus-formation slope collapsed from peak?
#   Peak velocity = fresh early adoption.
#   Decayed velocity = late window.
#   >70% decay from peak = late-adopter zone
#
# c3: NIS_MOMENTUM_DOMINANCE (0-1)
#   = NIS momentum_fraction (already computed)
#   High momentum fraction = signal running on narrative residue, not new info
#   When momentum dominates, you are entering on yesterday's signal
#
# c4: SBS_ECHO_SATURATION (0-1)
#   = SBS echo_density (already computed)
#   High echo density = signal has saturated its originating clusters
#   More adoption from these sources adds no new information
#
# c5: SLT_STAGE_MATURITY (0-1)
#   Stage-to-maturity mapping:
#     IGNITION:    0.0   (just formed, fully open)
#     VALIDATION:  0.2   (early confirmation, still open)
#     EXPANSION:   0.4   (prime entry window)
#     CROWDING:    0.75  (saturation approaching)
#     EXHAUSTION:  0.95  (narrative spent)
#     CLOSURE:     1.0   (fully locked)
#
# LALO_score = mean(c1, c2, c3, c4, c5)    range 0-1
#
# LALO states and effects:
#   OPEN_ADOPTION: LALO < 0.35
#     -> Early-to-mid window. Entry adds price-setting power.
#     -> No size restrictions beyond existing drift_risk cap
#     -> RTX Day 3: LALO = 0.24 OPEN_ADOPTION -> +3.90% WIN
#
#   LATE_ADOPTION: LALO 0.35-0.60
#     -> Becoming parrot-like. Max QUARTER_UNIT sizing (no HALF_UNIT even if ZPD CLEAN)
#     -> CE: no adjustment
#     -> GLD current: LALO = 0.40 LATE_ADOPTION -> QUARTER_UNIT cap confirmed
#
#   SATURATION_WARNING: LALO 0.60-0.80
#     -> Near parrot ceiling. IL PROBE only (no STAGGER, no FIRE_MODE)
#     -> CE: reduce by 0.10 (late-adoption penalty)
#     -> Last window before full lockout
#
#   LOCKED_OUT: LALO > 0.80
#     -> Pure late-adopter entry = no edge remaining
#     -> BLOCK regardless of other gate states
#     -> Override: even if ZPD CLEAN_ZONE and CE > 0.70, LALO LOCKED_OUT = LEAVE
#     -> CVX Day 80: LALO = 0.89 LOCKED_OUT -> CHAOS_ENTRY entered peak parrot zone
#
# LALO feeds into:
#   IL action selection: LOCKED_OUT overrides IL action -> forced LEAVE
#   CE COMPOSITE_EDGE: SATURATION_WARNING -> CE -= 0.10
#   Position sizing: LATE_ADOPTION caps at QUARTER_UNIT regardless of ZPD state
#   MOLTBOOK logging: LALO score at entry = parrot-index for the trade
#                     Post-trade: did LALO-predicted late-adopter risk manifest?
#
# LALO trade-level interpretation:
#   Low LALO (< 0.35): 'I am an early mover, adding information to price'
#   Mid LALO (0.35-0.60): 'I am mid-cycle, normal sizing, not an alpha generator'
#   High LALO (0.60-0.80): 'I am late, reduced sizing, probe only'
#   Very high LALO (> 0.80): 'I would be a parrot copying yesterday's trade'
#
# Portfolio retrospectives:
#   RTX Day 3:
#     c1 = 0.30 (CFD CONVERGING not LOCKED), c2 = 0.15 (dCS/dt still rising)
#     c3 = 0.30 (SIGNAL_DOMINANT), c4 = 0.25 (low SBS echo)
#     c5 = 0.20 (VALIDATION stage)
#     LALO = mean(0.30, 0.15, 0.30, 0.25, 0.20) = 0.24
#     State: OPEN_ADOPTION
#     Entry added edge. Not a parrot. +3.90% WIN.
#
#   CVX Day 80 (CHAOS_ENTRY):
#     c1 = 0.95 (CFD LOCKED saturation), c2 = 0.90 (velocity collapsed 90%)
#     c3 = 0.85 (MOMENTUM_DOMINANT, narrative residue only)
#     c4 = 0.80 (echo chamber), c5 = 0.95 (EXHAUSTION stage)
#     LALO = mean(0.95, 0.90, 0.85, 0.80, 0.95) = 0.89
#     State: LOCKED_OUT
#     CHAOS_ENTRY entered at maximum parrot territory.
#     Pipeline should have BLOCKED regardless of other gates.
#     consequence_persistence = 2.5 explained: late-adopter lockout was ignored.
#
#   GLD current:
#     c1 = 0.50 (CONVERGING, moderate), c2 = 0.35 (velocity decelerating)
#     c3 = 0.35 (mostly SIGNAL_DOMINANT), c4 = 0.40, c5 = 0.40 (EXPANSION)
#     LALO = mean(0.50, 0.35, 0.35, 0.40, 0.40) = 0.40
#     State: LATE_ADOPTION
#     Near parrot ceiling. Max QUARTER_UNIT (no HALF_UNIT upgrade).
#     +8.17% holds with correct late-window sizing.
#
# The parrot ceiling law:
#   The best pattern-user is the one who knows when the pattern dies.
#   Mimicry reaches a ceiling. LALO names when you are about to hit it.
#   You have become the late-adopter you were watching. Block regardless.

LALO_OPEN_ADOPTION       = 0.35
LALO_LATE_ADOPTION       = 0.60
LALO_SATURATION_WARNING  = 0.80
# Above LALO_SATURATION_WARNING = LOCKED_OUT

LALO_CE_PENALTY          = 0.10   # CE reduction when SATURATION_WARNING
LALO_BLOCK_OVERRIDE      = True   # LOCKED_OUT blocks regardless of other gates

SLT_STAGE_MATURITY = {
    'IGNITION': 0.0, 'VALIDATION': 0.2, 'EXPANSION': 0.4,
    'CROWDING': 0.75, 'EXHAUSTION': 0.95, 'CLOSURE': 1.0,
}

def compute_crowd_density(cfd_cs_score: float, cfd_state: str) -> float:
    base = min(cfd_cs_score / 10.0, 1.0) if cfd_cs_score > 1.0 else cfd_cs_score
    multiplier = 1.0 if cfd_state == 'LOCKED' else 0.5
    return round(max(0.0, min(1.0, base * multiplier)), 3)

def compute_velocity_decay(dcs_dt_current: float, dcs_dt_peak: float) -> float:
    if dcs_dt_peak <= 0:
        return 0.0
    decay = 1.0 - (dcs_dt_current / dcs_dt_peak)
    return round(max(0.0, min(1.0, decay)), 3)

def compute_stage_maturity(slt_stage: str) -> float:
    return SLT_STAGE_MATURITY.get(slt_stage, 0.5)

def classify_lalo(lalo_score: float) -> str:
    if lalo_score > LALO_SATURATION_WARNING: return 'LOCKED_OUT'
    elif lalo_score > LALO_LATE_ADOPTION:    return 'SATURATION_WARNING'
    elif lalo_score > LALO_OPEN_ADOPTION:    return 'LATE_ADOPTION'
    else:                                    return 'OPEN_ADOPTION'

def lalo_effects(lalo_state: str) -> dict:
    effects_map = {
        'OPEN_ADOPTION':   {'ce_adjustment': 0.0,              'max_size': 'UNRESTRICTED',
                             'il_max_action': 'FIRE_MODE_ELIGIBLE', 'block_override': False,
                             'note': 'OPEN_ADOPTION. Early window, entry adds edge.'},
        'LATE_ADOPTION':   {'ce_adjustment': 0.0,              'max_size': 'QUARTER_UNIT',
                             'il_max_action': 'STAGGER',            'block_override': False,
                             'note': 'LATE_ADOPTION. Max QUARTER_UNIT, no HALF_UNIT upgrade.'},
        'SATURATION_WARNING': {'ce_adjustment': -LALO_CE_PENALTY, 'max_size': 'EIGHTH_UNIT',
                             'il_max_action': 'PROBE',              'block_override': False,
                             'note': 'SATURATION_WARNING. PROBE only. CE penalty applied.'},
        'LOCKED_OUT':      {'ce_adjustment': -0.25,            'max_size': 'NONE',
                             'il_max_action': 'LEAVE',              'block_override': True,
                             'note': 'LOCKED_OUT. Parrot ceiling reached. BLOCK regardless of other gates.'},
    }
    return effects_map[lalo_state]

def compute_lalo(cfd_cs_score: float, cfd_state: str,
                 dcs_dt_current: float, dcs_dt_peak: float,
                 nis_momentum_fraction: float, sbs_echo_density: float,
                 slt_stage: str) -> dict:
    c1 = compute_crowd_density(cfd_cs_score, cfd_state)
    c2 = compute_velocity_decay(dcs_dt_current, dcs_dt_peak)
    c3 = round(max(0.0, min(1.0, nis_momentum_fraction)), 3)
    c4 = round(max(0.0, min(1.0, sbs_echo_density)), 3)
    c5 = compute_stage_maturity(slt_stage)
    lalo_score = round((c1 + c2 + c3 + c4 + c5) / 5, 3)
    state   = classify_lalo(lalo_score)
    effects = lalo_effects(state)
    return {
        'lalo_score': lalo_score,
        'lalo_state': state,
        'components': {
            'crowd_density':      c1,
            'velocity_decay':     c2,
            'momentum_dominance': c3,
            'echo_saturation':    c4,
            'stage_maturity':     c5,
        },
        'effects':    effects,
        'parrot_risk': state in ('SATURATION_WARNING', 'LOCKED_OUT'),
    }
