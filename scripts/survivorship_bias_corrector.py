# SURVIVORSHIP_BIAS_CORRECTOR (SBC)
# Module: S3A — Base-rate correction layer
# Added: April 17-18 2026
# Source: Nikhil Kamath / school friend / feedback-loop anecdotes session
#
# SBC corrects observed-pattern signals by estimating the base-rate
# probability of survivor success and discounting pattern inference
# accordingly.
#
# The session explicitly flagged this as an UNRESOLVED QUESTION:
# 'how does the MVP distinguish signal from survivorship bias in
# such anecdotes?' No existing mechanism addresses this.
#
# THE PROBLEM:
#   Every pattern the pipeline detects is derived only from OBSERVED outcomes
#   — successful traders, successful theses, successful historical setups.
#   The failed cases are SILENT and absent from the data.
#
#   'Dropout to billionaire' is visible because the 5 billionaires are famous.
#   The millions of failed dropouts are invisible.
#
#   When the pipeline computes 'SETUP X led to +15% gain in these 7 cases',
#   it never sees the 40 cases where SETUP X led to -10% loss and the trader
#   quit and vanished from the data.
#
#   Pattern inference from survivor data = INFLATED EDGE ESTIMATE.
#
# SBC is distinct from:
#   NSD:  pre-entry narrative vs structure (within-signal quality)
#   NII:  inference overreach within thesis (conclusion vs evidence scope)
#   NDI:  post-circulation narrative distortion (current cycle distortion)
#   ETIL: instrument tier reliability (historical instrument reliability)
#   LPC:  per-trade luck vs process (one outcome attribution)
#
# SBC asks: 'given this pattern is derived from K observed successes,
# how many silent failures likely exist for each success, and how should
# the inferred edge be discounted?'
#
# SBC COMPUTATION:
#
#   K:            observed_success_count (visible successful instances)
#   N_attempts:   estimated total attempts in the domain (incl. failures)
#   f:            survivor_fraction = K / N_attempts
#
# SURVIVOR PENALTY (applied to CE):
#   f >= 0.80:           penalty = 1.0        ROBUST_PATTERN (no adjustment)
#   0.30 <= f < 0.80:    penalty = f          TILTED_PATTERN (linear discount)
#   0.05 <= f < 0.30:    penalty = sqrt(f)    NARROW_PATTERN (sqrt discount)
#   f < 0.05:            penalty = sqrt(f)    LOTTERY_PATTERN (sqrt + warning)
#
# Why sqrt transform at f < 0.5:
#   We don't want to zero out a signal when f is very small.
#   A pattern with f=0.04 gets penalty = sqrt(0.04) = 0.20, not 0.04.
#   This acknowledges the pattern may still have SOME inference value
#   while recognising most practitioners fail.
#
# CE ADJUSTMENT:
#   CE_final = CE_raw * survivor_penalty
#
# PATTERN EXAMPLES:
#
#   'Dropout to billionaire':
#     K = 5 globally famous cases per generation
#     N_attempts = millions of dropouts
#     f = 10^-6 -> LOTTERY_PATTERN -> penalty = 0.001
#     Inferred 'edge' = 99.9% survivorship bias
#
#   'Value investing Buffett-style':
#     K = 300 documented practitioners
#     N_attempts = 5000 attempts
#     f = 0.06 -> NARROW_PATTERN -> penalty = 0.245
#     24.5% of raw edge preserved
#
#   'Earnings surprise momentum':
#     K = 1200 documented wins
#     N_attempts = 2000 attempts
#     f = 0.60 -> TILTED_PATTERN -> penalty = 0.60
#     60% of raw edge preserved
#
#   'Defence contractors on war':
#     K = 10 documented cases
#     N_attempts = 12 modern-era tension episodes
#     f = 0.83 -> ROBUST_PATTERN -> penalty = 1.0
#     Full CE preserved (mechanism is causal, not lottery)
#
#   'Gold in high-inflation regimes':
#     K = 30 documented cases
#     N_attempts = 35 inflation regimes across decades
#     f = 0.86 -> ROBUST_PATTERN -> penalty = 1.0
#
# UNMEASURABLE CASE:
#   When N_attempts is genuinely unknown, SBC flags the thesis
#   as UNMEASURABLE_BIAS and forces IL max action = PROBE only.
#   This prevents large sizing on theses that cannot be base-rate checked.
#
# SBC FEEDS INTO:
#   CE COMPOSITE_EDGE: CE_final = CE * survivor_penalty
#   MOLTBOOK logging: SBC tier and K, N recorded for each thesis
#   ECT inverse_selection: CHAOS_ENTRIES often have low SBC tier
#   IL max action: UNMEASURABLE_BIAS -> max PROBE only
#
# PORTFOLIO RETROSPECTIVES:
#
#   RTX Day 3:
#     Pattern: wartime defence procurement -> contractor stock rally
#     K = 10, N = 12, f = 0.83 -> ROBUST_PATTERN
#     penalty = 1.0
#     CE_raw = 0.834 -> CE_final = 0.834
#     STRONG_EDGE preserved. +3.90% WIN validated.
#
#   CVX Day 80:
#     Pattern: sustained oil rally on Iran tension
#     K = 3, N = 12, f = 0.25 -> NARROW_PATTERN
#     penalty = sqrt(0.25) = 0.50
#     CE_raw = 0.040 -> CE_final = 0.020 (still LEAVE)
#     SBC exposes: 'oil must rise on Iran' was built on 3 remembered
#     wins and 9 forgotten failures. Selective remembering = bias.
#
#   Session anecdotes (Nikhil / friend):
#     Pattern: non-elite education -> extraordinary wealth
#     K = 5-10 globally famous per generation, N = millions
#     f = 10^-6 -> LOTTERY_PATTERN
#     penalty = 0.001
#     Pattern has NO transferable edge.
#     99.9% of the 'lesson' is survivorship bias.
#
# THE SURVIVORSHIP BIAS LAW:
#   Every detected pattern is derived only from surviving data.
#   SBC asks: how many silent failures exist for each visible success?
#   The answer determines how much of the raw edge is real and how much
#   is selection bias. Without SBC, the pipeline inherits the entire
#   body of survivor-inflated historical edge estimates uncorrected.

SBC_ROBUST_THRESHOLD     = 0.80
SBC_TILTED_THRESHOLD     = 0.30
SBC_NARROW_THRESHOLD     = 0.05
# Below SBC_NARROW_THRESHOLD = LOTTERY_PATTERN

def compute_survivor_fraction(k_observed: int, n_attempts: int) -> float:
    if n_attempts <= 0 or k_observed < 0:
        return 0.0
    return max(0.0, min(1.0, k_observed / n_attempts))

def compute_survivor_penalty(f: float) -> float:
    import math
    if f >= SBC_ROBUST_THRESHOLD:
        return 1.0
    elif f >= SBC_TILTED_THRESHOLD:
        return round(f, 4)
    else:
        # NARROW or LOTTERY: sqrt transform preserves some signal
        return round(math.sqrt(f), 4) if f > 0 else 0.0

def classify_sbc_tier(f: float) -> str:
    if f >= SBC_ROBUST_THRESHOLD:   return 'ROBUST_PATTERN'
    elif f >= SBC_TILTED_THRESHOLD: return 'TILTED_PATTERN'
    elif f >= SBC_NARROW_THRESHOLD: return 'NARROW_PATTERN'
    else:                           return 'LOTTERY_PATTERN'

def compute_sbc(k_observed: int, n_attempts: int,
                n_confidence: str = 'medium',
                ce_raw: float = None) -> dict:
    if n_attempts <= 0:
        return {
            'sbc_tier':        'UNMEASURABLE_BIAS',
            'survivor_fraction': None,
            'survivor_penalty':  0.5,  # conservative default
            'ce_final':          round(ce_raw * 0.5, 3) if ce_raw is not None else None,
            'il_max_override':   'PROBE',
            'note':              'N_attempts unknown. Forcing IL PROBE max action.',
        }
    f       = compute_survivor_fraction(k_observed, n_attempts)
    penalty = compute_survivor_penalty(f)
    tier    = classify_sbc_tier(f)
    conf_adj = {'high': 1.0, 'medium': 0.9, 'low': 0.75}.get(n_confidence, 0.9)
    effective_penalty = round(penalty * conf_adj, 4)
    result = {
        'sbc_tier':            tier,
        'k_observed':          k_observed,
        'n_attempts':          n_attempts,
        'survivor_fraction':   round(f, 6),
        'survivor_penalty':    penalty,
        'n_confidence':        n_confidence,
        'confidence_adjusted_penalty': effective_penalty,
        'il_max_override':     'PROBE' if tier == 'LOTTERY_PATTERN' else None,
        'note': (
            f'{tier}: f={f:.4f}, raw_penalty={penalty:.4f}, '
            f'confidence={n_confidence} -> effective={effective_penalty:.4f}'
        ),
    }
    if ce_raw is not None:
        result['ce_raw']   = ce_raw
        result['ce_final'] = round(ce_raw * effective_penalty, 3)
    return result
