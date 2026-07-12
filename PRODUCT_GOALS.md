# Generalized PCB Stator Motor Generator: Product Goals

This document outlines the high-level product vision, specification, user experience principles, mathematical frameworks, and architectural decisions for `pcbstatorgen`—a generalized, local-first tool for generating multi-layer PCB stator layouts for both linear and rotary (axial-flux) coreless electric motors.

---

## 1. Primary Vision & Scope

The objective is to provide an intuitive, mathematically rigorous, and local-first toolchain for designing, simulating, and layout-drafting PCB stator motors. The toolchain is decoupled into three primary pillars:
1. **PCB Geometry Generation**: Analytical coil layout path generation.
2. **Magnetic & Multiphysics Simulation**: Force, torque, thermal, and friction modeling using Magpylib.
3. **Drafting Integration**: Automating layout routing directly into KiCad 10 via the live IPC Python API.

### Anti-Scope Creep Guardrails
*   **No Fader-Specific Jargon**: All references to motorized faders or audio mixers are removed from the core API and user interface. The tool is generalized to any linear or rotary mechanical actuator.
*   **No Public Distribution Packaging**: There is absolutely no support or packaging for the KiCad Package and Content Manager (PCM). The tool operates as a local, private plugin symlinked into standard directories and executed via a system-level Python virtual environment.
*   **One-Way Pipeline**: The workflow is stateless and strictly one-way (User Input $\to$ Optimization $\to$ KiCad IPC Write). There is no "read-from-board and edit" sync loop.

---

## 2. Structural & UI Paradigm Shift (Single Advanced Dashboard)

To maximize usability and streamline the design loop, the multi-step Wizard has been **completely removed**. In its place, the application adopts a single, highly integrated, state-contained **Advanced Dashboard**. This dashboard features:
1.  **Immediate Parameter Feedback**: Slide any variable and immediately see updated collateral calculations.
2.  **Dual-Fidelity Solvers**: Instant analytical approximations ($< 2\text{ms}$) coupled with an explicit, high-fidelity 3D Biot-Savart / Magpylib sweep on command.
3.  **Clean Separation of Concerns**: A high-level toggle between **Linear Motor** and **Radial (Rotary) Motor** cleanly shifts all UI labels, parameter scopes, and mathematical terminology.

    > ⚠️ **Radial (Rotary) mode is NOT YET IMPLEMENTED (Phase 4).**
    > `AxialMotorConfig` exists as a design stub — it has no geometry generation, no radial coil patterns, and no torque sweep. The Linear/Radial toggle is **disabled** in the UI and clearly labelled `TODO / not-yet-implemented`. Do NOT attempt to implement radial geometry in Phase 4. See [Section 7 — Deferred Scope](#7-deferred-scope--todo) for the full TODO list.

```
                  ┌──────────────────────────────────────────┐
                  │          TOPOLOGY WORKFLOW SELECTOR      │
                  │   [⬤ Linear Motion]   [◯ Radial — TODO] │
                  └────────────────────┬─────────────────────┘
                                       │ (linear only — radial disabled)
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                      ▼
┌───────────────────────────────────────┐             ┌───────────────────────────────────────┐
│        LINEAR ACTUATOR WORKFLOW       │             │      RADIAL MOTOR WORKFLOW (TODO)     │
│        (FULLY IMPLEMENTED)             │             │      AxialMotorConfig = stub          │
├───────────────────────────────────────┤             ├───────────────────────────────────────┤
│ • Active Area Length (mm) — INPUT     │             │ • Outer / Inner Diameter (mm)         │
│ • Center-to-Center Travel — DERIVED    │             │ • Radial Active Width (mm)            │
│ • Active Area Width (mm)              │             │ • Polar Coordinates [θ, r, z]          │
│ • Cartesian Coordinates [X, Y, Z]     │             │ • Conformal Polar Projection End-Arcs │
│ • Straight Serpentine End-Turns        │             │ • SpiralCoilGenerator — unimplemented │
└───────────────────────────────────────┘             └───────────────────────────────────────┘
```

---

## 3. Advanced Mode Parameter Fixes & Mathematical Grounding

The UI parameters have been overhauled to align perfectly with physical reality and standard electromagnetic machine design notation.

### A. Active Area Length ($L_{\text{active}}$, INPUT) → Center-to-Center Travel ($L_{\text{travel, c2c}}$, DERIVED)

> ⚠️ **Direction corrected (Phase 4).** The previous design had `travel` as a primary input and `active_length` as a derived output. This was **backwards from physical reality**. The user's actual workflow is:
> 1. Define the **active area for the PCB traces** (stator track length) — this is the physical board constraint.
> 2. Define the **magnet array** (magnet count + dimensions + gap → `coil_span` / mover length).
> 3. The **center-to-center travel** is then **calculated as a result**.

The **Active Zone Length** ($L_{\text{active}}$) is the physical region spanned by the stator traces on the PCB — this is the **primary INPUT** because it is constrained by the physical board the user can manufacture.

The **Center-to-Center Travel** ($L_{\text{travel, c2c}}$) represents the physical displacement of the mover's reference center point. This is a **DERIVED / READ-ONLY** value — the usable stroke that results from the board minus the mover:

$$L_{\text{travel, c2c}} = L_{\text{active}} - \text{coil\_span}$$

where $\text{coil\_span} = N_{\text{magnets}} \times \tau_p$ is the full span of the mover's magnet array ($N_{\text{magnets}}$ magnets × pole pitch $\tau_p$).

The UI must make this relationship immediately obvious:
> *"Your stator track is $L_{\text{active}}$ mm long, your mover array is $\text{coil\_span}$ mm long, so you get $L_{\text{travel, c2c}}$ mm of usable travel."*

This relationship ensures that the mover remains fully coupled to active stator coils across its entire stroke range, preventing sudden drops in force output at the travel limits. If the user reduces the active area below the coil span, the travel goes to zero or negative — the UI must validate and warn: *"Active area must be longer than the mover array (coil span = X mm)."*

#### Phase 6 (Svelte) Visual Illustration Requirement
The future Svelte UI (Phase 6) **must** include an interactive visual diagram illustrating this relationship:
- The **stator track** (PCB) rendered as a fixed-length horizontal bar labelled with $L_{\text{active}}$.
- The **mover** (magnet array) rendered as a shorter bar that slides along the stator, labelled with $\text{coil\_span}$.
- The **travel range** highlighted as the difference zone at both ends, labelled with $L_{\text{travel, c2c}}$.
- The diagram must update in real-time as the user drags any of: active area length, magnet count, magnet width, or magnet gap.
- Goal: make the identity $\text{travel} = \text{stator\_length} - \text{mover\_length}$ visually self-evident.

### B. Active Area Width ($W_{\text{active}}$)
"Board width" has been renamed to **Active Area Width** ($W_{\text{active}}$). 
*   This explicitly denotes the width of the region that the copper traces can occupy to generate force (i.e., the active vertical conductor length).
*   The mechanical board width will be wider to accommodate mounting holes, edge clearances, and routing channels, but $W_{\text{active}}$ is the primary driver of Lorentz force:
    $$F = I \cdot (\mathbf{L}_{\text{active\_conductor}} \times \mathbf{B})$$

### C. Magnet Grade & Remanence ($B_r$) Helper
To eliminate user guesswork, the UI provides an intuitive lookup helper correlating standard magnet grades and their maximum operating temperatures to their remanence ($B_r$) ranges at $20^\circ\text{C}$:

| Magnet Grade | Remanence Range ($B_r$ [T]) | Max Operating Temp (Suffixes: Std / H / SH / UH / EH / AH) |
| :---: | :---: | :--- |
| **N35** | 1.17 – 1.21 (Typ: 1.19) | Std ($80^\circ\text{C}$), H ($120^\circ\text{C}$), SH ($150^\circ\text{C}$), UH ($180^\circ\text{C}$), EH ($200^\circ\text{C}$), AH ($220^\circ\text{C}$) |
| **N38** | 1.21 – 1.25 (Typ: 1.23) | Std ($80^\circ\text{C}$), H ($120^\circ\text{C}$), SH ($150^\circ\text{C}$), UH ($180^\circ\text{C}$), EH ($200^\circ\text{C}$), AH ($220^\circ\text{C}$) |
| **N42** | 1.28 – 1.32 (Typ: 1.30) | Std ($80^\circ\text{C}$), H ($120^\circ\text{C}$), SH ($150^\circ\text{C}$), UH ($180^\circ\text{C}$), EH ($200^\circ\text{C}$), AH ($220^\circ\text{C}$) |
| **N44** | 1.32 – 1.36 (Typ: 1.34) | Typical grade for coreless actuator movers (e.g., N44H). |
| **N48** | 1.38 – 1.42 (Typ: 1.40) | High-performance industrial grade. |
| **N52** | 1.43 – 1.48 (Typ: 1.45) | Maximum commercial energy density. Low thermal limit (typically Std $80^\circ\text{C}$). |

### D. Magnet Gap and Pole Pitch Dynamic Calculation
The UI replaces the abstract "Magnet Pitch" with **Gap between magnets** ($g_{\text{magnet}}$) allowing $g_{\text{magnet}} \ge 0$.
*   A gap of $0\text{ mm}$ represents a continuous edge-to-edge magnet array.
*   The fundamental **pole pitch** ($\tau_p$) is computed dynamically in the background and presented as real-time feedback:
    $$\tau_p = W_{\text{magnet}} + g_{\text{magnet}}$$
    where $W_{\text{magnet}}$ is the magnet width along the travel axis.

---

## 4. Physics, Electromagnetics, and Sign Conventions

The core physics solvers utilize Magpylib to evaluate magnetic flux density ($B$), force ($F$), and torque ($T$).

### A. Step Smoothness & Cogging Feedback
A core distinction of coreless (air-core) PCB stator motors is that they possess **zero cogging force** ($F_{\text{cogging}} = 0$). Cogging force is caused by the magnetic attraction between permanent magnets and iron stator slots/teeth. Because our stator consists entirely of copper and FR4, there is no magnetic material to attract the magnets when the coils are unenergized.
However, **force ripple** (or torque ripple) still occurs when the motor is active:
1.  **Harmonic Force Ripple**: Caused by non-sinusoidal back-EMF, winding layout harmonics, and spatial magnet flux harmonics.
2.  **Array Edge Ripple**: In linear motors, as the finite-length magnet carriage glides over the stator, the entry and exit of magnets over coil turns creates force fluctuations.
3.  **Modeling Force Ripple**:
    $$\text{Ripple \%} = \frac{F_{\text{max}} - F_{\text{min}}}{F_{\text{mean}}} \times 100\%$$
    The live metrics panel calculates and displays this Ripple percentage based on the 3D physics sweep.

### B. Spacing Ratios & Vernier Windings
To combat spatial force harmonics and achieve ultra-smooth haptic slider operation, we introduce **Spacing Ratios / Vernier Windings**:
*   **1:1 Standard**: Standard fractional-slot concentrated or wave winding where the nominal slot pitch relates directly to the pole pitch ($3\text{ slots per } 2\text{ poles}$ for 3-phase).
*   **Vernier Fractional Slot Spacing**: Introducing deliberate fractional ratios (e.g., $4:5$ or $5:6$ spacing ratios of coils to poles).
*   *How it works*: By slightly offsetting coil centers relative to the magnetic poles (spatial phase-shifting), high-frequency force harmonics generated by individual coils cancel each other out, dramatically reducing spatial ripple (often by $>75\%$) at the expense of a minor reduction ($5-10\%$) in peak fundamental force.
*   *UI Implementation*: A dropdown allows selection of spacing ratios, dynamically modifying the stator winding pitch in the generator backend.

### C. Direct-Action Force Calibration (Newton's Third Law)
*   *The Physics*: When evaluating `magpy.getFT(magnets, coils)`, the library computes the electromagnetic force acting **on the stationary coils** ($\mathbf{F}_{\text{stator}}$).
*   *The Correction*: Since the PCB stator is physically bolted down, the actual moving body is the magnet carriage/rotor. The force acting on the mover is equal and opposite:
    $$\mathbf{F}_{\text{mover}} = -\mathbf{F}_{\text{stator}}$$
    $$\mathbf{T}_{\text{mover}} = -\mathbf{T}_{\text{stator}}$$
*   *Self-Calibration Guard*: At startup or configuration load, the simulator executes a single test step of $+0.1\tau_p$ forward. If the resulting $\mathbf{F}_{\text{mover}}$ is negative, the phase currents are automatically inverted ($180^\circ$ phase shift) to align the FOC electrical angle with positive mechanical motion.

### D. Real-world Friction & Normal Attraction Forces
*   **The Magnetic Normal Attraction Coupling**: If a steel keeper (back-iron plate) is placed behind the magnets to boost field intensity, the magnets attract the steel with a massive normal clamp force ($F_z$). This normal force clamps the mechanical guides, dramatically escalating friction:
    $$F_{\text{friction}} = \mu_{\text{bearing}} \cdot \left( F_{\text{payload}} + |F_{z,\text{magnetic}}| \right) + F_{\text{drag}}$$
*   **Breakaway vs. Dynamic Drag**:
    *   *Static Breakaway ($F_{\text{static}}$)*: The stiction force that must be overcome to initiate movement.
    *   *Dynamic Drag ($F_{\text{dynamic}}$)*: The ongoing sliding drag once in motion.
*   **Net Usable Output**: The GUI displays a stacked bar chart illustrating calculated electromagnetic force, opposing friction, and the final **Net Usable Force Margin** (the payload capability).

---

## 5. Supported Coil Topologies

To minimize scope creep, layout generation and preview support are restricted to two highly optimized, selectable topologies.

1.  **Square Serpentine (Standard Serpentine Wave Winding)**:
    *   *Linear*: $90^\circ$ abrupt transitions from active vertical traces to horizontal end-turn connectors.
    *   *Rotary*: Straight radial segments along sector boundaries transitioning to circular concentric arcs.
    *   *Performance*: Maximum copper density (fill factor), but higher spatial force harmonics (higher ripple %).
2.  **Sine Wave Serpentine (Sinusoidal Wave Winding)**:
    *   *Linear*: Traces run a continuous, smooth sine wave along the travel axis:
        $$y(x) = \frac{W_{\text{active}}}{2} \sin\left(\frac{\pi x}{\tau_p}\right) + \frac{W_{\text{active}}}{2}$$
    *   *Rotary*: Radial segments smoothly curve as a function of angle:
        $$r(\theta) = R_{\text{inner}} + \Delta R \cdot \sin^2\left(\frac{P \cdot \theta}{2}\right)$$
    *   *Performance*: Exceptionally clean sinusoidal back-EMF, **minimizing force/torque ripple** below $2\%$. Ideal for ultra-smooth haptic textures.

---

## 6. Architecture Decision: Pure Rust (Tauri + Svelte + magba)

### Decision
The application will be a **pure Rust** native desktop application built on **Tauri** (Rust core) with a **Svelte + Vite + Tailwind CSS** frontend. All physics computation — including analytical magnetic B-field, Lorentz force, and torque — runs natively in Rust. **No Python runtime or sidecar is required.**

### Rationale
- **magba** (v0.6.2, BSD-3-Clause) is a Rust crate that explicitly implements Magpylib's analytical closed-form B-field formulas for cuboid magnets, validated against Magpylib itself. It provides `CuboidMagnet`, `PathCurrent` (polyline conductors), `sources!` collection macro, and Rayon-parallel `compute_B_batch`.
- **Lorentz force** (`F = I·∫dL×B`) is a trivial ~20-line integration loop in Rust using `nalgebra` — sample B along each conductor segment, cross-product, sum. No external crate needed.
- **Torque** about a pivot is `τ = Σ(rᵢ × Fᵢ)` — 5 lines of `nalgebra`.
- **cfsem** (v11.2.0, MIT) is available as an optional complement for advanced Biot-Savart filament modeling or eddy-current body forces if needed in future phases.
- **Tauri Multi-Process**: Rust core with lightweight WebView frontend. UI state isolated in Svelte at 60 FPS; async command handlers (`#[tauri::command]`) offload computation to separate threads.
- **Zero Python dependency**: No PyInstaller, no JSON-RPC socket overhead, no serialization boundary. Single compiled binary (~15 MB). Native Rayon multi-threading.
- **KiCad 10 IPC**: The Rust core communicates with KiCad via Unix domain sockets directly, or via a minimal `kipy`-protocol shim. No Python translation layer needed.

---

## 7. Deferred Scope & TODO

The following features are explicitly **out of scope for the current phase** and tracked here to prevent accidental implementation.

### A. Radial / Axial-Flux Rotary Motor Mode — DEFERRED
`AxialMotorConfig` exists in `pcbstatorgen/config.py` as a design stub. It is **instantiable** (validates stator OD/ID, torque targets) but has **no functional geometry, physics, or torque sweep**. The following work is required before it can be used:

1. `SpiralCoilGenerator` — the natural coil topology for disk stators (in-out layer-pair winding).
2. Annular geometry in `WaveWindingGenerator` / `SpiralCoilGenerator` — conductors must follow circular arcs, not straight lines.
3. `MagnetArray` updated to arrange Cuboid magnets in a ring at the correct radial positions, not a linear array.
4. `ForceEvaluator` updated to compute **torque** [N·m] instead of linear force [N]; uses `magpy.getFT()` with a rotational pivot.
5. `LayerOptimizer` constraints adapted for disk geometry (annular area, circumferential slot pitch at mean radius).
6. KiCad writer updated to emit a circular board outline.
7. `HeightStackResult` extended for the dual-sided axial flux gap.

**Phase 4 UI handling**: The Linear/Radial toggle is **disabled** (greyed out or rendered as a non-clickable `TODO` label). No radial parameter inputs are exposed. Attempting to select radial mode is a no-op with an informational message: *"Radial (axial-flux) motor mode is not yet implemented. Tracked for a future phase."*

### B. Config Refactor: `active_area_length_m` as Stored Field — COMPLETED IN PHASE 4
The config refactor was completed in Phase 4 (not deferred to Phase 5). `LinearMotorConfig` now stores `active_area_length_m` as the primary input field, and `travel_m` is a **derived `@property`**: `active_area_length_m - coil_span_m`. The `active_length_m` property returns `active_area_length_m` directly. All tests, scripts, and serialization have been updated. The serialization layer accepts both new (`active_area_length_m`) and legacy (`travel_m`) JSON keys for backwards compatibility.

---

## 8. Technical Specifications (Phase 5+6 Combined Execution)

> Added by the Orchestrator to lock down architecture variables for the combined Rust physics core + Tauri/Svelte scaffold. These supersede any conflicting guidance.

### A. Combined-Phase Strategy
Phases 5 and 6 are executed **together** rather than sequentially. The Tauri + Svelte + Vite + Tailwind application shell is scaffolded FIRST so that Rust physics development happens inside a real desktop app (with `cargo` workspace, `#[tauri::command]` handlers, and a dev server) from day one — rather than porting to a bare Rust crate first and bolting Tauri on later.

### B. Workspace Layout
```
kicad-pcbmotorcoils/
├── pcbstatorgen/            # Python core — UNCHANGED, retained as test oracle (Stage 5 / Phase 7)
├── tests/                   # Python pytest suite — UNCHANGED, test oracle
├── crates/
│   └── pcbstatorgen-rs/     # Rust physics library crate (pure, no Tauri dep)
│       ├── Cargo.toml
│       └── src/ (config, units, magnet_grades, geometry/, magnetic/, stackup/, physics/)
├── app/                     # Tauri + Svelte desktop application
│   ├── src-tauri/           # Tauri host binary — depends on pcbstatorgen-rs
│   ├── src/                 # Svelte 5 frontend (runes mode)
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── Cargo.toml               # Workspace root (members: crates/pcbstatorgen-rs, app/src-tauri)
└── ...
```

### C. Pinned Crate Versions
| Crate | Version | Role |
| --- | --- | --- |
| `magba` | `=0.6.2` | Analytical cuboid B-field (Magpylib-validated). PINNED — wrap in adapter. |
| `nalgebra` | `0.33` | Vector math: cross-products, quaternions for magnet orientation. |
| `rayon` | `1.10` | Data-parallel B-field sampling across observation points. |
| `serde` / `serde_json` | `1.0` | Config + result serialization for Tauri IPC. |
| `tauri` | `2` | Desktop app host, async command handlers. |
| `svelte` | `5` | Frontend (runes: `$state`, `$derived`, `$effect`). |
| `vite` | `5+` | Frontend bundler / dev server. |
| `tailwindcss` | `3.4` | Utility CSS. |

### D. Adapter Layer Convention
All direct `magba` calls are isolated behind a `pcbstatorgen_rs::physics` adapter module. Upstream code (force evaluator, field sampler) calls `physics::compute_b_field(...)` / `physics::CuboidSource`, never `magba::...` directly. This insulates the codebase from magba API breaks if the version pin is lifted later.

### E. Test Oracle Protocol
- Python codebase is **NOT deleted** (Stage 5 deprecation is Phase 7). It remains the validation oracle.
- A `scripts/export_test_vectors.py` script dumps canonical JSON fixtures (config → coils → force sweeps) consumed by Rust unit tests.
- Rust tests load these vectors and assert numerical agreement within a documented tolerance (B-field ±1%, force ±2%, ripple ±0.5pp).

### F. Sign Conventions (locked)
- `F_mover = -F_stator` (Newton's Third Law calibration, §4.C).
- Self-calibration guard at startup: test step of `+0.1·τ_p`; if `F_mover < 0`, invert phase currents (180° shift).
- Ripple % = `(F_max - F_min) / |F_mean| × 100`.
- Travel = `active_area_length - coil_span` (active area is INPUT, travel is DERIVED/READ-ONLY).

### G. Scope Boundaries for Phase 5+6
- **Linear mode ONLY.** Radial/axial-flux UI toggle is disabled and labelled TODO. `AxialMotorConfig` remains a stub.
- KiCad IPC writer is Phase 7 — NOT in scope here. Tauri commands expose physics + geometry + stackup only.
- No public/distribution packaging.
