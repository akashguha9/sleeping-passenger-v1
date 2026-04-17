# NARRATIVE_DRIFT_MONITOR (NDM)
# Module: S5 / CAL
# Added: April 17 2026
# Source: Tarot / Barnum / illusion-pipeline session
#
# Continuous rolling tracker of whether the pipeline is drifting from
# signal-first to narrative-first approval behaviour.
#
# NDM_drift = narrative_confidence_avg - signal_strength_avg (rolling 30-day window)
#
# The 'model becomes the tarot reader without noticing' failure mode:
# The pipeline incrementally drifts toward approving theses because they are
# coherent stories rather than because they have strong evidential support.
# No single event triggers ZPD, but each marginal approval tilts the ratio.
#
# NDM is upstream of ZPD:
#   ZPD: detects multi-session repetition of same failed cluster (behavioural)
#   NDM: detects pipeline approving on narrative not signal (epistemic)
#   NDM fires BEFORE the cage forms that ZPD later detects.
#
# NDM is the rolling aggregate of NII over time:
#   NII: instantaneous inflation ratio at point of signal receipt
#   NDM: 30-day rolling average of approval quality metrics
#
# NDM_states:
#   GROUNDED:        NDM_drift < 0.05  -> signal-first, standard operation
#   WATCH:           NDM_drift 0.05-0.15 -> slight narrative creep, monitor
#   DRIFTING:        NDM_drift 0.15-0.30 -> narrative confidence outpacing signal
#                    -> apply 10% CE discount to ALL new entries pending review
#   NARRATIVE_FIRST: NDM_drift > 0.30 -> pipeline has become the tarot reader
#                    -> FULL_AUDIT_REQUIRED: review last 10 entries
#                    -> Block all new entries until NDM_drift < 0.10
#
# Supplementary warning flags:
#   falsifiability_rate < 0.60 -> FALSIFIABILITY_WARNING (too many elastic theses)
#   nii_avg > 3.0             -> NII_INFLATION_WARNING (narratives running inflated)
#
# CVX cluster retrospective:
#   After ZIM + CVX entry: war narrative still felt certain (0.65).
#   CE_corrected low (0.35). NDM_drift = 0.30 -> DRIFTING -> FULL_AUDIT
#   -> block CVX, XOM, USO. 3 of 6 losses caught before ZPD CAGE_FLAG.
#   NDM upstream catch prevented ZPD from needing to fire.
#
# RTX: HWE COMMITTED, CE_corrected high, NII=1.2. NDM_drift approx 0. GROUNDED. WIN.
# GLD: WMBRL=0.78, EDS CONFIRMING, HWE COMMITTED. NDM_drift near zero. WIN.
#
# The deepest law encoded by NDM:
#   Illusion = Narrative without consequence
#   Edge = Signal tested by consequence
# NDM enforces that the pipeline never becomes the former.

from collections import deque
from typing import Optional

NDM_GROUNDED_THRESHOLD       = 0.05
NDM_WATCH_THRESHOLD          = 0.15
NDM_DRIFTING_THRESHOLD       = 0.30
NDM_CLEAR_THRESHOLD          = 0.10
NDM_FALSIFIABILITY_WARNING   = 0.60
NDM_NII_WARNING              = 3.0
NDM_WINDOW_DAYS              = 30
NDM_DISCOUNT_DRIFTING        = 0.90   # 10% CE discount when DRIFTING
NDM_AUDIT_LOOKBACK           = 10     # review last N entries on FULL_AUDIT

class NDMEntry:
    def __init__(self, narrative_confidence: float, signal_strength: float,
                 is_falsifiable: bool, nii_score: float, days_ago: int = 0):
        self.narrative_confidence = narrative_confidence
        self.signal_strength      = signal_strength
        self.is_falsifiable       = is_falsifiable
        self.nii_score            = nii_score
        self.days_ago             = days_ago

def compute_ndm_drift(entry_window: list) -> dict:
    if not entry_window:
        return {'ndm_drift': 0.0, 'falsifiability_rate': 1.0, 'nii_avg': 1.0}
    n = len(entry_window)
    narrative_conf_avg = sum(e.narrative_confidence for e in entry_window) / n
    signal_strength_avg= sum(e.signal_strength      for e in entry_window) / n
    falsifiability_rate= sum(1 for e in entry_window if e.is_falsifiable) / n
    nii_avg            = sum(e.nii_score             for e in entry_window) / n
    ndm_drift = narrative_conf_avg - signal_strength_avg
    return {
        'ndm_drift':           round(ndm_drift, 3),
        'narrative_conf_avg':  round(narrative_conf_avg, 3),
        'signal_strength_avg': round(signal_strength_avg, 3),
        'falsifiability_rate': round(falsifiability_rate, 3),
        'nii_avg':             round(nii_avg, 2),
        'n_entries':           n,
    }

def classify_ndm_state(ndm_metrics: dict) -> str:
    drift = ndm_metrics['ndm_drift']
    if drift >= NDM_DRIFTING_THRESHOLD:
        return 'NARRATIVE_FIRST'
    elif drift >= NDM_WATCH_THRESHOLD:
        return 'DRIFTING'
    elif drift >= NDM_GROUNDED_THRESHOLD:
        return 'WATCH'
    else:
        return 'GROUNDED'

def ndm_gate(ndm_state: str, ndm_metrics: dict, ce_raw: float) -> dict:
    warnings = []
    if ndm_metrics['falsifiability_rate'] < NDM_FALSIFIABILITY_WARNING:
        warnings.append('FALSIFIABILITY_WARNING')
    if ndm_metrics['nii_avg'] > NDM_NII_WARNING:
        warnings.append('NII_INFLATION_WARNING')
    if ndm_state == 'NARRATIVE_FIRST':
        return {
            'action':       'FULL_AUDIT_REQUIRED',
            'ce_multiplier': 0.0,   # block all entries
            'ce_adjusted':  0.0,
            'message':      f'Pipeline narrative-first. Drift={ndm_metrics["ndm_drift"]:.2f}. Audit last {NDM_AUDIT_LOOKBACK} entries.',
            'warnings':     warnings,
        }
    elif ndm_state == 'DRIFTING':
        return {
            'action':       'APPLY_DRIFT_DISCOUNT',
            'ce_multiplier': NDM_DISCOUNT_DRIFTING,
            'ce_adjusted':  round(ce_raw * NDM_DISCOUNT_DRIFTING, 3),
            'message':      f'Narrative creep detected. Drift={ndm_metrics["ndm_drift"]:.2f}. 10% CE penalty.',
            'warnings':     warnings,
        }
    elif ndm_state == 'WATCH':
        return {
            'action':       'MONITOR',
            'ce_multiplier': 1.0,
            'ce_adjusted':  ce_raw,
            'message':      f'Slight narrative creep. Drift={ndm_metrics["ndm_drift"]:.2f}. Watch falsifiability_rate.',
            'warnings':     warnings,
        }
    else:
        return {
            'action':       'CLEAR',
            'ce_multiplier': 1.0,
            'ce_adjusted':  ce_raw,
            'message':      'Pipeline grounded. Signal-first approval confirmed.',
            'warnings':     warnings,
        }

def ndm_full_check(entry_window: list, ce_raw: float) -> dict:
    metrics    = compute_ndm_drift(entry_window)
    state      = classify_ndm_state(metrics)
    gate       = ndm_gate(state, metrics, ce_raw)
    return {
        'ndm_state':  state,
        'ndm_drift':  metrics['ndm_drift'],
        'metrics':    metrics,
        'gate':       gate,
    }
