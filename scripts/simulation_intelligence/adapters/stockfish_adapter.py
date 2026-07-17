"""Optional Stockfish adapter — the ONE real EXTERNAL_PROCESS integration.

Stockfish is a GPLv3 UCI chess engine.  Running it via an arm's-length
subprocess does not contaminate our code.  It is behind ``SIL_STOCKFISH_ENABLED``
(default OFF) and is NEVER on the default council path — the chess LENS uses a
native bounded-search transplant.  This adapter exists so the search-discipline
principle can be *demonstrated* against a real engine when an operator opts in.

Safety:
* subprocess with a FIXED argument list — no shell, no user input interpolation
* a hard timeout and single-thread pin (determinism)
* only runs if the binary is present AND the flag is on
* never raises: any failure degrades to ``available=False``

This adapter deliberately does not accept arbitrary FEN/positions from the API;
it evaluates a fixed startpos as a liveness/determinism proof only.  It has NO
market role and NO execution capability.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

try:
    from scripts.simulation_intelligence.adapters.base import (
        SimulationEngineAdapter, AdapterStatus, AdapterReport,
    )
    from scripts.simulation_intelligence import feature_flags as flags
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.adapters.base import (  # type: ignore[no-redef]
        SimulationEngineAdapter, AdapterStatus, AdapterReport,
    )
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]

_BINARY_NAMES = ("stockfish", "stockfish.exe")


def _find_binary() -> str | None:
    for name in _BINARY_NAMES:
        path = shutil.which(name)
        if path:
            return path
    return None


class StockfishAdapter(SimulationEngineAdapter):
    engine = "Stockfish"
    integration_mode = "EXTERNAL_PROCESS"
    transplanted_into = "chess"

    def is_available(self) -> bool:
        return flags.stockfish_enabled() and _find_binary() is not None

    def status(self) -> AdapterStatus:
        if not flags.stockfish_enabled():
            return AdapterStatus.DISABLED
        if _find_binary() is None:
            return AdapterStatus.UNAVAILABLE
        return AdapterStatus.AVAILABLE

    def report(self) -> AdapterReport:
        st = self.status()
        detail = {
            AdapterStatus.DISABLED: "SIL_STOCKFISH_ENABLED is off (default); chess lens uses native search",
            AdapterStatus.UNAVAILABLE: "stockfish binary not on PATH",
            AdapterStatus.AVAILABLE: "stockfish present; available as a search-discipline demonstration only",
        }.get(st, "")
        return AdapterReport(
            engine=self.engine, integration_mode=self.integration_mode,
            status=st.value, transplanted_into=self.transplanted_into, detail=detail,
        )

    def liveness_probe(self, movetime_ms: int = 50) -> dict[str, Any]:
        """Deterministic liveness probe: single-thread bestmove on startpos.

        Never raises; returns ``available=False`` on any problem.  This is a
        proof-of-integration only — it has no market meaning.
        """
        if not self.is_available():
            return {"available": False, "reason": self.status().value}
        binary = _find_binary()
        movetime = max(10, min(int(movetime_ms), 1000))
        commands = (
            "uci\n"
            "setoption name Threads value 1\n"
            "setoption name Hash value 16\n"
            "position startpos\n"
            f"go movetime {movetime}\n"
            "quit\n"
        )
        try:  # pragma: no cover - only runs when a real binary is present + enabled
            proc = subprocess.run(
                [binary],
                input=commands,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            bestmove = ""
            for line in proc.stdout.splitlines():
                if line.startswith("bestmove"):
                    bestmove = line.split()[1] if len(line.split()) > 1 else ""
                    break
            return {
                "available": True,
                "engine": "stockfish",
                "bestmove": bestmove,
                "deterministic": True,
                "threads": 1,
                "real_execution_allowed": False,
            }
        except Exception as exc:
            return {"available": False, "reason": f"stockfish_error:{type(exc).__name__}"}


__all__ = ["StockfishAdapter"]
