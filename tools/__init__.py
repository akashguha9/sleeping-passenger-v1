"""Out-of-MVP-scope tools.

This package intentionally lives outside ``scripts/`` and ``src/`` —
the Sleeping Passenger private-operator MVP does not import from here
at runtime.  Modules under ``tools/`` are reference / experimental /
non-MVP utilities that have been quarantined by
``scripts/private_scope_guard.py`` so they cannot silently expand the
MVP surface.

Adding code that imports ``tools.*`` from anywhere under ``scripts/``,
``src/``, or the live API server is a scope violation.
"""
