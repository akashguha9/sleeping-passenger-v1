# Release provenance

Lightweight "what exactly am I running?" evidence — no heavyweight
supply-chain platform, just hashes you can recompute.

## Build a manifest

```powershell
python scripts/build_release_manifest.py --test-summary "<pytest summary>"
```

Writes `dist/release_manifest_<UTC>.json` (gitignored) recording: git
commit/branch/**dirty flag** (a dirty tree is loudly marked
non-reproducible), Python and Node versions, SHA-256 of the dependency
locks (`requirements*.txt`, `package-lock.json` — this is the dependency
snapshot), key safety-bearing sources (`api_server.py`,
`runtime_config.py`, `advisory_contract.py`, `persistence.py`), every CI
workflow file, the supplied test summary, and the advisory-only
invariants pulled live from the safety module.

## Checksums

```powershell
python scripts/generate_checksums.py            # write dist/SHA256SUMS
python scripts/generate_checksums.py --verify   # recompute; fails on tamper
```

`SHA256SUMS` (sha256sum-compatible) covers the newest manifest, lockfiles,
LICENSE + ownership docs, and workflows. `--verify` is the tamper check:
any modified or missing file fails with the exact path.

## Release procedure (owner)

1. Clean tree (`git status` empty), full suites green.
2. `python scripts/build_release_manifest.py --test-summary "<N passed>"`
3. `python scripts/generate_checksums.py`
4. Keep `dist/` contents with the encrypted backup (the owner recovery
   pack) — together they prove *and* preserve the released state.
5. Later, on any machine: `python scripts/generate_checksums.py --verify`.

## SBOM note

A full SPDX/CycloneDX SBOM is deliberately out of scope for a private
single-operator MVP; the lockfile hashes in the manifest pin the exact
dependency set, and `pip-audit`/`npm audit` run against those same locks
in CI weekly. If this ever ships beyond the owner, generate an SBOM with
`pip-audit --format cyclonedx-json` / `npm sbom` at that point.
