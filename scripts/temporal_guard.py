"""Anti-leakage temporal guard (Pass 4) — no time travel in evaluation.

The single most common way a backtest lies is by letting information from
the future leak into the past. This module enforces the ordering contract
for every (feature, decision, outcome) triple used in evaluation:

    t_published ≤ t_observed ≤ t_decision < t_outcome

* ``t_published`` — when the information became public;
* ``t_observed``  — when it entered THIS system;
* ``t_decision``  — when the advisory signal was generated;
* ``t_outcome``   — when the outcome is measured.

Any violation marks the sample INVALID for backtest/evaluation — it is
never silently dropped or silently kept; the reason is recorded. Naive
(timezone-less) timestamps are violations by definition: IST vs CET vs
UTC confusion is exactly how "the article was published before my
decision" turns out to be false by 4.5 hours.

A manual override exists for deliberate research exceptions but requires
an explicit reason and writes a tamper-evident audit event — there is no
quiet way to bless leaked data.

Advisory-only: this module evaluates data hygiene; it cannot execute
anything. See docs/TEMPORAL_INTEGRITY.md for worked examples of
lookahead and survivorship bias.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from typing import Iterable

VALID = "valid"
INVALID = "invalid"
OVERRIDDEN = "overridden"


class TemporalError(ValueError):
    """Raised for unusable timestamp input (missing/naive/unparsable)."""


def parse_utc(value: str | _dt.datetime | None, field: str) -> _dt.datetime | None:
    """Parse to aware-UTC. Naive timestamps are refused, not assumed."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, _dt.datetime):
        dt = value
    else:
        try:
            dt = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise TemporalError(f"{field}: unparsable timestamp {value!r}") from exc
    if dt.tzinfo is None:
        raise TemporalError(
            f"{field}: naive timestamp {value!r} — refuse rather than guess "
            "a timezone (IST/CET/UTC offsets are leakage-sized)"
        )
    return dt.astimezone(_dt.timezone.utc)


@dataclasses.dataclass(frozen=True)
class TemporalVerdict:
    status: str  # valid | invalid | overridden
    reasons: tuple[str, ...]
    advisory_only: bool = True

    @property
    def usable_for_evaluation(self) -> bool:
        return self.status in (VALID, OVERRIDDEN)


def validate_sample(
    *,
    t_decision: str | _dt.datetime,
    t_outcome: str | _dt.datetime | None = None,
    t_observed: str | _dt.datetime | None = None,
    t_published: str | _dt.datetime | None = None,
) -> TemporalVerdict:
    """Enforce t_published ≤ t_observed ≤ t_decision < t_outcome.

    ``t_decision`` is mandatory. ``t_observed``/``t_published`` are
    optional per-feature; ``t_outcome`` is mandatory when the sample is
    used to score an outcome. Missing-but-required and naive timestamps
    are INVALID, with reasons.
    """
    reasons: list[str] = []
    try:
        decision = parse_utc(t_decision, "t_decision")
    except TemporalError as exc:
        return TemporalVerdict(INVALID, (str(exc),))
    if decision is None:
        return TemporalVerdict(INVALID, ("t_decision missing — a signal without a "
                                         "decision time cannot be evaluated",))

    observed = published = outcome = None
    for name, value in (("t_observed", t_observed), ("t_published", t_published),
                        ("t_outcome", t_outcome)):
        try:
            parsed = parse_utc(value, name)
        except TemporalError as exc:
            reasons.append(str(exc))
            continue
        if name == "t_observed":
            observed = parsed
        elif name == "t_published":
            published = parsed
        else:
            outcome = parsed

    if published is not None and observed is not None and published > observed:
        reasons.append(
            "t_published > t_observed: data 'published' after the system saw "
            "it — usually a revised/restated figure stamped with its original "
            "id (revision leakage)"
        )
    if observed is not None and observed > decision:
        reasons.append(
            "t_observed > t_decision: feature entered the system AFTER the "
            "signal was generated — lookahead leakage"
        )
    if published is not None and observed is None and published > decision:
        reasons.append(
            "t_published > t_decision: information became public after the "
            "decision (e.g. earnings released later that day) — lookahead "
            "leakage"
        )
    if outcome is not None and outcome <= decision:
        reasons.append(
            "t_outcome <= t_decision: outcome measured at or before the "
            "decision — the 'outcome' is part of the input (target leakage)"
        )
    if reasons:
        return TemporalVerdict(INVALID, tuple(reasons))
    return TemporalVerdict(VALID, ())


def override_sample(
    verdict: TemporalVerdict,
    *,
    reason: str,
    actor: str = "owner",
) -> TemporalVerdict:
    """Deliberate research override of an INVALID verdict.

    Requires a non-empty reason and writes a tamper-evident audit event —
    blessed leakage must be loud and attributable, never silent.
    """
    if verdict.status != INVALID:
        return verdict
    if not reason or not reason.strip():
        raise TemporalError("override requires an explicit non-empty reason")
    try:
        from scripts.audit_log import append_event
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from audit_log import append_event  # type: ignore[no-redef]
    append_event(
        "settings_change",
        actor=actor if actor in ("owner", "system") else "unknown",
        action="temporal_guard_override",
        outcome="override_granted",
        metadata={"reason": reason.strip(), "original_reasons": "; ".join(verdict.reasons)[:160]},
    )
    return TemporalVerdict(OVERRIDDEN, verdict.reasons + (f"override: {reason.strip()}",))


def filter_evaluation_samples(samples: Iterable[dict]) -> dict:
    """Partition samples into usable/rejected for backtesting.

    Each sample dict carries t_decision / t_outcome / t_observed /
    t_published keys (ISO strings or datetimes). Returns
    ``{"usable": [...], "rejected": [(sample, reasons), ...]}`` — the
    rejection list is part of the contract: silent drops hide bias.
    """
    usable: list[dict] = []
    rejected: list[tuple[dict, tuple[str, ...]]] = []
    for sample in samples:
        verdict = validate_sample(
            t_decision=sample.get("t_decision"),
            t_outcome=sample.get("t_outcome"),
            t_observed=sample.get("t_observed"),
            t_published=sample.get("t_published"),
        )
        if verdict.usable_for_evaluation:
            usable.append(sample)
        else:
            rejected.append((sample, verdict.reasons))
    return {"usable": usable, "rejected": rejected}
