# Simulation Engine Manifest — Sleeping Passenger SIL

**Manifest version:** `sil-engine-manifest-2026.07` · **Engines:** 18 · **Source of truth:** `scripts/simulation_intelligence/engine_manifest.py` (this document is generated from it)

This manifest records an **honest integration classification** for every one of the
eighteen named engines. The guiding rule (product constraint §2) is **capability
transplant, not dependency bloat**: we do *not* blindly install every engine. Each
engine is classified as exactly one of `NATIVE_LIBRARY`, `EXTERNAL_PROCESS`,
`ISOLATED_CONTAINER`, `OFFICIAL_API`, `ADAPTER_STUB`, `CONCEPT_TRANSPLANT`, or
`REJECTED`.

> **No engine is on the default runtime path.** The six-lens council runs to
> completion with **every** optional engine unavailable. The only two engines
> exposed as real optional integrations — Stockfish (`EXTERNAL_PROCESS`) and
> COPASI (`NATIVE_LIBRARY`) — are **OFF by default** behind feature flags and are
> never required. No engine grants execution permission; all outputs are
> `ADVISORY_ONLY` / `SIMULATED_ONLY`.

## Summary

- **15 × CONCEPT_TRANSPLANT** — the decision principle is re-implemented in original
  code (physics rollouts, reaction networks, agent ecosystems, telemetry/strategy,
  policy-value search, CFR/regret). Proprietary engines are **never** scraped,
  reverse-engineered, or imitated at the code level; only the published, well-known
  *algorithmic principle* is transplanted.
- **1 × NATIVE_LIBRARY** — COPASI (`copasi-basico`, Artistic-2.0) as an optional,
  flag-gated ODE/feedback-network accelerator for the biology lens.
- **1 × EXTERNAL_PROCESS** — Stockfish (GPLv3, arm's-length UCI subprocess,
  single fixed-arg binary, `Threads=1` for determinism), optional and flag-gated.
- **1 × REJECTED** — PhET (GPLv3 strong copyleft on source + browser-only teaching
  sims; wrong domain and a real licence hazard). The *explainability idea* survives
  as an original sensitivity/counterfactual UI, but no PhET code is used.

## Manifest table

| Engine | Domain | Version | Licence | Py3.13 | Win | Mode | Improves MVP | Decision |
|---|---|---|---|---|---|---|---|---|
| MuJoCo | PHYSICS | 3.10.0 (2026); PyPI `mujoco` cp313 wheel published | Apache-2.0 | yes — cp313 wheel on PyPI | yes — native win_amd64 wheel, no compiler | CONCEPT_TRANSPLANT | no — rigid-body contact dynamics has no market meaning; only the rollout concept transfers | CONCEPT_TRANSPLANT |
| Project Chrono | PHYSICS | Chrono 10.0.0 (Apr 2026); PyChrono conda-only py313 build | BSD-3-Clause | yes (conda) — NOT on PyPI; conda-only conflicts with pip/venv stack | yes — win-64 conda package | CONCEPT_TRANSPLANT | no — multiphysics irrelevant to markets; conda-only clashes with the stack | CONCEPT_TRANSPLANT |
| PhET Interactive Simulations | PHYSICS | Rolling HTML5 collection (~160 sims); no single version | Source GPLv3 (strong copyleft); published sim files CC BY 4.0 | NA — not Python | Browser only | REJECTED | no — educational STEM teaching sims have no market function; wrong domain and language | REJECTED |
| GROMACS | CHEMISTRY | 2026.3 (25 Jun 2026) | LGPL-2.1-or-later | NA — C++/CUDA app; gmxapi must be built against a local build | partial — no official Windows binaries; compile from source or WSL | CONCEPT_TRANSPLANT | no — an MD engine provides no market signal and is heavyweight/GPU-oriented | CONCEPT_TRANSPLANT |
| LAMMPS | CHEMISTRY | Stable 22 Jul 2025 (dev builds into 2026) | GPL-2.0-only | partial — `pip install lammps` ctypes wrapper over compiled liblammps | yes — official Windows installers + win_amd64 wheels | CONCEPT_TRANSPLANT | no — MD/particle engine yields no market signal; GPLv2 copyleft incompatible | CONCEPT_TRANSPLANT |
| OpenMM | CHEMISTRY | 8.5.2 (8 Jun 2026) | MIT (core/CPU/API); LGPL (optional GPU platforms) | yes — official cp313 wheels on PyPI | yes — first-class Windows wheels (best story of the MD three) | CONCEPT_TRANSPLANT | no — even though it is the only MD engine that COULD be native, the physics is irrelevant | CONCEPT_TRANSPLANT |
| PhysiCell | BIOLOGY | 1.14.2 (2025-01-20) | BSD-3-Clause | NA — C++; no pip package (PhysiCell-Studio is separate tooling) | partial — MinGW + per-model recompilation, no prebuilt binary | CONCEPT_TRANSPLANT | marginal — the rules-based agent-grammar concept is genuinely useful; the native engine is not | CONCEPT_TRANSPLANT |
| BioDynaMo | BIOLOGY | v1.04 (last clear stable; active into 2024-2025) | Apache-2.0 | NA — C++ platform, models compiled in C++ | no — explicitly unsupported on Windows and WSL (disqualifying) | CONCEPT_TRANSPLANT | no — cannot run on Windows at all; irrelevant domain; too heavy | CONCEPT_TRANSPLANT |
| COPASI | BIOLOGY | copasi-basico 0.86 (2026-01-13) over python-copasi | Artistic-License-2.0 (OSI-approved) | partial — basico is pure Python 3.7+; gated on a cp313 python-copasi wheel | yes — `pip install copasi-basico` works on Windows (subject to cp313 wheel) | NATIVE_LIBRARY | marginal — biochemistry itself is irrelevant, but the ODE/CTMC feedback-network solver is a real, honest optional accelerator for the biology/COPASI lens | NATIVE_LIBRARY |
| iRacing | RACING | Rolling subscription service; quarterly Season builds | Proprietary EULA + paid subscription (read-only irsdk is separate) | NA — C++ game; pyirsdk is Windows-only and needs a running client | yes (game) but unsuitable for a headless backend | CONCEPT_TRANSPLANT | no for native (proprietary Windows game, zero market data); the telemetry concept is useful | CONCEPT_TRANSPLANT |
| rFactor 2 | RACING | Steam rolling release (IP owned by Motorsport Games since Jul 2025) | Proprietary game EULA + Steam Subscriber Agreement | NA — C++; community readers Windows-only, need the game | yes (game) but not headless-server compatible | CONCEPT_TRANSPLANT | no for native; the versioned-buffer torn-read guard is a clean pattern for our replay writer | CONCEPT_TRANSPLANT |
| EA Sports F1 | RACING | F1 25 (30 May 2025) + 2026 Season Pack (3 Jun 2026); no separate 'F1 26' | Proprietary EA User Agreement; UDP spec published for reference only | NA — proprietary C++; pure-Python UDP parsers exist but need a running game | yes (game) but a GPU game must still run to emit telemetry | CONCEPT_TRANSPLANT | no for native; the strategy/pit-window/undercut concepts translate to advisory timing | CONCEPT_TRANSPLANT |
| Stockfish | CHESS | Stockfish 17.x (2024-2025 line, active) | GPL-3.0-or-later (engine binary) | NA (binary); Python `stockfish` wrapper is MIT but needs the binary present | yes — Windows binary available | EXTERNAL_PROCESS | marginal — real minimax search over *chess* is irrelevant, but the SEARCH DISCIPLINE is the model for our scenario search; the binary itself is an optional curiosity | EXTERNAL_PROCESS |
| Leela Chess Zero (lc0) | CHESS | lc0 0.31.x (2024-2025) | GPL-3.0 (engine); networks separate | NA — C++ engine + NN weights; no meaningful pip path for our use | yes (binary) but needs weights + GPU for strength | CONCEPT_TRANSPLANT | no — training/serving a NN without sufficient data is explicitly out of scope | CONCEPT_TRANSPLANT |
| Maia Chess | CHESS | Research models (Maia-1100..1900); lc0-based | Research/academic (lc0 GPLv3 lineage); non-commercial expectations on models | Original transplant (no Maia binary) | Original transplant (no Maia binary) | CONCEPT_TRANSPLANT | yes (as concept) — modelling operator bias/panic/FOMO to WARN the human is genuinely useful | CONCEPT_TRANSPLANT |
| GTO Wizard | POKER | Proprietary SaaS (rolling) | Proprietary SaaS EULA; no public general-purpose solve API for embedding | partial — only if a licensed API existed (it does not for our use) | yes (web) | CONCEPT_TRANSPLANT | no for native; the equilibrium-baseline concept is valuable | CONCEPT_TRANSPLANT |
| PioSOLVER | POKER | Proprietary Windows solver (Pio 3.x) | Proprietary paid licence (Windows) | NA — proprietary binary | yes (product) but licence-locked, not embeddable | CONCEPT_TRANSPLANT | no for native; the CFR/regret decision-tree framework is directly transplantable | CONCEPT_TRANSPLANT |
| MonkerSolver | POKER | Proprietary multi-way solver | Proprietary paid licence | NA — proprietary | yes (product) but not embeddable | CONCEPT_TRANSPLANT | no for native; multi-agent (not bull-vs-bear) modelling is valuable | CONCEPT_TRANSPLANT |
## Legal boundary

We do **not** scrape, reverse-engineer, or imitate proprietary code (iRacing,
rFactor 2, EA F1, GTO Wizard, PioSOLVER, MonkerSolver, Maia trained models). For
those, only the **published decision principle** is re-implemented in original
code behind a clean adapter contract. An interface class existing is **never**
claimed as "the engine is integrated": the two optional real integrations
(Stockfish, COPASI) are the only ones exposed as live adapters, and both report
`ENGINE_UNAVAILABLE` honestly when absent.

## Per-engine detail

### MuJoCo — PHYSICS

- **Intended capability:** Deterministic model-predictive forward-rollout: advance a constrained dynamic system under candidate forces and score the trajectory.
- **Official version (as researched):** 3.10.0 (2026); PyPI `mujoco` cp313 wheel published
- **Docs:** https://mujoco.readthedocs.io
- **Licence / commercial use:** Apache-2.0 — Permitted, no royalties; patent grant included.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS (native wheels) / yes — cp313 wheel on PyPI / yes — native win_amd64 wheel, no compiler
- **Hardware:** CPU; optional GPU only for the separate MJX package (not used)
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: ~50-70 MB self-contained wheel  |  runtime cost: Free, local CPU, negligible per-call
- **Determinism / reproducibility:** Deterministic per-platform given model+timestep+seed; not bit-identical cross-OS / High within one machine
- **Security risk / maintenance risk:** Low; only risk is parsing untrusted MJCF (never done here) / Low — Google DeepMind, active
- **Improves MVP?** no — rigid-body contact dynamics has no market meaning; only the rollout concept transfers
- **Decision:** CONCEPT_TRANSPLANT — Apache-2.0 + Windows/3.13 wheels make native trivial, but embedding a physics engine with zero market relevance violates the no-heavyweight-dep / fail-closed contract. We transplant deterministic constrained-dynamics rollout into physics/market_dynamics.
- **Transplanted into:** physics

### Project Chrono — PHYSICS

- **Intended capability:** Constraint-coupled multibody forward simulation of interacting entities (company/sector/index/suppliers) — force/shock propagation.
- **Official version (as researched):** Chrono 10.0.0 (Apr 2026); PyChrono conda-only py313 build
- **Docs:** https://api.projectchrono.org
- **Licence / commercial use:** BSD-3-Clause — Permitted, permissive, no copyleft.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS (C++); PyChrono via conda only / yes (conda) — NOT on PyPI; conda-only conflicts with pip/venv stack / yes — win-64 conda package
- **Hardware:** CPU multibody; optional GPU modules
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Hundreds of MB, conda-only (packaging conflict)  |  runtime cost: Free, local CPU, heavier than MuJoCo
- **Determinism / reproducibility:** Deterministic given fixed timestep/config / Moderate
- **Security risk / maintenance risk:** Low; local offline compute / Moderate — academic, conda-only distribution
- **Improves MVP?** no — multiphysics irrelevant to markets; conda-only clashes with the stack
- **Decision:** CONCEPT_TRANSPLANT — Permissive licence but conda-only heavyweight C++ engine with no market relevance. We transplant multi-body dependency-shock propagation into physics/dependency_dynamics.
- **Transplanted into:** physics

### PhET Interactive Simulations — PHYSICS

- **Intended capability:** Interactive live-parameter 'what-if' slider UX for exploratory explainability.
- **Official version (as researched):** Rolling HTML5 collection (~160 sims); no single version
- **Docs:** https://phet.colorado.edu
- **Licence / commercial use:** Source GPLv3 (strong copyleft); published sim files CC BY 4.0 — GPLv3 source would force our derivative open — a real legal hazard.
- **OS / Py3.13 / Windows:** Browser (JavaScript/HTML5) — client-side only / NA — not Python / Browser only
- **Hardware:** Trivial (browser)
- **Integration mode:** **REJECTED**  |  install footprint: None on backend (would be iframe/JS in frontend)  |  runtime cost: Free, client-side
- **Determinism / reproducibility:** N/A — interactive teaching sims, not a callable engine / N/A
- **Security risk / maintenance risk:** Embedding third-party JS/iframe adds XSS + supply-chain surface; GPLv3 copyleft risk / N/A as dependency
- **Improves MVP?** no — educational STEM teaching sims have no market function; wrong domain and language
- **Decision:** REJECTED — GPLv3 source copyleft + JS-only + wrong domain. We build our own PhET-style interactive assumption/sensitivity layer natively (physics/market_dynamics + frontend), importing nothing.
- **Transplanted into:** physics (native explainability, no PhET code)

### GROMACS — CHEMISTRY

- **Intended capability:** Ensemble statistical mechanics: many microstates relax into free-energy minima (metastable basins) — distribution-of-states thinking.
- **Official version (as researched):** 2026.3 (25 Jun 2026)
- **Docs:** https://manual.gromacs.org
- **Licence / commercial use:** LGPL-2.1-or-later — Permitted; copyleft only on modifications to GROMACS itself.
- **OS / Py3.13 / Windows:** Linux (first-class); Windows only by source build / NA — C++/CUDA app; gmxapi must be built against a local build / partial — no official Windows binaries; compile from source or WSL
- **Hardware:** GPU-oriented (CUDA/SYCL); heavy
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Large compiled toolchain  |  runtime cost: Heavy; GPU strongly preferred
- **Determinism / reproducibility:** Reproducible with fixed seed/config; FP nondeterminism on GPU / Moderate
- **Security risk / maintenance risk:** Low; local compute / Low — mature
- **Improves MVP?** no — an MD engine provides no market signal and is heavyweight/GPU-oriented
- **Decision:** CONCEPT_TRANSPLANT — Heavy GPU MD engine, not a Python lib, no Windows binaries. We transplant the ensemble/metastable-state principle into chemistry/reaction_network + uncertainty.
- **Transplanted into:** chemistry

### LAMMPS — CHEMISTRY

- **Intended capability:** Large-scale many-particle stat-mech with tunable 'temperature' and observable phase transitions — scalable many-node interaction.
- **Official version (as researched):** Stable 22 Jul 2025 (dev builds into 2026)
- **Docs:** https://docs.lammps.org
- **Licence / commercial use:** GPL-2.0-only — GPLv2 strong copyleft — distributing the ctypes wrapper contaminates our code.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS / partial — `pip install lammps` ctypes wrapper over compiled liblammps / yes — official Windows installers + win_amd64 wheels
- **Hardware:** CPU/GPU, MPI-scalable; heavy
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Large; native lib behind wheel  |  runtime cost: Heavy
- **Determinism / reproducibility:** Reproducible with fixed seed; MPI ordering caveats / Moderate
- **Security risk / maintenance risk:** Low; local compute / Low — mature (Sandia)
- **Improves MVP?** no — MD/particle engine yields no market signal; GPLv2 copyleft incompatible
- **Decision:** CONCEPT_TRANSPLANT — GPLv2 copyleft would contaminate a proprietary product; heavy MD engine. We transplant scalable many-agent + phase-transition principles into chemistry/phase_transition and biology.
- **Transplanted into:** chemistry

### OpenMM — CHEMISTRY

- **Intended capability:** Stochastic Langevin integration: state evolves as drift + friction + seeded noise — reproducible Monte-Carlo with a deterministic testing mode.
- **Official version (as researched):** 8.5.2 (8 Jun 2026)
- **Docs:** https://openmm.org
- **Licence / commercial use:** MIT (core/CPU/API); LGPL (optional GPU platforms) — Permissive; MIT core imposes no copyleft.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS / yes — official cp313 wheels on PyPI / yes — first-class Windows wheels (best story of the MD three)
- **Hardware:** CPU-capable; optional GPU
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Moderate wheel  |  runtime cost: Moderate; CPU-safe
- **Determinism / reproducibility:** Reproducible with explicit seed; deterministic on Reference/CPU platform / High (this is the model for our deterministic_rng design)
- **Security risk / maintenance risk:** Low / Low — active
- **Improves MVP?** no — even though it is the only MD engine that COULD be native, the physics is irrelevant
- **Decision:** CONCEPT_TRANSPLANT — Technically installable, but molecular dynamics has no market meaning. We transplant its explicit-seed / bounded-run / convergence Monte-Carlo discipline into deterministic_rng.
- **Transplanted into:** chemistry + deterministic_rng

### PhysiCell — BIOLOGY

- **Intended capability:** Rules-driven heterogeneous agent populations sensing an environment and changing behaviour — participant-cohort ecosystem modelling.
- **Official version (as researched):** 1.14.2 (2025-01-20)
- **Docs:** http://physicell.org
- **Licence / commercial use:** BSD-3-Clause — Permitted, permissive.
- **OS / Py3.13 / Windows:** Linux/macOS (C++); Windows via MinGW / NA — C++; no pip package (PhysiCell-Studio is separate tooling) / partial — MinGW + per-model recompilation, no prebuilt binary
- **Hardware:** CPU (OpenMP)
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: C++ source + compiler per model  |  runtime cost: Moderate/heavy
- **Determinism / reproducibility:** Seeded but recompilation-bound / Moderate
- **Security risk / maintenance risk:** Low / Moderate — academic
- **Improves MVP?** marginal — the rules-based agent-grammar concept is genuinely useful; the native engine is not
- **Decision:** CONCEPT_TRANSPLANT — C++ source, no wheel, per-model recompilation. We transplant heterogeneous rules-based agent populations into biology/agent_ecosystem.
- **Transplanted into:** biology

### BioDynaMo — BIOLOGY

- **Intended capability:** Large-scale parallel agent-based simulation: agents multiply, migrate, cluster, compete, adapt, die — narrative/agent population dynamics.
- **Official version (as researched):** v1.04 (last clear stable; active into 2024-2025)
- **Docs:** https://biodynamo.org
- **Licence / commercial use:** Apache-2.0 — Permitted; runtime stack (CERN ROOT) adds LGPL components.
- **OS / Py3.13 / Windows:** Linux/macOS only / NA — C++ platform, models compiled in C++ / no — explicitly unsupported on Windows and WSL (disqualifying)
- **Hardware:** CPU/parallel; heavy ROOT/ParaView stack
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Very heavy (ROOT + ParaView)  |  runtime cost: Heavy
- **Determinism / reproducibility:** Seeded / Moderate
- **Security risk / maintenance risk:** Low / Moderate
- **Improves MVP?** no — cannot run on Windows at all; irrelevant domain; too heavy
- **Decision:** CONCEPT_TRANSPLANT — No Windows/WSL support makes native/subprocess impossible on half our targets. We transplant agent multiply/migrate/adapt/die dynamics into biology/adaptation + contagion.
- **Transplanted into:** biology

### COPASI — BIOLOGY

- **Intended capability:** Coupled reaction-network dynamical systems: deterministic ODE + stochastic CTMC integration, steady-state, sensitivity — feedback/homeostasis networks.
- **Official version (as researched):** copasi-basico 0.86 (2026-01-13) over python-copasi
- **Docs:** https://basico.readthedocs.io
- **Licence / commercial use:** Artistic-License-2.0 (OSI-approved) — Permitted at no cost; does not force our source open for mere use.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS (python-copasi wheels) / partial — basico is pure Python 3.7+; gated on a cp313 python-copasi wheel / yes — `pip install copasi-basico` works on Windows (subject to cp313 wheel)
- **Hardware:** CPU, light
- **Integration mode:** **NATIVE_LIBRARY**  |  install footprint: Small pip install (optional extra `sil-copasi`)  |  runtime cost: Light, CPU
- **Determinism / reproducibility:** Deterministic ODE mode; seeded stochastic mode / High
- **Security risk / maintenance risk:** Low — local compute; loads SBML/CPS files (we would only load our own) / Low-moderate — active, single-lab
- **Improves MVP?** marginal — biochemistry itself is irrelevant, but the ODE/CTMC feedback-network solver is a real, honest optional accelerator for the biology/COPASI lens
- **Decision:** NATIVE_LIBRARY — The ONE chemistry/biology engine honestly installable natively (Artistic-2.0, pip, cross-platform incl. Windows). Wired behind the optional `sil-copasi` extra + feature flag; the biology lens uses it if present and falls back to the native transplant otherwise.
- **Transplanted into:** biology (optional native accelerator + native transplant)

### iRacing — RACING

- **Intended capability:** High-resolution 60 Hz decision telemetry: every state transition, delta vs a reference, and strategy adjustment — advisory decision telemetry.
- **Official version (as researched):** Rolling subscription service; quarterly Season builds
- **Docs:** https://www.iracing.com
- **Licence / commercial use:** Proprietary EULA + paid subscription (read-only irsdk is separate) — Cannot embed/redistribute; EULA bars third-party data mining of the client.
- **OS / Py3.13 / Windows:** Windows game (needs GPU + interactive session + login) / NA — C++ game; pyirsdk is Windows-only and needs a running client / yes (game) but unsuitable for a headless backend
- **Hardware:** GPU + desktop session + subscription
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A (cannot embed)  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Embedding a consumer game client in a backend is a non-starter / N/A
- **Improves MVP?** no for native (proprietary Windows game, zero market data); the telemetry concept is useful
- **Decision:** CONCEPT_TRANSPLANT — Proprietary Windows game under an anti-third-party EULA. We transplant its high-resolution decision-telemetry principle into racing/telemetry (every gate/override/warning recorded).
- **Transplanted into:** racing

### rFactor 2 — RACING

- **Intended capability:** Versioned shared-memory telemetry with torn-read detection (per-buffer version counters) — path-dependent dynamic-conditions modelling.
- **Official version (as researched):** Steam rolling release (IP owned by Motorsport Games since Jul 2025)
- **Docs:** https://www.studio-397.com
- **Licence / commercial use:** Proprietary game EULA + Steam Subscriber Agreement — No right to embed/redistribute; community plugin source is open but the game is not.
- **OS / Py3.13 / Windows:** Windows game + DLL plugin / NA — C++; community readers Windows-only, need the game / yes (game) but not headless-server compatible
- **Hardware:** GPU + interactive session
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Cannot embed a consumer game / IP owner (Motorsport Games) financially volatile — schema stability risk
- **Improves MVP?** no for native; the versioned-buffer torn-read guard is a clean pattern for our replay writer
- **Decision:** CONCEPT_TRANSPLANT — Proprietary Windows/GPU game. We transplant the versioned-buffer + path-dependence + dynamic-track-condition principle into racing/degradation and replay.
- **Transplanted into:** racing

### EA Sports F1 — RACING

- **Intended capability:** Documented fixed-schema UDP telemetry contract: numbered packet types, cadence, session IDs — strict versioned strategy/pit-window contracts.
- **Official version (as researched):** F1 25 (30 May 2025) + 2026 Season Pack (3 Jun 2026); no separate 'F1 26'
- **Docs:** https://www.ea.com/games/f1
- **Licence / commercial use:** Proprietary EA User Agreement; UDP spec published for reference only — Cannot embed/redistribute the game; consuming UDP with companion tools is tolerated for consumers.
- **OS / Py3.13 / Windows:** Windows/console game (UDP stream is network-delivered) / NA — proprietary C++; pure-Python UDP parsers exist but need a running game / yes (game) but a GPU game must still run to emit telemetry
- **Hardware:** GPU game
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Cannot embed a consumer game / N/A
- **Improves MVP?** no for native; the strategy/pit-window/undercut concepts translate to advisory timing
- **Decision:** CONCEPT_TRANSPLANT — Proprietary game. We transplant strategy selection, pit-window (early exit / delayed entry), safety-car / red-flag analogues, tyre-degradation and undercut/overcut into racing/strategy_simulator.
- **Transplanted into:** racing

### Stockfish — CHESS

- **Intended capability:** Bounded adversarial search with alpha-beta pruning, transposition caching, move ordering, quiescence, principal variation — evaluated scenario search.
- **Official version (as researched):** Stockfish 17.x (2024-2025 line, active)
- **Docs:** https://stockfishchess.org
- **Licence / commercial use:** GPL-3.0-or-later (engine binary) — GPLv3 — running the binary via subprocess does NOT contaminate our code (arm's-length).
- **OS / Py3.13 / Windows:** Windows, Linux, macOS (UCI binary) / NA (binary); Python `stockfish` wrapper is MIT but needs the binary present / yes — Windows binary available
- **Hardware:** CPU (NNUE); light
- **Integration mode:** **EXTERNAL_PROCESS**  |  install footprint: Single binary (optional; feature-flag gated)  |  runtime cost: Bounded by movetime/depth caps we set
- **Determinism / reproducibility:** Deterministic at fixed depth + single thread; nondeterministic multi-thread / High at Threads=1, fixed depth
- **Security risk / maintenance risk:** Subprocess to a trusted binary with a fixed arg list; no shell, no untrusted input / Low — very active OSS
- **Improves MVP?** marginal — real minimax search over *chess* is irrelevant, but the SEARCH DISCIPLINE is the model for our scenario search; the binary itself is an optional curiosity
- **Decision:** EXTERNAL_PROCESS — The only chess engine we expose as a real optional EXTERNAL_PROCESS (GPLv3 arm's-length subprocess, single fixed-arg binary, feature-flag + Threads=1 for determinism). The chess LENS itself is a native CONCEPT_TRANSPLANT of iterative-deepening scenario search; Stockfish is never on the default path.
- **Transplanted into:** chess (native search; Stockfish adapter is optional)

### Leela Chess Zero (lc0) — CHESS

- **Intended capability:** Policy-value architecture: P(branch) × V(resulting state), MCTS-style exploration with uncertainty and exploration penalty.
- **Official version (as researched):** lc0 0.31.x (2024-2025)
- **Docs:** https://lczero.org
- **Licence / commercial use:** GPL-3.0 (engine); networks separate — GPLv3 engine; requires a large NN weight file + ideally GPU.
- **OS / Py3.13 / Windows:** Windows, Linux, macOS / NA — C++ engine + NN weights; no meaningful pip path for our use / yes (binary) but needs weights + GPU for strength
- **Hardware:** GPU strongly preferred; large weights
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: Engine + multi-hundred-MB weights  |  runtime cost: Heavy without GPU
- **Determinism / reproducibility:** Nondeterministic (MCTS + FP); reproducibility hard / Low
- **Security risk / maintenance risk:** Loading untrusted NN weights is a supply-chain risk (we would train/ship none) / Moderate
- **Improves MVP?** no — training/serving a NN without sufficient data is explicitly out of scope
- **Decision:** CONCEPT_TRANSPLANT — No data to train an expensive NN; GPU/weights heavyweight. We transplant the policy-value architecture (branch probability × state value, with exploration penalty and model disagreement) into chess/policy_value as an original contract.
- **Transplanted into:** chess

### Maia Chess — CHESS

- **Intended capability:** Human-like move modelling: predict realistic (imperfect) human behaviour at a given skill — operator-behaviour / bias modelling.
- **Official version (as researched):** Research models (Maia-1100..1900); lc0-based
- **Docs:** https://maiachess.com
- **Licence / commercial use:** Research/academic (lc0 GPLv3 lineage); non-commercial expectations on models — Ambiguous for the trained models — treat as non-embeddable.
- **OS / Py3.13 / Windows:** Wherever lc0 runs / Original transplant (no Maia binary) / Original transplant (no Maia binary)
- **Hardware:** Same as lc0 if run natively
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A (transplant)  |  runtime cost: Negligible (native heuristics)
- **Determinism / reproducibility:** Deterministic (our native heuristic model) / High
- **Security risk / maintenance risk:** None (no external model) / Low (our code)
- **Improves MVP?** yes (as concept) — modelling operator bias/panic/FOMO to WARN the human is genuinely useful
- **Decision:** CONCEPT_TRANSPLANT — Licensing ambiguity + wrong domain for the trained model. We transplant human-error modelling (delay, confirmation/recency bias, overconfidence, panic, FOMO, stop-skipping, concentration, revenge) into chess/human_error to warn — never manipulate — the operator.
- **Transplanted into:** chess

### GTO Wizard — POKER

- **Intended capability:** Game-theory-optimal equilibrium baselines to distinguish robust vs assumption-dependent vs exploitative vs dominated actions.
- **Official version (as researched):** Proprietary SaaS (rolling)
- **Docs:** https://gtowizard.com
- **Licence / commercial use:** Proprietary SaaS EULA; no public general-purpose solve API for embedding — Cannot embed; API access (if any) is licence-gated and out of scope.
- **OS / Py3.13 / Windows:** Web SaaS / partial — only if a licensed API existed (it does not for our use) / yes (web)
- **Hardware:** Vendor-side
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Sending data to a third-party SaaS would leak candidate data — disallowed / N/A
- **Improves MVP?** no for native; the equilibrium-baseline concept is valuable
- **Decision:** CONCEPT_TRANSPLANT — Proprietary SaaS, no embeddable API, data-egress risk. We transplant equilibrium-baseline classification (robust / assumption-dependent / exploitative / dominated / no-action-edge) into poker/equilibrium.
- **Transplanted into:** poker

### PioSOLVER — POKER

- **Intended capability:** Bounded decision-tree + counterfactual-regret analysis: EV, downside, opportunity cost, max/counterfactual/tail regret, information value, value of waiting.
- **Official version (as researched):** Proprietary Windows solver (Pio 3.x)
- **Docs:** https://piosolver.com
- **Licence / commercial use:** Proprietary paid licence (Windows) — Cannot embed/redistribute.
- **OS / Py3.13 / Windows:** Windows / NA — proprietary binary / yes (product) but licence-locked, not embeddable
- **Hardware:** High RAM for large trees
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Cannot embed a licensed binary / N/A
- **Improves MVP?** no for native; the CFR/regret decision-tree framework is directly transplantable
- **Decision:** CONCEPT_TRANSPLANT — Proprietary Windows solver, licence-locked. We transplant a bounded decision-tree + counterfactual-regret framework (original CFR-style math) into poker/regret.
- **Transplanted into:** poker

### MonkerSolver — POKER

- **Intended capability:** Multi-player / multi-way equilibria — model many market actors (company, competitors, regulators, customers, suppliers, macro, index flows) not just bull/bear.
- **Official version (as researched):** Proprietary multi-way solver
- **Docs:** https://monkerware.com
- **Licence / commercial use:** Proprietary paid licence — Cannot embed/redistribute.
- **OS / Py3.13 / Windows:** Windows/Java / NA — proprietary / yes (product) but not embeddable
- **Hardware:** High RAM
- **Integration mode:** **CONCEPT_TRANSPLANT**  |  install footprint: N/A  |  runtime cost: N/A
- **Determinism / reproducibility:** N/A / N/A
- **Security risk / maintenance risk:** Cannot embed a licensed binary / N/A
- **Improves MVP?** no for native; multi-agent (not bull-vs-bear) modelling is valuable
- **Decision:** CONCEPT_TRANSPLANT — Proprietary solver. We transplant multi-party equilibrium + exploitability measurement (how easily the recommendation fails if one actor deviates) into poker/multi_agent + exploitability.
- **Transplanted into:** poker
