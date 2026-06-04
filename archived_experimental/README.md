# archived_experimental/

Code that is **not part of the runtime** and must never be imported by the
production pipeline. Kept for forensics / future reference only.

Exclusion is enforced by `tests/test_archived_code_isolation.py`, which asserts
that the production-core modules do not import anything under this directory.

## Contents

- `tribev2/` — vendored TRIBE v2 neuroscience / fMRI research library
  (brain-imaging studies: `wen2017`, `lebel2023bold`, `algonauts2025`, …).
  Unrelated to trading. Was under `scripts/external/tribev2/` and imported by
  nothing in the pipeline. The sandbox adapter `scripts/tribev2_adapter.py`
  still reports `wired_into_pipeline: False` and does not import this code.

- `_quarantine/` — files that do not compile, preserved with a `.broken`
  suffix so `compileall` skips them. Nothing in runtime may import them. Was
  under `scripts/_quarantine/`.

## Rule

To bring something back into runtime: move it to `scripts/` (or `src/`), give
it a documented decision function in `docs/CORE_ENGINE_MANIFEST.md`, and add a
behavioural test. The advisory-only / no-execution invariant applies to any
promoted module.
