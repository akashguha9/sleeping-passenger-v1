# ENVIRONMENT_QUALITY_SCORE (EQS)
# Module: S3B — Flow Dynamics / Signal Quality
# Added: April 16 2026
# Source: University/exploitation session reflection
#
# Cluster-level reciprocity tracking.
# Asks: is this thesis CONTAINER returning edge or extracting cost?
#
# War/energy cluster retrospective:
#   win_rate = 0/3 = 0.0
#   avg_pnl  = -9.44%
#   entry_timing_quality = 0 (all LATE or CHAOS)
#   reciprocity_rate = 0 (no thesis_confirmed exits)
#   EQS = 0.0 -> EXTRACTIVE -> CLOSED
#   After MP + ZIM: CVX and XOM would have been SHADOW_BOOK only
#
# EQS = 0.3*win_rate + 0.3*avg_pnl_norm + 0.2*entry_timing + 0.2*reciprocity
#
# Thresholds:
#   EQS > 0.6:  HIGH_RETURN    - standard entry rules
#   EQS 0.3-0.6: NEUTRAL       - apply ICT penalty
#   EQS < 0.3:  LOW_RETURN     - SHADOW_BOOK only
#   EQS < 0.15: EXTRACTIVE     - CLOSED, OLM review only

EQS_HIGH_RETURN  = 0.60
EQS_NEUTRAL_LOW  = 0.30
EQS_EXTRACTIVE   = 0.15

def compute_eqs(win_rate, avg_pnl_norm, entry_timing_quality, reciprocity_rate):
    return (0.3 * win_rate +
            0.3 * avg_pnl_norm +
            0.2 * entry_timing_quality +
            0.2 * reciprocity_rate)

def eqs_gate(eqs_score):
    if eqs_score > EQS_HIGH_RETURN:
        return "HIGH_RETURN"
    elif eqs_score > EQS_NEUTRAL_LOW:
        return "NEUTRAL"
    elif eqs_score > EQS_EXTRACTIVE:
        return "LOW_RETURN"
    else:
        return "EXTRACTIVE"
