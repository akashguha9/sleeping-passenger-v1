# NARRATIVE_DISTORTION_INDEX (NDI)
# Module: S1 — Post-circulation distortion scoring
# Added: April 17-18 2026
# Source: VW Beetle / Abbey Road / Paul barefoot / Chinese Whispers session
#
# NDI = (IL + AV + BI) - (SI + CDC)
#
# NSD scores signal quality BEFORE market entry.
# NDI scores how distorted a narrative ALREADY IN CIRCULATION has become,
# weighted by how far that distortion has spread and changed behavior.
#
# The Abbey Road insight:
#   'Paul McCartney is barefoot' = low NDI (observable, verified, low IL)
#   'Paul McCartney is dead because he is barefoot' = high NDI
#     (massive inferential overlay + viral spread + behavioral impact = LP purchases)
#     (near-zero signal integrity: no structural basis for the claim)
#
# NSD is pre-entry: 'is this signal structurally sound before I act?'
# NDI is post-circulation: 'is this narrative already distorted while I watch it spread?'
#
# 5 NDI components:
#
# IL: INTERPRETATION_LOAD (0-1, distortion amplifier)
#   = NII Conclusion_Scope / Evidence_Scope ratio (already computed in NII)
#   How much does the circulating narrative claim beyond its verifiable base?
#   Abbey Road 'Paul is dead': IL = 0.90 (massive inferential leap from barefoot+plate)
#   RTX Iran war thesis: IL = 0.25 (moderate, thesis is direct and causal)
#
# AV: AMPLIFICATION_VELOCITY (0-1, distortion amplifier)
#   = PSE P(spread) * (CFD dCS_dt_normalised)
#   How fast is this narrative spreading, regardless of truth?
#   'Paul is dead' at peak: AV = 0.85 (viral, no verification step)
#   High AV + low SI = dangerous distortion spreading quickly
#
# BI: BEHAVIORAL_IMPACT (0-1, distortion amplifier)
#   = NDM score (Narrative Displacement Metric: did this change prices/behavior?)
#   A narrative matters economically when people act on it even if it is false.
#   'Paul is dead': BI = 0.70 (Beatles LP purchases, radio play, media coverage)
#   CVX Day 80: BI = 0.75 (war/oil narrative drove many entries including CHAOS_ENTRY)
#
# SI: SIGNAL_INTEGRITY (0-1, reality anchor — subtractive)
#   = NSD SS Structural_Strength (already computed)
#   = 0.30*CIS2/10 + 0.25*HWE_max + 0.25*RTT_portability + 0.20*WMBRL
#   How verified is the underlying claim?
#   'Paul barefoot' = SI = 0.95 (directly observable, verified)
#   'Paul is dead' = SI = 0.05 (no structural evidence at all)
#
# CDC: CROSS_DOMAIN_CONFIRMATION (0-1, reality anchor — subtractive)
#   = CFD CC_score * (1 - SBS_echo_density)
#   Does the signal appear independently across multiple domains?
#   Multi-domain independent confirmation = CDC high = narrative grounded
#   Single-domain echo chamber = CDC low = narrative fragile
#   CVX Day 80: CDC = 0.10 (single-narrative media echo chamber)
#   RTX Day 3: CDC = 0.70 (geopolitics + procurement + PM + price all confirming)
#
# NDI = (IL + AV + BI) - (SI + CDC)
# Range: approximately -2 to +3
#
# NDI states and effects:
#   HIGHLY_DISTORTED: NDI > +1.0
#     -> Abbey Road 'Paul is dead' archetype
#     -> Narrative has massively outrun its signal basis AND is spreading with impact
#     -> CE COMPOSITE_EDGE: reduce by 0.15 (narratively inflated signals get penalised)
#     -> IL action: PROBE or SANDBOX (do not chase inflated narrative)
#     -> Two sub-states:
#        DISTORTION_GROWING (NDI rising week-over-week): can still be RIDDEN
#        DISTORTION_COLLAPSING (NDI falling): FADE opportunity
#
#   ELEVATED_DISTORTION: NDI +0.3 to +1.0
#     -> Narrative ahead of evidence, spreading but not fully viral
#     -> Flag: increase NSD monitoring, reduce sizing, do not FIRE_MODE
#     -> CE: no penalty yet, but watch trajectory
#
#   GROUNDED: NDI -0.3 to +0.3
#     -> Narrative roughly matches evidence
#     -> Normal pipeline processing, no adjustment
#     -> GLD current: NDI = -0.08 GROUNDED
#
#   UNDERREPORTED: NDI < -0.3
#     -> RTX archetype: structure ahead of narrative
#     -> Reality anchors (SI + CDC) exceed distortion amplifiers (IL + AV + BI)
#     -> SBE Signal_Density S: +0.10 double boost (combines with NSD UNDERVALUED boost)
#     -> DEUTERIUM isotope class doubly confirmed
#     -> Best entry condition: crowd has not yet noticed what the structure already shows
#
# NDI feeds into:
#   CE COMPOSITE_EDGE: HIGHLY_DISTORTED -> CE -= 0.15
#   IL action: HIGHLY_DISTORTED -> max action = IL PROBE (no FIRE_MODE on distorted signal)
#   NSD cross-check: NDI UNDERREPORTED + NSD UNDERVALUED = maximum DEUTERIUM signal
#   MOLTBOOK logging: was NDI HIGHLY_DISTORTED at entry? If yes: CHAOS_ENTRY risk pattern
#
# Portfolio retrospectives:
#   RTX Day 3: UNDERREPORTED
#     IL=0.25 (moderate), AV=0.65 (spreading structured), BI=0.40 (real price action)
#     SI=0.89 (CIS2+HWE+RTT PORTABLE+WMBRL), CDC=0.70 (multi-domain)
#     NDI = (0.25+0.65+0.40) - (0.89+0.70) = 1.30 - 1.59 = -0.29 UNDERREPORTED
#     S double boost -> SBE STRONG_FLOAT -> DEUTERIUM confirmed -> +3.90% WIN
#
#   CVX Day 80: HIGHLY_DISTORTED ('Paul is dead' in markets)
#     IL=0.85, AV=0.90, BI=0.75 -> 2.50
#     SI=0.16 (RTT HOSTILE, CIS2=2.0), CDC=0.10 (echo chamber) -> 0.26
#     NDI = 2.50 - 0.26 = +2.24 HIGHLY_DISTORTED
#     CE should have been reduced by 0.15 -> CE near zero
#     CHAOS_ENTRY entered at peak narrative distortion -> consequence_persistence=2.5
#
#   GLD current: GROUNDED
#     IL=0.35, AV=0.55, BI=0.45 -> 1.35
#     SI=0.83, CDC=0.60 -> 1.43
#     NDI = 1.35 - 1.43 = -0.08 GROUNDED
#     Normal processing -> CE=0.656 GOOD_EDGE -> QUARTER_UNIT STAGGER -> +8.17% holds
#
# The Abbey Road law: noise survives by borrowing signal.
# 'Paul barefoot' is real (NDI negative). 'Paul is dead' is NDI +2.5.
# Know which one you are trading.
# The best entries come when NDI is UNDERREPORTED and structure is already in place.

NDI_HIGHLY_DISTORTED    =  1.0
NDI_ELEVATED_DISTORTION =  0.3
NDI_GROUNDED_LOWER      = -0.3
# Below NDI_GROUNDED_LOWER = UNDERREPORTED

NDI_CE_PENALTY          =  0.15   # CE reduction when HIGHLY_DISTORTED
NDI_S_DOUBLE_BOOST      =  0.10   # additional SBE S boost when UNDERREPORTED

def compute_ndi(il: float, av: float, bi: float,
                si: float, cdc: float) -> dict:
    ndi = round((il + av + bi) - (si + cdc), 3)
    if ndi > NDI_HIGHLY_DISTORTED:   state = 'HIGHLY_DISTORTED'
    elif ndi > NDI_ELEVATED_DISTORTION: state = 'ELEVATED_DISTORTION'
    elif ndi > NDI_GROUNDED_LOWER:   state = 'GROUNDED'
    else:                            state = 'UNDERREPORTED'
    effects = {
        'HIGHLY_DISTORTED':   {
            'ce_adjustment': -NDI_CE_PENALTY,
            'sbe_s_boost': 0.0,
            'max_il_action': 'PROBE',
            'note': 'HIGHLY_DISTORTED: Abbey Road Paul-is-dead archetype. Fade or ride? Check NDI trajectory.'},
        'ELEVATED_DISTORTION':{
            'ce_adjustment': 0.0,
            'sbe_s_boost': 0.0,
            'max_il_action': 'STAGGER',
            'note': 'ELEVATED: narrative ahead of evidence. Flag. Increase NSD monitoring.'},
        'GROUNDED':           {
            'ce_adjustment': 0.0,
            'sbe_s_boost': 0.0,
            'max_il_action': 'FIRE_MODE_IF_OTHER_GATES_PASS',
            'note': 'GROUNDED: narrative and evidence aligned. Normal processing.'},
        'UNDERREPORTED':      {
            'ce_adjustment': 0.0,
            'sbe_s_boost': NDI_S_DOUBLE_BOOST,
            'max_il_action': 'FIRE_MODE_IF_OTHER_GATES_PASS',
            'note': 'UNDERREPORTED: RTX archetype. Structure ahead of narrative. DEUTERIUM doubly confirmed. S double boost.'},
    }
    return {
        'ndi':       ndi,
        'ndi_state': state,
        'components': {'IL': il, 'AV': av, 'BI': bi, 'SI': si, 'CDC': cdc},
        'amplifiers': round(il + av + bi, 3),
        'anchors':    round(si + cdc, 3),
        'effects':    effects[state],
    }

def ndi_amplification_velocity(pse_p_spread: float, cfd_dcs_dt_norm: float) -> float:
    return round(min(1.0, pse_p_spread * cfd_dcs_dt_norm * 1.2), 3)
