"""
Base class for all read-only Global Signal Fabric source loaders.

Contract
--------
- Every loader is READ-ONLY. No loader may write to any external system.
- Every fetch() returns a LoaderResult whose records each carry
  advisory_status="ADVISORY_ONLY" and human_review_required=True.
- Missing credentials raise SkipLoader, which tests treat as a clean skip.
- No network calls occur at import time.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"


class SkipLoader(Exception):
    """Raised when a loader cannot run (missing key, unavailable source, etc.).

    Tests that catch this treat it as a clean skip, not a failure.
    """


@dataclass
class LoaderResult:
    """Container returned by every source loader.

    Fields
    ------
    source_name   : identifier for the data source (e.g. "polymarket")
    records       : list of advisory observation dicts
    skipped       : True if the loader was skipped (no key / no data)
    skip_reason   : human-readable reason for skip (empty if not skipped)
    advisory_status : always "ADVISORY_ONLY"
    human_review_required : always True
    execution_gate : always "LOCKED"
    """

    source_name: str
    records: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    execution_gate: str = _EXECUTION_GATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "record_count": len(self.records),
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "advisory_status": self.advisory_status,
            "human_review_required": self.human_review_required,
            "execution_gate": self.execution_gate,
        }


class BaseSourceLoader(ABC):
    """Abstract base for all read-only source loaders."""

    source_name: str = "base"
    requires_key: bool = False

    @staticmethod
    def _require_env_key(env_var: str) -> str:
        """Return the env var value or raise SkipLoader if unset/empty."""
        value = os.environ.get(env_var, "").strip()
        if not value:
            raise SkipLoader(
                f"Required env var {env_var!r} is not set — loader skipped"
            )
        return value

    @staticmethod
    def _require_env_any(*names: str) -> str:
        """Return the first non-empty value among the given env var names, or raise SkipLoader."""
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        checked = ", ".join(repr(n) for n in names)
        raise SkipLoader(
            f"None of the required env vars [{checked}] are set — loader skipped"
        )

    @staticmethod
    def _stamp_record(record: dict[str, Any]) -> dict[str, Any]:
        """Attach advisory stamps to an observation record."""
        record.setdefault("advisory_status", _ADVISORY_STATUS)
        record.setdefault("human_review_required", True)
        record.setdefault("execution_gate", _EXECUTION_GATE)
        return record

    @abstractmethod
    def fetch(self) -> LoaderResult:
        """Read data from the source and return a LoaderResult.

        Must never write to any external system.
        Must never place, modify, cancel, or execute any order.
        On missing credentials, raise SkipLoader.
        """

    def safe_fetch(self) -> LoaderResult:
        """Wrap fetch() to convert SkipLoader into a skipped LoaderResult."""
        try:
            return self.fetch()
        except SkipLoader as exc:
            return LoaderResult(
                source_name=self.source_name,
                skipped=True,
                skip_reason=str(exc),
            )
        except Exception as exc:  # pylint: disable=broad-except
            return LoaderResult(
                source_name=self.source_name,
                skipped=True,
                skip_reason=f"loader error: {type(exc).__name__}: {exc}",
            )
