'use client';

/**
 * First Real Rows + Kanté Score Push sprint — Phase 3 container.
 *
 * Fetches the read-only `/evidence/*` backend surface and renders the
 * presentational `RealEvidenceCards`.  When an endpoint is unavailable the card
 * renders DEGRADED (never a green/LIVE chip on missing data); a mock fallback is
 * never shown as live; the predictive claim shows PREDICTIVE_CLAIM_LOCKED unless
 * the backend explicitly unlocks it.  No execution wording, no real-money claim.
 */
import { useEffect, useState } from 'react';

import {
  getEvidenceSourceTruth,
  getEvidenceCalibration,
  getEvidenceScoring,
  getEvidenceOutcomes,
  getEvidenceBundle,
  getEvidenceLiveDecisionPath,
  getEvidenceCapacityRisk,
  type EvidenceSourceTruthResponse,
  type EvidenceCalibrationResponse,
  type EvidenceScoringResponse,
  type EvidenceOutcomesResponse,
  type EvidenceBundleResponse,
  type EvidenceLiveDecisionResponse,
  type EvidenceCapacityRiskResponse,
} from '@/lib/apiClient';
import {
  mapSourceTruthProps,
  mapCalibrationProps,
  mapScoringProps,
  mapOutcomeLoopProps,
  mapBundleProps,
  mapLiveDecisionProps,
  mapCapacityRiskProps,
} from '@/lib/realEvidenceWiring';
import {
  SourceTruthCard,
  LiveDecisionPathCard,
  CapacityCorrelationCard,
  CalibrationEvidenceCard,
  OutcomeLoopCard,
  ScoringCoverageCard,
  EvidenceBundleCard,
} from '@/components/RealEvidenceCards';

interface EvidenceState {
  sourceTruth: EvidenceSourceTruthResponse | null;
  calibration: EvidenceCalibrationResponse | null;
  scoring: EvidenceScoringResponse | null;
  outcomes: EvidenceOutcomesResponse | null;
  bundle: EvidenceBundleResponse | null;
  decision: EvidenceLiveDecisionResponse | null;
  capacity: EvidenceCapacityRiskResponse | null;
}

const EMPTY: EvidenceState = {
  sourceTruth: null,
  calibration: null,
  scoring: null,
  outcomes: null,
  bundle: null,
  decision: null,
  capacity: null,
};

export function RealEvidenceLiveCards() {
  // Default state is all-null => every card renders DEGRADED until the backend
  // answers.  Missing data is never rendered as live.
  const [state, setState] = useState<EvidenceState>(EMPTY);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [sourceTruth, calibration, scoring, outcomes, bundle, decision, capacity] =
        await Promise.all([
          getEvidenceSourceTruth(),
          getEvidenceCalibration(),
          getEvidenceScoring(),
          getEvidenceOutcomes(),
          getEvidenceBundle(),
          getEvidenceLiveDecisionPath(),
          getEvidenceCapacityRisk(),
        ]);
      if (!cancelled) {
        setState({ sourceTruth, calibration, scoring, outcomes, bundle, decision, capacity });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-testid="real-evidence-live-cards" className="grid gap-4 md:grid-cols-2">
      <SourceTruthCard {...mapSourceTruthProps(state.sourceTruth)} />
      <LiveDecisionPathCard {...mapLiveDecisionProps(state.decision)} />
      <CapacityCorrelationCard {...mapCapacityRiskProps(state.capacity)} />
      <CalibrationEvidenceCard {...mapCalibrationProps(state.calibration)} />
      <OutcomeLoopCard {...mapOutcomeLoopProps(state.outcomes)} />
      <ScoringCoverageCard {...mapScoringProps(state.scoring)} />
      <EvidenceBundleCard {...mapBundleProps(state.bundle)} />
    </div>
  );
}

export default RealEvidenceLiveCards;
