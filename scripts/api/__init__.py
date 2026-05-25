"""scripts/api — FastAPI router package.

Identity Collapse + First-Day Operator sprint, Phase 9.

Routers extracted from the monolithic ``scripts/api_server.py``.  They
remain registered on the same ``app`` instance via
``app.include_router(...)`` so existing route URLs, AST tests, and the
advisory-stamp property test are all preserved.

Safety contract
---------------
Every router in this package is advisory-only.  No router defines a
broker, order, execute, buy, sell, or place-order route.  Every response
carries the canonical safety stamps sourced from
``scripts.advisory_contract``.
"""
