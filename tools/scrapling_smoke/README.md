# scrapling_smoke (quarantined)

A connectivity smoke check for the [`scrapling`](https://pypi.org/project/scrapling/)
web-fetcher library: it fetches `example.com` once over plain HTTP and once
through a headless browser and prints the page `<h1>`.

It is **not** part of the Sleeping Passenger MVP runtime. Web scraping is
outside the approved private-operator domains (signal ingestion, scoring,
journaling, reconciliation, refresh/reactor diagnostics), so this script lives
under `tools/` — physically off the MVP surface — and is tracked in
`scripts/private_scope_guard.py:QUARANTINED_TOOL_DIRS`.

Run manually only, with the optional `scrapling` dependency installed:

```bash
python tools/scrapling_smoke/scrapling_smoke.py
```

No module under `scripts/` or `src/` may import it.
