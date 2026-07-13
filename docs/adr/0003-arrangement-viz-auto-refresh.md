# 0003 — Arrangement selector auto-refreshes flux viz + force sweep

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

The user reported: "It is not possible to select different permanent magnet
configurations, such as halbach arrays or steel backing. This will change
the strength and flux of the magnets. This also needs some level of
visualization for the flux lines to be understood easily by the user."

The `MagnetArrangement` enum and its IPC DTO are already complete
(`crates/pcbstatorgen-rs/src/config.rs:18-26`,
`app/src-tauri/src/ipc.rs:42-75`); the missing piece is the UI control and
the visualization. The physics layer already branches on the arrangement
inside `MagnetArray::build_assembly`
(`crates/pcbstatorgen-rs/src/magnetic/magnet_model.rs:46-67`), so any
upstream change to the arrangement value automatically propagates to the
B-field sampler and the force evaluator.

Two UX patterns are possible:

1. **Auto-refresh**: when the user changes the arrangement, the B-field
   viz and force sweep recompute automatically.
2. **Manual recompute button**: the user changes the arrangement, then
   clicks a "Recompute" button to refresh the viz.

The user's framing — "This will change the strength and flux of the
magnets" — strongly implies they expect to *see* the change happen
immediately, not to click a separate button. The existing
`$derived`/`$effect` plumbing in the Svelte `ConfigStore` already
supports the auto-refresh pattern.

## Decision

When the user changes `magnet_arrangement` (or any of the magnet body
dimensions, or back-iron thickness), the B-field viz and the force sweep
recompute automatically. No manual "recompute" button is exposed for
these inputs.

The auto-refresh is implemented through the existing Svelte 5 reactivity
plumbing: the `ConfigStore` exposes a `$state` field for the
arrangement, the `FluxDiagram` component derives its `sample_b_field`
invoke arguments from that state via `$derived`, and a `$effect` triggers
the invoke when the derived value changes. A 150ms debounce (matching the
existing parameter-slider debounce in `App.svelte`) prevents thrash on
fast drags.

## Consequences

**Positive:**

- The user's stated intent is satisfied directly.
- The implementation is small — the existing reactivity plumbing is
  reused.
- No new UI element needs design or layout work.

**Negative:**

- Auto-refresh means the B-field command runs more often. The `magba`
  sampler is O(N_x × N_z × N_magnets); for a 24×12 grid and 4 magnets
  this is fast, but a future larger grid may need a more aggressive
  debounce or a worker.
- Auto-refresh can surprise users who want to compare arrangements
  side-by-side. (Mitigation: the panel can be frozen by switching the
  view to a different tab; future enhancement could add a "pause live
  updates" toggle.)

**Future constraints:**

- The 150ms debounce is the single source of truth for "user has
  stopped changing things" across the dashboard. Any new auto-refreshing
  control must respect it.
- The `sample_b_field` command is invoked on every change, so its
  performance budget directly affects the perceived snappiness of the
  arrangement selector.

## Alternatives considered

- **Manual recompute button.** Rejected: requires an extra click per
  change and doesn't match the user's "see the flux change"
  expectation.
- **Side-by-side comparison view.** Rejected: out of scope for this
  round; can be a follow-on enhancement if the user requests it.
- **Compute once at startup, cache statically.** Rejected: the entire
  point of the user's request is to see the field change with the
  arrangement.
