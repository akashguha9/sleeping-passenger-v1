# EXTERNAL_TOOL_INTEGRATION_LAYER (ETIL)
# Module: S9 — Tooling / Ingestion
# Added: April 17 2026
# Source: KeygraphHQ/shannon ingestion session
#
# Standardises how external tool outputs are normalised into typed signal
# structs before SNC routing. Shannon's architecture revealed this gap:
# before routing (SNC), correction (SDI), or purity scoring (SPF),
# there needs to be a schema contract for what each tool produces.
#
# Shannon analogy:
#   Nmap -> typed attack_surface struct -> feeds browser agent
#   Pipeline needs: Polymarket -> typed signal_struct -> feeds SNC
#
# ETIL defines per tool:
#   output_schema:         TypedDict of standardised fields
#   snc_pre_classification: SNC node_type (ANCHOR/TRIGGER/SYSTEM/DYLAN/DECOY)
#   reliability_prior:     float 0-1 (SPF equivalent for tools)
#   freshness_decay:       float (how fast output goes stale, per hour)
#
# SNC pre-classification routing table:
#   Kalshi/Polymarket     -> ANCHOR  (reference frame, high liquidity, odds-based)
#   feedparser/PRAW       -> SYSTEM or DECOY (narrative baseline or noise, SBS-dependent)
#   FinBERT               -> DYLAN   (direction mismatch detection input)
#   Grok/X API            -> DYLAN or SYSTEM (SOURCE_BUBBLE_SCORE determines which)
#   newspaper3k           -> SYSTEM  (news baseline, recurring)
#   KeyBERT               -> ANCHOR  (keyword extraction for thesis clustering)
#   rapidfuzz             -> BRIDGE  (cross-cluster entity matching)
#
# Shannon source: https://github.com/KeygraphHQ/shannon
# Shannon benchmark: 96.15% success rate on hint-free, source-aware XBOW benchmark
# Shannon uses: Nmap, Subfinder, WhatWeb, Schemathesis, browser automation
# Shannon engine: Claude Code (ANTHROPIC_API_KEY) — same as this pipeline's S9 layer
#
# ETIL is the first thing to implement in S9 Phase 1 (May 13 2026):
# Define schemas before connecting tools.
# Without ETIL, S9 tools produce raw output with no standardised path
# into the signal processing chain (SNC -> SDI -> CE).

from typing import TypedDict, Literal, Optional
from datetime import datetime

SNCNodeType = Literal['SYSTEM', 'DYLAN', 'TRIGGER', 'ANCHOR', 'BRIDGE', 'DECOY', 'TERMINAL']

class ETILSignal(TypedDict):
    source:              str           # tool name
    signal_type:         SNCNodeType   # pre-classification for SNC
    content:             dict          # standardised schema for this tool
    reliability_prior:   float         # 0.0 - 1.0
    timestamp:           str           # ISO 8601
    freshness_remaining: float         # 0.0 - 1.0 (decays over time)
    raw_output:          Optional[dict] # original tool output, preserved for audit

TOOL_SCHEMAS = {
    'kalshi': {
        'snc_pre_classification': 'ANCHOR',
        'reliability_prior':      0.90,
        'freshness_decay_per_hr': 0.15,  # odds stale after ~7 hours without update
        'output_fields': ['market_id', 'title', 'yes_price', 'no_price', 'volume', 'close_time'],
    },
    'polymarket': {
        'snc_pre_classification': 'ANCHOR',
        'reliability_prior':      0.88,
        'freshness_decay_per_hr': 0.15,
        'output_fields': ['condition_id', 'question', 'outcome_prices', 'volume', 'end_date'],
    },
    'feedparser': {
        'snc_pre_classification': 'SYSTEM',  # upgraded to DYLAN if EDS triggers
        'reliability_prior':      0.60,
        'freshness_decay_per_hr': 0.30,
        'output_fields': ['title', 'summary', 'published', 'source', 'link'],
    },
    'praw_reddit': {
        'snc_pre_classification': 'SYSTEM',  # or DECOY if SOURCE_BUBBLE_SCORE HIGH
        'reliability_prior':      0.45,
        'freshness_decay_per_hr': 0.50,
        'output_fields': ['subreddit', 'title', 'score', 'num_comments', 'created_utc'],
    },
    'finbert': {
        'snc_pre_classification': 'DYLAN',
        'reliability_prior':      0.75,
        'freshness_decay_per_hr': 0.20,
        'output_fields': ['text', 'sentiment', 'confidence', 'label'],
    },
    'grok_x': {
        'snc_pre_classification': 'DYLAN',  # or SYSTEM if narrative temperature LOW
        'reliability_prior':      0.70,
        'freshness_decay_per_hr': 0.40,
        'output_fields': ['tweet_id', 'text', 'author', 'created_at', 'engagement'],
    },
    'newspaper3k': {
        'snc_pre_classification': 'SYSTEM',
        'reliability_prior':      0.65,
        'freshness_decay_per_hr': 0.25,
        'output_fields': ['title', 'text', 'authors', 'publish_date', 'source_url'],
    },
    'keybert': {
        'snc_pre_classification': 'ANCHOR',
        'reliability_prior':      0.80,
        'freshness_decay_per_hr': 0.10,
        'output_fields': ['keywords', 'scores', 'source_text'],
    },
    'rapidfuzz': {
        'snc_pre_classification': 'BRIDGE',
        'reliability_prior':      0.85,
        'freshness_decay_per_hr': 0.05,
        'output_fields': ['query', 'match', 'score', 'match_type'],
    },
}

def normalise_tool_output(tool_name: str, raw_output: dict,
                           timestamp: Optional[str] = None) -> ETILSignal:
    if tool_name not in TOOL_SCHEMAS:
        raise ValueError(f'Unknown tool: {tool_name}. Add to TOOL_SCHEMAS first.')
    schema   = TOOL_SCHEMAS[tool_name]
    ts       = timestamp or datetime.utcnow().isoformat()
    content  = {k: raw_output.get(k) for k in schema['output_fields']}
    return ETILSignal(
        source               = tool_name,
        signal_type          = schema['snc_pre_classification'],
        content              = content,
        reliability_prior    = schema['reliability_prior'],
        timestamp            = ts,
        freshness_remaining  = 1.0,  # decays via freshness_decay_per_hr over time
        raw_output           = raw_output,
    )

def compute_freshness(etil_signal: ETILSignal, hours_elapsed: float) -> float:
    tool_name = etil_signal['source']
    if tool_name not in TOOL_SCHEMAS:
        return 0.5
    decay_rate = TOOL_SCHEMAS[tool_name]['freshness_decay_per_hr']
    return max(0.0, 1.0 - (decay_rate * hours_elapsed))

def etil_to_snc_input(etil_signal: ETILSignal, hours_elapsed: float = 0.0) -> dict:
    freshness = compute_freshness(etil_signal, hours_elapsed)
    effective_reliability = etil_signal['reliability_prior'] * freshness
    return {
        'node_type':             etil_signal['signal_type'],
        'source':                etil_signal['source'],
        'content':               etil_signal['content'],
        'effective_reliability': round(effective_reliability, 3),
        'freshness':             round(freshness, 3),
        'timestamp':             etil_signal['timestamp'],
        'ready_for_snc':         effective_reliability > 0.30,
    }
