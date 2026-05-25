"""Test helpers — advisory-only, non-canonical fixture utilities.

Anything written into ``tests/helpers/`` produces *temporary, derived,
non-canonical* artifacts only.  Nothing in this package may write into the
canonical runtime SQLite at ``runtime/mvp_local.db``; helpers that touch
SQLite must explicitly refuse the canonical runtime path and only operate on
``tmp_path`` / ``runtime/perf_fixtures/`` style DB files.
"""
