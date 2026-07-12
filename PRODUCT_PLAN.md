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
│  PHASE 5: Rust Physics Core (magba + nalgebra) IN-PROG │
│  - Branch: feat/phase5-6-rust-tauri (combined w/ P6)    │
│  - Workspace scaffolded: crates/pcbstatorgen-rs + app/  │
│  - Port config structs, coil generators to Rust         │
│  - Implement B-field via magba, Lorentz force natively │
│  - Validate against Python test vectors (scripts/fix.)  │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 6: Tauri + Svelte Desktop Application IN-PROGRESS│
│  - Tauri v2 + Svelte 5 + Vite + Tailwind scaffolded    │
│  - Async physics commands, Chromium DevTools            │
│  - Linear toggle ONLY (Radial still TODO)               │
│  - Live metrics, SVG previews                           │
│  - Interactive travel/active-area diagram:              │
│    stator bar + sliding mover bar + travel zone         │
│    (illustrates travel = stator_len - mover_len)        │
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
| **nalgebra**               | 0.33+   | Vector cross-products, quaternions for magnet orientation                                          |
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

## 5. Execution & Git Branch Strategy

### Test-Driven Validation Requirements

- **Offline Test-Driven Validation**: All changes must be backed by unit tests. The core config and geometry engines must remain runnable offline without requiring a live KiCad 10 IPC socket connection.

### Git Branch Strategy & Execution Guardrails

- **Branch Partitioning**: Feature developments for each phase will be executed on isolated feature branches (e.g., `feat/phase4-ui-overhaul`) and submitted as separate GitHub Pull Requests.
