# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the
`pcbstatorgen` project. ADRs are short, immutable documents that capture a
single architectural decision: the context, the choice, and its consequences.

## When to write an ADR

Write a new ADR whenever a decision:

- Locks in a non-obvious technical or product choice that future contributors
  will need to understand.
- Constrains future work (e.g. forbids a dependency, fixes a wire format,
  rejects an alternative that might be tempting later).
- Was the subject of a sign-off with the user / product-owner and could be
  re-litigated without the ADR.

Do **not** write an ADR for routine implementation choices that are
self-evident from the code.

## Numbering

ADRs are numbered sequentially with a four-digit zero-padded prefix
(`0001-title-in-kebab-case.md`). The number is permanent; do **not** renumber
or reuse numbers, even if an ADR is later superseded.

A new ADR that supersedes an old one keeps its own new number; the old ADR is
updated to add a "Superseded by" link and its status changes from `Accepted`
to `Superseded`.

## Status

Each ADR has exactly one status:

- **Proposed** — drafted, under review by the product-owner and/or the user.
- **Accepted** — ratified; binding on future work.
- **Superseded** — replaced by a later ADR (link to it).
- **Deprecated** — no longer applicable (link to context).

## Format

Use the template in `template.md`. The required sections are:

1. **Status** — one of the four values above.
2. **Date** — ISO-8601 date of last status change.
3. **Context** — the situation, the forces in play, the constraint(s) that
   forced the decision.
4. **Decision** — the choice, stated as a positive commitment.
5. **Consequences** — the positive and negative effects, including the
   constraints this places on future work.
6. **Alternatives considered** — what was rejected, and why.

Keep ADRs short (1-2 pages). Cite file:line references for every concrete
claim about the codebase. The ADR is the *why*; the code is the *what*.

## Index

| Number | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-via-grid-generator-for-serpentine-and-sinewave.md) | Inter-layer via-grid generator for Serpentine and SineWave | Accepted | 2026-07-13 |
| [0002](0002-flux-viz-via-rust-sample_b_field.md) | Flux visualization via Rust `sample_b_field` Tauri command | Accepted | 2026-07-13 |
| [0003](0003-arrangement-viz-auto-refresh.md) | Arrangement selector auto-refreshes flux viz + force sweep | Accepted | 2026-07-13 |
| [0004](0004-resting-position-as-real-derived-field.md) | Resting position as a real derived field `rest_offset_m` | Accepted | 2026-07-13 |
| [0005](0005-coilpreview-per-layer-z-offset.md) | CoilPreview per-layer Z offset | Accepted | 2026-07-13 |
| [0006](0006-rest-offset-is-sweep-translation-not-geometry-change.md) | `rest_offset_m` is a sweep-window translation, not a geometry change | Accepted | 2026-07-13 |
| [0007](0007-no-saved-state-serde-migration-needed-for-slice-1.md) | No saved-state serde migration needed for Slice 1 | Accepted | 2026-07-13 |

> A6 is intentionally unused — the sign-off skipped from A5 to A7, and the
> numbering is preserved for traceability against the strategic plan.
