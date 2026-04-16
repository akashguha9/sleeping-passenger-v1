# STRUCTURAL_INTEGRITY_SCORE (SIS)
# Module: S0 — Signal Intake
# Added: April 16 2026
# Source: Como/Venezia/Dennis Wise/Fàbregas session
#
# Scores the hidden operational depth of a thesis ENTITY —
# not the source quality (SPF) or signal quality (CE),
# but the structural coherence of the thing being signalled about.
#
# Dennis Wise = hidden coherence layer making Fàbregas output possible.
# Pipeline equivalent: entity structural depth discounts valid signals.
#
# COMPOSITE_EDGE_structural = COMPOSITE_EDGE x (0.5 + 0.5 x SIS)
# Low SIS (0.2): effective CE = CE x 0.6 -> structural discount
# High SIS (0.9): effective CE = CE x 0.95 -> near-full signal weight
#
# CVX retrospective:
#   SIS_execution = HIGH (well-run supermajor)
#   SIS_recruitment_alignment = LOW (thesis was geopolitical, not company-specific)
#   SIS_executive_filter = LOW (no Wise-layer between war narrative and entry)
#   Net SIS = 0.4 -> CE x 0.7 -> below 0.55 threshold -> LEAVE
#
# Components:
#   ownership_coherence:  aligned, committed ownership present?
#   executive_filter:     Wise-layer (noise reducer, translator, gatekeeper)?
#   recruitment_alignment: capability additions coherent with core thesis?
#   execution_quality:    visible executor has coherent system backing?

SIS_WEIGHTS = {
    'ownership_coherence': 0.25,
    'executive_filter': 0.30,
    'recruitment_alignment': 0.25,
    'execution_quality': 0.20,
}

def compute_sis(ownership, executive_filter, recruitment, execution):
    return (SIS_WEIGHTS['ownership_coherence'] * ownership +
            SIS_WEIGHTS['executive_filter'] * executive_filter +
            SIS_WEIGHTS['recruitment_alignment'] * recruitment +
            SIS_WEIGHTS['execution_quality'] * execution)

def apply_sis_discount(composite_edge, sis_score):
    multiplier = 0.5 + 0.5 * sis_score
    return composite_edge * multiplier
