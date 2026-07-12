//! Thin adapter over `magba` to insulate upstream code from API breaks.
//!
//! All direct `magba` calls live here. Upstream modules call these wrappers.
//! TODO(magnetics-sim-expert): implement CuboidSource, compute_b_field.
//!   See .opencode/active_task.json — Phase D.
