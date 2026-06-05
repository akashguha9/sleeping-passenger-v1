"""Zip simulation corpus ingestion subsystem (SIMULATION_ONLY).

This package safely inspects a large local zip archive, classifies its
contents into dataset families, parses the useful families into structured
*simulation* records, and produces segmented before/after readiness scores
for the Sleeping Passenger advisory MVP.

Hard invariants (see :mod:`src.simulation_zip.labels`):

* Everything produced here is SIMULATION / TRAINING / BENCHMARK material.
* Nothing here executes trades, creates broker orders, or gives financial
  advice.  The subsystem is advisory-only and fail-closed: a missing,
  corrupted, oversized, or unsafe zip yields a BLOCKED report, never fake
  metrics.
* Chess PGNs, hackathon files, and scraped text are NOT market data.  Market
  metrics are only computed when the archive actually contains dated,
  tickered, priced, outcome-bearing rows above explicit minimum thresholds.
"""
from __future__ import annotations

from src.simulation_zip.labels import (
    SIMULATION_LABELS,
    Label,
)
from src.simulation_zip.safety import SafetyStatus, ZipSafetyValidator
from src.simulation_zip.scanner import ZipInventoryScanner, ZipManifestBuilder
from src.simulation_zip.classifier import DatasetClassifier, DatasetFamily
from src.simulation_zip.harness import (
    SimulationCorpusIndexer,
    ZipSimulationIngestionReport,
    run_zip_simulation,
)

__all__ = [
    "SIMULATION_LABELS",
    "Label",
    "SafetyStatus",
    "ZipSafetyValidator",
    "ZipInventoryScanner",
    "ZipManifestBuilder",
    "DatasetClassifier",
    "DatasetFamily",
    "SimulationCorpusIndexer",
    "ZipSimulationIngestionReport",
    "run_zip_simulation",
]
