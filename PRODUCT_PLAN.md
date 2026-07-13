# Generalized PCB Stator Motor Generator: Product Plan

This document is the **high-level product roadmap** for `pcbstatorgen`.
It captures the phase history, the active bug tracker, the deferred wishes,
and pointers to the authoritative sources for round-level execution detail.

For product vision and specification, see `PRODUCT_GOALS.md`.
For the full system architecture, see `PRODUCT_ARCHITECTURE.md`.

> **Status (2026-07-13):** Phases 1–7 are **DONE**. 302 Rust tests pass
> workspace-wide and the Tauri host builds clean. Round-based work continues;
> see the **Known Issues (Active Bugs)** and **Wishes (Deferred / Backlog)**
> sections below for the current and next round of work. The Python codebase
> was fully removed in Phase 7 — any references to `pcbstatorgen/` (Python)
> or the Magpylib Python oracle are historical only.
>
> **Authoritative round-level detail** (per-WP breakdowns, file:line citations,
> verification blocks, subagent task allocations) lives in
> `.opencode/active_task.json`. This document intentionally avoids duplicating
> that execution-level content.

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
│  - Wizard removal, dashboard consolidation, travel     │
│    and board width fixes, magnet helpers, ripple.     │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 5: Rust Physics Core (magba + nalgebra)  (DONE) │
│  - Workspace: crates/pcbstatorgen-rs + app/ (Tauri v2) │
│  - Config structs, coil generators, stackup → Rust serde│
│  - B-field via magba, Lorentz force natively (nalgebra) │
│  - Newton's 3rd Law + self-calibration guard (ported)   │
│  - Validated vs Python (±1% B, ±2% F)                  │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 6: Tauri + Svelte Desktop Application   (DONE)  │
│  - Tauri v2 + Svelte 5 (runes) + Vite + Tailwind       │
│  - Svelte components, interactive travel diagram         │
│  - Live metrics, SVG previews, force sweep plot         │
│  - Linear toggle ONLY (Radial still TODO)               │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  PHASE 7: KiCad 10 IPC Writer (Rust native)    (DONE)  │
│  - kipy socket protocol in Rust (NNG + prost)          │
│  - Track/via grid generation, atomic commits (Ctrl+Z)  │
│  - Wire Phase-6 Tauri stubs to real core calls         │
│  - Svelte KiCad panel (connect, write, dry-run)        │
│  - Streamlit deprecation                               │
└────────────────────────────────────────────────────────┘
```

The phase roadmap above is a **historical record** (Phases 1–7 all DONE).
For current and next-round work, see **Known Issues (Active Bugs)** and
**Wishes (Deferred / Backlog)** below.

---

## Known Issues (Active Bugs)

This is the consolidated, high-level bug tracker. Bugs 1–15 are carried over
from prior rounds with their current status; the **Net Short-Circuit** bug
(Bug 16) is the only newly-reported, fully ACTIVE item this round.
**Only bugs marked ACTIVE still need work.** Per-round WP breakdowns,
file:line citations, and root-cause notes live in `.opencode/active_task.json`.

| #  | Bug                                                              | Status                                 | Notes                                                                                                                                                                                                              |
|----|------------------------------------------------------------------|----------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | `validate_write_preconditions` always reports 12 layers          | RESOLVED (Round 5)                     | —                                                                                                                                                                                                                  |
| 2  | Back iron graphics don't clear when toggling off                 | RESOLVED (Round 5)                     | —                                                                                                                                                                                                                  |
| 3  | Back iron thickness doesn't change peak force                     | RESOLVED (Round 5)                     | —                                                                                                                                                                                                                  |
| 4  | Halbach + back iron looks like Alternating + back iron           | PARTIALLY RESOLVED (Round 5)           | Full Halbach spatial layout deferred — see Wishes.                                                                                                                                                                  |
| 5  | KiCad via export fails: `could not unpack PCB_VIA`               | RESOLVED (Round 6 — `ALL_LAYERS` fix)  | Three-round fix sequence; the layer-set enumeration was the final blocker.                                                                                                                                         |
| 6  | Travel diagram magnets clip through PCB                          | PARTIALLY RESOLVED (Round 5)          | Further rework tracked under Bug 14.                                                                                                                                                                               |
| 7  | KiCad write STILL fails with `PCB_VIA` error                      | RESOLVED (same fix as Bug 5)           | Numbering retained for traceability.                                                                                                                                                                                |
| 8  | SVG coil view shows nothing (CoilPreview renders blank)          | RESOLVED (Round 6)                     | Bounding box order fix.                                                                                                                                                                                             |
| 9  | 3/4 view has overlapping boxes (PCB and magnet at same Y)       | RESOLVED (Round 6)                     | Z-stack offset fix.                                                                                                                                                                                                 |
| 10 | Front view air gap is cross-hatched (should be transparent)       | RESOLVED (Round 6)                     | Air gap now rendered as labeled empty region.                                                                                                                                                                       |
| 11 | Back iron show/hide not working correctly                         | RESOLVED (Round 6)                     | —                                                                                                                                                                                                                  |
| 12 | Choosing back iron should auto-add thickness                      | RESOLVED (Round 6)                     | Default ~1 mm applied on toggle-on.                                                                                                                                                                                 |
| 13 | Travel position measured from mover center, not track end         | RESOLVED (Round 6)                     | Slider range now lets the mover traverse the full active area.                                                                                                                                                      |
| 14 | TravelDiagram needs major rework                                  | PARTIALLY RESOLVED (Round 6)          | 2D side view removed; dimensions moved to 3/4 view; slider added. Remaining: 3/4 dimension annotations — DEFERRED.                                                                                                  |
| 15 | Back iron image applied even when `back_iron_thickness = 0`       | RESOLVED (Round 6)                     | Image-magnet routine now guards on `back_iron_thickness > 0`.                                                                                                                                                       |
| 16 | **Net short-circuit: all items saved with `(net "/A")`**          | **ACTIVE — deferred to new session**   | In `test/MagneticFader.kicad_pcb` all 588 items have `(net "/A")` instead of `{"/A","/B","/C"}`. The Rust source is verified correct by the new regression test `test_distinct_phase_nets_for_three_phase_config`, but the user-facing saved file still shows the bug. Likely a stale build, a mock-backend producing all-phase-A coils, or an uncovered serialization path. See artifact `test/MagneticFader.kicad_pcb` and the proof-of-correctness test. |

**Active items requiring work this round (Round 7+):**
- **Bug 16** — Net `/A` short-circuit (new; deferred to a fresh session).
- **Bug 4** — Halbach + back iron visualization (carryover; full Halbach spatial
  layout deferred to a dedicated round — see Wishes).

---

## Wishes (Deferred / Backlog)

Improvements the user has requested but deferred to a future round.

| #  | Wish                                             | Effort                | Notes                                                                                                                                                                                                                                            |
|----|--------------------------------------------------|-----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| W1 | Air gap editable in height stack visualization   | Small                 | `air_gap_mm` exists as a separate input; wish is to make it explicit/editable in the height stack diagram.                                                                                                                                       |
| W2 | Stackup visualization should be Y-Z oriented     | Small                 | Current orthographic side view is X-Z; rotate to Y-Z so the height profile along the stator length is visible. Likely subsumed by the Bug 14 rework (2D side view removed; dimensions moved to 3/4).                                              |
| W3 | Collapsible left panel sections                  | Small (stop-gap)      | Each subsection in `ParameterPanel.svelte` should have a clickable header that toggles its content visibility. Acknowledged as a stop-gap until the panel is redesigned.                                                                        |
| W4 | Backplane under PCB                              | Medium (future feature)| A second back-iron-like plate sits BELOW the PCB (below the bottom copper layer, below the coils) to increase the field for symmetry. The existing "above the magnets" back iron is unchanged. Requires a new config field and new image magnets in `build_image_magnets`. |
| W5 | SVG coil preview zoom + one-section pattern view | Medium (needs rework) | CoilPreview is too small; needs pan/zoom. Also: show ONE repeat of the wave pattern with annotations rather than the full repeating pattern. Blocked on Bug 8 (now RESOLVED).                                                                     |

### Future feature (expanded from W4 and Bug 4 carryover)

- **Backplane below the PCB** — refined W4. The user clarified: *"the back iron
  for the pcb is not inbetween the pcb and magnets. It is below the bottom
  layer, below the coils. The other back iron would be above the magnets (as it
  currently is)."* A second back-iron-like plate sits below the bottom copper
  layer to increase the field for symmetry; the existing above-magnets back
  iron is unchanged. Deferred to a future round. Requires a new config field
  and new image magnets in `build_image_magnets`.
- **Halbach array with proper spatial layout** — currently a simple N/S
  alternation with small 2 mm X-polarized interleave magnets. A proper Halbach
  has multiple magnet pieces per pole with specific sizes and angles
  (90°/45°). Substantial work — defer to a dedicated round.
- **Substantial Halbach boost visualization** — the user observed that
  "changing from Halbach to Halbach with steel shows improved force, even when
  back iron is 0." The immediate symptom (Bug 15) is now RESOLVED. The wish for
  a more substantial Halbach force-boost visualization is deferred.

---

## Round 7 — Net /A Short-Circuit Investigation + Docs Cleanup (2026-07-13)

**Scope:** One bug investigated but **unresolved** — Bug 16 (all items saved
with `(net "/A")`). The magnetics-sim-expert confirmed the current Rust source
is correct (a new regression test `test_distinct_phase_nets_for_three_phase_config`
produces `{"/A", "/B", "/C"}`), but the user-facing saved
`test/MagneticFader.kicad_pcb` artifact still shows the short-circuit (all 588
items on `/A`). Root cause is unresolved — candidates are a stale build, a mock
backend producing all-phase-A coils, or an uncovered serialization path. The
user deferred further investigation to a new session.

**Secondary scope:** Documentation cleanup — slimming this file
(`PRODUCT_PLAN.md`) down to a high-level roadmap and consolidating
round-level execution detail into `.opencode/active_task.json`.

**Owner:** deferred (Bug 16 to a fresh session; docs cleanup to `@product-owner`).
**Files touched this round:** docs only (`PRODUCT_PLAN.md`).

> Per-WP breakdowns, file:line citations, and verification blocks for Round 7
> are tracked in `.opencode/active_task.json` under `rounds.round-7-*`.

---

## Architectural Decisions

Architectural decisions are recorded as ADRs in [`docs/adr/`](docs/adr/README.md).
Each ADR captures the context, the choice, the consequences, and the
alternatives considered.

| ID       | Title                                                                                        | Status   |
|----------|----------------------------------------------------------------------------------------------|----------|
| [ADR-0001](docs/adr/0001-via-grid-generator-for-serpentine-and-sinewave.md) | Inter-layer via-grid generator for Serpentine and SineWave | Accepted |
| [ADR-0002](docs/adr/0002-flux-viz-via-rust-sample_b_field.md)               | Flux visualization via Rust `sample_b_field` Tauri command | Accepted |
| [ADR-0003](docs/adr/0003-arrangement-viz-auto-refresh.md)                  | Arrangement selector auto-refreshes flux viz + force sweep | Accepted |
| [ADR-0004](docs/adr/0004-resting-position-as-real-derived-field.md)        | Resting position as a real derived field `rest_offset_m`  | Accepted |
| [ADR-0005](docs/adr/0005-coilpreview-per-layer-z-offset.md)                | CoilPreview per-layer Z offset                            | Accepted |
| [ADR-0006](docs/adr/0006-rest-offset-is-sweep-translation-not-geometry-change.md) | `rest_offset_m` is a sweep-window translation, not a geometry change | Accepted |
| [ADR-0007](docs/adr/0007-no-saved-state-serde-migration-needed-for-slice-1.md) | No saved-state serde migration needed for Slice 1 | Accepted |

Additional architectural context (physics engine choice, KiCad IPC alignment,
Streamlit→Tauri transition) is documented in `PRODUCT_ARCHITECTURE.md` and the
referenced ADRs.

---

## Validation Requirements & Branch Strategy

- **Offline Test-Driven Validation:** All changes must be backed by unit tests.
  The core config and geometry engines must remain runnable offline without a
  live KiCad 10 IPC socket connection.
- **Branch Partitioning:** Each phase/round executes on an isolated feature
  branch (e.g. `feat/phase4-ui-overhaul`, `chore/round7-docs-cleanup`) and
  lands via a separate PR. Squash-merge on approval.
- **Parallel Verification Gate (Phase 7 onward):** `cargo test --workspace`
  must be green. The Python oracle gate is historical only (Python codebase
  removed in Phase 7).

---

## Authoritative Sources of Truth

| Artifact                       | Owner                | Contents                                                                                       |
|-------------------------------|----------------------|------------------------------------------------------------------------------------------------|
| `PRODUCT_GOALS.md`            | `@product-owner`     | Product vision, target hardware, winding topology requirements.                                |
| `PRODUCT_ARCHITECTURE.md`     | `@product-owner`     | System architecture, physics engine choice, KiCad IPC alignment, Streamlit→Tauri transition.   |
| `PRODUCT_PLAN.md` (this file) | `@product-owner`     | High-level phase roadmap, active bug tracker, deferred wishes, ADR pointer.                    |
| `.opencode/active_task.json`  | orchestrator         | **Authoritative** round-level execution detail: per-WP breakdowns, file:line citations, verification blocks, subagent task allocations. |
| `docs/adr/`                   | `@product-owner`     | Architectural Decision Records.                                                                |
