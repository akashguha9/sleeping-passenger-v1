# SIGNAL_NODE_CLASSIFIER (SNC)
# Module: S0 — Signal Intake
# Added: April 16 2026
# Source: Dylan / We Are the World session
#
# Routes each incoming signal to the correct processing module before CE is computed.
# Pipeline currently feeds all signals into CE as undifferentiated directional inputs.
# SNC classifies node type FIRST, then routes to the appropriate module.
#
# 7 node types and their routing:
#   SYSTEM:   maintains flow -> NIS baseline update
#   DYLAN:    meaningful distortion -> EDS mismatch computation
#   TRIGGER:  activates movement -> MTL/GSCE FINAL_THIRD check
#   ANCHOR:   reference frame -> CE threshold calibration
#   BRIDGE:   connects clusters -> PES (position entanglement) update
#   DECOY:    absorbs attention -> SDI_environment HIGH (CE discounted)
#   TERMINAL: confirms outcome -> CAL Moltbook logging
#
# Classification rules (rule-based):
#   SYSTEM:   SPF LOW + T_n LOW + recurring + NLR_lag LONG
#   DYLAN:    EDS_score > 0.3 + source_bubble LOW + symbolic_weight HIGH
#   TRIGGER:  PBSC=STAND_UP_RUN + TAT=PEAK + MTL=OPTIMAL
#   ANCHOR:   Polymarket/Kalshi source + high_liquidity + reference_level
#   BRIDGE:   connects two thesis clusters with low PES overlap
#   DECOY:    T_n HIGH + echo_density HIGH + SCM_history LOW_CONVERSION
#   TERMINAL: position_closed + thesis_outcome_confirmed
#
# Portfolio retrospective:
#   GLD:          SYSTEM -> maintain, hold -> +8.17%
#   Iran 64%:     DYLAN + TRIGGER -> EDS fires REVERSAL + MTL check -> ZIM exit -2.19% correct
#   War Day 80:   DECOY -> SDI_env HIGH -> CE_corrected LOW -> LEAVE -> -8.82% avoided
#   RTX Day 3:    TRIGGER -> MTL=OPTIMAL -> ENTER -> +3.90% WIN
#   CVX Day 30:   DYLAN -> EDS REVERSAL -> should have fired LEAVE -> -8.82% avoided

NODE_TYPES = ['SYSTEM', 'DYLAN', 'TRIGGER', 'ANCHOR', 'BRIDGE', 'DECOY', 'TERMINAL']

ROUTING_TABLE = {
    'SYSTEM':   'NIS_BASELINE_UPDATE',
    'DYLAN':    'EDS_MISMATCH_CHECK',
    'TRIGGER':  'GSCE_FINAL_THIRD_CHECK',
    'ANCHOR':   'CE_THRESHOLD_CALIBRATION',
    'BRIDGE':   'PES_UPDATE',
    'DECOY':    'SDI_ENVIRONMENT_INFLATE',
    'TERMINAL': 'CAL_MOLTBOOK_LOG',
}

def classify_signal_node(spf_score, t_n_score, echo_density, nlr_lag_days,
                          eds_score, symbolic_weight, pbsc_state, tat_state,
                          mtl_state, is_prediction_market, high_liquidity,
                          pes_bridge_score, scm_history_rate, position_closed,
                          thesis_confirmed):
    if position_closed and thesis_confirmed:
        return 'TERMINAL'
    if pbsc_state == 'STAND_UP_RUN' and tat_state == 'PEAK' and mtl_state == 'OPTIMAL':
        return 'TRIGGER'
    if is_prediction_market and high_liquidity:
        return 'ANCHOR'
    if t_n_score > 0.7 and echo_density > 0.6 and scm_history_rate < 0.3:
        return 'DECOY'
    if eds_score > 0.3 and symbolic_weight > 0.5:
        return 'DYLAN'
    if pes_bridge_score > 0.5:
        return 'BRIDGE'
    if spf_score < 0.3 and t_n_score < 0.4 and nlr_lag_days > 20:
        return 'SYSTEM'
    return 'SYSTEM'

def route_signal(node_type):
    return ROUTING_TABLE.get(node_type, 'CE_STANDARD_PROCESSING')

def snc_process(signal_features):
    node_type = classify_signal_node(**signal_features)
    routing   = route_signal(node_type)
    return {
        'node_type': node_type,
        'routing':   routing,
        'ce_path':   'DISCOUNTED' if node_type == 'DECOY' else 'STANDARD',
    }
