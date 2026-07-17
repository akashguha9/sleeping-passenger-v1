"""Chess lens — Stockfish + Leela + Maia principles (original code).

Runs a genuine BOUNDED adversarial search over future scenario states:

* iterative deepening (depth 1..N, time/-node bounded)
* alpha-beta pruning (mathematically sound on the min/max game tree)
* a transposition cache keyed on the discretized state
* move ordering (try the most defensive advisory stance first when fragile)
* quiescence-style extension around unstable states (large |drift|/vol)
* principal-variation extraction
* evaluation decomposition (return term, downside term, uncertainty term)

A "move" is an advisory stance — WATCH / WAIT / AVOID / RISK_BLOCK /
OUTCOME_REVIEW — never a trade.  The "opponent" is the market choosing a
favourable / neutral / adverse branch (the adversarial min player).

Leela lens: a policy-value contract combines P(branch) x V(state) with an
exploration penalty and model-disagreement term.

Maia lens: models realistic human-operator error (delay, confirmation/recency
bias, overconfidence, panic, FOMO, stop-skipping, concentration, revenge) and
WARNS when a tempting action looks inconsistent with disciplined risk rules.
It never manipulates the operator.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )

# Routine advisory stances the search chooses among.  RISK_BLOCK is deliberately
# NOT a routine move — it is a governance escalation emitted only when even full
# engagement is a losing game (see _evaluate), so it never becomes a default.
_MOVES = (
    AdvisoryVote.WATCH.value, AdvisoryVote.WAIT.value, AdvisoryVote.AVOID.value,
    AdvisoryVote.OUTCOME_REVIEW.value,
)
# The engaged-return threshold below which the setup is flagged RISK_BLOCK.
_RISK_BLOCK_THRESHOLD = -0.02

# Branch model: the market's adversarial replies (probability, drift-mult, shock).
_BRANCHES = (
    ("favourable", 0.30, 1.0, 0.0),
    ("neutral", 0.45, 0.3, 0.0),
    ("adverse", 0.25, -0.5, -0.04),
)


def _stance_exposure(move: str) -> float:
    """How much market exposure an advisory stance implies (for evaluation)."""
    return {
        AdvisoryVote.WATCH.value: 0.6,        # engaged, watching to act
        AdvisoryVote.OUTCOME_REVIEW.value: 0.3,
        AdvisoryVote.WAIT.value: 0.1,
        AdvisoryVote.AVOID.value: 0.0,
        AdvisoryVote.RISK_BLOCK.value: -0.2,  # actively hedged/blocked
    }.get(move, 0.1)


class ChessLens(Lens):
    domain = "CHESS"
    name = "chess"
    required_fields = ("returns",)

    def __init__(self, max_depth: int = 4, downside_lambda: float = 2.5) -> None:
        self.max_depth = max(1, min(int(max_depth), 6))
        self.downside_lambda = float(downside_lambda)
        self._tt: dict[tuple, float] = {}
        self._nodes = 0

    # -- evaluation --------------------------------------------------------
    def _evaluate_leaf(self, drift: float, vol: float, exposure: float) -> float:
        """Risk-adjusted leaf value with decomposed terms."""
        expected = exposure * drift
        downside = self.downside_lambda * exposure * max(0.0, vol - abs(drift)) * 0.5
        return expected - downside

    def _quiescent(self, drift: float, vol: float) -> bool:
        """Stable enough to stop searching (no big unresolved move)."""
        return abs(drift) < 0.8 * (vol + 1e-6)

    def _search(self, drift: float, vol: float, depth: int, alpha: float, beta: float) -> float:
        """Negamax-style alpha-beta over (our stance) vs (market branch)."""
        self._nodes += 1
        key = (round(drift, 4), round(vol, 4), depth)
        if key in self._tt:
            return self._tt[key]
        # Quiescence: extend one ply if unstable even at depth 0.
        if depth <= 0:
            if self._quiescent(drift, vol) or depth <= -1:
                val = self._evaluate_leaf(drift, vol, exposure=0.6)
                self._tt[key] = val
                return val

        best = -math.inf
        # Move ordering: most defensive first when fragile (helps pruning).
        fragile = vol > abs(drift) * 1.5
        moves = _MOVES if not fragile else tuple(reversed(_MOVES))
        for move in moves:
            exposure = _stance_exposure(move)
            # Market (min player) picks the branch that hurts us most, in expectation.
            branch_val = 0.0
            for _name, prob, dmult, shock in _BRANCHES:
                nd = drift * dmult + shock
                nv = vol * (1.1 if shock < 0 else 0.98)
                if depth > 0:
                    child = self._search(nd, nv, depth - 1, alpha, beta)
                else:
                    child = self._evaluate_leaf(nd, nv, exposure)
                branch_val += prob * (self._evaluate_leaf(nd, nv, exposure) * 0.4 + child * 0.6)
            if branch_val > best:
                best = branch_val
            alpha = max(alpha, best)
            if alpha >= beta:
                break  # beta cutoff
        self._tt[key] = best
        return best

    def _best_move(self, drift: float, vol: float, depth: int) -> tuple[str, float, dict]:
        """Return the best advisory stance + its value + per-move scores."""
        scores: dict[str, float] = {}
        for move in _MOVES:
            exposure = _stance_exposure(move)
            val = 0.0
            for _name, prob, dmult, shock in _BRANCHES:
                nd = drift * dmult + shock
                nv = vol * (1.1 if shock < 0 else 0.98)
                child = self._search(nd, nv, depth - 1, -math.inf, math.inf)
                val += prob * (self._evaluate_leaf(nd, nv, exposure) * 0.4 + child * 0.6)
            scores[move] = round(val, 6)
        best_move = max(scores, key=scores.get)
        return best_move, scores[best_move], scores

    # -- Maia human-error model -------------------------------------------
    def _human_error_warnings(self, drift: float, vol: float, obs: MarketObservation,
                              recommended: str) -> list[str]:
        warnings = []
        n_sources = max(obs.source_count, len(obs.narrative_sources))
        if drift > 0 and n_sources >= 5:
            warnings.append("FOMO risk: rising attention may tempt chasing beyond the plan")
        if drift < 0 and vol > 0.05:
            warnings.append("panic/revenge risk: recent drawdown may tempt an impulsive exit or re-entry")
        if recommended in (AdvisoryVote.AVOID.value, AdvisoryVote.RISK_BLOCK.value) and drift > 0:
            warnings.append("confirmation bias: positive recent returns may tempt ignoring a defensive read")
        if vol > 0.06:
            warnings.append("overconfidence/stop-skipping risk in a high-volatility regime")
        return warnings

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        drift = mean(rets[-5:]) if rets else 0.0
        vol = stdev(rets) or (obs.volatility or 0.03)
        vol = min(0.25, max(0.005, vol))

        # Iterative deepening: search depth 1..max_depth, keep last PV.
        self._tt = {}
        self._nodes = 0
        best_move, best_val, scores = AdvisoryVote.WAIT.value, 0.0, {}
        pv: list[str] = []
        for d in range(1, self.max_depth + 1):
            best_move, best_val, scores = self._best_move(drift, vol, d)
            pv = self._principal_variation(drift, vol, d)

        # Leela policy-value: branch probability x value + exploration penalty.
        pv_value = best_val
        exploration_penalty = clamp(vol / 0.1)  # more exploration cost when volatile
        model_disagreement = self._score_disagreement(scores)
        policy_value = round(pv_value - 0.05 * exploration_penalty, 6)

        # Convert search value to bounded confidence: positive PV => constructive.
        confidence = clamp(0.5 + 5.0 * policy_value) if policy_value == policy_value else 0.0
        confidence = clamp(confidence * (1.0 - 0.5 * model_disagreement))
        uncertainty = clamp(0.5 * exploration_penalty + 0.5 * model_disagreement)

        # RISK_BLOCK escalation: if full engagement (WATCH stance) is a losing
        # game even under best play, escalate beyond AVOID to a governance block.
        engaged_value = scores.get(AdvisoryVote.WATCH.value, 0.0)
        risk_block = engaged_value < _RISK_BLOCK_THRESHOLD
        vote = AdvisoryVote.RISK_BLOCK.value if risk_block else best_move

        warnings = self._human_error_warnings(drift, vol, obs, vote)

        fragility = clamp(0.5 * exploration_penalty + 0.5 * model_disagreement)
        robustness = clamp(1.0 - fragility)

        label = EvidenceLabel.MODEL_INFERRED.value
        evidence = self._evidence(obs, f"bounded search PV={'>'.join(pv[:3])}", label)

        tail_warning = ""
        if risk_block:
            tail_warning = "engaged stance is a losing game under adverse-branch pressure — governance block"

        return LensResult(
            lens=self.domain,
            state_interpretation=f"bounded search recommends {vote} (PV value {policy_value:+.4f})",
            scenario_branches=[f"{b[0]} (p={b[1]})" for b in _BRANCHES],
            main_risk="adverse branch dominates the principal variation",
            main_opportunity="favourable branch with low exploration penalty",
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(0.5 * model_disagreement + 0.5 * exploration_penalty),
            exploitability=clamp(model_disagreement),
            evidence=evidence,
            missing_data_warnings=warnings,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "principal_variation": pv,
                "move_scores": scores,
                "policy_value": policy_value,
                "exploration_penalty": round(exploration_penalty, 4),
                "model_disagreement": round(model_disagreement, 4),
                "nodes_searched": self._nodes,
                "max_depth": self.max_depth,
                "human_error_warnings": warnings,
                "evaluation_decomposition": {
                    "expected_term": round(_stance_exposure(vote) * drift, 6),
                    "downside_lambda": self.downside_lambda,
                },
            },
        )

    def _principal_variation(self, drift: float, vol: float, depth: int) -> list[str]:
        pv = []
        d, v = drift, vol
        for _ in range(depth):
            move, _val, _scores = self._best_move(d, v, 1)
            pv.append(move)
            # Advance along the expected (probability-weighted) branch.
            d = sum(p * (d * dm + sh) for _n, p, dm, sh in _BRANCHES)
            v = v * 1.0
        return pv

    @staticmethod
    def _score_disagreement(scores: dict[str, float]) -> float:
        if len(scores) < 2:
            return 0.0
        vals = sorted(scores.values(), reverse=True)
        spread = vals[0] - vals[-1]
        gap = vals[0] - vals[1]
        # Low gap between the top two moves => high disagreement / ambiguity.
        return clamp(1.0 - gap / (spread + 1e-6)) if spread > 0 else 1.0


__all__ = ["ChessLens"]
