# SIGNAL_BUOYANCY_ENGINE (SBE)
# Module: S35 — Synthesis / Decision Gate
# Added: April 17 2026
# Source: Compound 5-session block (buoyancy/water, chess, homeopathy, tempo, pub-art)
#
# THE GOVERNING EQUATION: B = S - (E + H)
#
# Synthesises all 11 existing component mechanisms into a single survival verdict.
# First mechanism in the pipeline that answers in one number:
# "Does this signal FLOAT or SINK in this specific environment right now?"
#
# Every prior mechanism feeds into SBE:
#   Signal_Density (S):      CIS2 + HWE + SPF + SF + WMBRL
#   Environment_Density (E): SBS + NII + EQS + LPS
#   Hardness_Penalty (H):    NDM + SDI_env + LPS_EXTREME
#
# B states:
#   STRONG_FLOAT:  B > 0.40  -> enter, high conviction
#   WEAK_FLOAT:    B 0.15-0.40 -> enter QUARTER_UNIT only
#   NEUTRAL:       B 0.0-0.15  -> watchlist, no capital
#   SINK:          B -0.15-0.0 -> reject
#   TRAP:          B < -0.15   -> strong reject, may be adversarial/manipulative
#
# Signal species (Isotope Classifier):
#   DEUTERIUM: SPF > 0.75 + institutional source
#              (filings, whale flow, Polymarket large liquidity move)
#              -> structural weight x1.3 boost to B
#   TRITIUM:   NIS = MOMENTUM_DOMINANT AND NII = HYPER AND SF = HYPED
#              -> decaying/unstable signal, B penalised x0.5
#   PROTIUM:   default — retail/media-driven, standard B calculation
#
# Persistence test:
#   B_t0: at signal receipt
#   B_t1: T+24h recheck
#   B_t2: T+7d recheck
#   If B_t0 = STRONG_FLOAT but B_t1 = SINK -> upgrade to TRAP
#
# Portfolio retrospectives:
#   RTX Day 3:
#     S=0.80 (CIS2 high, HWE COMMITTED, WMBRL=0.71, SF CLEAN, SPF good)
#     E=0.25 (low SBS, NII=1.2, EQS good, LPS MODERATE)
#     H=0.10 (NDM GROUNDED, SDI_env low, no LPS EXTREME)
#     B = 0.80 - 0.35 = +0.45 -> STRONG_FLOAT -> ENTER -> +3.90% WIN
#     Species: DEUTERIUM (institutional defence procurement)
#
#   CVX Day 80:
#     S=0.30 (CIS2=2.0, HWE=0.55, WMBRL=0.08, SF HYPED, SPF moderate)
#     E=0.70 (SBS high echo, NII HYPER, EQS poor, LPS EXTREME)
#     H=0.35 (NDM DRIFTING, SDI_env high, LPS EXTREME flag)
#     B = 0.30 - 1.05 = -0.75 -> TRAP -> REJECT -> -8.82% avoided
#     Species: TRITIUM (unstable war narrative, Day 80 saturation)
#
#   GLD current:
#     S=0.75 (CIS2 good, HWE COMMITTED, WMBRL=0.78, SF CLEAN)
#     E=0.30 (moderate echo, NII=1.4, good container)
#     H=0.10 (NDM GROUNDED)
#     B = 0.75 - 0.40 = +0.35 -> WEAK_FLOAT -> hold QUARTER_UNIT
#     Species: DEUTERIUM (institutional safe-haven, war regime)
#
# The buoyancy insight: a signal floats or sinks relative to its environment.
# The chess insight: sequence matters, tempo is edge, dead zones exist.
# The homeopathy insight: outcome != truth; perception residue is real.
# The tempo insight: IT - RT mismatch = throttle.
# The pub art insight: explore (Mario) -> narrate (Pub) -> compress (Gilroy).
# SBE = Gilroy layer: compresses everything into one focal verdict.
#
# Weights (heuristic until calibrated on T=10+ closed trades):
#   Signal_Density:    CIS2=0.20, HWE=0.25, SPF=0.20, SF=0.15, WMBRL=0.20
#   Environment_Density: SBS=0.25, NII=0.30, EQS=0.25, LPS=0.20
#   Hardness_Penalty:  NDM=0.40, SDI_env=0.40, LPS_extreme=0.20

SBE_STRONG_FLOAT = 0.40
SBE_WEAK_FLOAT   = 0.15
SBE_NEUTRAL      = 0.00
SBE_SINK         = -0.15
# Below SBE_SINK = TRAP

def compute_signal_density(cis2_score: float, hwe_max_weight: float,
                            spf_score: float, sf_score: float,
                            wmbrl_base_rate: float) -> float:
    s1 = min(cis2_score / 10.0, 1.0)
    s2 = min(hwe_max_weight, 1.0)
    s3 = min(spf_score / 10.0, 1.0)
    s4 = min(sf_score / 10.0, 1.0)
    s5 = min(wmbrl_base_rate, 1.0)
    return 0.20*s1 + 0.25*s2 + 0.20*s3 + 0.15*s4 + 0.20*s5

def compute_environment_density(sbs_echo_density: float, nii_score: float,
                                  eqs_score: float, lps_score: float) -> float:
    e1 = min(sbs_echo_density, 1.0)
    e2 = min(nii_score / 10.0, 1.0)
    e3 = max(0.0, 1.0 - min(eqs_score / 10.0, 1.0))  # inverted EQS
    e4 = min(lps_score / 10.0, 1.0)
    return 0.25*e1 + 0.30*e2 + 0.25*e3 + 0.20*e4

def compute_hardness_penalty(ndm_drift: float, sdi_environment: float,
                               lps_extreme: bool) -> float:
    h1 = min(ndm_drift * 2, 1.0)   # NDM_drift 0-0.5 -> 0-1.0
    h2 = min(sdi_environment, 1.0)
    h3 = 0.3 if lps_extreme else 0.0
    return 0.40*h1 + 0.40*h2 + 0.20*h3

def classify_signal_species(nis_state: str, nii_state: str, sf_state: str,
                             spf_score: float, source_type: str) -> str:
    if (nis_state == 'MOMENTUM_DOMINANT' and
        nii_state in ('HYPER', 'INFLATED') and
        sf_state == 'HYPED'):
        return 'TRITIUM'
    if spf_score >= 7.5 and source_type in ('institutional', 'filing', 'whale_flow'):
        return 'DEUTERIUM'
    return 'PROTIUM'

def apply_species_modifier(b_raw: float, species: str) -> float:
    if species == 'DEUTERIUM': return b_raw * 1.30
    if species == 'TRITIUM':   return b_raw * 0.50
    return b_raw  # PROTIUM

def classify_b_state(b_score: float) -> str:
    if b_score >= SBE_STRONG_FLOAT: return 'STRONG_FLOAT'
    elif b_score >= SBE_WEAK_FLOAT: return 'WEAK_FLOAT'
    elif b_score >= SBE_NEUTRAL:    return 'NEUTRAL'
    elif b_score >= SBE_SINK:       return 'SINK'
    else:                           return 'TRAP'

def sbe_entry_gate(b_state: str) -> dict:
    gates = {
        'STRONG_FLOAT': {'action': 'ENTER', 'size': 'QUARTER_UNIT',
                          'conviction': 'HIGH', 'note': 'Signal floats strongly.'},
        'WEAK_FLOAT':   {'action': 'ENTER_SMALL', 'size': 'HALF_QUARTER_UNIT',
                          'conviction': 'MODERATE', 'note': 'Signal floats but environment dense.'},
        'NEUTRAL':      {'action': 'WATCHLIST', 'size': 'NO_ENTRY',
                          'conviction': 'LOW', 'note': 'Signal barely floating. Monitor.'},
        'SINK':         {'action': 'REJECT', 'size': 'NO_ENTRY',
                          'conviction': 'NONE', 'note': 'Signal sinks. Environment too dense.'},
        'TRAP':         {'action': 'STRONG_REJECT', 'size': 'NO_ENTRY',
                          'conviction': 'NEGATIVE', 'note': 'TRAP. May be adversarial. CVX Day 80 pattern.'},
    }
    return gates.get(b_state, {'action': 'REJECT', 'size': 'NO_ENTRY'})

def sbe_full_check(cis2_score, hwe_max_weight, spf_score, sf_score, wmbrl_base_rate,
                   sbs_echo_density, nii_score, eqs_score, lps_score,
                   ndm_drift, sdi_environment, lps_extreme,
                   nis_state, nii_state, sf_state, source_type) -> dict:
    S = compute_signal_density(cis2_score, hwe_max_weight, spf_score, sf_score, wmbrl_base_rate)
    E = compute_environment_density(sbs_echo_density, nii_score, eqs_score, lps_score)
    H = compute_hardness_penalty(ndm_drift, sdi_environment, lps_extreme)
    b_raw   = S - (E + H)
    species = classify_signal_species(nis_state, nii_state, sf_state, spf_score, source_type)
    b_adj   = apply_species_modifier(b_raw, species)
    b_state = classify_b_state(b_adj)
    gate    = sbe_entry_gate(b_state)
    return {
        'b_score':       round(b_adj, 3),
        'b_raw':         round(b_raw, 3),
        'b_state':       b_state,
        'species':       species,
        'signal_density': round(S, 3),
        'env_density':   round(E, 3),
        'hardness':      round(H, 3),
        'components':    {'S': round(S,3), 'E': round(E,3), 'H': round(H,3)},
        'gate':          gate,
    }
