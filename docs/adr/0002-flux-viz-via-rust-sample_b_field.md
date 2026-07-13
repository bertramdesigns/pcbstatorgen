# 0002 — Flux visualization via Rust `sample_b_field` Tauri command

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

The user wants a flux-line visualization that updates when the magnet
arrangement changes, so the strength and flux of different configurations
(Alternating vs Halbach, with or without back-iron) are immediately
comprehensible.

Two natural approaches:

1. **A `sample_b_field` Tauri command** that wraps the existing
   `MagnetArray::bfield_at_pcb_surface`
   (`crates/pcbstatorgen-rs/src/magnetic/magnet_model.rs:216`) and returns
   sampled B-field vectors to a Svelte component for rendering.
2. **A `magpylib` Python sidecar** that re-implements the B-field sampling
   on the Python side and ships the result to the Svelte frontend.

`PRODUCT_GOALS.md §6` explicitly forbids a Python sidecar: "No Python
runtime or sidecar is required." The historical reference repo
`magpylib` is registered in `opencode.json` as a research source, but
nothing in `app/` imports it. The Rust physics core is the sole
authoritative implementation; `magba =0.6.2` is pinned
(`crates/pcbstatorgen-rs/Cargo.toml`) and the B-field math routes
through the `pcbstatorgen_rs::physics` adapter.

## Decision

Add a new `#[tauri::command] sample_b_field` that wraps
`MagnetArray::bfield_at_pcb_surface` and returns
`Vec<BFieldSampleIpc { x_m, z_m, bx_t, bz_t, mag_t }>` sampled on an X–Z
grid. The Svelte frontend renders an arrow grid from these samples.

The B-field math must route through `pcbstatorgen_rs::physics` — no
direct `magba` calls. `magpylib` may be consulted as read-only research
(for streamline algorithms, field-plot conventions, etc.) but must not
be imported anywhere in the app or Tauri host.

## Consequences

**Positive:**

- The user's request is satisfied with a single Tauri command and a single
  Svelte component. The Rust physics core is the source of truth.
- The "no Python sidecar" architectural constraint is preserved
  (`PRODUCT_GOALS.md §6`).
- Future B-field visualizations (1D plots, 2D heatmaps, animated
  commutation) can reuse the same IPC DTO with no backend changes.

**Negative:**

- The X–Z grid sampling is O(N_x × N_z × N_magnets) and may be slow for
  fine grids. The default 24×12 grid is the suggested upper bound.
- Magpylib's streamlines and field-line integration algorithms are
  battle-tested; this ADR deliberately rejects them in favor of a
  simpler arrow grid. Streamlines can be a follow-on.

**Future constraints:**

- The `BFieldSampleIpc` DTO is part of the public IPC surface. Adding
  fields is additive and safe; removing or renaming fields is a breaking
  change.
- The `sample_b_field` command should be `spawn_blocking`-wrapped
  (consistent with the rest of the Tauri command surface in
  `app/src-tauri/src/commands.rs`).

## Alternatives considered

- **`magpylib` Python sidecar.** Rejected: explicitly forbidden by
  `PRODUCT_GOALS.md §6`. Even if the constraint were relaxed, this would
  require a Python runtime, a `pip install` step, and a serialization
  boundary — orders of magnitude more surface area than the
  `sample_b_field` command.
- **JS-side `magpylib` port (e.g. via WASM).** Rejected: not registered
  as a project reference, would require a separate package, and would
  duplicate the math already implemented in `magba`.
- **Pre-baked static field images.** Rejected: cannot respond to live
  parameter changes; the user explicitly asked for "different permanent
  magnet configurations" to be selectable.
