"""CLI wrapper: build today's real PEG observations, then mature horizons.

Invoked by the scheduled refresh wrapper after the state capture.  Safe
when inputs are missing — every gap is reported, nothing is fabricated.
RESEARCH_ONLY; read-only over canonical data, writes only the PEG corpus.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timezone, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.quant_peg_dataset_builder import (
    build_new_observations,
    mature_observations,
    real_peg_census,
)


def main() -> int:
    run_date = datetime.now(timezone.utc).date().isoformat()
    build = build_new_observations(run_date=run_date)
    mature = mature_observations()
    census = real_peg_census()
    print(json.dumps({"build": build, "mature": mature,
                      "census": census}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
