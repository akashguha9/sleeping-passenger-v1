"""Section metadata for GMAT Club forum scraping.

Page counts reflect the user-supplied snapshot; they will drift over time.
Re-run the discovery routine in cli.py (--discover) to refresh.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    code: str           # short id used in filenames / CLI
    name: str           # human label
    base_path: str      # e.g. "problem-solving-ps-140"
    last_page: int      # 1-indexed inclusive
    page_size: int = 50 # GMAT Club default; last page may have fewer

    def index_url(self, page: int) -> str:
        """Listing-page URL. Page 1 has no /index-N/ suffix."""
        root = f"https://gmatclub.com/forum/{self.base_path}/"
        if page <= 1:
            return root
        return f"{root}index-{(page - 1) * self.page_size}.html"


SECTIONS: dict[str, Section] = {
    "PS":  Section("PS",  "Problem Solving",       "problem-solving-ps-140",      820),
    "CR":  Section("CR",  "Critical Reasoning",    "critical-reasoning-cr-139",   262),
    "DS":  Section("DS",  "Data Sufficiency",      "data-sufficiency-ds-141",     361),
    "GT":  Section("GT",  "Graphs and Tables",     "graphs-and-tables-g-t-457",    19),
    "MSR": Section("MSR", "Multi-Source Reasoning","multi-source-reasoning-msr-456", 4),
    "TPA": Section("TPA", "Two-Part Analysis",     "two-part-analysis-tpa-455",    17),
}


def total_problems_estimate() -> int:
    return sum(s.last_page * s.page_size for s in SECTIONS.values())
