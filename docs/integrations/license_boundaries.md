# License Boundaries

This MVP does not copy GPL or AGPL source code into the core repository.

Boundaries:
- `poly_data`: GPL-3.0 sidecar, exported CSV/JSON only, no direct imports
- `TrendRadar`: GPL-3.0 sidecar, exported JSON/TXT/CSV only, no direct imports
- `FinceptTerminal`: AGPL-3.0/commercial sidecar, exported analytics only, no direct imports
- `Kronos`: MIT optional dependency, lazy import only
- `TradingAgents`: Apache-2.0 optional/mock committee, lazy or mock-safe use only
- `Apollo-11`: public-domain doctrine reference only, no assembly import or copied source

Hard rules:
- External outputs are evidence candidates only
- Real execution is disabled
- Paper execution is the maximum allowed action
