"""Advisory response-contract constants + a pure exception sanitizer.

Extracted from the 3,029-line ``api_server`` god-module. These are the
advisory-only invariants stamped on API responses (advisory status, human-only
execution mode, zero AI executions) plus a pure error-text sanitizer that
prevents path/DB-name leakage. Pure: no FastAPI, no I/O, no module state.

Behaviour is byte-identical to the prior in-module definitions; ``api_server``
re-imports these under their original private names.
"""

from __future__ import annotations

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_MODE = "HUMAN_ONLY"
AI_EXECUTION_COUNT = 0
API_VERSION = "1.0.0"


def safe_exc_summary(exc: BaseException) -> str:
    """Return the exception type name only.

    Eliminates leakage of absolute paths, DB filenames, and third-party library
    internals through per-route ``"error": safe_exc_summary(exc)`` shortcuts.
    Full detail is still written to the server log at the calling site.
    """
    return type(exc).__name__
