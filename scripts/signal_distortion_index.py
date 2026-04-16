# SIGNAL_DISTORTION_INDEX (SDI)
# Module: S0 — Signal Intake
# Added: April 16 2026
# Source: Sing Street / MDMA / Dublin session
#
# Decomposes an observed CE at point of receipt into 3 orthogonal components:
#   1. SDI_base:        what CE would be in neutral state + neutral environment
#   2. SDI_state:       operator psychological amplification or penalty
#   3. SDI_environment: market regime and narrative heat inflation
#
# CE_corrected = SDI_base / (1 + SDI_state + SDI_environment)
#
# Distinct from:
#   SPF: scores source-level strategic distortion (different object)
#   NIS: tracks momentum vs fresh signal over time (temporal, not instantaneous)
#   SDI: decomposes THIS signal RIGHT NOW at point of receipt
#
# The MDMA/concert insight:
#   The environment and state were doing the signal work, not the base thesis.
#   SDI corrects for that at S0 before CE enters any downstream gate.
#
# CVX retrospective:
#   SDI_base: moderate (war thesis underlying)
#   SDI_state: near-zero (April 4 DRAINED — should have penalised)
#   SDI_environment: HIGH (T_n=HIGH + M_total=LOW Day80 + echo=ELEVATED)
#   CE_corrected = moderate / (1 + 0 + HIGH) -> below 0.55 threshold -> LEAVE
#   -8.82% avoided.
#
# RTX retrospective:
#   SDI_base: good (defence thesis, fresh signal)
#   SDI_state: POSITIVE (Human realm, no CHAOS proximity)
#   SDI_environment: LOW (T_n=MODERATE + M_total=ADEQUATE + echo=LOW)
#   CE_corrected approx CE_raw -> threshold passed -> ENTER -> +3.90% WIN
#
# Component inputs:
#   SDI_base = CE_raw * (1 - SPF) * SIS * EQS
#   SDI_state = THREE_POISONS_bias_total * REALM_bonus * BIS_rolling_delta
#     (positive: Human realm + recent WIN)
#     (negative: ANIMAL realm + CHAOS proximity)
#   SDI_environment = T_n * (1 - TYNDALL_M_total) * SOURCE_BUBBLE_echo_density

SDI_STATE_POSITIVE_MULTIPLIER  =  0.10  # Human realm + recent WIN boost
SDI_STATE_NEGATIVE_MULTIPLIER  = -0.15  # ANIMAL realm + CHAOS proximity penalty
SDI_ENV_HIGH_THRESHOLD  = 0.50
SDI_ENV_LOW_THRESHOLD   = 0.20

def compute_sdi_base(ce_raw, spf_score, sis_score, eqs_score):
    return ce_raw * (1 - spf_score) * sis_score * eqs_score

def compute_sdi_state(three_poisons_bias, realm_bonus, bis_delta):
    raw = three_poisons_bias * realm_bonus * bis_delta
    if raw > 0:
        return raw * SDI_STATE_POSITIVE_MULTIPLIER
    else:
        return raw * abs(SDI_STATE_NEGATIVE_MULTIPLIER)

def compute_sdi_environment(t_n, tyndall_m_total, echo_density):
    return t_n * (1 - tyndall_m_total) * echo_density

def apply_sdi_correction(ce_raw, sdi_base, sdi_state, sdi_environment):
    denominator = 1 + max(sdi_state, 0) + sdi_environment
    return sdi_base / denominator

def classify_sdi_environment(sdi_env_score):
    if sdi_env_score > SDI_ENV_HIGH_THRESHOLD:
        return 'HIGH_INFLATION'
    elif sdi_env_score > SDI_ENV_LOW_THRESHOLD:
        return 'MODERATE_INFLATION'
    else:
        return 'LOW_INFLATION'

def sdi_full_correction(ce_raw, spf, sis, eqs, three_poisons, realm_bonus,
                        bis_delta, t_n, tyndall_m, echo_density):
    base = compute_sdi_base(ce_raw, spf, sis, eqs)
    state = compute_sdi_state(three_poisons, realm_bonus, bis_delta)
    env = compute_sdi_environment(t_n, tyndall_m, echo_density)
    corrected = apply_sdi_correction(ce_raw, base, state, env)
    return {
        'ce_raw':          round(ce_raw, 3),
        'sdi_base':        round(base, 3),
        'sdi_state':       round(state, 3),
        'sdi_environment': round(env, 3),
        'ce_corrected':    round(corrected, 3),
        'env_regime':      classify_sdi_environment(env),
    }
