"""Customer-facing feature gate.

proof_loop_hardening_sprint, Phase 5.

The customer-facing product layer (/api/customer/*, /model-portfolio
page, basket registry UI, customer-language translator) was added
*before* the proof loop closed.  Until the proof loop closes, this
layer must be off by default, and even when force-enabled it must be
labelled DEMO_ONLY / UNCALIBRATED.

Hard rule (math)::

    customer_facing_enabled =
        env_flag_true
      AND N_real >= 20
      AND evidence_status IN {
          SUFFICIENT_FOR_INVESTOR_DEMO,
          SUFFICIENT_FOR_PRIVATE_BETA,
        }

The local-dev override `MVP_ENABLE_CUSTOMER_FACING=1` flips
`env_flag_true` to True, but does NOT lower the `N_real` floor.  When
the floor fails, the gate still reports
`customer_facing_enabled = False` but allows a `demo_only_label =
"DEMO_ONLY / UNCALIBRATED"` so the UI can render the work for review.

Safety
~~~~~~
* Read-only.  Reads at most ``runtime/release/calibration_report.json``
  and ``runtime/release/evidence_manifest.json``.  Never writes.
* No broker / order / fill / position / execution path.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


ENV_FLAG_NAME = "MVP_ENABLE_CUSTOMER_FACING"
INVESTOR_READY_STATUSES = frozenset({
    "SUFFICIENT_FOR_INVESTOR_DEMO",
    "SUFFICIENT_FOR_PRIVATE_BETA",
})
N_REAL_FLOOR = 20

CUSTOMER_FACING_DISABLED_MESSAGE = (
    "Customer-facing mode is disabled until proof loop has at least "
    "N_real >= 20 and evidence_status is investor-demo eligible."
)
CUSTOMER_FACING_DEMO_LABEL = "DEMO_ONLY / UNCALIBRATED"


@dataclass(frozen=True)
class CustomerFacingGateState:
    customer_facing_enabled: bool
    env_flag_true: bool
    n_real: int
    n_real_floor: int
    evidence_status: str
    calibration_status: str
    demo_only_label: str | None
    disabled_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_facing_enabled": bool(self.customer_facing_enabled),
            "env_flag_true": bool(self.env_flag_true),
            "n_real": int(self.n_real),
            "n_real_floor": int(self.n_real_floor),
            "evidence_status": str(self.evidence_status),
            "calibration_status": str(self.calibration_status),
            "demo_only_label": self.demo_only_label,
            "disabled_message": self.disabled_message,
        }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _env_flag_true(env: dict[str, str] | None) -> bool:
    env = env if env is not None else os.environ
    raw = str(env.get(ENV_FLAG_NAME) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def evaluate_gate(
    *,
    env: dict[str, str] | None = None,
    calibration_report_path: Path | None = None,
    evidence_manifest_path: Path | None = None,
) -> CustomerFacingGateState:
    """Pure evaluation of the gate.  Reads at most two JSON files."""
    env_flag_true = _env_flag_true(env)

    cr_path = (
        calibration_report_path
        or _REPO_ROOT / "runtime" / "release" / "calibration_report.json"
    )
    em_path = (
        evidence_manifest_path
        or _REPO_ROOT / "runtime" / "release" / "evidence_manifest.json"
    )

    cr = _read_json(cr_path)
    em = _read_json(em_path)

    calibration_status = str(
        cr.get("calibration_status") or "INSUFFICIENT_EVIDENCE"
    ).strip().upper()
    try:
        n_real = int(cr.get("n_real") or cr.get("N_real") or 0)
    except (TypeError, ValueError):
        n_real = 0

    evidence_status = str(
        em.get("evidence_status") or "EMPTY"
    ).strip().upper()

    proof_loop_passes = (
        n_real >= N_REAL_FLOOR
        and evidence_status in INVESTOR_READY_STATUSES
    )
    customer_facing_enabled = bool(env_flag_true and proof_loop_passes)

    demo_only_label: str | None = None
    disabled_message: str | None = None
    if not customer_facing_enabled:
        if env_flag_true:
            # Local-dev override: show the work but flag it.
            demo_only_label = CUSTOMER_FACING_DEMO_LABEL
        else:
            disabled_message = CUSTOMER_FACING_DISABLED_MESSAGE

    return CustomerFacingGateState(
        customer_facing_enabled=customer_facing_enabled,
        env_flag_true=env_flag_true,
        n_real=int(n_real),
        n_real_floor=N_REAL_FLOOR,
        evidence_status=evidence_status,
        calibration_status=calibration_status,
        demo_only_label=demo_only_label,
        disabled_message=disabled_message,
    )


def stamp_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the gate state to a customer-facing API response."""
    state = evaluate_gate()
    out = dict(payload)
    out["customer_facing_gate"] = state.to_dict()
    return out


__all__ = [
    "CUSTOMER_FACING_DEMO_LABEL",
    "CUSTOMER_FACING_DISABLED_MESSAGE",
    "CustomerFacingGateState",
    "ENV_FLAG_NAME",
    "INVESTOR_READY_STATUSES",
    "N_REAL_FLOOR",
    "evaluate_gate",
    "stamp_payload",
]
