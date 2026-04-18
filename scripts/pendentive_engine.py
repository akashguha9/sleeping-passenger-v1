# PENDENTIVE_ENGINE (PE)
# Module: S0 — Pre-routing coherence layer
# Added: April 17 2026
# Source: Hagia Sophia / Mehmed / Constantinople session
#
# Converts heterogeneous signal domains onto a common 0-1 scoring surface
# BEFORE SNC classification and BEFORE SBE synthesis.
#
# The pendentive insight:
#   The dome (SBE) doesn't sit on the square (heterogeneous signals) directly.
#   It sits on the pendentive (PE coherent 0-1 surface).
#   Without PE, SBE's Signal_Density S compares probabilities to Z-scores
#   to text confidences — incommensurable.
#   With PE, all inputs are on the same spherical scoring surface.
#
# Pipeline position:
#   RAW_SIGNALS (incommensurable) -> [SF noise gate] -> [PE 0-1 surface]
#   -> [SNC route] -> [SDI correct] -> [SBE B = S-(E+H)]
#
# PE is distinct from:
#   ETIL: normalises per-tool output to TypedDict schemas (not 0-1 surface)
#   SDI:  corrects CE post-routing (operates on thesis, not raw domain signals)
#   SBE:  synthesises all mechanisms into B score (PE is its prerequisite)
#   PE:   maps domain-native incommensurable values onto 0-1 common surface
#
# 5 signal domains with conversion functions:
#
# 1. PREDICTION_MARKET (Kalshi, Polymarket):
#    coherent = probability (already 0-1)
#    confidence_weight = liquidity_score × source_reliability
#    Example: P(Iran strike) = 0.72 -> coherent = 0.72
#
# 2. NLP_SENTIMENT (FinBERT, Grok/X):
#    coherent = (sentiment_score + 1) / 2    maps [-1,+1] -> [0,1]
#    where: positive=+1 -> 1.0, negative=-1 -> 0.0, neutral=0 -> 0.5
#    confidence_weight = model_confidence × SPF_source_tier
#    Example: FinBERT +0.84 -> coherent = (0.84+1)/2 = 0.92
#
# 3. PRICE_ACTION (price feeds, velocity data):
#    coherent = sigmoid(Z_score_normalised_velocity)
#    where: Z = (current_velocity - mean_velocity) / std_velocity
#    sigmoid(x) = 1 / (1 + exp(-x))
#    confidence_weight = volume_ratio × time_window_freshness
#    Example: price velocity Z = +1.8 -> sigmoid(1.8) = 0.858
#
# 4. TEXT_EVENT (Reuters, Bloomberg headlines, filings):
#    coherent = NLP_relevance × entity_confidence × (CIS2_score / 10)
#    confidence_weight = SPF_source_tier (T1=0.9, T2=0.7, T3=0.5, T4=0.3)
#    Example: high relevance filing: 0.85 × 0.90 × 0.9 = 0.69
#
# 5. FLOW (whale activity, options flow, institutional):
#    coherent = sigmoid(whale_z_score)
#    where whale_z = (current_flow - mean_flow) / std_flow
#    confidence_weight = options_OI_ratio × time_to_catalyst_factor
#    Example: whale_z = +2.1 -> sigmoid(2.1) = 0.891
#
# Portfolio retrospectives:
#   RTX Day 3:
#     Polymarket P(defence) = 0.71 -> coherent = 0.71 (weight 0.85)
#     FinBERT +0.82             -> coherent = 0.91 (weight 0.76)
#     Price velocity Z = +1.8   -> coherent = 0.86 (weight 0.80)
#     Reuters filing SPF T1     -> coherent = 0.69 (weight 0.90)
#     PE weighted avg           -> S_input = 0.80
#     SBE B = 0.80 - 0.35 = +0.45 STRONG_FLOAT WIN
#
#   CVX Day 80:
#     Polymarket P(Iran) declining = 0.38 -> coherent = 0.38 (weight 0.72)
#     FinBERT -0.55 (declining)   -> coherent = 0.225 (weight 0.60)
#     Price velocity Z = -0.8     -> coherent = 0.31 (weight 0.55)
#     WMBRL base_rate             -> coherent = 0.08 (as proxy, weight 0.80)
#     PE weighted avg             -> S_input = 0.30
#     SBE B = 0.30 - 1.05 = -0.75 TRAP REJECTED
#
# Hagia Sophia architecture correspondence:
#   Square base = messy heterogeneous raw signals
#   Pendentive = PE coherent 0-1 surface
#   Dome = SBE unified B score
#   The dome (SBE) sits on the pendentive (PE), not directly on the square (raw signals)

import math

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def pe_prediction_market(probability: float, liquidity_score: float = 0.7,
                          source_reliability: float = 0.85) -> dict:
    coherent = max(0.0, min(1.0, probability))
    confidence = liquidity_score * source_reliability
    return {
        'domain': 'PREDICTION_MARKET',
        'coherent_score': round(coherent, 3),
        'confidence_weight': round(confidence, 3),
        'raw_value': probability,
    }

def pe_nlp_sentiment(sentiment_score: float, model_confidence: float,
                      spf_source_tier: float = 0.7) -> dict:
    coherent = max(0.0, min(1.0, (sentiment_score + 1) / 2))
    confidence = model_confidence * spf_source_tier
    return {
        'domain': 'NLP_SENTIMENT',
        'coherent_score': round(coherent, 3),
        'confidence_weight': round(confidence, 3),
        'raw_value': sentiment_score,
    }

def pe_price_action(current_velocity: float, mean_velocity: float,
                     std_velocity: float, volume_ratio: float = 1.0,
                     freshness_factor: float = 1.0) -> dict:
    if std_velocity <= 0:
        z_score = 0.0
    else:
        z_score = (current_velocity - mean_velocity) / std_velocity
    coherent = sigmoid(z_score)
    confidence = volume_ratio * freshness_factor
    return {
        'domain': 'PRICE_ACTION',
        'coherent_score': round(coherent, 3),
        'confidence_weight': round(min(confidence, 1.0), 3),
        'raw_value': {'velocity': current_velocity, 'z_score': round(z_score, 2)},
    }

def pe_text_event(nlp_relevance: float, entity_confidence: float,
                   cis2_score: float, spf_tier: float = 0.7) -> dict:
    coherent = max(0.0, min(1.0, nlp_relevance * entity_confidence * (cis2_score / 10.0)))
    confidence = spf_tier
    return {
        'domain': 'TEXT_EVENT',
        'coherent_score': round(coherent, 3),
        'confidence_weight': round(confidence, 3),
        'raw_value': {'relevance': nlp_relevance, 'entity_conf': entity_confidence},
    }

def pe_flow(current_flow: float, mean_flow: float, std_flow: float,
             options_oi_ratio: float = 1.0, catalyst_time_factor: float = 1.0) -> dict:
    if std_flow <= 0:
        whale_z = 0.0
    else:
        whale_z = (current_flow - mean_flow) / std_flow
    coherent = sigmoid(whale_z)
    confidence = min(options_oi_ratio, 1.0) * min(catalyst_time_factor, 1.0)
    return {
        'domain': 'FLOW',
        'coherent_score': round(coherent, 3),
        'confidence_weight': round(confidence, 3),
        'raw_value': {'flow': current_flow, 'whale_z': round(whale_z, 2)},
    }

def pe_weighted_average(domain_outputs: list) -> dict:
    if not domain_outputs:
        return {'pe_coherent_avg': 0.5, 'pe_confidence_avg': 0.5, 'domain_count': 0}
    total_weight = sum(d['confidence_weight'] for d in domain_outputs)
    if total_weight <= 0:
        return {'pe_coherent_avg': 0.5, 'pe_confidence_avg': 0.5, 'domain_count': len(domain_outputs)}
    weighted_score = sum(d['coherent_score'] * d['confidence_weight'] for d in domain_outputs)
    pe_avg = weighted_score / total_weight
    conf_avg = total_weight / len(domain_outputs)
    return {
        'pe_coherent_avg':  round(pe_avg, 3),
        'pe_confidence_avg':round(min(conf_avg, 1.0), 3),
        'domain_count':     len(domain_outputs),
        'domains_present':  [d['domain'] for d in domain_outputs],
    }

def pe_full_pipeline(domain_inputs: list) -> dict:
    outputs   = [d for d in domain_inputs if d is not None]
    result    = pe_weighted_average(outputs)
    is_coherent = (result['pe_coherent_avg'] is not None and
                   result['pe_confidence_avg'] >= 0.3 and
                   result['domain_count'] >= 1)
    return {
        **result,
        'is_coherent':    is_coherent,
        'ready_for_snc':  is_coherent,
        'sbe_s_input':    result['pe_coherent_avg'] if is_coherent else None,
        'note':           'PE coherent surface ready for SBE S computation' if is_coherent
                          else 'Insufficient domain coverage or confidence',
    }
