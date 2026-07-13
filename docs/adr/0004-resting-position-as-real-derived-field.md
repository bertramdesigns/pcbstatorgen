# 0004 — Resting position as a real derived field `rest_offset_m`

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

The user reported: "The spacing ratio and its impact on the resolution
has no effect and is not helpful. When this is discussed, it needs to
discuss the 'resting position.' for example 1:1 will rest directly over
the coil position if correctly layed out. Where as vernier spacing would
rest in-between, increasing the step resolution."

Investigation showed two compounding causes:

1. The frontend mock in `app/src/lib/tauri.ts:160-196` (used when the
   backend is unreachable) generates **identical segments for every
   spacing-ratio value**. When the user changes the dropdown, nothing
   visibly changes.
2. There is no "resting position" concept in the codebase. The force
   sweep samples `linspace(0.0, travel_m, n_positions)`
   (`crates/pcbstatorgen-rs/src/magnetic/force_eval.rs:196`) starting at
   raw zero, with no relationship to the spacing ratio.

The user explicitly framed the rest position as a physical phenomenon
that depends on the spacing ratio: at 1:1 the mover rests directly over
a coil, at 4:5 (or other Vernier ratios) it rests between coils. This is
a real quantity, derivable from the configuration:

```
rest_offset_m = (pole_pitch / phases) × (1 − spacing_ratio)
```

Two natural responses:

1. **Help text only.** Add tooltips and a derived-geometry display, but
   don't change any math.
2. **Real derived field.** Add `rest_offset_m` to `LinearMotorConfig`,
   expose it via IPC, display it in the UI, and rebase the force sweep
   start so the sweep is anchored to the rest position.

The user said the dropdown currently "has no effect and is not helpful."
Help text alone repeats that failure mode.

## Decision

Add a real derived field `rest_offset_m` to `LinearMotorConfig`:

```rust
pub fn rest_offset_m(&self) -> f64 {
    ((self.pole_pitch_m() / self.phases as f64) * (1.0 - self.spacing_ratio))
        .clamp(0.0, self.pole_pitch_m())
}
```

The field is:

- **Derived only** — not user input, not serialized in
  `LinearMotorConfigIpc`, not part of any saved state.
- **Exposed via `ConfigDerivedIpc`** as `rest_offset_m` and `slot_pitch_m`
  (the latter is the basis of the offset and was previously hidden from
  the UI).
- **Surfaced in the UI's "Derived Geometry" block** as a read-only
  value.
- **Anchors the force sweep**: `linspace(rest, travel + rest, n)` instead
  of `linspace(0, travel, n)`.

At the default `spacing_ratio = 1.0`, `rest = 0.0` and the sweep is
byte-identical to the pre-ADR behaviour. The change only becomes visible
at Vernier ratios.

## Consequences

**Positive:**

- The spacing-ratio dropdown now produces a visible, physically
  meaningful change in the UI: a non-zero rest offset and a sweep
  anchored to it.
- The "resting position" concept is now first-class in the codebase,
  not just help text.
- At 1:1 (the default), the change is byte-identical to the old
  behaviour — no test fixture churn is required.

**Negative:**

- The force sweep start is now a function of the spacing ratio, not
  raw zero. Any future test that asserts specific x-positions must
  account for this.
- The formula clamps at `0.0` for `spacing_ratio > 1.0` (which the
  config allows, up to 2.0). This is a deliberate choice: a "wider
  pitch" ratio means the mover has no preferred rest position, so
  `0.0` is a reasonable default.

**Future constraints:**

- The `rest_offset_m()` formula is the contract. Any future change to
  the resting-position definition (e.g. to model detent torque) must
  update this method and add a new test, but should not rename the
  field — the IPC DTO and UI are bound to the name.
- `ConfigDerivedIpc` is now an additive IPC DTO. Old Svelte clients
  that don't know about `rest_offset_m` or `slot_pitch_m` ignore them
  silently (serde default for unknown fields).

## Alternatives considered

- **Help text only.** Rejected: directly contradicts the user's
  "has no effect" complaint.
- **Add a `rest_offset_m` user input field (not derived).** Rejected:
  the rest position is a function of the spacing ratio, not an
  independent parameter. Exposing it as user input would either
  override the spacing ratio or be ignored by it.
- **Compute `rest_offset_m` only in the Svelte UI, not in the core.**
  Rejected: the force sweep runs in the core, and the rest anchor
  must be available there to avoid a UI/core desync.
