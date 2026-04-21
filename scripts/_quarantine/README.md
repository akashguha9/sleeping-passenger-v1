# scripts/_quarantine

Holding area for scripts that do not compile or are otherwise broken but
whose content we want to preserve for forensics.

**Rules:**
- Files here have a `.broken` suffix so `python -m compileall scripts` skips them.
- Nothing in active runtime may import from this directory.
- Fixing a file means moving it back to `scripts/` with its original name.

## Current contents

- `source_signaling_discount.py.broken` — SyntaxError on f-string backslash
  escapes (line 218, `f'{ssd_result[\"ssd_tier\"]}'`). Not imported by any
  active runtime module. Quarantined so `compileall scripts` passes cleanly.
