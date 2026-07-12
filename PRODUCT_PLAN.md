# Generalized PCB Stator Motor Generator: Product Plan

This document contains the implementation roadmap, architectural feasibility studies, transition plans, branch strategy, and validation requirements for `pcbstatorgen`. For product vision and specification, see `PRODUCT_GOALS.md`.

---

## 1. Multi-Phase Development Roadmap

```
┌────────────────────────────────────────────────────────┐
│  PHASE 1: Foundations & Scaffolding            (DONE)  │
│  - Mathematical units, configs, structures.            │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 2: Coil Geometry & Physics Core         (DONE)  │
│  - Serpentine solvers, Magpylib integration.           │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 3: UI Modernization & Commutation Fix   (DONE)  │
│  - Basic Streamlit, Newton's Third Law calibration.    │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 4: SINGLE-DASHBOARD UI OVERHAUL         (DONE)  │
│  - Wizard removal, advanced dashboard consolidation,   │
│    travel and board width fixes, magnet helpers,       │
│    spacing ratios/Vernier dropdown, ripple calculations.│
│  - Python core decoupled & JSON-serializable (DONE)    │
│  - Radial (axial-flux) toggle DISABLED — TODO           │
│  - Travel calc direction FIX: active_area = INPUT,      │
│    travel = DERIVED (config refactor done in P4)        │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 5: Rust Physics Core (magba + nalgebra)   DONE  │
│  - Branch: feat/phase5-6-rust-tauri (combined w/ P6)    │
│  - Workspace: crates/pcbstatorgen-rs + app/ (Tauri v2)  │
│  - Config structs, coil generators, stackup → Rust serde │
│  - B-field via magba, Lorentz force natively (nalgebra) │
│  - Newton's 3rd Law + self-calibration guard (ported)   │
│  - 179 Rust tests pass; validated vs Python (±1% B, ±2% F)│
│  - KNOWN ISSUE: 170% force ripple — commutation align-  │
│    ment bug (coil geometry vs. electrical angle). See   │
│    §6 — Known Issues & Remaining Work.                  │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 6: Tauri + Svelte Desktop Application     DONE  │
│  - Tauri v2 + Svelte 5 (runes) + Vite + Tailwind       │
│  - 11 Svelte components, interactive travel diagram     │
│  - 9 Tauri #[tauri::command] handlers (3 real, 6 stub) │
│  - Linear toggle ONLY (Radial still TODO)               │
│  - Live metrics, SVG previews, force sweep plot          │
│  - KNOWN ISSUE: 6 stub commands need real pcbstatorgen- │
│    rs wiring. See §6 — Known Issues & Remaining Work.   │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 7: KiCad 10 IPC Writer (Rust native)             │
│  - kipy socket protocol in Rust                          │
│  - Track/via grid generation, atomic commits (Ctrl+Z)  │
│  - Streamlit deprecation                                │
└────────────────────────────────────────────────────────┘
```

---

## 2. Physics Engine: Pure Rust with magba

### Decision

All magnetic field, force, and torque computation will be implemented natively in Rust. No Python runtime or sidecar is required.

### Key Crates

| Crate                      | Version | Role                                                                                               |
| -------------------------- | ------- | -------------------------------------------------------------------------------------------------- |
| **magba**                  | 0.6.2   | Analytical B-field from CuboidMagnet, PathCurrent, source collections (validated against Magpylib) |
| **nalgebra**               | 0.34+   | Vector cross-products, quaternions for magnet orientation (bumped from 0.33 — magba 0.6.2 requires 0.34.2) |
| **rayon**                  | 1.10+   | Data-parallel field sampling across observation points                                             |
| **cfsem** (optional)       | 11.2    | Advanced Biot-Savart filament modeling, eddy-current body forces                                   |
| **serde** / **serde_json** | 1.0     | Config serialization for Tauri IPC                                                                 |

### What Magpylib Provided vs. Rust Replacement

| Magpylib (Python)                                        | Rust Equivalent                                                                   |
| -------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `magpy.magnet.Cuboid(polarization, position, dimension)` | `magba::magnet::CuboidMagnet::new(pos, quaternion, polarization_T, dims)`         |
| `magpy.Collection(*magnets)`                             | `magba::sources!(m1, m2, ...)` → `SourceAssembly`                                 |
| `magpy.getB(collection, observers)`                      | `assembly.compute_B_batch(&points)` (Rayon-parallel)                              |
| `magpy.current.Polyline(current, vertices, meshing)`     | `magba::currents::PathCurrent`                                                    |
| `magpy.getFT(magnets, polylines)` — force + torque       | Sample B along segments, then `F = I · Σ(dLᵢ × Bᵢ)`, `τ = Σ(rᵢ × Fᵢ)` (~20 lines) |

### Risks & Mitigations

- **magba is young** (1 contributor, 2 GitHub stars, pre-1.0): Pin version (`=0.6.2`), vendor/fork if long-term stability is needed.
- **No ready-made Lorentz-force API**: The integration loop is trivial (sample B, cross-product, sum). The hard part (closed-form cuboid B-field) is solved by magba.
- **Magba API may change**: Write a thin adapter layer (`pcbstatorgen-rs::physics`) so upstream code is insulated from magba API breaks.

---

## 3. Streamlit vs. Tauri Feasibility Study (Historical Reference)

### A. Why Streamlit Was Replaced

1. **Stateless Execution Bottleneck**: Full script re-run on every widget interaction; severe state-synchronization bugs, page flashes, lost input focus.
2. **No Fine-Grained Reactivity**: Sub-state updates, slider throttling, and interactive animations were near-impossible.
3. **Debugging Limitations**: No standard DevTools; print-statement debugging clashed with rerun loop.

### B. Tauri + Svelte Resolution

- **Multi-Process**: Rust core + lightweight WebView frontend. UI state in Svelte at 60 FPS.
- **Async Command Handlers**: `#[tauri::command]` offloads physics to separate threads.
- **Chromium DevTools**: Full element inspection, console tracing, performance profiling.
- **Svelte**: Compiles to direct DOM manipulation (no virtual DOM). Sub-millisecond reactivity, tiny bundles.

---

## 4. KiCad 10 IPC Alignment Architecture

KiCad 10 exposes its scripting and board-manipulation capabilities via a socket-based IPC protocol (`kipy`). In a pure-Rust Tauri application, the Rust core communicates directly:

```
┌──────────────┐   Tauri IPC     ┌──────────────┐   Unix Socket   ┌──────────────┐
│   Svelte UI  │ ──────────────▶ │  Rust Core   │ ──────────────▶ │  KiCad 10    │
│  (Dashboard)  │ ◀────────────── │ (Tauri Host) │ ◀────────────── │  (Board/PCB) │
└──────────────┘   async commands └──────────────┘   kipy protocol  └──────────────┘
                                         │
                                         │ magba + nalgebra
                                         ▼
                                 ┌──────────────┐
                                 │  Physics     │
                                 │  (B-field,   │
                                 │   F, τ)      │
                                 └──────────────┘
```

1. **Direct Rust-to-KiCad**: The Rust core implements the `kipy` socket protocol directly (JSON over Unix domain socket). No Python translation layer.
2. **Simplicity**: All physics, geometry generation, and KiCad communication happen in a single compiled Rust binary.

---

## 5. 5-Stage Transition Plan (Pure Rust)

```
┌────────────────────────────────────────────────────────┐
│  STAGE 1: Rust Physics Core                             │
│  - Create pcbstatorgen-rs Rust crate                    │
│  - Port config dataclasses to Rust structs (serde)      │
│  - Port coil generators (serpentine, sine wave) to Rust │
│  - Implement B-field via magba, Lorentz force natively  │
│  - Port height stackup + power/thermal equations        │
│  - Validate against Python test vectors                 │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  STAGE 2: Tauri Shell Scaffolding                       │
│  - Initialize Tauri (Svelte + Vite + Tailwind CSS)      │
│  - Wire Tauri commands to Rust physics functions         │
│  - Set up async/threaded execution for heavy sweeps      │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  STAGE 3: Svelte Frontend & Live Metric Binding         │
│  - Build single-dashboard UI with Svelte components     │
│  - Linear toggle (Radial still TODO/disabled)            │
│  - Magnet grade helper, Vernier ratios, ripple metrics   │
│  - Interactive stator/mover/travel diagram              │
│  - Bind sliders to throttled Tauri backend commands     │
│  - Integrate Chromium DevTools for debugging             │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  STAGE 4: KiCad 10 IPC Writer                           │
│  - Implement kipy socket protocol in Rust                │
│  - Track/via grid generation and atomic commits         │
│  - End-to-end board writing test                        │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  STAGE 5: Streamlit Deprecation                         │
│  - Parallel verification runs (Rust vs Python)          │
│  - Safe deletion of gui/streamlit_app.py + server.py    │
│  - Python codebase retained as reference/test oracle    │
└────────────────────────────────────────────────────────┘
```

---

## 6. Known Issues & Remaining Work (Post Phase 5+6)

The following items are tracked as follow-up work after the Phase 5+6 combined execution. They do not block Phase 7 (KiCad IPC Writer) but should be addressed before final Streamlit deprecation (Stage 5).

### A. Tauri Command Stubs — 6 of 9 Commands Need Real Wiring

The Tauri backend (`app/src-tauri/src/commands.rs`) exposes 9 `#[tauri::command]` async handlers. Three are fully wired to real `pcbstatorgen-rs` calls; six return placeholder/stub data and are marked with `// TODO: replace with real pcbstatorgen-rs call`:

| Command | Status | Notes |
| --- | --- | --- |
| `compute_config_derived` | **REAL** | Calls core `LinearMotorConfig` derived methods. |
| `validate_config` | **REAL** | Delegates to core `validate()` + UI-level travel warnings. |
| `get_magnet_grades` | **REAL** | Reads core `magnet_grades::MAGNET_GRADES`. |
| `generate_coils` | **STUB** | Returns a hardcoded serpentine path. Needs wiring to `WaveWindingGenerator` / `SineWaveWindingGenerator`. Conversion layer (`CoilPathIpc::from_core`) is already implemented. |
| `evaluate_force_sweep` | **STUB** | Returns a sinusoidal force profile. Needs wiring to `ForceEvaluator::evaluate()`. |
| `compute_stackup` | **STUB** | Returns placeholder layer data. Needs wiring to `HeightStackCalculator`. |
| `compute_power_budget` | **STUB** | Returns I²R estimate. Needs wiring to `PowerEstimator`. |
| `compute_friction` | **STUB** | Returns split friction values. Needs wiring to `FrictionEstimator`. |
| `compute_height_stack` | **PARTIAL** | Assembles `HeightStackResult` from config fields; `total_height_m()` computed for real. |

**Effort**: ~1 day. The `pcbstatorgen-rs` implementations all exist and pass tests. The IPC conversion layer (`ipc.rs`) has `from_core()` methods ready. Each stub just needs its handler body changed from placeholder to the real call.

### B. Force Ripple — 170% Ripple (Commutation Alignment Bug)

The force sweep produces **170% ripple** with negative min thrust at every 3rd sample position (once per FOC electrical cycle). This is reproduced **identically** in both the Python oracle and the Rust port — the physics is consistent, but the commutation is misaligned.

**Root cause**: The electrical angle formula `θ_e = 2π·p/(2τ) + phase_shift` is misaligned with the actual Bz phase at the Phase-A conductor positions. The self-calibration guard (Newton's Third Law) correctly sets `phase_shift = 0`, but the coil geometry positions do not align with the assumed magnet pole centers, causing current to peak against the field once per cycle.

**Impact**: Force output oscillates between +72 mN and -3 mN instead of a smooth ~45 mN average with <5% ripple.

**Fix approach**: Audit `WaveWindingGenerator` conductor x-positions against `MagnetArray` pole centers. The Phase-A first conductor should sit at a magnet pole center (peak Bz) at position 0. May require adjusting the `conductor_x_positions()` formula or the electrical angle offset.

**Not a blocker for Phase 7**: KiCad track generation does not depend on force sweep quality. The force evaluator produces finite, deterministic values suitable for layout validation.

### C. Python Oracle Patched — Newton's Third Law + Self-Calibration Guard

The Python `ForceEvaluator` (`pcbstatorgen/magnetic/force_eval.py`) was patched during Phase 5 to add:
1. **Newton's Third Law sign flip**: `F_mover = -F_stator` applied to all force and torque outputs (PRODUCT_GOALS.md §4.C).
2. **Self-calibration guard**: Test step at `+0.1·τ_p` forward; if `F_mover.x < 0`, set `phase_shift = π` to align FOC with positive motion.
3. **Dynamic phase shift**: Replaced the hardcoded `+ math.pi` offset in `θ_e` with `+ self._phase_shift` (set by the self-calibration guard).

The Rust port (`crates/pcbstatorgen-rs/src/magnetic/force_eval.rs`) implements the same logic. Test vectors (`scripts/fixtures/test_vectors.json`) were re-exported after the patch and are consistent between Python and Rust.

---

### Test-Driven Validation Requirements

- **Offline Test-Driven Validation**: All changes must be backed by unit tests. The core config and geometry engines must remain runnable offline without requiring a live KiCad 10 IPC socket connection.

### Git Branch Strategy & Execution Guardrails

- **Branch Partitioning**: Feature developments for each phase will be executed on isolated feature branches (e.g., `feat/phase4-ui-overhaul`) and submitted as separate GitHub Pull Requests.
