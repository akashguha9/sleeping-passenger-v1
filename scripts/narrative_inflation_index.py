# NARRATIVE_INFLATION_INDEX (NII)
# Module: S2 — Narrative Engine
# Added: April 17 2026
# Source: Viral / misinformation content session
#
# Measures how far the WINNING narrative's claims extend beyond its evidence scope.
# NII = Conclusion_Scope / Evidence_Scope
#
# Orthogonal to all existing mechanisms:
#   SDI:  corrects for market environment heat (regime inflation)
#   CIS2: scores causal chain quality within the thesis
#   NIS:  tracks fresh signal vs momentum fraction over time
#   HWE:  manages competing hypothesis weight distribution
#   NII:  how inflated are the CLAIMS relative to EVIDENCE right now?
#
# A signal can have LOW SDI_environment but HIGH NII:
#   Market is not hot (SDI_env LOW) -> SDI discount is small
#   But narrative claims 10x its evidence scope -> NII = HYPER -> 60% discount
#   This is the CVX Day 80 pattern: SDI alone was insufficient to block entry.
#
# NII states and CE discount multipliers:
#   GROUNDED:  NII < 1.5  -> standard CE weight (1.00)
#   EXTENDED:  NII 1.5-3.0 -> apply 15% CE discount (0.85)
#   INFLATED:  NII 3.0-6.0 -> apply 35% CE discount (0.65)
#              Flag: NARRATIVE_INFLATION_WARNING
#   HYPER:     NII > 6.0  -> apply 60% CE discount (0.40)
#              Trigger: NIS review + HWE PREMATURE_CLOSURE check
#
# Portfolio retrospectives:
#   RTX Day 3:   Conclusion scope narrow (defence procurement).
#                Evidence: Polymarket rising, WMBRL base_rate=0.71, Day 3.
#                NII = 1.2 -> GROUNDED -> full CE -> ENTER -> +3.90% WIN.
#
#   CVX Day 80:  Conclusion scope: global energy sustained at full war-premium.
#                Evidence: price already declined, WMBRL=0.08, CIS2=2.0.
#                Narrative claiming 10x evidence scope.
#                NII > 6.0 -> HYPER -> 60% CE discount -> below threshold -> LEAVE.
#                -8.82% avoided.
#
#   GLD current: Conclusion: safe-haven bid during active war regime.
#                Evidence: WMBRL=0.78, TAT BUILDING, EDS CONFIRMING.
#                NII = 1.4 -> GROUNDED -> full CE -> +8.17% confirms.
#
# Source of insight:
#   'Viral content sells certainty not truth. Fact anchor + speculative
#    expansion is the core misinformation mechanism. Narrative inflation
#    index scores conclusion scope / evidence scope.'

NII_GROUNDED_THRESHOLD  = 1.5
NII_EXTENDED_THRESHOLD  = 3.0
NII_INFLATED_THRESHOLD  = 6.0

NII_DISCOUNT = {
    'GROUNDED':  1.00,
    'EXTENDED':  0.85,
    'INFLATED':  0.65,
    'HYPER':     0.40,
}

def estimate_conclusion_scope(nar_archetype, assets_affected_count,
                               duration_claim_days, magnitude_claim_pct,
                               mechanism_count):
    archetype_base = {
        'COMPOUNDING':  1.0,
        'HYBRID':       1.5,
        'ATTENTION':    2.5,
        'EXTRACTION':   4.0,
    }.get(nar_archetype, 2.0)
    breadth_factor  = 1 + (assets_affected_count - 1) * 0.3
    duration_factor = 1 + max(0, (duration_claim_days - 14)) / 30
    magnitude_factor= 1 + max(0, (magnitude_claim_pct - 5)) / 10
    return archetype_base * breadth_factor * duration_factor * magnitude_factor

def estimate_evidence_scope(verified_references, total_claims,
                             cis2_score, hwe_max_weight,
                             wmbrl_base_rate, days_since_signal):
    anchor_density = verified_references / max(total_claims, 1)
    cis2_normalised = cis2_score / 10.0
    hwe_normalised  = hwe_max_weight
    base_rate_score = wmbrl_base_rate
    time_penalty    = max(0, 1 - days_since_signal / 90)
    return ((anchor_density * 0.25) + (cis2_normalised * 0.30) +
            (hwe_normalised * 0.25) + (base_rate_score * 0.20)) * time_penalty

def compute_nii(conclusion_scope, evidence_scope):
    if evidence_scope <= 0.01:
        return 9.9  # near-zero evidence = HYPER regardless
    return conclusion_scope / evidence_scope

def classify_nii_state(nii_score):
    if nii_score >= NII_INFLATED_THRESHOLD:
        return 'HYPER'
    elif nii_score >= NII_EXTENDED_THRESHOLD:
        return 'INFLATED'
    elif nii_score >= NII_GROUNDED_THRESHOLD:
        return 'EXTENDED'
    else:
        return 'GROUNDED'

def apply_nii_discount(ce_raw, nii_state):
    return ce_raw * NII_DISCOUNT.get(nii_state, 1.0)

def nii_full_check(ce_raw, nar_archetype, assets_affected_count,
                   duration_claim_days, magnitude_claim_pct, mechanism_count,
                   verified_references, total_claims, cis2_score,
                   hwe_max_weight, wmbrl_base_rate, days_since_signal):
    conclusion = estimate_conclusion_scope(
        nar_archetype, assets_affected_count,
        duration_claim_days, magnitude_claim_pct, mechanism_count)
    evidence = estimate_evidence_scope(
        verified_references, total_claims,
        cis2_score, hwe_max_weight, wmbrl_base_rate, days_since_signal)
    nii_score  = compute_nii(conclusion, evidence)
    nii_state  = classify_nii_state(nii_score)
    ce_adj     = apply_nii_discount(ce_raw, nii_state)
    triggers   = []
    if nii_state == 'HYPER':
        triggers.append('NIS_REVIEW')
        triggers.append('HWE_PREMATURE_CLOSURE_CHECK')
    elif nii_state == 'INFLATED':
        triggers.append('NARRATIVE_INFLATION_WARNING')
    return {
        'nii_score':        round(nii_score, 2),
        'nii_state':        nii_state,
        'conclusion_scope': round(conclusion, 2),
        'evidence_scope':   round(evidence, 3),
        'ce_raw':           round(ce_raw, 3),
        'ce_adjusted':      round(ce_adj, 3),
        'discount_applied': NII_DISCOUNT.get(nii_state, 1.0),
        'triggers':         triggers,
    }
