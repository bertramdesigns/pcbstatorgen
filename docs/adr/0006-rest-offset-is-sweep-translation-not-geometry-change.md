# 0006 — `rest_offset_m` is a sweep-window translation, not a geometry change

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

ADR 0004 introduced `rest_offset_m` as a real derived field on
`LinearMotorConfig`. The natural follow-up question: does the rest
offset change the *physical* travel range of the motor, or just the
window the force sweep samples over?

`travel_m` is a derived quantity in the codebase with a locked
contract from `PRODUCT_GOALS.md §3.A` and `PRODUCT_PLAN.md §6`:

```
travel_m = active_area_length_m − coil_span_m
```

It is a geometric property of the stator (board) and the mover
(magnet array), not a function of the spacing ratio. Changing the
spacing ratio does not change the active area, the coil span, or the
mover length.

The Vernier rest position is a *phase offset* of the magnet's
preferred rest point relative to the coil centers. At 1:1 the magnet
rests directly over a coil; at 4:5 it rests between coils. The
distance the magnet can travel along the stator is unchanged; only
the *starting point* of the sweep shifts.

## Decision

`travel_m` semantics are **unchanged**. The rest offset is a
*phase offset* applied to the force-sweep window only:

```rust
// crates/pcbstatorgen-rs/src/magnetic/force_eval.rs:196-197
let rest = config.rest_offset_m();
let positions = linspace(rest, config.travel_m() + rest, self.n_positions);
```

The sweep covers the same physical distance (`travel_m`) — it is
simply translated by `rest` so that the first sample is taken at the
magnet's rest position, not at raw zero. Coil geometry, active area,
and `coil_span` are all unaffected.

## Consequences

**Positive:**

- The locked `travel_m = active − coil_span` contract is preserved.
  No downstream code that depends on `travel_m` needs to change.
- The force sweep is now physically meaningful: the first sample
  corresponds to the magnet at rest, and the last to the magnet at
  one full travel past the rest position. The peak force, mean
  force, and ripple percentage are all preserved.
- At the default `spacing_ratio = 1.0`, `rest = 0.0` and the sweep
  is byte-identical to the pre-ADR behaviour.

**Negative:**

- The force-sweep plot (in `ForceSweepPlot.svelte`) may show the
  magnet starting at a non-zero x position. This is correct but may
  surprise users who expect x=0 to be the "home" position. The
  plot's x-axis label is "Mover position (mm)" — the unit is still
  correct, but the origin is now the rest position rather than the
  board edge.

**Future constraints:**

- Any future code that asserts specific x-positions in the force
  sweep must account for the rest offset. The 1:1 default preserves
  the old behaviour, so this is a forward-compatibility constraint,
  not a backward-incompatibility one.
- If a future ADR introduces a "physical travel" concept distinct
  from the sweep window, it must not redefine `travel_m`. Add a new
  field, do not repurpose the existing one.

## Alternatives considered

- **Redefine `travel_m` to subtract `rest_offset_m`.** Rejected: would
  change the locked `travel_m = active − coil_span` contract and
  require updating every consumer of `travel_m`.
- **Apply the rest offset in the UI only, not the core.** Rejected:
  the force sweep runs in the core, and a UI/core desync would
  produce inconsistent metrics.
- **Add a separate "effective_travel_m" field that includes the
  rest offset.** Rejected: the sweep distance is unchanged, only
  the window start shifts. There is no new "effective travel" to
  expose.
