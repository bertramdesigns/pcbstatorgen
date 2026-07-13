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
│  PHASE 7: KiCad 10 IPC Writer (Rust native)       (DONE)│
│  - kipy socket protocol in Rust (NNG + prost)          │
│  - Track/via grid generation, atomic commits (Ctrl+Z)  │
│  - Wire 6 Phase-6 Tauri stubs to real core calls       │
│  - Svelte KiCad panel (connect, write, dry-run)        │
│  - Streamlit deprecation (Stage 5)                      │
│  - 222 Rust tests pass; 548 Python oracle tests pass   │
│  See §7 — Phase 7 Technical Specification              │
└────────────────────────────────────────────────────────┘
```

---

## 7. Phase 7 Technical Specification — KiCad 10 IPC Writer + Streamlit Deprecation

> Added by the Orchestrator to lock down execution variables for Phase 7.
> Supersedes any conflicting guidance. See `PRODUCT_ARCHITECTURE.md` for the
> full system architecture.

### 7.1 Phase 7 Scope Summary

Phase 7 executes **Stage 4** (KiCad IPC Writer) and **Stage 5** (Streamlit
Deprecation) of the 5-Stage Transition Plan (§5). It is the final phase before
the product reaches feature-complete status.

| Workstream                          | Stage | Priority | Effort   |
| ----------------------------------- | ----- | -------- | -------- |
| Rust NNG socket client + prost      | 4     | P0       | 2 days   |
| KiCad writer module (Track/Via)     | 4     | P0       | 2 days   |
| Atomic commit (BeginCommit/End)    | 4     | P0       | 0.5 day  |
| Vendored .proto files + build.rs    | 4     | P0       | 0.5 day  |
| Wire 6 Tauri stubs to real core     | 4     | P0       | 1 day    |
| 3 new Tauri commands (connect/write/ping) | 4 | P0     | 1 day    |
| Svelte KiCad panel                  | 4     | P1       | 1 day    |
| Offline unit tests (writer, client) | 4    | P0       | 1 day    |
| Gated live integration test         | 4     | P1       | 0.5 day  |
| Streamlit deletion (gui/, launcher) | 5     | P2       | 0.25 day |
| Parallel verification gate          | 5     | P0       | 0.5 day  |
| **Total**                           |       |          | **~10 days** |

### 7.2 Subagent Task Breakdown

The work is partitioned into **5 parallelizable tasks** for delegation to
technical subagents. Dependencies are noted; independent tasks run concurrently.

#### Task A: Protobuf Vendor + Build Infrastructure
**Depends on:** Nothing (blocking for Tasks B, C).
**Deliverables:**
1. Copy `kipy/proto/` from the `kicad-python` reference repo into `crates/pcbstatorgen-rs/proto/`.
2. Add `prost = "0.13"` and `prost-build = "0.13"` (build-dep) to `crates/pcbstatorgen-rs/Cargo.toml`.
3. Write `crates/pcbstatorgen-rs/build.rs` invoking `prost_build` to compile all `.proto` files.
4. Add a `kicad::proto` module in `src/kicad/mod.rs` re-exporting generated types.
5. Verify `cargo build` succeeds with generated proto types.
6. Write `scripts/sync_protos.sh` to re-copy protos from the reference repo.

**Acceptance:** `cargo build` compiles; `prost`-generated structs for `ApiRequest`, `ApiResponse`, `Track`, `Via`, `BeginCommit`, `CreateItems`, `EndCommit` are importable.

#### Task B: NNG Socket Client
**Depends on:** Task A (proto types for envelope).
**Deliverables:**
1. Add `nng = "1.0"` to `crates/pcbstatorgen-rs/Cargo.toml`.
2. Implement `src/kicad/client.rs`: `KiCadClient` struct with `connect()`, `send()`, `recv()`, envelope packing/unpacking.
3. Implement `src/kicad/errors.rs`: `KiCadError` enum (Connection, Api, Protocol, NotConnected).
4. Implement `KicadTransport` trait + `MockTransport` for offline testing.
5. Socket path resolution: `KICAD_API_SOCKET` env var → default `ipc:///tmp/kicad/api.sock`.
6. Token negotiation: cache `kicad_token` from first response.

**Acceptance:** `KiCadClient::send()` packs an `ApiRequest` envelope, sends via NNG, receives `ApiResponse`, unpacks, returns typed response or `ApiError`. `MockTransport` unit tests pass.

#### Task C: KiCad Writer Module (Track/Via/Commit)
**Depends on:** Task A (proto types), Task B (client).
**Deliverables:**
1. `src/kicad/writer.rs`: `coils_to_board_items(coils: &[PhaseCoil], config: &LinearMotorConfig) -> Vec<BoardItem>` — pure function, no socket.
   - Straight `CoilSegment` → `Track` proto (start, end, width, layer, net).
   - `center_via_positions` → `Via` proto (position, drill, width, layer_set, net).
   - Unit conversion: metres → nanometres (`m_to_nm`).
2. `src/kicad/layer_map.rs`: `layer_idx_to_board_layer(idx, total) -> BoardLayer` (0→B_Cu, N-1→F_Cu, else In{n}_Cu).
3. `src/kicad/commit.rs`: `Commit` struct wrapping `BeginCommit → create_items → EndCommit`.
   - `Commit::begin(board) -> Commit`
   - `Commit::create_items(items) -> Vec<KIID>`
   - `Commit::end() -> ()` (drops the commit, finalizes in KiCad — single Ctrl+Z)
4. `src/kicad/board.rs`: `BoardHandle` with `get_copper_layer_count()`, `get_board_name()`.
5. Offline unit tests: verify `coils_to_board_items` output for serpentine + sine wave configs.

**Acceptance:** `cargo test -p pcbstatorgen-rs kicad::` passes. Writer output matches Python `test_kicad_writer.py` expectations (coordinates ±1 nm).

#### Task D: Tauri Command Wiring (6 stubs + 3 new)
**Depends on:** Task C (writer), existing pcbstatorgen-rs core.
**Deliverables:**
1. **Wire 6 existing stubs** in `app/src-tauri/src/commands.rs` to real `pcbstatorgen-rs` calls:
   - `generate_coils` → `WaveWindingGenerator::generate_all_layers()` + `CoilPathIpc::from_core()`.
   - `evaluate_force_sweep` → `ForceEvaluator::evaluate()`.
   - `compute_stackup` → `StackupCalculator::compute()`.
   - `compute_power_budget` → `PowerEstimator::estimate()`.
   - `compute_friction` → `FrictionEstimator::estimate()`.
   - `compute_height_stack` → wire remaining placeholder fields to `HeightStackCalculator`.
2. **Add 3 new commands:**
   - `connect_kicad` → `KiCadClient::connect()`, return board name + copper layers.
   - `write_coils_to_board` → generate coils, `coils_to_board_items()`, `Commit::create_items()`, `Commit::end()`.
   - `ping_kicad` → `KiCad::ping()`, return version.
3. Register all 3 new commands in `app/src-tauri/src/main.rs` `generate_handler!`.
4. All commands use `spawn_blocking` for socket I/O and heavy computation.

**Acceptance:** `cargo build -p pcbstatorgen-app` succeeds. All 9+3 commands return real data. No stub markers remain.

#### Task E: Svelte KiCad Panel + Streamlit Deprecation
**Depends on:** Task D (Tauri commands available).
**Deliverables:**
1. **Svelte frontend** (`app/src/lib/components/KicadPanel.svelte`):
   - Connection status indicator (green/red dot + board name).
   - "Write to Board" button → invokes `write_coils_to_board`.
   - Dry-run toggle: when on, calls `generate_coils` only (no socket write).
   - Error/success toast notifications.
   - Uses Svelte 5 runes (`$state`, `$derived`, `$effect`).
2. **Streamlit deprecation:**
   - Delete `gui/streamlit_app.py`.
   - Delete `scripts/run_headless.py`.
   - Keep `pcbstatorgen/` Python core + `tests/` + `scripts/export_test_vectors.py` as oracle.
   - Move `plugin_entry.py` to `docs/reference/plugin_entry.py` (protocol reference).
   - Update README to remove Streamlit references.
3. **Parallel verification gate:**
   - Run `cargo test --workspace` (all 179+ tests pass).
   - Run `pytest tests/` (Python oracle passes).
   - Both must be green before Streamlit files are deleted.

**Acceptance:** Svelte panel renders, connects, and writes. `gui/` directory removed. CI is green on both Rust and Python test suites.

### 7.3 Execution Order & Parallelism

```
Day 1-2:  Task A (proto vendor + build.rs)  ──────────────┐
                                                          │
Day 2-4:  Task B (NNG client)  ──────────────────────────┐ │
                                                        │ │
Day 3-5:  Task C (writer + commit)  ◀── depends on B ──┘ │
                                                        │ │
Day 4-5:  Task D (Tauri wiring)  ◀── depends on C ──────┘ │
                                                          │
Day 5-6:  Task E part 1 (Svelte panel)  ◀── depends on D  │
                                                          │
Day 6-7:  Task D/E parallel (live test + stub wiring)     │
                                                          │
Day 7-8:  Task E part 2 (Streamlit deletion + verify) ◀──┘
```

**Tasks A and the first half of E (Svelte component scaffold) can start in
parallel** — the Svelte panel can be built against the Tauri command signatures
before the Rust implementation lands.

### 7.4 Risk Register (Phase 7)

| Risk                              | Likelihood | Impact | Mitigation                                                   |
| --------------------------------- | ---------- | ------ | ------------------------------------------------------------ |
| `nng` crate API differs from pynng | Medium     | High   | Wrap in `KicadTransport` trait; fall back to `nng-sys` FFI.  |
| Proto schema mismatch (KiCad 10 version skew) | Low | High   | Pin proto files from the exact kicad-python commit matching installed KiCad 10. |
| 170% force ripple blocks writer   | Low        | None   | Writer does not depend on force sweep quality (§6.B).        |
| KiCad not running during dev      | High       | Medium | Offline unit tests via `MockTransport`; live test gated.     |
| `prost-build` can't resolve proto imports | Medium | High | Vendor all transitive `.proto` deps; test `cargo build` first. |

### 7.5 Acceptance Criteria (Phase 7 Complete)

1. **Rust:** `cargo test --workspace` — all tests pass (179 existing + new kicad module tests).
2. **Python oracle:** `pytest tests/` — all tests pass.
3. **Tauri app:** `cargo build -p pcbstatorgen-app` succeeds; no stub markers in `commands.rs`.
4. **KiCad writer:** Offline tests verify `coils_to_board_items` for serpentine + sine wave.
5. **Live integration** (manual): connect to running KiCad 10, write coils, Ctrl+Z rolls back cleanly.
6. **Streamlit:** `gui/` directory deleted; README updated; no Streamlit references remain.
7. **Svelte:** KiCad panel connects, writes, shows status, handles errors gracefully.

### 7.6 Branch Strategy

- **Feature branch:** `feat/phase7-kicad-ipc-writer`
- **PR target:** `main`
- All 5 tasks land on the same feature branch (they are tightly coupled).
- Squash-merge on approval.

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

### C. Python Oracle — FULLY DEPRECATED (Post-Phase 7)

The Python codebase has been **fully removed**. The Rust core is the sole
authoritative implementation. The verification gate (222 Rust tests + 548
Python tests, all green) confirmed parity before deletion.

**Deleted:**
- `pcbstatorgen/` — Python physics core (test oracle)
- `tests/` — Python pytest suite
- `pyproject.toml` — Python project config
- `scripts/export_test_vectors.py` — fixture generator
- `pcbstatorgen/server.py` — dead JSON-RPC sidecar (pre-Phase-5 architecture)
- `.pytest_cache/`, all `__pycache__/` directories

**Retained:**
- `scripts/fixtures/test_vectors.json` — committed as static test data (un-gitignored)
- `docs/reference/plugin_entry.py` — kipy protocol reference for the Rust port
- `scripts/sync_protos.sh` — proto sync script

The Rust test suite (`crates/pcbstatorgen-rs/tests/test_vectors.rs`) loads the
committed fixtures directly — no Python runtime is needed to regenerate them.

---

### Test-Driven Validation Requirements

- **Offline Test-Driven Validation**: All changes must be backed by unit tests. The core config and geometry engines must remain runnable offline without requiring a live KiCad 10 IPC socket connection.

### Git Branch Strategy & Execution Guardrails

- **Branch Partitioning**: Feature developments for each phase will be executed on isolated feature branches (e.g., `feat/phase4-ui-overhaul`) and submitted as separate GitHub Pull Requests.
