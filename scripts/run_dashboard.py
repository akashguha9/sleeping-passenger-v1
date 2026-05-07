"""Helper for launching the optional Streamlit dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Print or launch the optional Streamlit dashboard.")
    parser.add_argument("--launch", action="store_true", help="Launch streamlit if it is installed.")
    args = parser.parse_args()
    command = "streamlit run src/dashboard/streamlit_app.py"
    print(command)
    if args.launch:
        try:
            import streamlit.web.cli as stcli  # pragma: no cover - optional path
            import sys

            sys.argv = ["streamlit", "run", "src/dashboard/streamlit_app.py"]
            raise SystemExit(stcli.main())
        except ImportError:
            print("Streamlit is not installed. Install the optional dependency to launch the dashboard.")


if __name__ == "__main__":
    main()
