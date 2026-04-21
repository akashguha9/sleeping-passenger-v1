# SOURCE_SIGNALING_DISCOUNT (SSD)
# Module: S0 — Source-level performative-style discount
# Added: April 17-18 2026
# Source: Nikhil Kamath extended / humility / validation-independence / signaling session
#
# SSD weights incoming signals by the performative-signaling density
# of their HUMAN SOURCE, not just by SPF source tier reliability.
#
# The gap in the pipeline:
#   SPF scores source_tier (T1 primary/official vs T4 secondary/retail)
#   But WITHIN a tier, sources vary wildly in PERFORMATIVE STYLE.
#
#   Two T2 analysts:
#     A) Quiet operator publishing weekly technical notes
#     B) CNBC pundit shouting theatrical calls
#
#   Both get the same SPF tier. They should not get the same signal weight.
#
# The session explicitly introduced:
#   - Low-signaling behavior as substance heuristic
#   - Validation independence as execution stability marker
#   - Performance-theater as distraction risk
#   - BUT: 'calm != proof, loud != proof' — heuristic only, not certainty
#
# SSD is distinct from:
#   SPF: source_tier reliability (T1-T4)
#   BIS: operator self-integrity (applies to self, not external sources)
#   NSD: signal narrative vs structural depth (content-level)
#   NDI: post-circulation narrative distortion (narrative-level)
#   OSM: operator pre-pipeline state (self-state)
#   SBC: base-rate correction (population-level)
#
# SSD asks: 'does this specific human source's performative style
# correlate with lower signal quality?'
#
# 5 SSD COMPONENTS (each 0-1):
#
# c1: PROMOTION_DENSITY
#   Frequency of self-promotional content / total content
#   Self-citations, self-quotes, 'as I predicted', awards mentioned
#   Quiet operator = 0.1, loud influencer = 0.8
#
# c2: CERTAINTY_INFLATION
#   Proportion of statements using high-certainty language
#   "Definitely", "guaranteed", "this will", "the ONLY", "obviously"
#   Normal analyst = 0.2, pundit = 0.7
#
# c3: APPEARANCE_CADENCE
#   Media appearance density (CNBC, podcasts, conferences)
#   Frequency-normalized against sector baseline
#   Quiet operator = 0.1, media regular = 0.8
#
# c4: TITLE_PREFIX_USAGE
#   Use of 'Dr', 'Prof', 'Award-winning', 'Bestseller', 'Forbes 30u30'
#   Signal-prefixing behavior in bio and citations
#   None = 0.0, status-stacked = 0.9
#
# c5: VALIDATION_DEPENDENCE
#   Response patterns to criticism/praise
#   Extreme reactivity = high score
#   Stoic = 0.1, reactive = 0.8
#
# SSD_score = mean(c1, c2, c3, c4, c5)
# Range: 0.0 (pure operator) to 1.0 (pure performer)
#
# SSD DISCOUNT FUNCTION:
#   signal_discount = 1.0 - (SSD_score * 0.40)
#   
#   Maximum discount capped at 40% (SSD=1.0 gives discount=0.60)
#   Even extreme performers retain 60% weight — they might still produce
#   real information. SSD is weight adjustment, not truth verdict.
#
#   Minimum discount of 0% for SSD=0.0 (pure operator).
#
#   CE_adjusted_by_source = CE_raw * signal_discount
#
# SSD TIERS:
#   OPERATOR_STYLE:   SSD < 0.25, discount 0-10%     (Nikhil archetype)
#   MIXED_STYLE:      SSD 0.25-0.50, discount 10-20% (typical analyst)
#   PERFORMER_STYLE:  SSD 0.50-0.75, discount 20-30% (media regular)
#   THEATRICAL_STYLE: SSD > 0.75, discount 30-40%    (high-signaling pundit)
#
# IMPORTANT CAVEATS (session-flagged false-positive risks):
#   - Loud sources are not automatically wrong (some pundits are right)
#   - Quiet sources are not automatically correct (some quiet = irrelevant)
#   - SSD is a HEURISTIC WEIGHT, not a truth verdict
#   - 40% cap prevents over-correction
#   - Combine with track record (SPF) and signal content (NSD) — never standalone
#   - P(substance | low-signaling) < 1 always
#
# SSD FEEDS INTO:
#   CE COMPOSITE_EDGE: CE_final *= (1 - SSD_score * 0.40)
#   SPF sub-tier: SSD_score modulates rank within same source_tier
#   MOLTBOOK logging: SSD per-source recorded for post-trade attribution
#   Long-term source calibration: per-source SSD vs outcome correlation
#     allows SSD to self-calibrate over time — if low-signaling sources
#     really produce better signals, the 40% cap can be tightened;
#     if not, the cap can be relaxed
#
# SAME SIGNAL, DIFFERENT SOURCES EXAMPLE:
#   Signal content: 'Iran escalation -> defense contractor rally'
#   
#   Source A (DoD procurement filing):
#     SPF=T1, SSD=0.10, discount=0.96
#     CE=0.80 -> CE_adjusted=0.768 STRONG_EDGE
#   
#   Source B (geopolitical newsletter):
#     SPF=T2, SSD=0.25, discount=0.90
#     CE=0.80 -> CE_adjusted=0.720 STRONG_EDGE
#   
#   Source C (CNBC pundit segment):
#     SPF=T3, SSD=0.65, discount=0.74
#     CE=0.80 -> CE_adjusted=0.592 GOOD_EDGE
#   
#   Source D (Twitter finance influencer):
#     SPF=T4, SSD=0.80, discount=0.68
#     CE=0.80 -> CE_adjusted=0.544 GOOD_EDGE
#   
#   Source E (quiet fund manager note at T2):
#     SPF=T2, SSD=0.15, discount=0.94
#     CE=0.80 -> CE_adjusted=0.752
#     NOTE: Source E exceeds Source B despite same SPF tier — 
#     SSD provides sub-tier sorting within SPF.
#
# PORTFOLIO RETROSPECTIVES:
#   RTX Day 3:
#     Sources: DoD filings, specialist defense analyst notes, geopolitics
#     SSD_score = 0.25 (mixed tending to operator)
#     signal_discount = 0.90 (10% discount)
#     CE_raw = 0.834 -> CE_adjusted = 0.751 -> STRONG_EDGE preserved
#     +3.90% WIN validated.
#   
#   CVX Day 80 (CHAOS_ENTRY):
#     Sources: war/oil pundit commentary, financial influencer tweets,
#              media-regular analyst appearances
#     SSD_score = 0.70 (performer-to-theatrical)
#     signal_discount = 0.72 (28% discount)
#     CE_raw = 0.040 -> CE_adjusted = 0.029 (already LEAVE-tier)
#     SSD exposes that source-layer performative-density contributed to
#     the CVX thesis distortion that led to CHAOS_ENTRY.
#   
#   GLD current:
#     Sources: inflation data, gold-miner earnings, institutional research
#     SSD_score = 0.35 (mixed)
#     signal_discount = 0.86 (14% discount)
#     CE_raw = 0.656 -> CE_adjusted = 0.564 -> GOOD_EDGE preserved
#     QUARTER_UNIT STAGGER confirmed.
#
# THE LOW-SIGNALING LAW:
#   Not every loud source is wrong; not every quiet source is right.
#   But performative-signaling density correlates with signal distortion.
#   SSD is the source-level adjustment the pipeline was missing between
#   SPF (reliability tier) and NSD (content assessment).

SSD_OPERATOR_THRESHOLD    = 0.25
SSD_MIXED_THRESHOLD       = 0.50
SSD_PERFORMER_THRESHOLD   = 0.75
# Above SSD_PERFORMER_THRESHOLD = THEATRICAL_STYLE

SSD_MAX_DISCOUNT_WEIGHT   = 0.40  # maximum discount is 40%

def classify_ssd_tier(ssd_score: float) -> str:
    if ssd_score < SSD_OPERATOR_THRESHOLD:    return 'OPERATOR_STYLE'
    elif ssd_score < SSD_MIXED_THRESHOLD:     return 'MIXED_STYLE'
    elif ssd_score < SSD_PERFORMER_THRESHOLD: return 'PERFORMER_STYLE'
    else:                                     return 'THEATRICAL_STYLE'

def compute_ssd_discount(ssd_score: float) -> float:
    discount_factor = 1.0 - (max(0.0, min(1.0, ssd_score)) * SSD_MAX_DISCOUNT_WEIGHT)
    return round(discount_factor, 4)

def compute_ssd(promotion_density: float,
                certainty_inflation: float,
                appearance_cadence: float,
                title_prefix_usage: float,
                validation_dependence: float,
                ce_raw: float = None,
                source_name: str = None) -> dict:
    def clamp(v): return max(0.0, min(1.0, v))
    c1 = clamp(promotion_density)
    c2 = clamp(certainty_inflation)
    c3 = clamp(appearance_cadence)
    c4 = clamp(title_prefix_usage)
    c5 = clamp(validation_dependence)
    ssd_score      = round((c1 + c2 + c3 + c4 + c5) / 5, 4)
    tier           = classify_ssd_tier(ssd_score)
    signal_discount = compute_ssd_discount(ssd_score)
    discount_pct    = round((1.0 - signal_discount) * 100, 1)
    result = {
        'source_name':      source_name or 'unnamed',
        'ssd_score':        ssd_score,
        'ssd_tier':         tier,
        'components': {
            'promotion_density':     c1,
            'certainty_inflation':   c2,
            'appearance_cadence':    c3,
            'title_prefix_usage':    c4,
            'validation_dependence': c5,
        },
        'signal_discount_factor': signal_discount,
        'discount_pct':           discount_pct,
        'note': (
            f'{tier}: SSD={ssd_score:.3f}, '
            f'discount={discount_pct:.1f}%, '
            f'signal weight={signal_discount:.3f}'
        ),
    }
    if ce_raw is not None:
        result['ce_raw']             = ce_raw
        result['ce_source_adjusted'] = round(ce_raw * signal_discount, 3)
    return result

def combine_ssd_with_spf(ssd_result: dict, spf_tier: str) -> dict:
    combined = dict(ssd_result)
    combined['spf_tier']     = spf_tier
    combined['spf_ssd_note'] = (
        f'{spf_tier}/{ssd_result[\"ssd_tier\"]}: source is {spf_tier}-tier '
        f'{ssd_result[\"ssd_tier\"].lower()}. SSD provides sub-tier weight.'
    )
    return combined
