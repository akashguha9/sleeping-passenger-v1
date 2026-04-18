# NARRATIVE_STRUCTURE_DIVERGENCE (NSD)
# Module: S1 — Narrative quality audit layer
# Added: April 17-18 2026
# Source: Mallya / Omar / Modi / Banga — four archetypes session
#
# NSD = NS - SS
# How much does the narrative surface exceed structural depth?
#
# The Kingfisher insight:
#   Kingfisher was genuinely best-in-class by experience metrics.
#   Its narrative surface was strong: premium, admired, best product.
#   Its structural spine was fragile: high leverage, fuel exposure, wrong cost base.
#   NSD = high NS - low SS = OVEREXTENDED → hidden fragility behind glamour.
#
# The RTX insight (UNDERVALUED):
#   Defence procurement was building quietly in Polymarket.
#   Narrative was NOT loud — not trending, not in headlines.
#   Structural depth was HIGH — strong CIS2, HWE COMMITTED, RTT PORTABLE.
#   NSD = low NS - high SS = UNDERVALUED → DEUTERIUM: structure ahead of narrative.
#
# NS (Narrative Strength) — measures LOUDNESS and CONFIDENCE, not quality:
#   n1 (25%): CFD CS / 10         (how much consensus has formed)
#   n2 (25%): NIS momentum_fraction (how momentum-driven vs signal-driven)
#   n3 (25%): 1 - SPF/10           (high prestige sources but low quality = high NS)
#   n4 (25%): 1 - SF/10            (loud/noisy signals score higher NS)
#   NS = 0.25*(n1 + n2 + n3_inv + n4_inv)
#   NOTE: NS is not a quality score — it measures how much social/narrative energy
#         exists around a signal regardless of whether it is justified.
#
# SS (Structural Strength) — measures EVIDENCE, CAUSALITY, REGIME STABILITY:
#   s1 (30%): CIS2_score / 10      (causal mechanism quality)
#   s2 (25%): HWE max_weight        (best hypothesis has real evidentiary weight)
#   s3 (25%): RTT portability score (1.0 PORTABLE, 0.7 CONDITIONAL, 0.3 REGIME_BOUND, 0.0 HOSTILE)
#   s4 (20%): WMBRL base_rate       (historically grounded base rate at this node)
#   SS = 0.30*s1 + 0.25*s2 + 0.25*s3 + 0.20*s4
#
# NSD = NS - SS     range approximately -1 to +1
#
# NSD states and effects:
#   OVEREXTENDED: NSD > +0.30
#     -> Kingfisher archetype: narrative far exceeds structure
#     -> SBE Hardness_Penalty H += 0.15 (penalises buoyancy score B)
#     -> MTL PEAK eligibility blocked (cannot upgrade to FIRE_MODE from MTL PEAK)
#     -> ZPD Gate 2 (ASS HIGH) harder to pass
#     -> CVX Day 80: NSD = +0.63 OVEREXTENDED -> confirms SBE TRAP
#
#   ELEVATED: NSD +0.10 to +0.30
#     -> Narrative somewhat ahead of structure
#     -> Reduce MTL PEAK eligibility (delay FIRE_MODE by one MTL state)
#     -> No H penalty, but no S boost
#
#   NEUTRAL: NSD -0.10 to +0.10
#     -> Narrative and structure roughly aligned
#     -> No adjustment to SBE, MTL, or ZPD
#
#   UNDERVALUED: NSD < -0.10
#     -> RTX archetype: structure ahead of narrative
#     -> SBE Signal_Density S += 0.10 boost (structure supports more than narrative reflects)
#     -> DEUTERIUM isotope class confirmed for SBE species check
#     -> ASS O asymmetry_ratio gets +0.05 boost (more upside than market knows)
#     -> RTX Day 3: NSD = -0.53 UNDERVALUED -> confirms STRONG_FLOAT DEUTERIUM
#
# NSD is distinct from:
#   NII: Conclusion_Scope / Evidence_Scope — catches inflation WITHIN the thesis
#        (is the thesis making claims beyond its evidence?)
#        NSD is broader: how loud is the SIGNAL vs how deep is the STRUCTURE
#   EDS: price vs narrative direction — post-action market response divergence
#        NSD is pre-action: catches the divergence BEFORE market has responded
#   SBE: B = S-(E+H) — present-state buoyancy
#        NSD FEEDS INTO SBE via H and S adjustments
#   RTT: regime stress testing
#        RTT is one INPUT to NSD's SS component (portability score)
#
# Portfolio retrospectives:
#   RTX Day 3:
#     NS: CFD=0.65 (0.163), NIS SIGNAL_DOMINANT=0.30 (0.075),
#         1-SPF(0.75)=0.25 (0.063), 1-SF(0.65)=0.35 (0.088) -> NS = 0.39
#     SS: CIS2=0.95 (0.285), HWE=0.85 (0.213), RTT PORTABLE=1.0 (0.250), WMBRL=0.71 (0.142)
#         -> SS = 0.89
#     NSD = 0.39 - 0.89 = -0.50 -> UNDERVALUED
#     -> S boost +0.10 applied to SBE Signal_Density -> confirms STRONG_FLOAT, DEUTERIUM
#     -> +3.90% WIN confirms
#
#   CVX Day 80:
#     NS: CFD LOCKED=0.90 (0.225), NIS MOMENTUM=0.85 (0.213),
#         1-SPF(0.50)=0.50 (0.125), 1-SF(0.10)=0.90 (0.225) -> NS = 0.79
#     SS: CIS2=0.20 (0.060), HWE=0.35 (0.088), RTT HOSTILE=0.0 (0.000), WMBRL=0.08 (0.016)
#         -> SS = 0.16
#     NSD = 0.79 - 0.16 = +0.63 -> OVEREXTENDED (Kingfisher archetype)
#     -> H penalty +0.15 applied to SBE Hardness_Penalty H
#     -> confirms SBE B = TRAP (-0.75 confirmed)
#     -> -8.82% avoided
#
#   GLD current:
#     NS ≈ 0.45 (moderate consensus, SF CLEAN, NIS SIGNAL_DOMINANT)
#     SS ≈ 0.85 (CIS2 good, HWE COMMITTED, RTT PORTABLE, WMBRL 0.78)
#     NSD = 0.45 - 0.85 = -0.40 -> UNDERVALUED
#     -> S boost -> QUARTER_UNIT sizing confirmed -> +8.17% holds
#
# Four archetypes from the session:
#   Mallya / Kingfisher: FRAGILE NARRATIVE -> NSD OVEREXTENDED -> H penalty
#   Omar / J&K:          COMPRESSED RISK   -> LPS EXTREME -> suppressed signal
#   Lalit Modi / IPL:    REINFORCING SYSTEM -> SANGAM SSSC -> incentive alignment
#   Ajay Banga:          ADAPTIVE OPERATOR  -> RTT PORTABLE -> luck × execution
#
# The Kingfisher law: admiration is not solvency.
# NS >> SS means the narrative surface is ahead of the structural spine.
# Always audit. Every strong public signal deserves a hidden-layer check.

NSD_OVEREXTENDED_THRESHOLD = +0.30
NSD_ELEVATED_THRESHOLD     = +0.10
NSD_NEUTRAL_LOWER          = -0.10
# Below NSD_NEUTRAL_LOWER = UNDERVALUED

NSD_H_PENALTY     = 0.15   # added to SBE Hardness_Penalty H when OVEREXTENDED
NSD_S_BOOST       = 0.10   # added to SBE Signal_Density S when UNDERVALUED
NSD_O_BOOST       = 0.05   # added to ASS O asymmetry_ratio when UNDERVALUED

RTT_PORTABILITY_SCORES = {
    'PORTABLE': 1.0, 'CONDITIONAL': 0.7, 'REGIME_BOUND': 0.3,
    'HOSTILE': 0.0, 'ELEGANT_FRAGILE': 0.0,
}

def compute_narrative_strength(cfd_cs: float, nis_momentum_fraction: float,
                                spf_avg: float, sf_score: float) -> float:
    n1 = min(cfd_cs / 10.0, 1.0)
    n2 = min(nis_momentum_fraction, 1.0)
    n3 = max(0.0, 1.0 - min(spf_avg / 10.0, 1.0))  # inverted: high prestige = loud
    n4 = max(0.0, 1.0 - min(sf_score / 10.0, 1.0))  # inverted: noisy = high NS
    return round(0.25*(n1 + n2 + n3 + n4), 3)

def compute_structural_strength(cis2_score: float, hwe_max_weight: float,
                                 rtt_friction_tier: str, wmbrl_base_rate: float) -> float:
    s1 = min(cis2_score / 10.0, 1.0)
    s2 = min(hwe_max_weight, 1.0)
    s3 = RTT_PORTABILITY_SCORES.get(rtt_friction_tier, 0.5)
    s4 = min(wmbrl_base_rate, 1.0)
    return round(0.30*s1 + 0.25*s2 + 0.25*s3 + 0.20*s4, 3)

def classify_nsd_state(nsd: float) -> str:
    if nsd > NSD_OVEREXTENDED_THRESHOLD:  return 'OVEREXTENDED'
    elif nsd > NSD_ELEVATED_THRESHOLD:    return 'ELEVATED'
    elif nsd > NSD_NEUTRAL_LOWER:         return 'NEUTRAL'
    else:                                 return 'UNDERVALUED'

def nsd_adjustments(nsd_state: str) -> dict:
    if nsd_state == 'OVEREXTENDED':
        return {
            'sbe_h_adjustment': NSD_H_PENALTY,
            'sbe_s_adjustment': 0.0,
            'ass_o_adjustment': 0.0,
            'mtl_peak_blocked': True,
            'note':             'OVEREXTENDED: Kingfisher archetype. H penalty applied. MTL PEAK blocked.',
        }
    elif nsd_state == 'ELEVATED':
        return {
            'sbe_h_adjustment': 0.0,
            'sbe_s_adjustment': 0.0,
            'ass_o_adjustment': 0.0,
            'mtl_peak_blocked': True,   # delay FIRE_MODE by one MTL state
            'note':             'ELEVATED: narrative somewhat ahead. MTL PEAK eligibility reduced.',
        }
    elif nsd_state == 'UNDERVALUED':
        return {
            'sbe_h_adjustment': 0.0,
            'sbe_s_adjustment': NSD_S_BOOST,
            'ass_o_adjustment': NSD_O_BOOST,
            'mtl_peak_blocked': False,
            'note':             'UNDERVALUED: RTX archetype. S boost. DEUTERIUM class confirmed.',
        }
    return {
        'sbe_h_adjustment': 0.0, 'sbe_s_adjustment': 0.0,
        'ass_o_adjustment': 0.0, 'mtl_peak_blocked': False,
        'note': 'NEUTRAL: no adjustment.',
    }

def nsd_full_check(cfd_cs, nis_momentum_fraction, spf_avg, sf_score,
                   cis2_score, hwe_max_weight, rtt_friction_tier, wmbrl_base_rate) -> dict:
    NS  = compute_narrative_strength(cfd_cs, nis_momentum_fraction, spf_avg, sf_score)
    SS  = compute_structural_strength(cis2_score, hwe_max_weight, rtt_friction_tier, wmbrl_base_rate)
    nsd = round(NS - SS, 3)
    state = classify_nsd_state(nsd)
    adj   = nsd_adjustments(state)
    return {
        'nsd':         nsd,
        'nsd_state':   state,
        'NS':          NS,
        'SS':          SS,
        'adjustments': adj,
    }
