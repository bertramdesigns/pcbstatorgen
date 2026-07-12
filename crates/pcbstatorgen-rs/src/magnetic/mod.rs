//! Magnet arrays, coil current model, force/torque evaluator.
//!
//! Ports `pcbstatorgen/magnetic/`. Depends on the `physics` adapter layer.
//!
//! ## Module layout
//! - [`magnet_model`] — `MagnetArray` (4 arrangements: Alternating, Halbach, back-iron)
//! - [`coil_model`] — `CoilCurrentModel` (active segments → force integration)
//! - [`force_eval`] — `ForceEvaluator` + `ForceResult` (Lorentz force, Newton's 3rd Law)

pub mod coil_model;
pub mod force_eval;
pub mod magnet_model;

pub use coil_model::CoilCurrentModel;
pub use force_eval::{CommutationMode, ForceEvaluator, ForceResult};
pub use magnet_model::MagnetArray;
