# SILENCE_FILTER (SF)
# Module: S0 — Signal Intake (pre-classification gate)
# Added: April 17 2026
# Source: Rumi / RUMI ENGINE session
#
# Scores the RAW INCOMING SIGNAL at first contact, before SNC classification.
# The earliest possible gate in the pipeline.
#
# Architecture position:
#   RAW_SIGNAL -> [SILENCE_FILTER] -> SNC -> SDI -> ETIL -> SPF -> ...
#
# SF is distinct from all related mechanisms:
#   SPF: scores credibility of a single SOURCE (per source, not per signal)
#   SBS: scores echo density per NARRATIVE CLUSTER (post-clustering)
#   NIS: tracks momentum fraction per ACTIVE THESIS (during monitoring)
#   SF:  scores RAW SIGNAL at first contact — quiet/persistent vs loud/recent
#
# The Rumi operationalised:
#   The best signals are often not the loudest but the most coherent and persistent.
#   PRISTINE = the signal that keeps returning quietly across independent sources.
#   HYPED = loud, recent, concentrated on one channel = suspicious.
#
# SF formula:
#   SF = alpha * (1/noise_density) + beta * persistence_score + gamma * source_independence
#
# Where:
#   noise_density:      mention_velocity / baseline_velocity
#                       HIGH noise = loud trending = penalty
#                       LOW noise = quiet = reward
#   persistence_score:  normalised score from 0-10 based on days_persisted
#                       > 7 days quiet = maximum persistence reward
#                       appeared today only = minimum
#   source_independence: 1 - max_cross_source_correlation
#                        5 independent sources >> 50 correlated echoes
#                        Uses SBS echo_density inverted as proxy
#
# SF states:
#   HYPED:    SF < 3.0 -> loud, recent, concentrated -> penalise in composite
#   NOISY:    SF 3.0-5.5 -> moderate noise -> standard flow, no boost or penalty
#   CLEAN:    SF 5.5-7.5 -> low noise, multi-day persistence -> boost in composite
#   PRISTINE: SF > 7.5 -> quiet, persistent >= 7 days, independent -> maximum boost
#
# Weights (heuristic until calibrated on T=10+ closed trades):
#   alpha = 0.30  (noise_density penalty — crowds are suspicious)
#   beta  = 0.40  (persistence reward — time is the test)
#   gamma = 0.30  (source_independence reward — echo is not confirmation)
#
# Portfolio retrospectives:
#   RTX Day 3:   Defence procurement building in Polymarket 10+ days, not Twitter trending.
#                SF = CLEAN (persistence >= 7d, low noise). Boost. +3.90% WIN.
#   CVX Day 80:  War narrative on every channel, Day 80 saturation, no quiet persistence.
#                SF = HYPED (high noise density, single concentrated narrative).
#                Earliest upstream rejection — upstream of NII, NDM, ZPD.
#                -8.82% avoided.
#   GLD current: Safe-haven across Polymarket, gold futures, geopolitical analysis — quiet.
#                SF = PRISTINE. Maximum boost. +8.17% confirms.
#   Crypto token (Rumi case study): High Twitter velocity, 6 hours old, single platform.
#                SF = HYPED (approx 1.5). Reject. RUMI composite score ~ 3.1.

SF_HYPED_THRESHOLD    = 3.0
SF_NOISY_THRESHOLD    = 5.5
SF_CLEAN_THRESHOLD    = 7.5

SF_ALPHA = 0.30   # noise_density penalty weight
SF_BETA  = 0.40   # persistence reward weight
SF_GAMMA = 0.30   # source_independence reward weight

def compute_noise_density_score(mention_velocity: float,
                                 baseline_velocity: float) -> float:
    if baseline_velocity <= 0:
        return 5.0
    ratio = mention_velocity / baseline_velocity
    if ratio >= 10.0:  return 0.0    # extremely loud, maximum penalty
    elif ratio >= 5.0: return 2.0
    elif ratio >= 2.0: return 4.0
    elif ratio >= 1.0: return 6.0
    elif ratio >= 0.5: return 8.0
    else:              return 10.0   # barely any noise, maximum reward

def compute_persistence_score(days_persisted: int) -> float:
    if days_persisted <= 0:   return 0.0
    elif days_persisted <= 1: return 1.0
    elif days_persisted <= 3: return 3.0
    elif days_persisted <= 7: return 5.5
    elif days_persisted <= 14:return 7.5
    elif days_persisted <= 30:return 9.0
    else:                     return 10.0  # > 30 days quiet = PRISTINE persistence

def compute_source_independence_score(echo_density: float) -> float:
    # echo_density from SBS: 0 = fully independent, 1 = full echo chamber
    return max(0.0, (1 - echo_density) * 10.0)

def compute_silence_filter(mention_velocity: float, baseline_velocity: float,
                            days_persisted: int, echo_density: float) -> dict:
    noise_score       = compute_noise_density_score(mention_velocity, baseline_velocity)
    persistence_score = compute_persistence_score(days_persisted)
    independence_score= compute_source_independence_score(echo_density)
    sf_score = (SF_ALPHA * noise_score +
                SF_BETA  * persistence_score +
                SF_GAMMA * independence_score)
    return {
        'sf_score':          round(sf_score, 2),
        'noise_score':       round(noise_score, 2),
        'persistence_score': round(persistence_score, 2),
        'independence_score':round(independence_score, 2),
        'noise_ratio':       round(mention_velocity / max(baseline_velocity, 0.001), 2),
        'days_persisted':    days_persisted,
        'echo_density':      echo_density,
    }

def classify_sf_state(sf_score: float) -> str:
    if sf_score >= SF_CLEAN_THRESHOLD:
        return 'PRISTINE'
    elif sf_score >= SF_NOISY_THRESHOLD:
        return 'CLEAN'
    elif sf_score >= SF_HYPED_THRESHOLD:
        return 'NOISY'
    else:
        return 'HYPED'

def sf_composite_modifier(sf_state: str) -> float:
    # CE composite modifier: applied multiplicatively to CE_corrected downstream
    modifiers = {
        'PRISTINE': 1.15,   # boost: quiet persistent independent signal
        'CLEAN':    1.05,   # mild boost
        'NOISY':    1.00,   # neutral
        'HYPED':    0.60,   # penalty: loud, recent, concentrated
    }
    return modifiers.get(sf_state, 1.0)

def silence_filter_full_check(mention_velocity: float, baseline_velocity: float,
                               days_persisted: int, echo_density: float) -> dict:
    result = compute_silence_filter(mention_velocity, baseline_velocity,
                                    days_persisted, echo_density)
    state  = classify_sf_state(result['sf_score'])
    modifier = sf_composite_modifier(state)
    block  = (state == 'HYPED')
    return {
        'sf_score':          result['sf_score'],
        'sf_state':          state,
        'ce_modifier':       modifier,
        'block_at_intake':   block,
        'block_reason':      'SF=HYPED: loud/recent/concentrated. Rumi: loudness is not validity.' if block else None,
        'components':        result,
    }
