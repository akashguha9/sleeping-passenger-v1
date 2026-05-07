from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RenderedRealityPacket:
    signal_id: str
    mode: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def render_reality_packet(
    packet: dict[str, Any],
    *,
    mode: str,
    failure_record: dict[str, Any] | None = None,
) -> RenderedRealityPacket:
    normalized_mode = str(mode or "validate").lower()
    lens_rows = packet.get("lens_interpretations", [])
    context_profile = packet.get("context_profile", {})
    if normalized_mode == "scout":
        payload = {
            "possible_meanings": [
                {
                    "lens_name": row.get("lens_name"),
                    "meaning_label": row.get("meaning_label"),
                    "meaning_score": row.get("meaning_score"),
                }
                for row in lens_rows
            ],
            "context_profile": context_profile,
        }
    elif normalized_mode == "execute":
        payload = {
            "entry": packet.get("raw_signal", {}).get("entry_condition", "INTERPRET_FIRST"),
            "size": packet.get("recommended_action"),
            "invalidation": packet.get("raw_signal", {}).get("invalidation", "DRIFT_OR_VALIDATION_FAILURE"),
            "exit_logic": packet.get("raw_signal", {}).get("exit_logic", "REVIEW_ON_CONTEXT_BREAK"),
            "interpretation_confidence": packet.get("interpretation_confidence"),
            "chaos_veto": packet.get("chaos_veto"),
        }
    elif normalized_mode == "risk":
        payload = {
            "ambiguity": packet.get("reason_codes", []),
            "interpretation_drift": packet.get("interpretation_drift"),
            "chaos_veto": packet.get("chaos_veto"),
            "liquidity": context_profile.get("liquidity"),
            "spread": context_profile.get("spread"),
            "regime": context_profile.get("regime"),
        }
    elif normalized_mode == "review":
        payload = {
            "failure_attribution": failure_record or {},
            "selected_interpretation": packet.get("selected_interpretation"),
            "interpretation_confidence": packet.get("interpretation_confidence"),
            "reason_codes": packet.get("reason_codes", []),
        }
    else:
        payload = {
            "selected_interpretation": packet.get("selected_interpretation"),
            "interpretation_drift": packet.get("interpretation_drift"),
            "interpretation_confidence": packet.get("interpretation_confidence"),
            "context_assumptions": context_profile,
            "recommended_action": packet.get("recommended_action"),
        }
        normalized_mode = "validate"
    return RenderedRealityPacket(
        signal_id=str(packet.get("signal_id", "UNKNOWN")),
        mode=normalized_mode,
        payload=payload,
    )
