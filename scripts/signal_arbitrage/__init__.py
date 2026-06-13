"""signal_arbitrage — Fable 5 upstream-to-downstream signal-arbitrage layer.

A timed signal-arbitrage pipeline that scores whether a narrative has enough
vitality to become financial reality *before the market notices*.  The layers,
in pipeline order:

    1. platform_ecology    — classify each platform as its own signal ecology
    2. tokenizer           — decompose raw text into typed, dense tokens
    3. synthetic_liquidity — detect bot/fake engagement contamination
    4. blind_validation    — would it survive with the story removed? (purity cap)
    5. binary_truth        — force claims into a 1/0 genome
    6. vitality_funnel     — transfer-gated 11-stage survival
    7. timing              — threshold / ante / half-life state machine
    8. interpretation_gap  — beholder lenses + mispricing
    9. provenance          — hash-chained verifiable memory + freshness
   10. opportunity         — multiplicatively reality-gated final decision

Everything is pure, deterministic, dependency-free, ADVISORY_ONLY.  No broker
calls; real-money execution is PROHIBITED by design.
"""
from __future__ import annotations

from .platform_ecology import classify_platform, platform_ecology_score, PlatformEcology
from .tokenizer import extract_tokens, semantic_density_score, TokenizationResult, Token
from .synthetic_liquidity import detect_synthetic_liquidity, ContaminationResult
from .blind_validation import validate_blind, BlindValidationResult
from .binary_truth import build_truth_ledger, BinaryTruthResult, TruthBit
from .vitality_funnel import compute_vitality, VitalityResult, STAGES
from .timing import classify_timing, TimingResult
from .interpretation_gap import interpret_beholders, InterpretationResult
from .provenance import ProvenanceLedger, freshness_score
from .opportunity import SignalDossier, score_opportunity
from .ceiling import analyze_signal, legacy_baseline_score, expand_ceiling
from .strategist import strategize_signal
from .mythos import MythosObservation, run_mythos
from .mythos_ledger import MythosLedgerStore, MythosClaim
from .mythos_pipeline import run_pipeline
from .mythos_aggregator import (
    aggregate_cluster, run_aggregated_pipeline, group_observations,
)
from .mythos_corpus import (
    CalibrationRecord, build_calibration_record, backfill_calibration_records,
    run_real_calibration, real_corpus_backfill_readiness,
)
from .mythos_capture import (
    capture_decision_snapshot, resolve_decision_outcome, append_decision_snapshot,
    decision_id_for,
)
from .advisory_runner import (
    run_advisory_with_capture, resolve_capture_config, CaptureConfig,
    check_decision_capture_corpus,
)

__all__ = [
    "classify_platform", "platform_ecology_score", "PlatformEcology",
    "extract_tokens", "semantic_density_score", "TokenizationResult", "Token",
    "detect_synthetic_liquidity", "ContaminationResult",
    "validate_blind", "BlindValidationResult",
    "build_truth_ledger", "BinaryTruthResult", "TruthBit",
    "compute_vitality", "VitalityResult", "STAGES",
    "classify_timing", "TimingResult",
    "interpret_beholders", "InterpretationResult",
    "ProvenanceLedger", "freshness_score",
    "SignalDossier", "score_opportunity",
    "analyze_signal", "legacy_baseline_score", "expand_ceiling",
    "strategize_signal",
    "MythosObservation", "run_mythos", "MythosLedgerStore", "MythosClaim",
    "run_pipeline",
    "aggregate_cluster", "run_aggregated_pipeline", "group_observations",
    "CalibrationRecord", "build_calibration_record", "backfill_calibration_records",
    "run_real_calibration", "real_corpus_backfill_readiness",
    "capture_decision_snapshot", "resolve_decision_outcome",
    "append_decision_snapshot", "decision_id_for",
    "run_advisory_with_capture", "resolve_capture_config", "CaptureConfig",
    "check_decision_capture_corpus",
]
