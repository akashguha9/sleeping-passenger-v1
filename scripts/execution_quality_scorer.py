# EXECUTION_QUALITY_SCORER (EQS)
# Module: S8 — Post-entry transmission fidelity
# Added: April 17-18 2026
# Source: Football / boots / Jabulani / Butterfly shoes session
#
# EQS = mean(instrument_fidelity, timing_fidelity, size_fidelity, post_entry_coherence)
#
# The Jabulani law: the best signal through the wrong instrument = distorted outcome.
# Not because the signal was wrong, but because the transmission chain broke.
#
# ZPD: checks all 6 gates PRE-entry (precision check)
# ASS: Q = O×S PRE-entry (trade quality)
# EQS: scores AFTER entry — how cleanly did execution preserve signal quality?
#
# Ball archetypes mapped to EQS regimes:
#   T90 / Tiempo:  HIGH_FIDELITY (0.75+) — controllable volatility, skill dominates
#   Heavy local:   MODERATE (0.50-0.75) — high threshold, clean post-trigger
#   Zoom Fly:      LOW_FIDELITY (0.25-0.50) — directional bias, instrument distorts
#   Jabulani:      BROKEN_CHAIN (<0.25) — mid-path mutation, thesis betrays post-entry
#
# 4 transmission components (each 0-1):
#
# 1. INSTRUMENT_FIDELITY:
#    How cleanly does this specific instrument transmit the signal?
#    = (1 - bid_ask_spread_ratio) * (1 - slippage_rate) * instrument_liquidity
#    T90 = large-cap liquid, tight spread = high fidelity
#    Jabulani = volatile, wide spread, unpredictable = low fidelity
#    NSD OVEREXTENDED instruments score lower (narrative biases the medium)
#
# 2. TIMING_FIDELITY:
#    Was the entry executed at the MTL timing planned?
#    = 1 - |actual_time_fraction - target_MTL_time_fraction|
#    RTX Day 3: target OPENING (0.21), actual Day 3 (0.21) -> fidelity = 1.0
#    CVX Day 80: target was NEVER (MTL EXPIRED = 0.0), actual entered = timing_fidelity = 0.10
#
# 3. SIZE_FIDELITY:
#    Was the actual position size what ZPD/IL authorized?
#    = 1.0 if actual_size_category == authorized_size_category
#    = 0.0 if CHAOS_ENTRY (entered QUARTER_UNIT when SANDBOX or BLOCK authorized)
#    = 0.5 if partial violation (entered PROBE size when STAGGER tranche was plan)
#    This is the behavioral transmission check: did the operator follow the sizing protocol?
#    CHAOS_ENTRY pattern: size_fidelity = 0.0 -> EQS BROKEN_CHAIN regardless of other components
#
# 4. POST_ENTRY_COHERENCE:
#    After entry, is the thesis still behaving as expected?
#    Checked at T+24h and T+7d
#    = fraction of checks where SBE B_state is same tier as at entry
#    = 1.0 if thesis held fully (T90 regime)
#    = 0.0 if thesis mutated immediately (Jabulani: path changes mid-flight)
#    Sources: SBE B_state recheck, NSD state recheck, PSE P(spread) recheck
#
# EQS = mean(if1, tf, sf, pec)
#
# EQS states:
#   HIGH_FIDELITY:   EQS >= 0.75 -> T90 regime, execution preserved signal
#   MODERATE:        EQS 0.50-0.75 -> some transmission loss, acceptable
#   LOW_FIDELITY:    EQS 0.25-0.50 -> significant distortion, flag for review
#   BROKEN_CHAIN:    EQS < 0.25  -> Jabulani regime, major transmission failure
#
# EQS feeds into:
#   MOLTBOOK post-trade log: EQS score + component breakdown per trade
#   LUCKY_PASS_CLASSIFIER LPC: separate skill quality from execution quality
#   CAL: EQS is execution-level calibration input (T=10+ → learn which layer breaks most)
#   MW learning loop: BROKEN_CHAIN trades reviewed separately (instrument distorted signal)
#
# Portfolio retrospectives:
#   RTX Day 3: T90 regime
#     if1=0.92 (RTX large-cap liquid), tf=0.95 (MTL OPENING D3 planned),
#     sf=1.00 (QUARTER_UNIT authorized, QUARTER_UNIT entered)
#     pec=0.90 (SBE held STRONG_FLOAT at T+24h, +3.90% WIN)
#     EQS = mean(0.92, 0.95, 1.00, 0.90) = 0.94 -> HIGH_FIDELITY
#
#   CVX Day 80: Jabulani regime (CHAOS_ENTRY)
#     if1=0.60 (CVX liquid but NSD OVEREXTENDED = biased instrument)
#     tf=0.10 (MTL EXPIRED, entered far from any authorized window)
#     sf=0.00 (ZPD BLOCK + ASS REJECT = no size authorized, entered QUARTER_UNIT)
#     pec=0.10 (thesis mutated immediately at T+24h)
#     EQS = mean(0.60, 0.10, 0.00, 0.10) = 0.20 -> BROKEN_CHAIN
#     consequence_persistence=2.5 now explained: all 4 transmission layers failed
#
#   JPM (CHAOS_ENTRY): Zoom Fly directional bias archetype
#     if1=0.70 (JPM large-cap), tf=0.30 (CFD LOCKED = wrong timing window)
#     sf=0.00 (IL said SANDBOX = no real capital, entered QUARTER_UNIT)
#     pec=0.40 (partial thesis but contaminated)
#     EQS = mean(0.70, 0.30, 0.00, 0.40) = 0.35 -> LOW_FIDELITY
#
#   GLD current: T90 regime
#     if1=0.88 (GLD/SGOL liquid), tf=0.90 (MTL BUILDING planned and hit)
#     sf=1.00 (QUARTER_UNIT authorized and entered)
#     pec=0.85 (thesis holding, +8.17% unrealised)
#     EQS = mean(0.88, 0.90, 1.00, 0.85) = 0.91 -> HIGH_FIDELITY
#
# The strategic law: difficulty is acceptable. Jabulani is not.
# Hard is fine. Hidden chaos destroys transmission fidelity.
# EQS tells you which layer broke — not just that it broke.

EQS_HIGH_FIDELITY    = 0.75
EQS_MODERATE         = 0.50
EQS_LOW_FIDELITY     = 0.25
# Below EQS_LOW_FIDELITY = BROKEN_CHAIN

def compute_instrument_fidelity(bid_ask_spread_ratio: float, slippage_rate: float,
                                  liquidity_score: float,
                                  nsd_overextended: bool = False) -> float:
    base = (1 - bid_ask_spread_ratio) * (1 - slippage_rate) * liquidity_score
    if nsd_overextended:
        base *= 0.85   # NSD OVEREXTENDED introduces instrument bias
    return round(max(0.0, min(1.0, base)), 3)

def compute_timing_fidelity(actual_time_fraction: float,
                             target_mtl_time_fraction: float,
                             mtl_state: str) -> float:
    if mtl_state == 'EXPIRED':
        return 0.05  # entry in EXPIRED window = near-zero timing fidelity
    delta = abs(actual_time_fraction - target_mtl_time_fraction)
    return round(max(0.0, min(1.0, 1.0 - delta)), 3)

def compute_size_fidelity(authorized_size_category: str,
                           actual_size_category: str) -> float:
    if authorized_size_category in ('BLOCK', 'SANDBOX', 'VETO'):
        if actual_size_category in ('QUARTER_UNIT', 'HALF_UNIT', 'FULL'):
            return 0.00   # CHAOS_ENTRY: full violation
        return 1.00
    if authorized_size_category == actual_size_category:
        return 1.00
    # Partial mismatch (e.g. entered PROBE when STAGGER was plan)
    size_order = ['EIGHTH_UNIT', 'HALF_QUARTER_UNIT', 'QUARTER_UNIT', 'HALF_UNIT', 'FULL']
    try:
        auth_idx = size_order.index(authorized_size_category)
        act_idx  = size_order.index(actual_size_category)
        return round(max(0.0, 1.0 - abs(auth_idx - act_idx) * 0.25), 3)
    except ValueError:
        return 0.50

def compute_post_entry_coherence(checks_passed: int, checks_total: int) -> float:
    if checks_total == 0:
        return 1.0   # no checks yet = assume coherent
    return round(checks_passed / checks_total, 3)

def classify_eqs_state(eqs: float) -> str:
    if eqs >= EQS_HIGH_FIDELITY:  return 'HIGH_FIDELITY'
    elif eqs >= EQS_MODERATE:     return 'MODERATE'
    elif eqs >= EQS_LOW_FIDELITY: return 'LOW_FIDELITY'
    else:                         return 'BROKEN_CHAIN'

def eqs_full_check(bid_ask_spread_ratio, slippage_rate, liquidity_score,
                   actual_time_fraction, target_mtl_time_fraction, mtl_state,
                   authorized_size_category, actual_size_category,
                   coherence_checks_passed, coherence_checks_total,
                   nsd_overextended=False) -> dict:
    if1 = compute_instrument_fidelity(bid_ask_spread_ratio, slippage_rate,
                                      liquidity_score, nsd_overextended)
    tf  = compute_timing_fidelity(actual_time_fraction, target_mtl_time_fraction, mtl_state)
    sf  = compute_size_fidelity(authorized_size_category, actual_size_category)
    pec = compute_post_entry_coherence(coherence_checks_passed, coherence_checks_total)
    eqs = round((if1 + tf + sf + pec) / 4, 3)
    state = classify_eqs_state(eqs)
    chaos_entry = (sf == 0.00 and authorized_size_category in ('BLOCK','SANDBOX','VETO'))
    return {
        'eqs':                     eqs,
        'eqs_state':               state,
        'instrument_fidelity':     if1,
        'timing_fidelity':         tf,
        'size_fidelity':           sf,
        'post_entry_coherence':    pec,
        'chaos_entry_detected':    chaos_entry,
        'weakest_component':       min({'instrument':if1,'timing':tf,'size':sf,'coherence':pec},
                                       key=lambda k: {'instrument':if1,'timing':tf,'size':sf,'coherence':pec}[k]),
        'note': ('BROKEN_CHAIN: Jabulani regime. All layers failed.' if state=='BROKEN_CHAIN' else
                 'HIGH_FIDELITY: T90 regime. Execution preserved signal.' if state=='HIGH_FIDELITY' else
                 f'{state}: Review {min({"instrument":if1,"timing":tf,"size":sf,"coherence":pec}, key=lambda k: {"instrument":if1,"timing":tf,"size":sf,"coherence":pec}[k])} component.'),
    }
