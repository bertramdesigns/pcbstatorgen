# 0007 — No saved-state serde migration needed for Slice 1

**Status:** Accepted
**Date:** 2026-07-13
**Superseded by:** —
**Supersedes:** —

## Context

Slice 1 introduced two new fields:

- `rest_offset_m` — added to `LinearMotorConfig` as a *derived* method,
  not as a stored field.
- `slot_pitch_m` and `rest_offset_m` — added to `ConfigDerivedIpc` as
  *additive* fields.

The product-owner strategic plan flagged a hypothetical risk: "Saved
state serde: existing saved configs have no `back_iron_thickness_m` /
arrangement value → deserialise panic." This ADR addresses whether
Slice 1's actual changes need a saved-state migration.

Two questions:

1. **Is there a saved-state path that could break?** The Svelte
   frontend persists config in a store (`app/src/lib/stores/config.svelte.ts`)
   but it is in-memory only — there is no `localStorage` or
   `IndexedDB` persistence in the current codebase. The Rust core
   is configured at startup; `LinearMotorConfig` is constructed
   fresh each time, not deserialised from disk.
2. **Does `ConfigDerivedIpc` need a migration on the wire?** No. The
   DTO is *additive* — old Svelte clients that don't know about
   `rest_offset_m` or `slot_pitch_m` ignore them silently (serde
   default behaviour for unknown fields).

## Decision

Slice 1 introduces no stored fields in `LinearMotorConfig` and no
breaking changes to any IPC DTO. No `#[serde(default)]` migration is
required this round, and no `ConfigDerivedIpc` migration is required
on the wire.

If a future change adds a *stored* field to `LinearMotorConfig` or
adds a *required* field to `LinearMotorConfigIpc`, that change must
include either `#[serde(default)]` (with a sensible default) or a
documented migration step. This ADR is a record of Slice 1's
specifics, not a general license to skip serde migration in the
future.

## Consequences

**Positive:**

- Slice 1 has zero backwards-compatibility risk. The Tauri host
  binary and the Svelte frontend can be deployed independently.
- The `ConfigDerivedIpc` is now an additive DTO with 10 fields (was
  9). Adding fields is a non-event; removing or renaming is a
  breaking change.

**Negative:**

- A future change that adds a *required* IPC field will require a
  coordinated release. This ADR is not a workaround for that; it's
  a record of what was safe this round.

**Future constraints:**

- Any new stored field on `LinearMotorConfig` must be paired with
  a serde default OR a documented migration. The historical record
  is in this ADR.
- `ConfigDerivedIpc` is now a long-lived additive DTO. Renaming or
  removing fields requires a major version bump of the IPC contract.

## Alternatives considered

- **Add `#[serde(default)]` defensively to all fields in
  `LinearMotorConfig`.** Rejected: defensive defaults hide the real
  contract. Each field should have an explicit, intentional default
  only if the field is genuinely optional.
- **Persist the Svelte store to `localStorage` so the saved-state
  risk becomes real.** Out of scope for this round; if pursued in
  the future, the migration concern re-opens.
