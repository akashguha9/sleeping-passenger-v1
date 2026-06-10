"""Adapters that convert ingestion-layer data into alpha-framework signals.

Offline-safe: nothing in this package performs network I/O.  Adapters
consume already-fetched snapshots (or deterministic mock fixtures) from
``src/ingestion`` clients and manual dicts.
"""
