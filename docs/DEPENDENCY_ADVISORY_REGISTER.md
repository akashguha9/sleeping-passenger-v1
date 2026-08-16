# Dependency advisory register

Accepted-risk register for known, unresolved dependency advisories.
Every entry must carry a `review_by` date; `scripts/audit_dependency_advisory_register.py`
**fails** (CI-enforced) once an entry is past due, forcing a fresh look
instead of silent rot. Accepted risk owner for all entries: **Akash Guha**.

Rules:

- Only advisories that CI tolerates belong here (currently: Moderate and
  below — `npm audit --omit=dev --audit-level=high` and
  `pip-audit --strict` gate High/Critical hard and must NOT be weakened).
- Do not blindly force-fix: `npm audit fix --force` for the entry below
  proposes downgrading `next` 16 → 9.3.3, which is absurd and would break
  the build.
- When an upstream fix lands, take it, then delete the entry.

## Open entries

| ID | Package | Severity | Transitive source | Affected path | Why not fixed | Upstream status | CI behavior | Review by | Owner |
| -- | ------- | -------- | ----------------- | ------------- | ------------- | --------------- | ----------- | --------- | ----- |
| ADV-2026-001 | postcss (<8.5.10) | Moderate | bundled by `next` (`node_modules/next/node_modules/postcss`) | GHSA-qx2v-qp2m-jg93 — XSS via unescaped `</style>` in stringified CSS output | `next@16.2.7` pins its own bundled postcss; no non-breaking fix exists (npm's only "fix" is a downgrade to next 9). Exploit requires attacker-controlled CSS reaching PostCSS stringify — this app compiles only its own Tailwind sources at build time, no user CSS path exists. | Affected range per advisory: next 9.3.4-canary.0 – 16.3.0-canary.5; track next releases > 16.3.0 for a bundled postcss >= 8.5.10. Re-reviewed 2026-08-16: lockfile still resolves bundled postcss 8.4.31 under `next`; justification unchanged (no user CSS path). | `npm audit --omit=dev --audit-level=high` passes (Moderate); surfaced in logs every run. | 2026-09-15 | Akash Guha |

## Resolved (history)

| ID | Package | Severity | Resolution | Date |
| -- | ------- | -------- | ---------- | ---- |
| ADV-2026-000 | vitest (<=3.2.5, dev-only) | Critical (GHSA-5xrq-8626-4rwp) | Upgraded vitest 1.x → 4.x in Pass 1; suite stayed green (198/198). | 2026-06-10 |

## Review procedure

1. `cd frontend; npm audit` (and `pip-audit -r requirements.txt`).
2. If an upstream fix exists: apply, run `npm test`, `npx tsc --noEmit`,
   `npm run build`; delete the entry into the Resolved table.
3. If not: re-validate the "why not fixed" reasoning still holds and bump
   `review_by` by at most 60 days.
4. Never add High/Critical production advisories here — fix them or hold
   the release; the CI gates for those must stay hard.
