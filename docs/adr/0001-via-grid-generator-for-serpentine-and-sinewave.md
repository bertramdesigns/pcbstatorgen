# 0001 — Inter-layer via-grid generator for Serpentine and SineWave

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

The user reported that KiCad exports contain no vias and that tracks from
different layers appear to overlap. Investigation confirmed two root causes:

- `CoilTopologyIpc` exposes only two topologies — `Serpentine` and
  `SineWave` — for the user-selectable coil generator
  (`app/src-tauri/src/ipc.rs:84-109`).
- Both topologies leave `center_via_positions = vec![]`
  (`crates/pcbstatorgen-rs/src/geometry/wave_winding.rs:212`). The only
  generator that populates this field is `SpiralCoilGenerator`
  (`crates/pcbstatorgen-rs/src/geometry/coil_generators.rs:289, 297, 328, 338`).
- There is no inter-layer end-turn-to-end-turn via generator anywhere in the
  codebase. The README originally advertised "Grid via arrays at every
  end-turn — dozens of small parallel vias" but no code implements this.

There are two natural ways to address this:

1. **Expand the topology surface** to expose `Concentrated`, `Rhombic`, and
   `Spiral`, which would naturally populate `center_via_positions`.
2. **Add an inter-layer end-turn via-grid generator** that runs for the two
   existing topologies without changing the topology surface.

The user-facing complaint is "vias are missing for the topology I can
select," not "I want more topologies." Expanding the topology surface would
add IPC DTO churn, a saved-state serde migration for any persisted
configuration, and a wider blast radius for testing.

## Decision

Add an inter-layer end-turn via-grid generator inside
`crates/pcbstatorgen-rs/src/geometry/wave_winding.rs` that populates
`center_via_positions` for the existing `Serpentine` and `SineWave`
topologies. Do not change the `CoilTopologyIpc` surface.

The generator must:

- Place at least one through-via at each inter-layer transition point (the
  end-turn where the coil path crosses from one layer to the next).
- Respect `drill_diameter < slot_pitch − 2 × annular_ring` so adjacent
  phases cannot short through a shared via pad.
- Update `scripts/fixtures/test_vectors.json` to reflect populated vias.
- Preserve the existing `BeginCommit/EndCommit` atomic transaction in
  `write_coils_to_board` (`app/src-tauri/src/commands.rs:477-509`).

## Consequences

**Positive:**

- The user's complaint is fixed with the smallest possible blast radius.
- No IPC DTO churn, no serde migration, no new topology to document in the
  UI.
- The atomic commit guarantee from Phase 7 is preserved — all tracks and
  vias are written in one undo step.

**Negative:**

- The end-turn via placement rule (one via per inter-layer transition) is a
  heuristic. Real designs may want to skip vias where the routing naturally
  continues on the same net; this ADR does not introduce per-net via
  control.
- The fixture update in `test_vectors.json` is a one-time churn. Future
  changes to the via generator must regenerate the fixture.

**Future constraints:**

- Any future topology that needs vias must populate `center_via_positions`
  in its generator, not rely on a default.
- The drill-clearance guard must remain in place; loosening it would
  reintroduce the short-circuit risk.

## Alternatives considered

- **Expand `CoilTopologyIpc` to expose Concentrated/Rhombic/Spiral.**
  Rejected: larger blast radius (new UI control, new serde paths, new
  generator wiring), and doesn't directly address the user's complaint.
- **Add a default "pad at every coil endpoint" rule in the writer layer.**
  Rejected: would emit vias even for single-layer coils where they are
  unnecessary, and would couple the writer to the generator more tightly
  than necessary.
