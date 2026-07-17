"""Verified engine manifest for all eighteen named simulation engines.

Every engine carries an HONEST integration classification.  The cardinal rule:
an interface class existing does NOT mean an engine is "integrated".  Fourteen
engines are CONCEPT_TRANSPLANT (we reimplement the decision principle in
original Python — no dependency), one is a genuinely installable
NATIVE_LIBRARY behind an optional extra (COPASI/basico), one is an
EXTERNAL_PROCESS behind a feature flag (Stockfish UCI binary), and one is
REJECTED (PhET — GPLv3 source copyleft + wrong domain/language).

Facts (versions, licences, OS/Python-3.13 support) were researched against
official sources in 2026-07 and are recorded verbatim-ish for auditability.
This module is pure data + accessors: no imports of the engines themselves, no
network, no DB.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

MANIFEST_VERSION = "sil-engine-manifest-2026.07"

# Integration modes (exactly one per engine).
NATIVE_LIBRARY = "NATIVE_LIBRARY"
EXTERNAL_PROCESS = "EXTERNAL_PROCESS"
ISOLATED_CONTAINER = "ISOLATED_CONTAINER"
OFFICIAL_API = "OFFICIAL_API"
ADAPTER_STUB = "ADAPTER_STUB"
CONCEPT_TRANSPLANT = "CONCEPT_TRANSPLANT"
REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class EngineManifestEntry:
    engine: str
    domain: str
    intended_capability: str
    current_version: str
    doc_source: str
    license: str
    commercial_use: str
    supported_os: str
    python313: str
    windows: str
    hardware: str
    integration_mode: str
    install_footprint: str
    runtime_cost: str
    determinism: str
    reproducibility: str
    security_risks: str
    maintenance_risk: str
    improves_mvp: str
    final_decision: str
    reason: str
    # Which SIL lens transplants this engine's principle (if any).
    transplanted_into: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


_M = EngineManifestEntry

MANIFEST: tuple[EngineManifestEntry, ...] = (
    # ---------------------------- PHYSICS ---------------------------------
    _M(
        engine="MuJoCo",
        domain="PHYSICS",
        intended_capability="Deterministic model-predictive forward-rollout: advance a constrained "
                            "dynamic system under candidate forces and score the trajectory.",
        current_version="3.10.0 (2026); PyPI `mujoco` cp313 wheel published",
        doc_source="https://mujoco.readthedocs.io",
        license="Apache-2.0",
        commercial_use="Permitted, no royalties; patent grant included.",
        supported_os="Windows, Linux, macOS (native wheels)",
        python313="yes — cp313 wheel on PyPI",
        windows="yes — native win_amd64 wheel, no compiler",
        hardware="CPU; optional GPU only for the separate MJX package (not used)",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="~50-70 MB self-contained wheel",
        runtime_cost="Free, local CPU, negligible per-call",
        determinism="Deterministic per-platform given model+timestep+seed; not bit-identical cross-OS",
        reproducibility="High within one machine",
        security_risks="Low; only risk is parsing untrusted MJCF (never done here)",
        maintenance_risk="Low — Google DeepMind, active",
        improves_mvp="no — rigid-body contact dynamics has no market meaning; only the rollout concept transfers",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Apache-2.0 + Windows/3.13 wheels make native trivial, but embedding a physics engine "
               "with zero market relevance violates the no-heavyweight-dep / fail-closed contract. "
               "We transplant deterministic constrained-dynamics rollout into physics/market_dynamics.",
        transplanted_into="physics",
    ),
    _M(
        engine="Project Chrono",
        domain="PHYSICS",
        intended_capability="Constraint-coupled multibody forward simulation of interacting entities "
                            "(company/sector/index/suppliers) — force/shock propagation.",
        current_version="Chrono 10.0.0 (Apr 2026); PyChrono conda-only py313 build",
        doc_source="https://api.projectchrono.org",
        license="BSD-3-Clause",
        commercial_use="Permitted, permissive, no copyleft.",
        supported_os="Windows, Linux, macOS (C++); PyChrono via conda only",
        python313="yes (conda) — NOT on PyPI; conda-only conflicts with pip/venv stack",
        windows="yes — win-64 conda package",
        hardware="CPU multibody; optional GPU modules",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Hundreds of MB, conda-only (packaging conflict)",
        runtime_cost="Free, local CPU, heavier than MuJoCo",
        determinism="Deterministic given fixed timestep/config",
        reproducibility="Moderate",
        security_risks="Low; local offline compute",
        maintenance_risk="Moderate — academic, conda-only distribution",
        improves_mvp="no — multiphysics irrelevant to markets; conda-only clashes with the stack",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Permissive licence but conda-only heavyweight C++ engine with no market relevance. "
               "We transplant multi-body dependency-shock propagation into physics/dependency_dynamics.",
        transplanted_into="physics",
    ),
    _M(
        engine="PhET Interactive Simulations",
        domain="PHYSICS",
        intended_capability="Interactive live-parameter 'what-if' slider UX for exploratory explainability.",
        current_version="Rolling HTML5 collection (~160 sims); no single version",
        doc_source="https://phet.colorado.edu",
        license="Source GPLv3 (strong copyleft); published sim files CC BY 4.0",
        commercial_use="GPLv3 source would force our derivative open — a real legal hazard.",
        supported_os="Browser (JavaScript/HTML5) — client-side only",
        python313="NA — not Python",
        windows="Browser only",
        hardware="Trivial (browser)",
        integration_mode=REJECTED,
        install_footprint="None on backend (would be iframe/JS in frontend)",
        runtime_cost="Free, client-side",
        determinism="N/A — interactive teaching sims, not a callable engine",
        reproducibility="N/A",
        security_risks="Embedding third-party JS/iframe adds XSS + supply-chain surface; GPLv3 copyleft risk",
        maintenance_risk="N/A as dependency",
        improves_mvp="no — educational STEM teaching sims have no market function; wrong domain and language",
        final_decision=REJECTED,
        reason="GPLv3 source copyleft + JS-only + wrong domain. We build our own PhET-style interactive "
               "assumption/sensitivity layer natively (physics/market_dynamics + frontend), importing nothing.",
        transplanted_into="physics (native explainability, no PhET code)",
    ),
    # ---------------------------- CHEMISTRY -------------------------------
    _M(
        engine="GROMACS",
        domain="CHEMISTRY",
        intended_capability="Ensemble statistical mechanics: many microstates relax into free-energy "
                            "minima (metastable basins) — distribution-of-states thinking.",
        current_version="2026.3 (25 Jun 2026)",
        doc_source="https://manual.gromacs.org",
        license="LGPL-2.1-or-later",
        commercial_use="Permitted; copyleft only on modifications to GROMACS itself.",
        supported_os="Linux (first-class); Windows only by source build",
        python313="NA — C++/CUDA app; gmxapi must be built against a local build",
        windows="partial — no official Windows binaries; compile from source or WSL",
        hardware="GPU-oriented (CUDA/SYCL); heavy",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Large compiled toolchain",
        runtime_cost="Heavy; GPU strongly preferred",
        determinism="Reproducible with fixed seed/config; FP nondeterminism on GPU",
        reproducibility="Moderate",
        security_risks="Low; local compute",
        maintenance_risk="Low — mature",
        improves_mvp="no — an MD engine provides no market signal and is heavyweight/GPU-oriented",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Heavy GPU MD engine, not a Python lib, no Windows binaries. We transplant the "
               "ensemble/metastable-state principle into chemistry/reaction_network + uncertainty.",
        transplanted_into="chemistry",
    ),
    _M(
        engine="LAMMPS",
        domain="CHEMISTRY",
        intended_capability="Large-scale many-particle stat-mech with tunable 'temperature' and observable "
                            "phase transitions — scalable many-node interaction.",
        current_version="Stable 22 Jul 2025 (dev builds into 2026)",
        doc_source="https://docs.lammps.org",
        license="GPL-2.0-only",
        commercial_use="GPLv2 strong copyleft — distributing the ctypes wrapper contaminates our code.",
        supported_os="Windows, Linux, macOS",
        python313="partial — `pip install lammps` ctypes wrapper over compiled liblammps",
        windows="yes — official Windows installers + win_amd64 wheels",
        hardware="CPU/GPU, MPI-scalable; heavy",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Large; native lib behind wheel",
        runtime_cost="Heavy",
        determinism="Reproducible with fixed seed; MPI ordering caveats",
        reproducibility="Moderate",
        security_risks="Low; local compute",
        maintenance_risk="Low — mature (Sandia)",
        improves_mvp="no — MD/particle engine yields no market signal; GPLv2 copyleft incompatible",
        final_decision=CONCEPT_TRANSPLANT,
        reason="GPLv2 copyleft would contaminate a proprietary product; heavy MD engine. We transplant "
               "scalable many-agent + phase-transition principles into chemistry/phase_transition and biology.",
        transplanted_into="chemistry",
    ),
    _M(
        engine="OpenMM",
        domain="CHEMISTRY",
        intended_capability="Stochastic Langevin integration: state evolves as drift + friction + seeded "
                            "noise — reproducible Monte-Carlo with a deterministic testing mode.",
        current_version="8.5.2 (8 Jun 2026)",
        doc_source="https://openmm.org",
        license="MIT (core/CPU/API); LGPL (optional GPU platforms)",
        commercial_use="Permissive; MIT core imposes no copyleft.",
        supported_os="Windows, Linux, macOS",
        python313="yes — official cp313 wheels on PyPI",
        windows="yes — first-class Windows wheels (best story of the MD three)",
        hardware="CPU-capable; optional GPU",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Moderate wheel",
        runtime_cost="Moderate; CPU-safe",
        determinism="Reproducible with explicit seed; deterministic on Reference/CPU platform",
        reproducibility="High (this is the model for our deterministic_rng design)",
        security_risks="Low",
        maintenance_risk="Low — active",
        improves_mvp="no — even though it is the only MD engine that COULD be native, the physics is irrelevant",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Technically installable, but molecular dynamics has no market meaning. We transplant its "
               "explicit-seed / bounded-run / convergence Monte-Carlo discipline into deterministic_rng.",
        transplanted_into="chemistry + deterministic_rng",
    ),
    # ---------------------------- BIOLOGY ---------------------------------
    _M(
        engine="PhysiCell",
        domain="BIOLOGY",
        intended_capability="Rules-driven heterogeneous agent populations sensing an environment and "
                            "changing behaviour — participant-cohort ecosystem modelling.",
        current_version="1.14.2 (2025-01-20)",
        doc_source="http://physicell.org",
        license="BSD-3-Clause",
        commercial_use="Permitted, permissive.",
        supported_os="Linux/macOS (C++); Windows via MinGW",
        python313="NA — C++; no pip package (PhysiCell-Studio is separate tooling)",
        windows="partial — MinGW + per-model recompilation, no prebuilt binary",
        hardware="CPU (OpenMP)",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="C++ source + compiler per model",
        runtime_cost="Moderate/heavy",
        determinism="Seeded but recompilation-bound",
        reproducibility="Moderate",
        security_risks="Low",
        maintenance_risk="Moderate — academic",
        improves_mvp="marginal — the rules-based agent-grammar concept is genuinely useful; the native engine is not",
        final_decision=CONCEPT_TRANSPLANT,
        reason="C++ source, no wheel, per-model recompilation. We transplant heterogeneous rules-based "
               "agent populations into biology/agent_ecosystem.",
        transplanted_into="biology",
    ),
    _M(
        engine="BioDynaMo",
        domain="BIOLOGY",
        intended_capability="Large-scale parallel agent-based simulation: agents multiply, migrate, "
                            "cluster, compete, adapt, die — narrative/agent population dynamics.",
        current_version="v1.04 (last clear stable; active into 2024-2025)",
        doc_source="https://biodynamo.org",
        license="Apache-2.0",
        commercial_use="Permitted; runtime stack (CERN ROOT) adds LGPL components.",
        supported_os="Linux/macOS only",
        python313="NA — C++ platform, models compiled in C++",
        windows="no — explicitly unsupported on Windows and WSL (disqualifying)",
        hardware="CPU/parallel; heavy ROOT/ParaView stack",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Very heavy (ROOT + ParaView)",
        runtime_cost="Heavy",
        determinism="Seeded",
        reproducibility="Moderate",
        security_risks="Low",
        maintenance_risk="Moderate",
        improves_mvp="no — cannot run on Windows at all; irrelevant domain; too heavy",
        final_decision=CONCEPT_TRANSPLANT,
        reason="No Windows/WSL support makes native/subprocess impossible on half our targets. We "
               "transplant agent multiply/migrate/adapt/die dynamics into biology/adaptation + contagion.",
        transplanted_into="biology",
    ),
    _M(
        engine="COPASI",
        domain="BIOLOGY",
        intended_capability="Coupled reaction-network dynamical systems: deterministic ODE + stochastic "
                            "CTMC integration, steady-state, sensitivity — feedback/homeostasis networks.",
        current_version="copasi-basico 0.86 (2026-01-13) over python-copasi",
        doc_source="https://basico.readthedocs.io",
        license="Artistic-License-2.0 (OSI-approved)",
        commercial_use="Permitted at no cost; does not force our source open for mere use.",
        supported_os="Windows, Linux, macOS (python-copasi wheels)",
        python313="partial — basico is pure Python 3.7+; gated on a cp313 python-copasi wheel",
        windows="yes — `pip install copasi-basico` works on Windows (subject to cp313 wheel)",
        hardware="CPU, light",
        integration_mode=NATIVE_LIBRARY,
        install_footprint="Small pip install (optional extra `sil-copasi`)",
        runtime_cost="Light, CPU",
        determinism="Deterministic ODE mode; seeded stochastic mode",
        reproducibility="High",
        security_risks="Low — local compute; loads SBML/CPS files (we would only load our own)",
        maintenance_risk="Low-moderate — active, single-lab",
        improves_mvp="marginal — biochemistry itself is irrelevant, but the ODE/CTMC feedback-network solver "
                     "is a real, honest optional accelerator for the biology/COPASI lens",
        final_decision=NATIVE_LIBRARY,
        reason="The ONE chemistry/biology engine honestly installable natively (Artistic-2.0, pip, "
               "cross-platform incl. Windows). Wired behind the optional `sil-copasi` extra + feature flag; "
               "the biology lens uses it if present and falls back to the native transplant otherwise.",
        transplanted_into="biology (optional native accelerator + native transplant)",
    ),
    # ---------------------------- RACING ----------------------------------
    _M(
        engine="iRacing",
        domain="RACING",
        intended_capability="High-resolution 60 Hz decision telemetry: every state transition, delta vs a "
                            "reference, and strategy adjustment — advisory decision telemetry.",
        current_version="Rolling subscription service; quarterly Season builds",
        doc_source="https://www.iracing.com",
        license="Proprietary EULA + paid subscription (read-only irsdk is separate)",
        commercial_use="Cannot embed/redistribute; EULA bars third-party data mining of the client.",
        supported_os="Windows game (needs GPU + interactive session + login)",
        python313="NA — C++ game; pyirsdk is Windows-only and needs a running client",
        windows="yes (game) but unsuitable for a headless backend",
        hardware="GPU + desktop session + subscription",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A (cannot embed)",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Embedding a consumer game client in a backend is a non-starter",
        maintenance_risk="N/A",
        improves_mvp="no for native (proprietary Windows game, zero market data); the telemetry concept is useful",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary Windows game under an anti-third-party EULA. We transplant its high-resolution "
               "decision-telemetry principle into racing/telemetry (every gate/override/warning recorded).",
        transplanted_into="racing",
    ),
    _M(
        engine="rFactor 2",
        domain="RACING",
        intended_capability="Versioned shared-memory telemetry with torn-read detection (per-buffer version "
                            "counters) — path-dependent dynamic-conditions modelling.",
        current_version="Steam rolling release (IP owned by Motorsport Games since Jul 2025)",
        doc_source="https://www.studio-397.com",
        license="Proprietary game EULA + Steam Subscriber Agreement",
        commercial_use="No right to embed/redistribute; community plugin source is open but the game is not.",
        supported_os="Windows game + DLL plugin",
        python313="NA — C++; community readers Windows-only, need the game",
        windows="yes (game) but not headless-server compatible",
        hardware="GPU + interactive session",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Cannot embed a consumer game",
        maintenance_risk="IP owner (Motorsport Games) financially volatile — schema stability risk",
        improves_mvp="no for native; the versioned-buffer torn-read guard is a clean pattern for our replay writer",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary Windows/GPU game. We transplant the versioned-buffer + path-dependence + "
               "dynamic-track-condition principle into racing/degradation and replay.",
        transplanted_into="racing",
    ),
    _M(
        engine="EA Sports F1",
        domain="RACING",
        intended_capability="Documented fixed-schema UDP telemetry contract: numbered packet types, cadence, "
                            "session IDs — strict versioned strategy/pit-window contracts.",
        current_version="F1 25 (30 May 2025) + 2026 Season Pack (3 Jun 2026); no separate 'F1 26'",
        doc_source="https://www.ea.com/games/f1",
        license="Proprietary EA User Agreement; UDP spec published for reference only",
        commercial_use="Cannot embed/redistribute the game; consuming UDP with companion tools is tolerated for consumers.",
        supported_os="Windows/console game (UDP stream is network-delivered)",
        python313="NA — proprietary C++; pure-Python UDP parsers exist but need a running game",
        windows="yes (game) but a GPU game must still run to emit telemetry",
        hardware="GPU game",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Cannot embed a consumer game",
        maintenance_risk="N/A",
        improves_mvp="no for native; the strategy/pit-window/undercut concepts translate to advisory timing",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary game. We transplant strategy selection, pit-window (early exit / delayed entry), "
               "safety-car / red-flag analogues, tyre-degradation and undercut/overcut into racing/strategy_simulator.",
        transplanted_into="racing",
    ),
    # ---------------------------- CHESS -----------------------------------
    _M(
        engine="Stockfish",
        domain="CHESS",
        intended_capability="Bounded adversarial search with alpha-beta pruning, transposition caching, "
                            "move ordering, quiescence, principal variation — evaluated scenario search.",
        current_version="Stockfish 17.x (2024-2025 line, active)",
        doc_source="https://stockfishchess.org",
        license="GPL-3.0-or-later (engine binary)",
        commercial_use="GPLv3 — running the binary via subprocess does NOT contaminate our code (arm's-length).",
        supported_os="Windows, Linux, macOS (UCI binary)",
        python313="NA (binary); Python `stockfish` wrapper is MIT but needs the binary present",
        windows="yes — Windows binary available",
        hardware="CPU (NNUE); light",
        integration_mode=EXTERNAL_PROCESS,
        install_footprint="Single binary (optional; feature-flag gated)",
        runtime_cost="Bounded by movetime/depth caps we set",
        determinism="Deterministic at fixed depth + single thread; nondeterministic multi-thread",
        reproducibility="High at Threads=1, fixed depth",
        security_risks="Subprocess to a trusted binary with a fixed arg list; no shell, no untrusted input",
        maintenance_risk="Low — very active OSS",
        improves_mvp="marginal — real minimax search over *chess* is irrelevant, but the SEARCH DISCIPLINE is "
                     "the model for our scenario search; the binary itself is an optional curiosity",
        final_decision=EXTERNAL_PROCESS,
        reason="The only chess engine we expose as a real optional EXTERNAL_PROCESS (GPLv3 arm's-length "
               "subprocess, single fixed-arg binary, feature-flag + Threads=1 for determinism). The chess "
               "LENS itself is a native CONCEPT_TRANSPLANT of iterative-deepening scenario search; Stockfish "
               "is never on the default path.",
        transplanted_into="chess (native search; Stockfish adapter is optional)",
    ),
    _M(
        engine="Leela Chess Zero (lc0)",
        domain="CHESS",
        intended_capability="Policy-value architecture: P(branch) × V(resulting state), MCTS-style "
                            "exploration with uncertainty and exploration penalty.",
        current_version="lc0 0.31.x (2024-2025)",
        doc_source="https://lczero.org",
        license="GPL-3.0 (engine); networks separate",
        commercial_use="GPLv3 engine; requires a large NN weight file + ideally GPU.",
        supported_os="Windows, Linux, macOS",
        python313="NA — C++ engine + NN weights; no meaningful pip path for our use",
        windows="yes (binary) but needs weights + GPU for strength",
        hardware="GPU strongly preferred; large weights",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="Engine + multi-hundred-MB weights",
        runtime_cost="Heavy without GPU",
        determinism="Nondeterministic (MCTS + FP); reproducibility hard",
        reproducibility="Low",
        security_risks="Loading untrusted NN weights is a supply-chain risk (we would train/ship none)",
        maintenance_risk="Moderate",
        improves_mvp="no — training/serving a NN without sufficient data is explicitly out of scope",
        final_decision=CONCEPT_TRANSPLANT,
        reason="No data to train an expensive NN; GPU/weights heavyweight. We transplant the policy-value "
               "architecture (branch probability × state value, with exploration penalty and model "
               "disagreement) into chess/policy_value as an original contract.",
        transplanted_into="chess",
    ),
    _M(
        engine="Maia Chess",
        domain="CHESS",
        intended_capability="Human-like move modelling: predict realistic (imperfect) human behaviour at a "
                            "given skill — operator-behaviour / bias modelling.",
        current_version="Research models (Maia-1100..1900); lc0-based",
        doc_source="https://maiachess.com",
        license="Research/academic (lc0 GPLv3 lineage); non-commercial expectations on models",
        commercial_use="Ambiguous for the trained models — treat as non-embeddable.",
        supported_os="Wherever lc0 runs",
        python313="Original transplant (no Maia binary)",
        windows="Original transplant (no Maia binary)",
        hardware="Same as lc0 if run natively",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A (transplant)",
        runtime_cost="Negligible (native heuristics)",
        determinism="Deterministic (our native heuristic model)",
        reproducibility="High",
        security_risks="None (no external model)",
        maintenance_risk="Low (our code)",
        improves_mvp="yes (as concept) — modelling operator bias/panic/FOMO to WARN the human is genuinely useful",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Licensing ambiguity + wrong domain for the trained model. We transplant human-error "
               "modelling (delay, confirmation/recency bias, overconfidence, panic, FOMO, stop-skipping, "
               "concentration, revenge) into chess/human_error to warn — never manipulate — the operator.",
        transplanted_into="chess",
    ),
    # ---------------------------- POKER -----------------------------------
    _M(
        engine="GTO Wizard",
        domain="POKER",
        intended_capability="Game-theory-optimal equilibrium baselines to distinguish robust vs "
                            "assumption-dependent vs exploitative vs dominated actions.",
        current_version="Proprietary SaaS (rolling)",
        doc_source="https://gtowizard.com",
        license="Proprietary SaaS EULA; no public general-purpose solve API for embedding",
        commercial_use="Cannot embed; API access (if any) is licence-gated and out of scope.",
        supported_os="Web SaaS",
        python313="partial — only if a licensed API existed (it does not for our use)",
        windows="yes (web)",
        hardware="Vendor-side",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Sending data to a third-party SaaS would leak candidate data — disallowed",
        maintenance_risk="N/A",
        improves_mvp="no for native; the equilibrium-baseline concept is valuable",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary SaaS, no embeddable API, data-egress risk. We transplant equilibrium-baseline "
               "classification (robust / assumption-dependent / exploitative / dominated / no-action-edge) "
               "into poker/equilibrium.",
        transplanted_into="poker",
    ),
    _M(
        engine="PioSOLVER",
        domain="POKER",
        intended_capability="Bounded decision-tree + counterfactual-regret analysis: EV, downside, "
                            "opportunity cost, max/counterfactual/tail regret, information value, value of waiting.",
        current_version="Proprietary Windows solver (Pio 3.x)",
        doc_source="https://piosolver.com",
        license="Proprietary paid licence (Windows)",
        commercial_use="Cannot embed/redistribute.",
        supported_os="Windows",
        python313="NA — proprietary binary",
        windows="yes (product) but licence-locked, not embeddable",
        hardware="High RAM for large trees",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Cannot embed a licensed binary",
        maintenance_risk="N/A",
        improves_mvp="no for native; the CFR/regret decision-tree framework is directly transplantable",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary Windows solver, licence-locked. We transplant a bounded decision-tree + "
               "counterfactual-regret framework (original CFR-style math) into poker/regret.",
        transplanted_into="poker",
    ),
    _M(
        engine="MonkerSolver",
        domain="POKER",
        intended_capability="Multi-player / multi-way equilibria — model many market actors (company, "
                            "competitors, regulators, customers, suppliers, macro, index flows) not just bull/bear.",
        current_version="Proprietary multi-way solver",
        doc_source="https://monkerware.com",
        license="Proprietary paid licence",
        commercial_use="Cannot embed/redistribute.",
        supported_os="Windows/Java",
        python313="NA — proprietary",
        windows="yes (product) but not embeddable",
        hardware="High RAM",
        integration_mode=CONCEPT_TRANSPLANT,
        install_footprint="N/A",
        runtime_cost="N/A",
        determinism="N/A",
        reproducibility="N/A",
        security_risks="Cannot embed a licensed binary",
        maintenance_risk="N/A",
        improves_mvp="no for native; multi-agent (not bull-vs-bear) modelling is valuable",
        final_decision=CONCEPT_TRANSPLANT,
        reason="Proprietary solver. We transplant multi-party equilibrium + exploitability measurement "
               "(how easily the recommendation fails if one actor deviates) into poker/multi_agent + exploitability.",
        transplanted_into="poker",
    ),
)

# Sanity: exactly 18 engines, exactly one mode each.
assert len(MANIFEST) == 18, "engine manifest must list all eighteen engines"


def summary() -> dict[str, Any]:
    """Machine-readable manifest summary grouped by integration mode."""
    by_mode: dict[str, list[str]] = {}
    for e in MANIFEST:
        by_mode.setdefault(e.integration_mode, []).append(e.engine)
    return {
        "manifest_version": MANIFEST_VERSION,
        "engine_count": len(MANIFEST),
        "by_mode": by_mode,
        "native_integrations": by_mode.get(NATIVE_LIBRARY, []),
        "external_process_integrations": by_mode.get(EXTERNAL_PROCESS, []),
        "concept_transplants": by_mode.get(CONCEPT_TRANSPLANT, []),
        "rejected": by_mode.get(REJECTED, []),
        "honesty_note": (
            "No proprietary engine is embedded. Only COPASI (Artistic-2.0, optional pip extra) is a "
            "real NATIVE_LIBRARY and only Stockfish (GPLv3, arm's-length subprocess, feature-flagged) "
            "is a real EXTERNAL_PROCESS; both are OFF by default and the base workflow runs without them."
        ),
    }


def as_dicts() -> list[dict[str, Any]]:
    return [e.to_dict() for e in MANIFEST]


def get(engine_name: str) -> EngineManifestEntry | None:
    key = engine_name.strip().lower()
    for e in MANIFEST:
        if e.engine.lower() == key or key in e.engine.lower():
            return e
    return None


__all__ = [
    "MANIFEST_VERSION", "MANIFEST", "EngineManifestEntry",
    "NATIVE_LIBRARY", "EXTERNAL_PROCESS", "ISOLATED_CONTAINER", "OFFICIAL_API",
    "ADAPTER_STUB", "CONCEPT_TRANSPLANT", "REJECTED",
    "summary", "as_dicts", "get",
]
