# 0005 — CoilPreview per-layer Z offset

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

The user reported: "When exporting to KiCad vias have been completely
missed and all the tracks are generated on top of each other."

Investigation showed two distinct issues bundled under that complaint:

1. **KiCad export bug (real)**: vias are missing because the two
   topologies the UI exposes leave `center_via_positions` empty. This
   is addressed by ADR 0001.
2. **CoilPreview SVG bug (cosmetic)**: every layer's segments are
   drawn at the same Z=0 in the SVG
   (`app/src/lib/components/CoilPreview.svelte:73-89`), so a 4-layer
   coil looks identical to a 1-layer coil. The tracks appear to
   overlap on the preview even though the underlying layer assignment
   is correct (`crates/pcbstatorgen-rs/src/kicad/layer_map.rs:27-41`
   and `crates/pcbstatorgen-rs/tests/kicad_writer.rs:217-238`).

ADR 0001 fixes the export bug. This ADR fixes the preview bug.

Three possible fixes:

1. **Per-layer Z offset in the SVG** — offset each layer by a few
   pixels in the y direction; fade each layer's stroke opacity. Add
   a "schematic, not to scale" caption.
2. **Layer toggle in the preview** — show one layer at a time, with
   a control to switch.
3. **Separate "Layer Stacking" diagram** — a new component that
   shows layers in a side cross-section.

The user's complaint is the appearance of overlap, not the
information that layers are distinct. The export already has them
distinct; only the preview misrepresents this. A per-layer Z offset
addresses the appearance with the smallest UI change.

## Decision

Modify `app/src/lib/components/CoilPreview.svelte` so that:

- Each layer's segments are offset by `layer_idx × 6 px` in the SVG
  y-axis.
- Each layer's `stroke-opacity` is `max(0.35, 1.0 − layer_idx × 0.15)`.
- A "Schematic — layer offsets are for readability, not physical
  scale" caption is added in the bottom-right corner of the SVG.

Phase coloring is still keyed by `phase_idx` (not by layer). End-turn
segments remain dashed and slightly fainter than active segments
within the same layer.

## Consequences

**Positive:**

- The user's "tracks overlapping" complaint is addressed in the
  preview immediately.
- The change is one file, ~15 lines, no new components or props.
- The actual KiCad export (a separate code path through
  `crates/pcbstatorgen-rs/src/kicad/`) is unchanged — its
  per-layer `BoardLayer` assignment was already correct.

**Negative:**

- The SVG is now schematic, not geometrically accurate. The caption
  is the primary mitigation. A user who misreads the diagram as a
  physical scale drawing could make a wrong design decision.
- The fix is cosmetic. The real overlap (in the export) is fixed by
  ADR 0001, not here.

**Future constraints:**

- The 6 px offset and the 0.15 opacity step are visual tuning
  constants. If the typical layer count grows beyond ~6, the lower
  layers may become hard to see and the constants may need
  adjustment.
- A future 3D-aware preview (e.g. an isometric projection) would
  supersede this fix. Until then, the caption is the contract.

## Alternatives considered

- **Layer toggle in the preview.** Rejected: requires a new UI
  control, doesn't address the "all my layers are visible at once"
  use case.
- **Separate Layer Stacking diagram.** Rejected: a new component for
  a fix that 15 lines in the existing component can deliver.
- **3D isometric projection.** Deferred to Round N+1 per the user's
  "maybe not in this round" framing. This ADR is a stepping stone,
  not a permanent solution.
