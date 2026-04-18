# CONSENSUS_FORMATION_DETECTOR (CFD)
# Module: S0 / S3A — Upstream corpus scanner (most upstream mechanism)
# Added: April 17 2026
# Source: Code words / emojis / slang / colloquial / consensus session
#
# Measures the RATE OF CONSENSUS FORMATION across the raw narrative corpus
# BEFORE any signal enters the SF → PE → SNC → SBE pipeline.
#
# CS = PC × RS × CC × MS
#   PC (Phrase Convergence):     are different people using the same words?
#   RS (Repetition Sync):        are independent sources repeating in same window?
#   CC (Context Collapse):       how many distinct communities hitting the theme?
#   MS (Meaning Stability):      is the interpretation consistent across source types?
#
# PRIMARY TRIGGER: dCS/dt — the slope of consensus, not the absolute level.
# The best trades live between EMERGING and CONVERGING, not at LOCKED.
#
# CFD states:
#   FORMING:    CS < 0.15  -> nascent, no consensus -> note only
#   EMERGING:   CS 0.15-0.40 -> early consensus -> watchlist, monitor dCS/dt
#   CONVERGING: CS 0.40-0.65 -> strong consensus building -> feed into SF -> PE -> SBE
#   LOCKED:     CS > 0.65  -> consensus complete -> route to SLT EXHAUSTION check only
#
# CFD is UPSTREAM of NIS, SBS, and SSSC:
#   NIS: tracks momentum WITHIN an active thesis (fires AFTER pipeline entry)
#   SBS: scores echo_density at NARRATIVE CLUSTER level (fires at cluster scoring)
#   SSSC: detects signal CONFLUENCE within the pipeline (fires on processed signals)
#   CFD: fires on RAW CORPUS before processing — CREATES the signal NIS will track
#
# Portfolio retrospectives:
#   RTX Day 3:
#     2-3 days before entry: Polymarket + defence analysts + news all convergening.
#     PC rising: same "defence procurement escalation" language across sources.
#     CC rising: finance + geopolitical + news contexts all hitting theme.
#     MS rising: consistent bullish direction across all source types.
#     dCS/dt HIGH -> CFD CONVERGING -> feed into SF -> PE -> SBE B=+0.45 WIN.
#
#   CVX Day 80:
#     All sources already saying same thing. CS high but dCS/dt near zero.
#     Dictionary stage equivalent: consensus complete = EXHAUSTION.
#     CFD LOCKED -> route to SLT EXHAUSTION check -> block entry.
#     -8.82% avoided. CFD is the earliest saturation signal.
#
# Pipeline position (most upstream):
#   RAW_CORPUS -> [CFD] -> FORMING/EMERGING/CONVERGING/LOCKED
#   -> if CONVERGING: feed theme into [SF] -> [PE] -> [SNC] -> SBE
#   -> if LOCKED: route to SLT CROWDING/EXHAUSTION check only
#
# The consensus law:
#   The slope of consensus is the trade, not the level.
#   Dictionary = LOCKED = late. CONVERGING = the window.
#   'Real signal is the moment just before everyone agrees.'
#
# Component scoring (each 0-1):
#   PC: 1 - semantic_variance(top_phrases_t, top_phrases_{t-1}) across source clusters
#   RS: temporal_autocorrelation_across_sources(theme, window=24h)
#   CC: unique_context_count / max_context_count
#   MS: 1 - interpretation_variance across source types
#
# dCS/dt trigger threshold (heuristic until calibrated on T=10+):
#   TRIGGER_THRESHOLD = 0.08 per scan window (12-24h)
#   i.e. CS rising by 0.08+ in one window = EMERGING -> action

CFD_FORMING_THRESHOLD    = 0.15
CFD_EMERGING_THRESHOLD   = 0.40
CFD_CONVERGING_THRESHOLD = 0.65
CFD_DCDT_TRIGGER         = 0.08   # minimum slope to trigger feed into SF
CFD_LOCKED_DCDT_EXIT     = 0.00   # LOCKED with zero/negative slope = EXHAUSTION

def compute_cs(pc: float, rs: float, cc: float, ms: float) -> float:
    return max(0.0, min(1.0, pc * rs * cc * ms))

def classify_cfd_state(cs: float) -> str:
    if cs >= CFD_CONVERGING_THRESHOLD:  return 'LOCKED'
    elif cs >= CFD_EMERGING_THRESHOLD:  return 'CONVERGING'
    elif cs >= CFD_FORMING_THRESHOLD:   return 'EMERGING'
    else:                               return 'FORMING'

def compute_dcdt(cs_current: float, cs_previous: float) -> float:
    return cs_current - cs_previous

def cfd_routing_decision(cfd_state: str, dcdt: float) -> dict:
    if cfd_state == 'LOCKED':
        if dcdt <= CFD_LOCKED_DCDT_EXIT:
            return {
                'action':     'ROUTE_TO_EXHAUSTION',
                'feed_to_sf': False,
                'note':       'LOCKED + flat/declining slope. SLT EXHAUSTION check. CVX Day 80 pattern.',
            }
        else:
            return {
                'action':     'WATCHLIST_ONLY',
                'feed_to_sf': False,
                'note':       'LOCKED but still rising. Do not enter. Monitor for saturation.',
            }
    elif cfd_state == 'CONVERGING':
        if dcdt >= CFD_DCDT_TRIGGER:
            return {
                'action':     'FEED_TO_SF',
                'feed_to_sf': True,
                'note':       'CONVERGING + rising slope. Primary trigger. Feed into SF -> PE -> SBE.',
            }
        else:
            return {
                'action':     'WATCHLIST',
                'feed_to_sf': False,
                'note':       'CONVERGING but slope slowing. Watch for acceleration.',
            }
    elif cfd_state == 'EMERGING':
        if dcdt >= CFD_DCDT_TRIGGER:
            return {
                'action':     'WATCHLIST_ALERT',
                'feed_to_sf': False,
                'note':       'EMERGING with rising slope. Add to watchlist. Monitor PC/RS/CC/MS.',
            }
        return {'action': 'NOTE_ONLY', 'feed_to_sf': False, 'note': 'EMERGING, slow slope.'}
    else:
        return {'action': 'IGNORE', 'feed_to_sf': False, 'note': 'FORMING. Too early.'}

def cfd_full_check(pc: float, rs: float, cc: float, ms: float,
                   pc_prev: float = None, rs_prev: float = None,
                   cc_prev: float = None, ms_prev: float = None) -> dict:
    cs = compute_cs(pc, rs, cc, ms)
    if all(v is not None for v in [pc_prev, rs_prev, cc_prev, ms_prev]):
        cs_prev = compute_cs(pc_prev, rs_prev, cc_prev, ms_prev)
        dcdt    = compute_dcdt(cs, cs_prev)
    else:
        cs_prev = None
        dcdt    = 0.0
    state    = classify_cfd_state(cs)
    routing  = cfd_routing_decision(state, dcdt)
    return {
        'cs':         round(cs, 3),
        'cs_prev':    round(cs_prev, 3) if cs_prev is not None else None,
        'dcdt':       round(dcdt, 3),
        'cfd_state':  state,
        'components': {'PC': round(pc,3), 'RS': round(rs,3),
                       'CC': round(cc,3), 'MS': round(ms,3)},
        'routing':    routing,
        'feed_to_sf': routing['feed_to_sf'],
    }
