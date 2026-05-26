"""Role-fit + absolute readiness scorecard for the local advisory MVP.

Kanté Role-Fit Sprint, Phase 1.

This module separates two questions that the older scorecard kept conflating:

1. **Absolute readiness** ``A_s`` — "How close is the segment to production /
   private beta / public SaaS maturity?"  Brutally honest; Public SaaS can
   stay at 1.5 forever and that is correct.

2. **Role-fit readiness** ``R_s`` — "Given this segment's intended role in
   *this* local-first MVP, is it performing that role at an elite level?"
   A refusal/safety segment that perfectly performs refusal earns a 10/10
   without scoring goals; a calibration gate earns a 10/10 by blocking
   false predictive claims even when N_real = 0.

Formulas
~~~~~~~~

* ``R_s        = 10 * Σ_i (w_i * p_i)``                with ``Σ_i w_i = 1``
* ``E_s        = min(1, evidence_items_present / evidence_items_required)``
* ``R_adj_s    = R_s * (0.7 + 0.3 * E_s) * C_s``
* ``OverallAbsolute = Σ_s W_abs_s * A_s / Σ_s W_abs_s``
* ``OverallRoleFit  = Σ_s W_role_s * R_adj_s * T_s / Σ_s W_role_s * T_s``

NOT_TARGETED segments (``T_s == 0``) are excluded from the OverallRoleFit
denominator entirely; their per-segment dashboard score is the string
``"NOT_TARGETED_THIS_YEAR"`` rather than a number.

Safety
~~~~~~
* Read-only.  Does not call brokers, does not execute, does not touch
  secrets, does not weaken any advisory stamp.
* Emits the canonical advisory-only stamps via
  :mod:`scripts.advisory_contract`.
* When the live ``runtime/release/calibration_report.json`` says
  ``predictive_claim_allowed = false`` (or the file is missing), the
  ``Scoring/model logic quality`` segment is held below its predictive
  ceiling regardless of what static weights would otherwise produce.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.advisory_contract import (  # noqa: E402
    AUDIT_ONLY_STORE,
    CANONICAL_STORE,
    advisory_safety_stamps,
)


DEFAULT_JSON_OUT = _REPO_ROOT / "runtime" / "release" / "segment_role_scorecard.json"
DEFAULT_MD_OUT = _REPO_ROOT / "docs" / "scorecards" / "SEGMENT_ROLE_SCORECARD.md"
DEFAULT_CALIBRATION_REPORT = _REPO_ROOT / "runtime" / "release" / "calibration_report.json"

CALIBRATION_N_MIN = 200
# Hard cap when neither calibration evidence nor the probability-snapshot
# pipeline has shipped.  Cleared only by:
#   * raising the cap to ``SCORING_MODEL_CEILING_PIPELINE_ONLY`` once
#     the probability pipeline lands; or
#   * unlocking calibration entirely once N_real ≥ N_min with usable
#     model_probability.
SCORING_MODEL_CEILING_NO_EVIDENCE = 5.8
# Cap when the probability-snapshot pipeline exists but no calibration
# pairs have landed yet.  Spec: "If N_real < 50: ScoringModelScore =
# min(6.1, 5.8 + 0.3 × ProbabilitySnapshotImplemented)".
SCORING_MODEL_CEILING_PIPELINE_ONLY = 6.1
ABSOLUTE_PUBLIC_SAAS_CEILING = 1.5
ABSOLUTE_PRIVATE_BETA_CEILING = 5.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    """One scoring criterion under a segment's role."""

    criterion: str
    weight: float
    performance: float
    evidence: tuple[str, ...] = ()
    blocker: str = ""


@dataclass
class Segment:
    """A scored segment with both absolute and role-fit lenses."""

    segment: str
    role_name: str
    role_description: str
    target_relevance: float        # T_s in [0, 1]
    absolute_score: float          # A_s in [0, 10]
    absolute_ceiling_reason: str   # why A_s cannot go higher
    confidence: float              # C_s in [0, 1]
    criteria: list[Criterion]
    blockers: list[str]
    next_action: str
    absolute_weight: float = 1.0   # W_abs_s
    role_weight: float = 1.0       # W_role_s

    # Derived values populated by `_finalise`.
    role_fit_score: float = 0.0
    evidence_completeness: float = 0.0
    confidence_adjusted_role_fit: float = 0.0
    not_targeted: bool = False

    def _validate(self) -> None:
        if not (0.0 <= self.target_relevance <= 1.0):
            raise ValueError(f"{self.segment}: target_relevance out of [0,1]")
        if not (0.0 <= self.absolute_score <= 10.0):
            raise ValueError(f"{self.segment}: absolute_score out of [0,10]")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"{self.segment}: confidence out of [0,1]")
        if self.criteria:
            total = sum(c.weight for c in self.criteria)
            if not math.isclose(total, 1.0, abs_tol=1e-6):
                raise ValueError(
                    f"{self.segment}: criterion weights sum to {total!r}, expected 1.0"
                )
            for c in self.criteria:
                if not (0.0 <= c.weight <= 1.0):
                    raise ValueError(f"{self.segment}/{c.criterion}: weight out of [0,1]")
                if not (0.0 <= c.performance <= 1.0):
                    raise ValueError(
                        f"{self.segment}/{c.criterion}: performance out of [0,1]"
                    )

    def _finalise(self, repo_root: Path) -> None:
        self._validate()
        # Role-fit score: R_s = 10 * Σ(w_i * p_i).
        if not self.criteria:
            self.role_fit_score = 0.0
        else:
            self.role_fit_score = round(
                10.0 * sum(c.weight * c.performance for c in self.criteria), 4
            )

        # Evidence completeness: per-criterion all-evidence-paths-present.
        if not self.criteria:
            self.evidence_completeness = 0.0
        else:
            satisfied = 0
            for c in self.criteria:
                paths = c.evidence
                if not paths:
                    # A criterion with no evidence path cannot contribute to E_s.
                    continue
                if all((repo_root / p).exists() for p in paths):
                    satisfied += 1
            self.evidence_completeness = round(satisfied / len(self.criteria), 4)

        self.not_targeted = self.target_relevance == 0.0

        # Confidence-adjusted role-fit: R_adj_s = R_s * (0.7 + 0.3*E_s) * C_s.
        self.confidence_adjusted_role_fit = round(
            self.role_fit_score
            * (0.7 + 0.3 * self.evidence_completeness)
            * self.confidence,
            4,
        )


# ---------------------------------------------------------------------------
# Segment definitions
# ---------------------------------------------------------------------------


def _segments(calibration_unlocked: bool) -> list[Segment]:
    """Return the canonical 41-segment list with role-fit criteria.

    ``calibration_unlocked`` reflects the live state of
    ``runtime/release/calibration_report.json``: when False (N_real < 200 or
    file missing), the "Scoring/model logic quality" segment is held below
    ``SCORING_MODEL_CEILING_NO_EVIDENCE`` regardless of nominal performance.
    """
    # Full Role-Uplift Sprint: when calibration remains locked but the
    # probability-snapshot pipeline has shipped, lift the Scoring/model
    # ceiling from 5.8 to 6.1.  This is intentionally below the spec's
    # 6.4 "infrastructure-only" ceiling because no calibration pairs
    # have landed yet; raising further is not earned.
    probability_pipeline_present = (
        _REPO_ROOT / "scripts" / "probability_snapshot.py"
    ).exists() and (
        _REPO_ROOT / "tests" / "test_probability_snapshot.py"
    ).exists()
    if calibration_unlocked:
        scoring_model_abs = 7.5
        scoring_predictive_p = 1.0
    elif probability_pipeline_present:
        scoring_model_abs = 6.1
        scoring_predictive_p = 0.0
    else:
        scoring_model_abs = SCORING_MODEL_CEILING_NO_EVIDENCE
        scoring_predictive_p = 0.0

    return [
        # 1 ---------------------------------------------------------------
        Segment(
            segment="Product clarity / customer understandability",
            role_name="Local-first advisory copilot pitch",
            role_description=(
                "Make the local-first, advisory-only nature obvious to anyone "
                "reading the README or first-run UI."
            ),
            target_relevance=1.0,
            absolute_score=8.5,
            absolute_ceiling_reason="Recorded demo + screenshots still missing.",
            confidence=0.9,
            criteria=[
                Criterion(
                    "README states ADVISORY_ONLY and local-first up front",
                    0.34,
                    1.0,
                    ("README.md", "docs/ADVISORY_DISCLOSURE.md"),
                ),
                Criterion(
                    "UI banner / badges reinforce no-execution posture",
                    0.33,
                    1.0,
                    (
                        "frontend/src/components/NoExecutionBanner.tsx",
                        "frontend/src/components/AdvisoryOnlyBadge.tsx",
                    ),
                ),
                Criterion(
                    "Final scorecard documents lens differences honestly",
                    0.33,
                    0.95,
                    ("docs/FINAL_SCORECARD.md",),
                ),
            ],
            blockers=["No recorded 5-minute demo or screenshot pack."],
            next_action="Record a 5-minute demo and pin it from README.",
        ),
        # 2 ---------------------------------------------------------------
        Segment(
            segment="Advisory-only safety integrity",
            role_name="Ball-winning defensive midfielder",
            role_description=(
                "Prevent execution drift: no broker SDKs, no order routes, "
                "advisory stamps everywhere, AI never granted execution."
            ),
            target_relevance=1.0,
            absolute_score=9.8,
            absolute_ceiling_reason=(
                "Capped at 9.8 until an external red-team confirms no drift."
            ),
            confidence=0.97,
            criteria=[
                Criterion(
                    "Advisory stamp property test passes on safe GETs",
                    0.30,
                    1.0,
                    ("tests/test_advisory_stamp_property.py",),
                ),
                Criterion(
                    "Forbidden execution-route test pins zero broker routes",
                    0.25,
                    1.0,
                    ("tests/test_api_server.py",),
                ),
                Criterion(
                    "advisory_contract.py is the single stamp source",
                    0.25,
                    1.0,
                    ("scripts/advisory_contract.py",),
                ),
                Criterion(
                    "ai_execution_count=0 and broker_api_called=false stamps",
                    0.20,
                    1.0,
                    ("runtime/release/release_gate_proof.json",),
                ),
            ],
            blockers=[],
            next_action="Schedule an external red-team review of advisory routes.",
        ),
        # 3 ---------------------------------------------------------------
        Segment(
            segment="Execution-lock integrity",
            role_name="Goal-line clearance defender",
            role_description=(
                "Keep execution_gate=LOCKED everywhere; no live trading path."
            ),
            target_relevance=1.0,
            absolute_score=9.7,
            absolute_ceiling_reason=(
                "Capped pending a documented annual rotation drill of the lock."
            ),
            confidence=0.97,
            criteria=[
                Criterion(
                    "execution_gate=LOCKED in advisory contract module",
                    0.40,
                    1.0,
                    ("scripts/advisory_contract.py",),
                ),
                Criterion(
                    "Release gate proof shows LOCKED stamps",
                    0.30,
                    1.0,
                    ("runtime/release/release_gate_proof.json",),
                ),
                Criterion(
                    "No broker SDK import in repo (negative-evidence test)",
                    0.30,
                    1.0,
                    ("tests/test_api_server.py",),
                ),
            ],
            blockers=[],
            next_action="Run an annual lock-rotation drill and document it.",
        ),
        # 4 ---------------------------------------------------------------
        Segment(
            segment="Backend architecture",
            role_name="Modular FastAPI advisory backend",
            role_description=(
                "Routes/scripts cleanly separated; SQLite canonical; routers "
                "modularised; no business logic in route handlers."
            ),
            target_relevance=1.0,
            absolute_score=7.5,
            absolute_ceiling_reason="Script pile still large; no Postgres adapter.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "api_server.py composes modular routers",
                    0.35,
                    0.9,
                    ("scripts/api_server.py", "scripts/api/routers"),
                ),
                Criterion(
                    "Architecture boundaries doc exists and is current",
                    0.30,
                    0.9,
                    ("docs/ARCHITECTURE.md", "docs/ARCHITECTURE_BOUNDARIES.md"),
                ),
                Criterion(
                    "Architecture fitness checker enforces shape",
                    0.35,
                    0.9,
                    ("scripts/architecture_fitness.py",),
                ),
            ],
            blockers=["No Postgres adapter; script pile not yet collapsed."],
            next_action="Land Postgres adapter behind a feature flag.",
        ),
        # 5 ---------------------------------------------------------------
        Segment(
            segment="Frontend architecture",
            role_name="Strict React/TS operator surface",
            role_description=(
                "Strict TypeScript; small, composable components; no any/ts-ignore."
            ),
            target_relevance=1.0,
            absolute_score=8.5,
            absolute_ceiling_reason=(
                "Page extracted (live-signals page down from 1116 → ~478 lines via "
                "LiveSignalEmptyState + LiveSignalsHeader + RunRefreshPanel); "
                "Storybook / visual regression still missing."
            ),
            confidence=0.9,
            criteria=[
                Criterion(
                    "frontend npx tsc --noEmit passes on strict",
                    0.30,
                    1.0,
                    ("frontend/tsconfig.json",),
                ),
                Criterion(
                    "Live-signals page extracted into focused sub-components",
                    0.30,
                    1.0,
                    (
                        "frontend/src/components/live-signals/LiveSignalEmptyState.tsx",
                        "frontend/src/components/live-signals/LiveSignalsHeader.tsx",
                        "frontend/src/components/live-signals/RunRefreshPanel.tsx",
                    ),
                ),
                Criterion(
                    "Small, named components in src/components",
                    0.20,
                    0.95,
                    ("frontend/src/components",),
                ),
                Criterion(
                    "Component unit tests exist alongside components",
                    0.20,
                    0.95,
                    ("frontend/src/components/__tests__",),
                ),
            ],
            blockers=["No visual regression coverage."],
            next_action="Add Storybook or Playwright visual snapshots for top panels.",
        ),
        # 6 ---------------------------------------------------------------
        Segment(
            segment="Frontend UX truthfulness",
            role_name="Honest-state painter",
            role_description=(
                "Never claim live/fresh when source is mock, stale, or degraded."
            ),
            target_relevance=1.0,
            absolute_score=9.3,
            absolute_ceiling_reason="No full e2e suite asserting truth markers under load.",
            confidence=0.95,
            criteria=[
                Criterion(
                    "TopTruthBar renders mock/fallback when source is mock",
                    0.35,
                    1.0,
                    (
                        "frontend/src/components/TopTruthBar.tsx",
                        "frontend/src/components/__tests__/TopTruthBar.spec.tsx",
                    ),
                ),
                Criterion(
                    "SourceConfigurationSnapshot surfaces degraded counts",
                    0.35,
                    1.0,
                    (
                        "frontend/src/components/SourceConfigurationSnapshot.tsx",
                        "frontend/src/components/__tests__/SourceConfigurationSnapshot.spec.tsx",
                    ),
                ),
                Criterion(
                    "AdvisoryEmptyState communicates absence, not synthetic data",
                    0.30,
                    1.0,
                    (
                        "frontend/src/components/AdvisoryEmptyState.tsx",
                        "frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx",
                    ),
                ),
            ],
            blockers=["No e2e suite asserts truth markers under live load."],
            next_action="Add a Playwright e2e covering mock + degraded toggles.",
        ),
        # 7 ---------------------------------------------------------------
        Segment(
            segment="Mock/fallback transparency",
            role_name="Truth-surface marker",
            role_description=(
                "Mock or fallback data can never be mistaken for live truth: "
                "global mock chip, panel-level fallback labels, source-snapshot "
                "unavailable copy, no mock contamination in canonical store."
            ),
            target_relevance=1.0,
            absolute_score=9.6,
            absolute_ceiling_reason=(
                "Capped at 9.6 until row-level mock chip lands on every signal card."
            ),
            confidence=0.95,
            criteria=[
                Criterion(
                    "Global mock chip via TopTruthBar",
                    0.25,
                    1.0,
                    (
                        "frontend/src/components/TopTruthBar.tsx",
                        "frontend/src/components/__tests__/TopTruthBar.spec.tsx",
                    ),
                ),
                Criterion(
                    "Panel-level fallback labels in SourceHealthPanel",
                    0.25,
                    1.0,
                    ("frontend/src/components/SourceHealthPanel.tsx",),
                ),
                Criterion(
                    "Snapshot 'unavailable' copy when backend down",
                    0.25,
                    1.0,
                    ("frontend/src/components/SourceConfigurationSnapshot.tsx",),
                ),
                Criterion(
                    "No mock contamination in canonical SQLite",
                    0.25,
                    1.0,
                    ("docs/CALIBRATION_CORPUS.md",),
                ),
            ],
            blockers=["Row-level mock chip on every signal card pending."],
            next_action="Add a row-level mock chip to SignalCard.",
        ),
        # 8 ---------------------------------------------------------------
        Segment(
            segment="Data-source realism",
            role_name="Realistic-but-bounded data layer",
            role_description=(
                "Where live, we say live; where mock, we say mock; never blur."
            ),
            target_relevance=1.0,
            absolute_score=7.5,
            absolute_ceiling_reason="Several sources still rely on bounded mocks.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Source registry distinguishes live vs mock",
                    0.5,
                    0.9,
                    ("docs/DATA_SOURCE_LICENSE_REGISTER.md",),
                ),
                Criterion(
                    "Kalshi operator truth panel reflects real watchdog state",
                    0.5,
                    0.9,
                    (
                        "frontend/src/components/KalshiOperatorTruthPanel.tsx",
                        "runtime/release/kalshi_watchdog_summary.json",
                    ),
                ),
            ],
            blockers=["Several sources rely on bounded mocks."],
            next_action="Promote one bounded-mock source to a live adapter.",
        ),
        # 9 ---------------------------------------------------------------
        Segment(
            segment="Live-source integration quality",
            role_name="Live-feed contract enforcer",
            role_description=(
                "When a source is wired live, contract tests / canaries gate it; "
                "no silent stale or partial reads pass as truth."
            ),
            target_relevance=0.8,
            absolute_score=6.5,
            absolute_ceiling_reason="Most sources remain bounded mocks; canary live-only.",
            confidence=0.8,
            criteria=[
                Criterion(
                    "Hosted canary workflow asserts live contract",
                    0.5,
                    0.9,
                    ("docs/HOSTED_CANARY.md",),
                ),
                Criterion(
                    "Live provider evidence file present and stamped",
                    0.5,
                    0.9,
                    ("runtime/release/live_provider_evidence.json",),
                ),
            ],
            blockers=["Only Kalshi has the full live-canary contract today."],
            next_action="Extend the live canary to one additional provider.",
        ),
        # 10 --------------------------------------------------------------
        Segment(
            segment="Source-health observability",
            role_name="Freshness/degraded-state truth surface",
            role_description=(
                "Freshness, last_success_at, degraded, never_run all visible "
                "without an operator having to read logs."
            ),
            target_relevance=1.0,
            absolute_score=9.0,
            absolute_ceiling_reason="No external alerting wired (Slack/email).",
            confidence=0.95,
            criteria=[
                Criterion(
                    "SourceHealthPanel renders per-source freshness state",
                    0.30,
                    1.0,
                    ("frontend/src/components/SourceHealthPanel.tsx",),
                ),
                Criterion(
                    "Source-config snapshot counts fresh/stale/degraded",
                    0.30,
                    1.0,
                    ("frontend/src/components/SourceConfigurationSnapshot.tsx",),
                ),
                Criterion(
                    "Watchdog status panel + tests cover degraded states",
                    0.20,
                    1.0,
                    (
                        "frontend/src/components/WatchdogStatusPanel.tsx",
                        "frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx",
                    ),
                ),
                Criterion(
                    "Kalshi source-health JSON written under runtime/release",
                    0.20,
                    1.0,
                    ("runtime/release/kalshi_source_health.json",),
                ),
            ],
            blockers=["No external alerting (Slack/email) wired."],
            next_action="Wire one external alert sink for degraded states.",
        ),
        # 11 --------------------------------------------------------------
        Segment(
            segment="Scoring/model logic quality",
            role_name="Predictive engine",
            role_description=(
                "Real predictive validity: N_real >= 200, Brier ≤ 0.25, "
                "ECE ≤ 0.10, MCE ≤ 0.25, reliability diagram generated."
            ),
            target_relevance=1.0,
            absolute_score=scoring_model_abs,
            absolute_ceiling_reason=(
                "Hard cap at 5.8 until N_real ≥ 200 with usable model_probability."
            ),
            confidence=0.75,
            criteria=[
                Criterion(
                    "N_real ≥ 200 with usable model_probability",
                    0.4,
                    scoring_predictive_p,
                    ("runtime/release/calibration_report.json",),
                    blocker="N_real=0 with usable p — no predictive claim allowed."
                    if not calibration_unlocked
                    else "",
                ),
                Criterion(
                    "Brier / ECE / MCE measured and within thresholds",
                    0.3,
                    scoring_predictive_p,
                    ("scripts/calibration_report.py",),
                ),
                Criterion(
                    "Score axes EMS/EQS/DS/LS/EFS/APS documented",
                    0.15,
                    1.0,
                    ("docs/CALIBRATION_CORPUS.md",),
                ),
                Criterion(
                    "Reliability diagram artefact generated",
                    0.15,
                    scoring_predictive_p,
                    ("runtime/release/calibration_report.json",),
                ),
            ],
            blockers=(
                []
                if calibration_unlocked
                else [
                    "N_real=0 with usable model_probability — predictive validity not yet earnable.",
                ]
            ),
            next_action=(
                "Begin labelling outcomes against stored model_probability snapshots."
            ),
        ),
        # 12 --------------------------------------------------------------
        Segment(
            segment="Calibration gate honesty",
            role_name="False-confidence blocker",
            role_description=(
                "Refuse to claim predictive validity until thresholds pass; "
                "report N_real, N_min, BS, ECE, MCE, and predictive_claim_allowed "
                "honestly."
            ),
            target_relevance=1.0,
            absolute_score=9.7,
            absolute_ceiling_reason="External calibration audit not yet performed.",
            confidence=0.97,
            criteria=[
                Criterion(
                    "N_real and N_min explicit in calibration_report.json",
                    0.25,
                    1.0,
                    ("runtime/release/calibration_report.json",),
                ),
                Criterion(
                    "predictive_claim_allowed=false when N_real < N_min",
                    0.25,
                    1.0,
                    (
                        "scripts/calibration_report.py",
                        "tests/test_calibration_report.py",
                    ),
                ),
                Criterion(
                    "Brier / ECE / MCE formulas covered by unit tests",
                    0.25,
                    1.0,
                    ("tests/test_calibration_report.py",),
                ),
                Criterion(
                    "Calibration corpus excludes fixture/mock from N_real",
                    0.25,
                    1.0,
                    (
                        "tests/test_calibration_corpus.py",
                        "docs/CALIBRATION_CORPUS.md",
                    ),
                ),
            ],
            blockers=[],
            next_action="Commission an external calibration audit when N_real ≥ 200.",
        ),
        # 13 --------------------------------------------------------------
        Segment(
            segment="Calibration corpus evidence",
            role_name="Outcome-labelled evidence ledger",
            role_description=(
                "Curate a corpus of (model_probability, outcome) pairs "
                "drawn from canonical SQLite, fixture/mock-excluded."
            ),
            target_relevance=1.0,
            absolute_score=4.5,
            absolute_ceiling_reason=(
                "N_real with usable model_probability is currently 0."
            ),
            confidence=0.9,
            criteria=[
                Criterion(
                    "Corpus path published with provenance",
                    0.4,
                    1.0,
                    ("runtime/release/calibration_corpus.json",),
                ),
                Criterion(
                    "Corpus curator script enforces fixture/mock exclusion",
                    0.3,
                    1.0,
                    (
                        "scripts/calibration_report.py",
                        "tests/test_calibration_corpus.py",
                    ),
                ),
                Criterion(
                    "Records carry advisory/execution stamps",
                    0.3,
                    1.0,
                    ("runtime/release/calibration_corpus.json",),
                ),
            ],
            blockers=["No usable model_probability snapshots in corpus yet."],
            next_action="Persist model_probability with every signal advisory.",
        ),
        # 14 --------------------------------------------------------------
        Segment(
            segment="State-machine / archetype clarity",
            role_name="Regime-aware state machine",
            role_description=(
                "Bull / non-bull / collapse / archetype transitions are explicit "
                "and audited."
            ),
            target_relevance=1.0,
            absolute_score=7.0,
            absolute_ceiling_reason="Transitions audited but evolving.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Archetype profile + registry modules and tests",
                    0.5,
                    0.9,
                    (
                        "scripts/archetype_profile.py",
                        "scripts/archetype_registry.py",
                        "tests/test_archetype_profile.py",
                    ),
                ),
                Criterion(
                    "Bull state report exists and is stamped",
                    0.5,
                    0.9,
                    ("runtime/bull_state_report.json",),
                ),
            ],
            blockers=["Some archetypes lack reliability evidence."],
            next_action="Tie each archetype to a Brier-style outcome stat.",
        ),
        # 15 --------------------------------------------------------------
        Segment(
            segment="Signal explainability",
            role_name="Why-this-signal narrator",
            role_description=(
                "Every advisory signal explains the axes that drove it."
            ),
            target_relevance=1.0,
            absolute_score=7.5,
            absolute_ceiling_reason="Narratives are static; no per-signal LM rationale.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "SignalScorePanel exposes per-axis scores in UI",
                    0.5,
                    0.9,
                    ("frontend/src/components/SignalScorePanel.tsx",),
                ),
                Criterion(
                    "Why-today summary written under runtime/release",
                    0.5,
                    0.9,
                    ("runtime/release/why_today_summary.json",),
                ),
            ],
            blockers=["No per-signal natural-language rationale yet."],
            next_action="Add an explainability section to SignalCard.",
        ),
        # 16 --------------------------------------------------------------
        Segment(
            segment="Portfolio/trade recommendation safety",
            role_name="Advisory recommendation guard",
            role_description=(
                "Recommendations never imply execution; manual-log workflow "
                "is the only mutation path."
            ),
            target_relevance=1.0,
            absolute_score=9.0,
            absolute_ceiling_reason="No external review of recommendation surface.",
            confidence=0.92,
            criteria=[
                Criterion(
                    "Manual trade log form is the only mutation entrypoint",
                    0.5,
                    1.0,
                    (
                        "frontend/src/components/ManualTradeLogForm.tsx",
                        "frontend/src/components/__tests__/ManualTradeLogForm.aiModel.spec.tsx",
                    ),
                ),
                Criterion(
                    "Portfolio truth summary written and stamped",
                    0.5,
                    1.0,
                    ("runtime/release/portfolio_truth_summary.json",),
                ),
            ],
            blockers=[],
            next_action="Schedule a UX review of advisory recommendation copy.",
        ),
        # 17 --------------------------------------------------------------
        Segment(
            segment="Risk / chaos / veto logic",
            role_name="Veto-and-recover layer",
            role_description=(
                "Every fragile branch can be vetoed safely; chaos paths fall "
                "back to advisory degraded states."
            ),
            target_relevance=1.0,
            absolute_score=7.8,
            absolute_ceiling_reason="No fault-injection harness yet.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Board-control safety layer present and tested",
                    0.5,
                    0.9,
                    (
                        "scripts/board_control_safety_layer.py",
                        "tests/test_board_control_safety_layer.py",
                    ),
                ),
                Criterion(
                    "Failure-mode handling documented",
                    0.5,
                    0.9,
                    ("docs/E2E_TEST_PLAN.md",),
                ),
            ],
            blockers=["No automated fault-injection harness."],
            next_action="Add a chaos-style test harness for the refresh loop.",
        ),
        # 18 --------------------------------------------------------------
        Segment(
            segment="Testing depth",
            role_name="Truth-gate test ladder",
            role_description=(
                "Property tests + contract tests + runtime artefact coherence."
            ),
            target_relevance=1.0,
            absolute_score=9.2,
            absolute_ceiling_reason="No mutation testing yet.",
            confidence=0.95,
            criteria=[
                Criterion(
                    "Advisory stamp property test covers ≥90% safe GETs",
                    0.25,
                    1.0,
                    ("tests/test_advisory_stamp_property.py",),
                ),
                Criterion(
                    "Runtime artefact coherence strict suite passes",
                    0.25,
                    1.0,
                    ("tests/test_runtime_artifact_coherence_strict.py",),
                ),
                Criterion(
                    "Calibration math is unit-tested",
                    0.25,
                    1.0,
                    ("tests/test_calibration_report.py",),
                ),
                Criterion(
                    "Credential hygiene test present and green",
                    0.25,
                    1.0,
                    ("tests/test_credential_hygiene.py",),
                ),
            ],
            blockers=["No mutation testing."],
            next_action="Add a small mutmut sweep for the safety modules.",
        ),
        # 19 --------------------------------------------------------------
        Segment(
            segment="Frontend tests",
            role_name="Component truth tests",
            role_description=(
                "Component-level spec coverage of the top truth-surface panels "
                "plus a vitest-based truth-flow integration suite covering the "
                "seven advisory-only flows (mock/live, snapshot, refresh, "
                "calibration gate, forbidden-vocabulary scan)."
            ),
            target_relevance=1.0,
            absolute_score=8.5,
            absolute_ceiling_reason=(
                "Vitest integration substitute caps frontend tests at ≤ 8.6 "
                "per the sprint spec (Playwright not yet installed)."
            ),
            confidence=0.92,
            criteria=[
                Criterion(
                    "Top-truth panels have component specs",
                    0.30,
                    1.0,
                    (
                        "frontend/src/components/__tests__/TopTruthBar.spec.tsx",
                        "frontend/src/components/__tests__/SourceConfigurationSnapshot.spec.tsx",
                    ),
                ),
                Criterion(
                    "Watchdog + reconciliation panels have specs",
                    0.30,
                    1.0,
                    (
                        "frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx",
                        "frontend/src/components/__tests__/ReconciliationCard.currency.spec.tsx",
                    ),
                ),
                Criterion(
                    "Truth-flow integration spec covers the 7 required flows",
                    0.40,
                    1.0,
                    (
                        "frontend/src/components/__tests__/truth_flow.integration.spec.tsx",
                    ),
                ),
            ],
            blockers=[
                "Frontend tests not yet wired into CI.",
                "Playwright not installed; integration substitute caps at 8.6.",
            ],
            next_action="Wire vitest into CI; evaluate Playwright as a follow-up.",
        ),
        # 20 --------------------------------------------------------------
        Segment(
            segment="Backend tests",
            role_name="Backend contract suite",
            role_description=(
                "Stamps, routes, calibration, persistence, watchdog covered."
            ),
            target_relevance=1.0,
            absolute_score=9.0,
            absolute_ceiling_reason="No long-running soak tests.",
            confidence=0.95,
            criteria=[
                Criterion(
                    "api_server tests cover safe + forbidden routes",
                    0.5,
                    1.0,
                    ("tests/test_api_server.py",),
                ),
                Criterion(
                    "Advisory contract test pins stamp invariants",
                    0.5,
                    1.0,
                    ("tests/test_advisory_contract.py",),
                ),
            ],
            blockers=["No soak test."],
            next_action="Add a 10-minute soak test for the refresh orchestrator.",
        ),
        # 21 --------------------------------------------------------------
        Segment(
            segment="Integration tests",
            role_name="End-to-end advisory loop test",
            role_description=(
                "Spanning fetch → score → moltbook → refresh, advisory-only."
            ),
            target_relevance=1.0,
            absolute_score=7.5,
            absolute_ceiling_reason="No Playwright e2e yet.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Cross-module integration tests exist",
                    0.5,
                    0.9,
                    ("tests/test_ai_schema_integration.py",),
                ),
                Criterion(
                    "Real-API canary workflow is gated and stamped",
                    0.5,
                    0.9,
                    ("tests/test_real_api_canary_workflow.py",),
                ),
            ],
            blockers=["No Playwright workflow e2e."],
            next_action="Add a 13-step Playwright e2e once a stable demo dataset exists.",
        ),
        # 22 --------------------------------------------------------------
        Segment(
            segment="Runtime hygiene",
            role_name="Artefact coherence enforcer",
            role_description=(
                "All runtime/* JSON artefacts are coherent, stamped, and "
                "honest about provenance."
            ),
            target_relevance=1.0,
            absolute_score=8.7,
            absolute_ceiling_reason="No JSON-schema validation per artefact.",
            confidence=0.92,
            criteria=[
                Criterion(
                    "Runtime artefact coherence strict suite",
                    0.5,
                    1.0,
                    ("tests/test_runtime_artifact_coherence_strict.py",),
                ),
                Criterion(
                    "Release-gate proof present and stamped",
                    0.5,
                    1.0,
                    ("runtime/release/release_gate_proof.json",),
                ),
            ],
            blockers=["No per-artefact JSON schema validation."],
            next_action="Generate JSON schemas for top 5 runtime artefacts.",
        ),
        # 23 --------------------------------------------------------------
        Segment(
            segment="Logging / auditability",
            role_name="Audit-trail keeper",
            role_description=(
                "JSONL audit mirror for every canonical SQLite mutation."
            ),
            target_relevance=1.0,
            absolute_score=8.5,
            absolute_ceiling_reason="No external SIEM sink wired.",
            confidence=0.9,
            criteria=[
                Criterion(
                    "JSONL is audit-only, SQLite canonical",
                    0.5,
                    1.0,
                    ("scripts/advisory_contract.py",),
                ),
                Criterion(
                    "Moltbook feedback JSONL written audit-only",
                    0.5,
                    1.0,
                    ("runtime/moltbook_feedback_cases.jsonl",),
                ),
            ],
            blockers=["No external SIEM."],
            next_action="Document a SIEM sink option for future deployments.",
        ),
        # 24 --------------------------------------------------------------
        Segment(
            segment="Persistence model / database truth",
            role_name="Canonical-store discipline",
            role_description=(
                "SQLite canonical, demo rows quarantined, holdings truth "
                "centralised."
            ),
            target_relevance=1.0,
            absolute_score=8.5,
            absolute_ceiling_reason="Single-tenant SQLite; no Postgres parity yet.",
            confidence=0.92,
            criteria=[
                Criterion(
                    "Canonical SQLite present",
                    0.4,
                    1.0,
                    ("runtime/mvp_local.db",),
                ),
                Criterion(
                    "Persistence integrity summary written",
                    0.3,
                    1.0,
                    ("runtime/release/persistence_integrity_summary.json",),
                ),
                Criterion(
                    "Daily payload truth file present",
                    0.3,
                    1.0,
                    ("data/daily_payload",),
                ),
            ],
            blockers=["No Postgres parity."],
            next_action="Ship a Postgres adapter behind a flag.",
        ),
        # 25 --------------------------------------------------------------
        Segment(
            segment="JSONL vs SQLite truth discipline",
            role_name="Canonical/audit boundary keeper",
            role_description=(
                "Never let JSONL be canonical; tests pin the invariant."
            ),
            target_relevance=1.0,
            absolute_score=9.5,
            absolute_ceiling_reason="Pinned by tests; cap pending external review.",
            confidence=0.95,
            criteria=[
                Criterion(
                    "jsonl_is_canonical = False stamp everywhere",
                    0.5,
                    1.0,
                    ("scripts/advisory_contract.py",),
                ),
                Criterion(
                    "Calibration corpus declares canonical='sqlite'",
                    0.5,
                    1.0,
                    ("runtime/release/calibration_corpus.json",),
                ),
            ],
            blockers=[],
            next_action="Add an explicit test that scans for jsonl_is_canonical=True.",
        ),
        # 26 --------------------------------------------------------------
        Segment(
            segment="Deployment readiness",
            role_name="Local-first deploy",
            role_description=(
                "Local-first; hosted single-VPS plan documented but unvalidated."
            ),
            target_relevance=0.5,
            absolute_score=6.0,
            absolute_ceiling_reason="Hosted deploy not yet validated.",
            confidence=0.8,
            criteria=[
                Criterion(
                    "Local deployment checklist present",
                    0.5,
                    1.0,
                    ("docs/LOCAL_DEPLOYMENT_CHECKLIST.md",),
                ),
                Criterion(
                    "Hosted deployment plan present",
                    0.5,
                    0.9,
                    ("docs/HOSTED_DEPLOYMENT_PLAN.md",),
                ),
            ],
            blockers=["Hosted deploy never executed."],
            next_action="Run a one-shot hosted deploy on a throwaway VPS.",
        ),
        # 27 --------------------------------------------------------------
        Segment(
            segment="Local developer experience",
            role_name="First-day operator concierge",
            role_description=(
                "An operator can run, refresh, and read the scorecard locally "
                "in under an hour."
            ),
            target_relevance=1.0,
            absolute_score=9.0,
            absolute_ceiling_reason=(
                "Bootstrap script lands a 10/10 dry-run preflight; recorded "
                "demo / walkthrough video still pending."
            ),
            confidence=0.92,
            criteria=[
                Criterion(
                    "Local deployment checklist + README present",
                    0.3,
                    1.0,
                    ("docs/LOCAL_DEPLOYMENT_CHECKLIST.md", "README.md"),
                ),
                Criterion(
                    "Scorecard generator runnable from CLI",
                    0.2,
                    1.0,
                    ("scripts/segment_role_scorecard.py",),
                ),
                Criterion(
                    "Backup + restore docs present",
                    0.2,
                    1.0,
                    ("scripts/backup_db.py", "scripts/backup_local_state.py"),
                ),
                Criterion(
                    "Bootstrap operator script + tests present",
                    0.3,
                    1.0,
                    (
                        "scripts/bootstrap_local_operator.py",
                        "tests/test_bootstrap_local_operator.py",
                    ),
                ),
            ],
            blockers=["No recorded walkthrough video."],
            next_action="Record the demo from docs/demo/DEMO_SCRIPT_5_MIN.md.",
        ),
        # 28 --------------------------------------------------------------
        Segment(
            segment="Security posture",
            role_name="Local-first security baseline",
            role_description=(
                "Local token auth, rate-limit, security headers, advisory-only."
            ),
            target_relevance=1.0,
            absolute_score=7.3,
            absolute_ceiling_reason="No hosted secrets manager; no third-party audit.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Local API token panel + tests",
                    0.5,
                    1.0,
                    (
                        "frontend/src/components/LocalApiTokenPanel.tsx",
                        "frontend/src/components/__tests__/LocalApiTokenPanel.spec.tsx",
                    ),
                ),
                Criterion(
                    "API token gate contract test passes",
                    0.5,
                    1.0,
                    ("tests/test_api_token_gate_contract.py",),
                ),
            ],
            blockers=["No third-party audit; no hosted secrets manager."],
            next_action="Schedule a lightweight security review.",
        ),
        # 29 --------------------------------------------------------------
        Segment(
            segment="Secret-handling posture",
            role_name="Secret-redaction enforcer",
            role_description=(
                "Secrets never serialised, never printed; redaction tests pin it."
            ),
            target_relevance=1.0,
            absolute_score=9.3,
            absolute_ceiling_reason="No external red-team on secrets paths.",
            confidence=0.95,
            criteria=[
                Criterion(
                    "Credential hygiene test passes",
                    0.5,
                    1.0,
                    ("tests/test_credential_hygiene.py",),
                ),
                Criterion(
                    "Credential hygiene report written and stamped",
                    0.5,
                    1.0,
                    ("runtime/release/credential_hygiene_report.json",),
                ),
            ],
            blockers=["No external red-team."],
            next_action="Add a secrets-pattern grep to CI.",
        ),
        # 30 --------------------------------------------------------------
        Segment(
            segment="Documentation quality",
            role_name="Operator-first doc set",
            role_description=(
                "Every contract has a doc, every doc cites the test that pins it."
            ),
            target_relevance=1.0,
            absolute_score=9.0,
            absolute_ceiling_reason="Some docs duplicate; need consolidation.",
            confidence=0.92,
            criteria=[
                Criterion(
                    "Architecture + boundaries docs present",
                    0.25,
                    1.0,
                    ("docs/ARCHITECTURE.md", "docs/ARCHITECTURE_BOUNDARIES.md"),
                ),
                Criterion(
                    "Advisory disclosure + safety model docs present",
                    0.25,
                    1.0,
                    (
                        "docs/ADVISORY_DISCLOSURE.md",
                        "docs/ADVISORY_ONLY_SAFETY_MODEL.md",
                    ),
                ),
                Criterion(
                    "Calibration corpus + hosted canary docs present",
                    0.25,
                    1.0,
                    ("docs/CALIBRATION_CORPUS.md", "docs/HOSTED_CANARY.md"),
                ),
                Criterion(
                    "Final + role-fit scorecard docs both reachable",
                    0.25,
                    1.0,
                    (
                        "docs/FINAL_SCORECARD.md",
                        "docs/scorecards/ROLE_FIT_SCORING_MODEL.md",
                    ),
                ),
            ],
            blockers=["Some duplication across older docs."],
            next_action="Prune duplicate sections from the legacy docs.",
        ),
        # 31 --------------------------------------------------------------
        Segment(
            segment="Operator workflow usability",
            role_name="13-step workflow conductor",
            role_description=(
                "The first-day operator can complete the canonical workflow "
                "without reading source."
            ),
            target_relevance=1.0,
            absolute_score=8.8,
            absolute_ceiling_reason=(
                "5-minute demo script + screenshot checklist + truth-flow "
                "integration tests landed; recorded video walkthrough still "
                "pending operator capture."
            ),
            confidence=0.92,
            criteria=[
                Criterion(
                    "Demo case studies + rehearsal notes present",
                    0.25,
                    1.0,
                    (
                        "docs/DEMO_CASE_STUDIES.md",
                        "docs/DEMO_REHEARSAL_NOTES.md",
                    ),
                ),
                Criterion(
                    "E2E test plan documents the workflow",
                    0.25,
                    1.0,
                    ("docs/E2E_TEST_PLAN.md",),
                ),
                Criterion(
                    "5-min demo + walkthrough + screenshot checklist present",
                    0.25,
                    1.0,
                    (
                        "docs/demo/DEMO_SCRIPT_5_MIN.md",
                        "docs/demo/LOCAL_FIRST_WALKTHROUGH.md",
                        "docs/demo/SCREENSHOT_CHECKLIST.md",
                        "docs/demo/OPERATOR_PROOF_MANIFEST.json",
                    ),
                ),
                Criterion(
                    "Truth-flow integration tests cover the operator surface",
                    0.25,
                    1.0,
                    (
                        "frontend/src/components/__tests__/truth_flow.integration.spec.tsx",
                    ),
                ),
            ],
            blockers=["No recorded walkthrough video."],
            next_action="Record a 5-minute walkthrough video and update the manifest.",
        ),
        # 32 --------------------------------------------------------------
        Segment(
            segment="Commercial SaaS readiness",
            role_name="Out-of-scope striker",
            role_description=(
                "Not the role this MVP plays this year; flagged NOT_TARGETED."
            ),
            target_relevance=0.0,
            absolute_score=ABSOLUTE_PUBLIC_SAAS_CEILING,
            absolute_ceiling_reason=(
                "Hard capped at 1.5 — multi-tenant auth, hosted DB, billing all absent."
            ),
            confidence=0.95,
            criteria=[
                Criterion(
                    "NOT_TARGETED documented in FINAL_SCORECARD",
                    1.0,
                    1.0,
                    ("docs/FINAL_SCORECARD.md",),
                ),
            ],
            blockers=["Out of scope this year."],
            next_action="Revisit only after local-first showcase ships.",
        ),
        # 33 --------------------------------------------------------------
        Segment(
            segment="Feedback-loop / Moltbook readiness",
            role_name="Closed-loop learning ledger",
            role_description=(
                "Moltbook captures advisory outcomes for later calibration."
            ),
            target_relevance=1.0,
            absolute_score=8.0,
            absolute_ceiling_reason="No labelled outcome corpus yet.",
            confidence=0.88,
            criteria=[
                Criterion(
                    "Moltbook entry card + feedback ledger present",
                    0.5,
                    1.0,
                    (
                        "frontend/src/components/MoltbookEntryCard.tsx",
                        "runtime/moltbook_feedback_summary.json",
                    ),
                ),
                Criterion(
                    "Feedback cases JSONL written audit-only",
                    0.5,
                    1.0,
                    ("runtime/moltbook_feedback_cases.jsonl",),
                ),
            ],
            blockers=["No outcome-labelled corpus yet."],
            next_action="Begin labelling moltbook outcomes against signal probability.",
        ),
        # 34 --------------------------------------------------------------
        Segment(
            segment="Maintainability",
            role_name="Future-operator readability",
            role_description=(
                "Tests + docs + advisory contract make changes safe to land."
            ),
            target_relevance=1.0,
            absolute_score=7.5,
            absolute_ceiling_reason="Script pile still large.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Architecture fitness checker pins boundaries",
                    0.5,
                    0.9,
                    ("scripts/architecture_fitness.py",),
                ),
                Criterion(
                    "Advisory contract module is the single safety source",
                    0.5,
                    1.0,
                    ("scripts/advisory_contract.py",),
                ),
            ],
            blockers=["Script directory not yet collapsed."],
            next_action="Group scripts into named subpackages.",
        ),
        # 35 --------------------------------------------------------------
        Segment(
            segment="Performance / scalability",
            role_name="Local-machine performance",
            role_description=(
                "Acceptable latency for a single-operator local workflow."
            ),
            target_relevance=0.5,
            absolute_score=5.0,
            absolute_ceiling_reason="No concurrency or scaling work.",
            confidence=0.75,
            criteria=[
                Criterion(
                    "Cockpit hot-path indexes applied",
                    1.0,
                    0.9,
                    ("scripts/apply_cockpit_hot_path_indexes.py",),
                ),
            ],
            blockers=["No load test."],
            next_action="Add a 5-minute Locust scenario for the API.",
        ),
        # 36 --------------------------------------------------------------
        Segment(
            segment="Failure-mode handling",
            role_name="Graceful-degradation conductor",
            role_description=(
                "When a source fails, the UI degrades to advisory empty/stale "
                "states truthfully rather than fabricating data; the failure-"
                "mode harness pins twelve scenarios (timeout, malformed "
                "payload, empty response, staleness, lock contention, "
                "missing keys, corrupted artifacts, missing outcomes, "
                "missing axes, missing calibration report)."
            ),
            target_relevance=1.0,
            absolute_score=8.8,
            absolute_ceiling_reason=(
                "Harness covers 12/12 scenarios; full chaos-style fuzz "
                "harness for the refresh orchestrator still pending."
            ),
            confidence=0.92,
            criteria=[
                Criterion(
                    "AdvisoryEmptyState handles absent data truthfully",
                    0.25,
                    1.0,
                    (
                        "frontend/src/components/AdvisoryEmptyState.tsx",
                        "frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx",
                    ),
                ),
                Criterion(
                    "Watchdog status panel surfaces failures",
                    0.20,
                    1.0,
                    (
                        "frontend/src/components/WatchdogStatusPanel.tsx",
                        "frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx",
                    ),
                ),
                Criterion(
                    "Anti-staleness rules tested",
                    0.20,
                    1.0,
                    ("tests/test_anti_staleness_rules.py",),
                ),
                Criterion(
                    "Failure-mode harness covers 12/12 scenarios",
                    0.35,
                    1.0,
                    ("tests/test_failure_mode_harness.py",),
                ),
            ],
            blockers=["No fuzz-style chaos harness."],
            next_action="Add a fuzz harness for the refresh orchestrator.",
        ),
        # 37 --------------------------------------------------------------
        Segment(
            segment="Real-user readiness",
            role_name="Single-operator readiness",
            role_description=(
                "Ready for the *local* operator role; not for multi-user beta."
            ),
            target_relevance=0.6,
            absolute_score=6.5,
            absolute_ceiling_reason="No multi-user auth, no hosted DB.",
            confidence=0.85,
            criteria=[
                Criterion(
                    "Local API token gate works end-to-end",
                    0.5,
                    1.0,
                    ("tests/test_api_token_gate.py",),
                ),
                Criterion(
                    "First-day operator surface documented",
                    0.5,
                    1.0,
                    ("docs/LOCAL_DEPLOYMENT_CHECKLIST.md",),
                ),
            ],
            blockers=["No multi-user identity layer."],
            next_action="Design a multi-user identity layer behind a flag.",
        ),
        # 38 --------------------------------------------------------------
        Segment(
            segment="Overall MVP readiness",
            role_name="Local-first showcase composite",
            role_description=(
                "Composite — weighted average of the segments that matter to "
                "this MVP's role today."
            ),
            target_relevance=1.0,
            absolute_score=8.2,
            absolute_ceiling_reason="Composite ceiling tied to per-segment ceilings.",
            confidence=0.92,
            criteria=[
                Criterion(
                    "Per-segment composite agrees with FINAL_SCORECARD",
                    1.0,
                    1.0,
                    ("docs/FINAL_SCORECARD.md",),
                ),
            ],
            blockers=["Bound by per-segment ceilings."],
            next_action="Unlock per-segment ceilings to lift the composite.",
        ),
        # 39 --------------------------------------------------------------
        Segment(
            segment="Local-first showcase",
            role_name="Local-first showcase",
            role_description=(
                "End-to-end local demo: safe, honest, observable, reproducible."
            ),
            target_relevance=1.0,
            absolute_score=9.2,
            absolute_ceiling_reason=(
                "Demo script + walkthrough + screenshot checklist + truth-"
                "flow integration tests + bootstrap script all landed; "
                "recorded demo video and a real calibration corpus still "
                "pending."
            ),
            confidence=0.93,
            criteria=[
                Criterion(
                    "Local deployment checklist + README present",
                    0.2,
                    1.0,
                    ("docs/LOCAL_DEPLOYMENT_CHECKLIST.md", "README.md"),
                ),
                Criterion(
                    "Top-truth panels render honest state",
                    0.2,
                    1.0,
                    (
                        "frontend/src/components/TopTruthBar.tsx",
                        "frontend/src/components/SourceConfigurationSnapshot.tsx",
                    ),
                ),
                Criterion(
                    "Calibration honesty + advisory safety stamped",
                    0.3,
                    1.0,
                    (
                        "runtime/release/calibration_report.json",
                        "runtime/release/release_gate_proof.json",
                    ),
                ),
                Criterion(
                    "5-min demo + walkthrough + bootstrap operator preflight",
                    0.3,
                    1.0,
                    (
                        "docs/demo/DEMO_SCRIPT_5_MIN.md",
                        "docs/demo/LOCAL_FIRST_WALKTHROUGH.md",
                        "scripts/bootstrap_local_operator.py",
                    ),
                ),
            ],
            blockers=["No recorded demo video; no real calibration corpus."],
            next_action="Record the demo, capture screenshots, and pin from README.",
        ),
        # 40 --------------------------------------------------------------
        Segment(
            segment="Private beta readiness",
            role_name="Design-stage candidate",
            role_description=(
                "Design exists for auth + hosted DB + user isolation + "
                "staging smoke; readiness report quantifies the design-only "
                "ceiling at 6.2 until real Auth + HostedDB land."
            ),
            target_relevance=0.5,
            absolute_score=5.5,
            absolute_ceiling_reason=(
                "Hard capped at 6.2 design-only; capped at 5.0 here until "
                "user-isolation contract test ships.  Real multi-user auth + "
                "hosted DB still absent."
            ),
            confidence=0.88,
            criteria=[
                Criterion(
                    "Hosted deployment plan documented",
                    0.25,
                    1.0,
                    ("docs/HOSTED_DEPLOYMENT_PLAN.md",),
                ),
                Criterion(
                    "Legal/privacy compliance notes present",
                    0.25,
                    1.0,
                    (
                        "docs/LEGAL_PRIVACY_NOTES.md",
                        "docs/LEGAL_PRIVACY_COMPLIANCE_MODEL.md",
                    ),
                ),
                Criterion(
                    "Thin-slice + auth/user-isolation + staging docs present",
                    0.25,
                    1.0,
                    (
                        "docs/private_beta/PRIVATE_BETA_THIN_SLICE.md",
                        "docs/private_beta/AUTH_AND_USER_ISOLATION_PLAN.md",
                        "docs/private_beta/STAGING_SMOKE_CHECK.md",
                    ),
                ),
                Criterion(
                    "Readiness report + tests pin design-only cap",
                    0.25,
                    1.0,
                    (
                        "scripts/private_beta_readiness_report.py",
                        "tests/test_private_beta_readiness_report.py",
                    ),
                ),
            ],
            blockers=["No multi-user auth, no hosted DB."],
            next_action="Implement the documented auth design behind a flag.",
        ),
        # 41 --------------------------------------------------------------
        Segment(
            segment="Public SaaS readiness",
            role_name="Out-of-scope striker",
            role_description=(
                "Not a target role for this MVP this year; intentionally low."
            ),
            target_relevance=0.0,
            absolute_score=ABSOLUTE_PUBLIC_SAAS_CEILING,
            absolute_ceiling_reason=(
                "Out of scope: no multi-tenant, no billing, no legal audit, "
                "no SaaS deploy."
            ),
            confidence=0.95,
            criteria=[
                Criterion(
                    "FINAL_SCORECARD declares public-prod 'do not pursue'",
                    1.0,
                    1.0,
                    ("docs/FINAL_SCORECARD.md",),
                ),
            ],
            blockers=["Out of scope this year."],
            next_action="Revisit only after private-beta ships.",
        ),
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _read_calibration_unlocked(report_path: Path) -> bool:
    """Return True iff the live calibration report says predictive_claim_allowed.

    Missing / unreadable file → False (honest default: no predictive claim).
    """
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("predictive_claim_allowed") is not True:
        return False
    n_real = data.get("n_real")
    try:
        return int(n_real) >= CALIBRATION_N_MIN
    except (TypeError, ValueError):
        return False


def _aggregate(segments: list[Segment]) -> dict[str, float | list[str]]:
    """Return overall absolute + overall role-fit aggregates."""
    abs_num = 0.0
    abs_den = 0.0
    for s in segments:
        abs_num += s.absolute_weight * s.absolute_score
        abs_den += s.absolute_weight
    overall_absolute = abs_num / abs_den if abs_den else 0.0

    role_num = 0.0
    role_den = 0.0
    not_targeted: list[str] = []
    for s in segments:
        if s.target_relevance == 0.0:
            not_targeted.append(s.segment)
            continue
        role_num += s.role_weight * s.confidence_adjusted_role_fit * s.target_relevance
        role_den += s.role_weight * s.target_relevance
    overall_role_fit = role_num / role_den if role_den else 0.0

    return {
        "overall_absolute": round(overall_absolute, 4),
        "overall_role_fit": round(overall_role_fit, 4),
        "not_targeted_segments": not_targeted,
    }


def build_report(
    *,
    repo_root: Path = _REPO_ROOT,
    calibration_report_path: Path = DEFAULT_CALIBRATION_REPORT,
) -> dict[str, Any]:
    """Produce the full role-fit scorecard report as a dict."""
    calibration_unlocked = _read_calibration_unlocked(calibration_report_path)
    segments = _segments(calibration_unlocked=calibration_unlocked)
    for s in segments:
        s._finalise(repo_root=repo_root)

    aggregate = _aggregate(segments)

    safety = advisory_safety_stamps()

    return {
        "script": "segment_role_scorecard.py",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "advisory_status": safety["advisory_status"],
        "execution_gate": safety["execution_gate"],
        "broker_api_called": safety["broker_api_called"],
        "ai_execution_count": safety["ai_execution_count"],
        "can_execute": safety["can_execute"],
        "execution_permission": safety["execution_permission"],
        "human_review_required": safety["human_review_required"],
        "broker_order_id": safety["broker_order_id"],
        "canonical_store": CANONICAL_STORE,
        "audit_only_store": AUDIT_ONLY_STORE,
        "jsonl_is_canonical": False,
        "calibration_unlocked": calibration_unlocked,
        "calibration_n_min": CALIBRATION_N_MIN,
        "scoring_model": {
            "overall_absolute_formula": (
                "OverallAbsolute = Σ_s W_abs_s * A_s / Σ_s W_abs_s"
            ),
            "overall_role_fit_formula": (
                "OverallRoleFit = Σ_s W_role_s * R_adj_s * T_s / "
                "Σ_s W_role_s * T_s   (NOT_TARGETED excluded)"
            ),
            "role_fit_formula": "R_s = 10 * Σ_i (w_i * p_i)",
            "evidence_completeness_formula": (
                "E_s = min(1, evidence_items_present / evidence_items_required)"
            ),
            "confidence_adjustment_formula": (
                "R_adj_s = R_s * (0.7 + 0.3 * E_s) * C_s"
            ),
        },
        "segments": [
            _segment_to_dict(s) for s in segments
        ],
        "overall_absolute": aggregate["overall_absolute"],
        "overall_role_fit": aggregate["overall_role_fit"],
        "not_targeted_segments": aggregate["not_targeted_segments"],
    }


def _segment_to_dict(s: Segment) -> dict[str, Any]:
    """Render a segment as the canonical JSON shape."""
    dashboard_score: float | str
    if s.target_relevance == 0.0:
        dashboard_score = "NOT_TARGETED_THIS_YEAR"
    else:
        dashboard_score = round(s.confidence_adjusted_role_fit, 4)
    return {
        "segment": s.segment,
        "role_name": s.role_name,
        "role_description": s.role_description,
        "target_relevance": round(s.target_relevance, 4),
        "absolute_score": round(s.absolute_score, 4),
        "absolute_ceiling_reason": s.absolute_ceiling_reason,
        "role_fit_score": round(s.role_fit_score, 4),
        "confidence": round(s.confidence, 4),
        "evidence_completeness": round(s.evidence_completeness, 4),
        "confidence_adjusted_role_fit": round(s.confidence_adjusted_role_fit, 4),
        "dashboard_score": dashboard_score,
        "absolute_weight": round(s.absolute_weight, 4),
        "role_weight": round(s.role_weight, 4),
        "criteria": [
            {
                "criterion": c.criterion,
                "weight": round(c.weight, 4),
                "performance": round(c.performance, 4),
                "evidence": list(c.evidence),
                "blocker": c.blocker,
            }
            for c in s.criteria
        ],
        "blockers": list(s.blockers),
        "next_action": s.next_action,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    """Render a human-friendly Markdown view of the role-fit scorecard."""
    lines: list[str] = []
    lines.append("# Segment Role-Fit Scorecard")
    lines.append("")
    lines.append(
        f"> Generated {report['generated_at_utc']} · "
        f"advisory_status=`{report['advisory_status']}` · "
        f"execution_gate=`{report['execution_gate']}` · "
        f"broker_api_called=`{report['broker_api_called']}` · "
        f"ai_execution_count=`{report['ai_execution_count']}`."
    )
    lines.append("")
    lines.append(
        "> Two lenses, on purpose. **Absolute readiness** asks "
        "*'how close to production / private beta / public SaaS?'*. "
        "**Role-fit readiness** asks *'given this segment's role in this "
        "local-first MVP, is it performing that role at an elite level?'*. "
        "A refusal/safety segment that refuses perfectly is 10/10 even if "
        "it never scores a goal."
    )
    lines.append("")
    lines.append("## Formulas")
    lines.append("")
    lines.append("```")
    lines.append("R_s        = 10 * Σ_i (w_i * p_i)   with Σ_i w_i = 1")
    lines.append(
        "E_s        = min(1, evidence_items_present / evidence_items_required)"
    )
    lines.append("R_adj_s    = R_s * (0.7 + 0.3 * E_s) * C_s")
    lines.append("OverallAbsolute = Σ_s W_abs_s * A_s / Σ_s W_abs_s")
    lines.append(
        "OverallRoleFit  = Σ_s W_role_s * R_adj_s * T_s "
        "/ Σ_s W_role_s * T_s   (NOT_TARGETED excluded)"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        f"**Calibration unlocked**: `{report['calibration_unlocked']}` "
        f"(N_min={report['calibration_n_min']}).  When False, the "
        "*Scoring/model logic quality* segment cannot exceed its "
        f"no-evidence ceiling of {SCORING_MODEL_CEILING_NO_EVIDENCE}/10."
    )
    lines.append("")
    lines.append("## Composite scores")
    lines.append("")
    lines.append("| Lens | Score /10 |")
    lines.append("|---|---:|")
    lines.append(f"| Overall absolute readiness | {report['overall_absolute']:.3f} |")
    lines.append(f"| Overall role-fit readiness | {report['overall_role_fit']:.3f} |")
    lines.append("")
    not_targeted = report["not_targeted_segments"]
    if not_targeted:
        lines.append("**NOT_TARGETED (excluded from role-fit denominator):**")
        for n in not_targeted:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("## Per-segment scorecard")
    lines.append("")
    lines.append(
        "| # | Segment | Role | T_s | A_s | R_s | C_s | E_s | R_adj_s | Dashboard |"
    )
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, s in enumerate(report["segments"], start=1):
        dash = s["dashboard_score"]
        dash_str = (
            "NOT_TARGETED" if dash == "NOT_TARGETED_THIS_YEAR" else f"{float(dash):.2f}"
        )
        lines.append(
            f"| {i} | {s['segment']} | {s['role_name']} | "
            f"{s['target_relevance']:.2f} | "
            f"{s['absolute_score']:.2f} | "
            f"{s['role_fit_score']:.2f} | "
            f"{s['confidence']:.2f} | "
            f"{s['evidence_completeness']:.2f} | "
            f"{s['confidence_adjusted_role_fit']:.2f} | "
            f"{dash_str} |"
        )
    lines.append("")

    lines.append("## Per-segment criteria")
    lines.append("")
    for s in report["segments"]:
        lines.append(f"### {s['segment']} — *{s['role_name']}*")
        lines.append("")
        lines.append(f"> {s['role_description']}")
        lines.append("")
        lines.append(
            f"- target_relevance `T_s` = {s['target_relevance']:.2f}"
        )
        lines.append(
            f"- absolute_score `A_s` = {s['absolute_score']:.2f}  "
            f"(ceiling: {s['absolute_ceiling_reason']})"
        )
        lines.append(
            f"- role_fit_score `R_s` = {s['role_fit_score']:.2f}"
        )
        lines.append(
            f"- confidence `C_s` = {s['confidence']:.2f}, "
            f"evidence_completeness `E_s` = {s['evidence_completeness']:.2f}"
        )
        lines.append(
            f"- **confidence-adjusted role-fit `R_adj_s` = {s['confidence_adjusted_role_fit']:.2f}**"
        )
        lines.append("")
        lines.append("| Criterion | w_i | p_i | Evidence | Blocker |")
        lines.append("|---|---:|---:|---|---|")
        for c in s["criteria"]:
            ev = ", ".join(f"`{p}`" for p in c["evidence"]) or "—"
            blk = c["blocker"] or "—"
            lines.append(
                f"| {c['criterion']} | {c['weight']:.2f} | "
                f"{c['performance']:.2f} | {ev} | {blk} |"
            )
        if s["blockers"]:
            lines.append("")
            lines.append("**Blockers**:")
            for b in s["blockers"]:
                lines.append(f"- {b}")
        lines.append("")
        lines.append(f"**Next action**: {s['next_action']}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Role-fit + absolute readiness scorecard generator.  "
            "Read-only; advisory-only."
        ),
    )
    parser.add_argument("--json", default=None, help="Write JSON to this path.")
    parser.add_argument("--markdown", default=None, help="Write Markdown to this path.")
    parser.add_argument(
        "--calibration-report",
        default=str(DEFAULT_CALIBRATION_REPORT),
        help="Calibration report to read predictive_claim_allowed from.",
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        help="Print JSON to stdout in addition to any --json file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        calibration_report_path=Path(args.calibration_report),
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    if args.markdown:
        out = Path(args.markdown)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown(report), encoding="utf-8")
    if args.stdout_json or (args.json is None and args.markdown is None):
        sys.stdout.write(payload + "\n")
    else:
        sys.stdout.write(
            f"role-fit scorecard: overall_absolute={report['overall_absolute']:.3f} "
            f"overall_role_fit={report['overall_role_fit']:.3f} "
            f"not_targeted={len(report['not_targeted_segments'])}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
