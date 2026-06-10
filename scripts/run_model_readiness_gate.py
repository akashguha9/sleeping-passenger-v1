"""Single-command model readiness gate (Pass 5, Phase 12).

    python scripts/run_model_readiness_gate.py

Runs every model-quality control against the live modules and fails
closed (exit 1) on any severe violation: execution capability appearing
anywhere, an unsourced LLM claim carrying weight, future data surviving
evaluation, severe weight-sanity findings, a red-team failure, a banned
phrase escaping the memo guard, a scorecard exceeding its evidence cap,
or a broken advisory-only invariant.

Stdlib + repo modules only, fast enough for CI.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

UTC = _dt.timezone.utc


def _check(name: str, fn) -> tuple[str, bool, str]:
    try:
        ok, detail = fn()
        return name, bool(ok), str(detail)
    except Exception as exc:  # a crashing gate is a failing gate
        return name, False, f"exception: {type(exc).__name__}: {exc}"


def gate_registry() -> tuple[bool, str]:
    data = json.loads((_REPO_ROOT / "model_registry.json").read_text(encoding="utf-8"))
    bad = [m["name"] for m in data["models"]
           if m.get("execution_capable") is not False
           or m.get("human_required") is not True
           or m.get("uses_future_data") is not False
           or not str(m.get("owner", "")).strip()]
    return not bad, f"{len(data['models'])} models; violations: {bad or 'none'}"


def gate_invariants() -> tuple[bool, str]:
    from scripts import runtime_config as rc

    ok = (rc.ADVISORY_STATUS == "ADVISORY_ONLY"
          and rc.EXECUTION_MODE == "HUMAN_ONLY"
          and rc.EXECUTION_GATE == "LOCKED"
          and rc.AI_EXECUTION_COUNT == 0
          and rc.BROKER_API_CALLED is False)
    return ok, "ADVISORY_ONLY / HUMAN_ONLY / LOCKED / 0 / False"


def gate_evidence_ledger() -> tuple[bool, str]:
    from scripts import data_quality as dq

    violations = dq.verify_ledger()
    return not violations, f"ledger violations: {len(violations)}"


def gate_temporal() -> tuple[bool, str]:
    from scripts import temporal_guard as tg

    dec = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    leak = tg.validate_sample(t_decision=dec, t_published=dec + _dt.timedelta(hours=1),
                              t_outcome=dec + _dt.timedelta(days=1))
    clean = tg.validate_sample(t_decision=dec, t_published=dec - _dt.timedelta(days=1),
                               t_outcome=dec + _dt.timedelta(days=1))
    ok = leak.status == tg.INVALID and clean.status == tg.VALID
    return ok, "future data invalid, clean data valid"


def gate_llm_grounding() -> tuple[bool, str]:
    from scripts import llm_grounding_guard as gg

    unsourced = gg.ground_claim(claim="X will moon", symbol="ACME",
                                base_weight=0.9, evidence_items=[])
    halluc = gg.ground_claim(claim="fake co", symbol="FAKE", base_weight=0.9,
                             evidence_items=[{"evidence_id": "E", "symbol": "FAKE",
                                              "confidence": 1.0, "claim": "fake co"}],
                             known_symbols={"ACME"})
    ok = unsourced.weight == 0.0 and halluc.classification == gg.REJECTED
    return ok, "unsourced weight=0; hallucinated ticker rejected"


def gate_weight_sanity() -> tuple[bool, str]:
    from scripts import weight_sanity as ws

    result = ws.run_sanity()
    return result["severe_count"] == 0, f"severe findings: {result['severe_count']}"


def gate_sensitivity_on_production_weights() -> tuple[bool, str]:
    from scripts import sensitivity_analysis as sa
    from scripts.daily_scoring import FCS_WEIGHTS

    report = sa.analyze(dict(FCS_WEIGHTS),
                        {k: 0.8 for k in FCS_WEIGHTS},
                        decision_threshold=0.5, require_weight_sum_1=True)
    # A confidently-clean input set must not ABSTAIN; fragility on
    # borderline inputs is expected and surfaced elsewhere.
    return report["recommendation"] == sa.PROCEED, (
        f"production FCS weights on strong inputs → {report['recommendation']}"
    )


def gate_redteam() -> tuple[bool, str]:
    from scripts import redteam_model as rt

    cases = rt.run_cases()
    failed = [c["name"] for c in cases if not c["ok"]]
    return not failed, f"{len(cases) - len(failed)}/{len(cases)} safe; failed: {failed or 'none'}"


def gate_tournament_synthetic() -> tuple[bool, str]:
    import tempfile

    from scripts import signal_tournament as st

    t0 = _dt.datetime(2026, 1, 1, tzinfo=UTC)
    samples = [{
        "signal_id": f"G{i}", "symbol": "SYN",
        "t_decision": (t0 + _dt.timedelta(days=i)).isoformat(),
        "t_outcome": (t0 + _dt.timedelta(days=i + 5)).isoformat(),
        "features": {k: 0.7 for k in ("acqs", "mean_model_score",
                                      "cross_model_agreement", "why_today_score",
                                      "data_quality", "freshness_score",
                                      "liquidity_quality")},
        "net_return": 0.01 if i % 2 else -0.005,
    } for i in range(40)]
    with tempfile.TemporaryDirectory() as tmp:
        result = st.run_tournament(
            samples, oos_start=(t0 + _dt.timedelta(days=20)).isoformat(),
            ledger_path=Path(tmp) / "ledger.jsonl",
        )
    ok = result["ranking_basis"] == "out_of_sample_only" and result["NOT_AN_ORDER"]
    return ok, f"ranking_basis={result['ranking_basis']}"


def gate_memo_banned_phrases() -> tuple[bool, str]:
    from scripts import generate_decision_memo as memo

    for phrase in memo.BANNED_PHRASES:
        try:
            memo.render_memo({"ticker": "ACME", "signal": f"this is {phrase}"})
            return False, f"banned phrase {phrase!r} ESCAPED the guard"
        except memo.MemoError:
            continue
    return True, f"all {len(memo.BANNED_PHRASES)} banned phrases refused"


def gate_scorecard_caps() -> tuple[bool, str]:
    from scripts import model_scorecard as sc

    score, note = sc.apply_evidence_caps(
        10.0, has_tests=True, has_out_of_sample=True,
        has_independent_validation=False)
    return score < 10.0 and note is not None, "10 without independent validation clamped"


def gate_shadow_ledger_contract() -> tuple[bool, str]:
    from scripts import signal_tournament as st

    try:
        st.append_shadow_observation({"variant": "x", "order_id": "evil"},
                                     path=Path("/tmp/never-written.jsonl"))
        return False, "order-shaped row was ACCEPTED"
    except st.LedgerContractError:
        return True, "order-shaped ledger row refused"


GATES = (
    ("advisory_invariants", gate_invariants),
    ("model_registry", gate_registry),
    ("evidence_ledger", gate_evidence_ledger),
    ("temporal_guard", gate_temporal),
    ("llm_grounding", gate_llm_grounding),
    ("weight_sanity", gate_weight_sanity),
    ("sensitivity_production_weights", gate_sensitivity_on_production_weights),
    ("redteam", gate_redteam),
    ("signal_tournament_synthetic", gate_tournament_synthetic),
    ("memo_banned_phrases", gate_memo_banned_phrases),
    ("scorecard_evidence_caps", gate_scorecard_caps),
    ("shadow_ledger_contract", gate_shadow_ledger_contract),
)


def main() -> int:
    print(f"model readiness gate · {_dt.datetime.now(UTC).isoformat()}")
    failures = 0
    for name, fn in GATES:
        gname, ok, detail = _check(name, fn)
        print(f"  [{'PASS' if ok else 'FAIL'}] {gname}: {detail}")
        if not ok:
            failures += 1
    print(f"result: {'PASS' if failures == 0 else f'FAIL ({failures} gate(s))'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
