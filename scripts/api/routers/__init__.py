"""scripts/api/routers — read-only FastAPI routers.

Each module exposes a ``router`` attribute (a ``fastapi.APIRouter`` instance)
which the main ``scripts/api_server.py`` includes via
``app.include_router(...)``.

Routers are split by concern:

* ``readiness_router`` — release-gate / daily-signal / source-health /
  live-refresh / portfolio-truth / fresh-discovery / why-today /
  model-disagreement / signal-input-quality / compliance / business-value
  readiness envelopes.

Every router is advisory-only and read-only.  No broker / order /
execute / buy / sell / place-order route is defined here.
"""
