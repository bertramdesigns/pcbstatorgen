//! pcbstatorgen-rs: Analytical magnetic field, Lorentz force, and PCB stator
//! geometry for coreless linear motors — pure Rust port of the Python
//! `pcbstatorgen` core.
//!
//! ## Module map
//! - [`config`] — serde structs mirroring the Python dataclasses (LinearMotorConfig, etc.)
//! - [`units`] — SI unit conversion helpers (mm, mils, oz, skin depth)
//! - [`magnet_grades`] — NdFeB grade → remanence lookup table
//! - [`geometry`] — coil path generators (serpentine, sine wave, concentrated, rhombic, spiral)
//! - [`magnetic`] — magnet arrays, coil current model, force/torque evaluator
//! - [`physics`] — thin adapter over `magba` (insulates from API breaks)
//! - [`stackup`] — height stack, power budget, friction budget
//! - [`foc_spec`] — FOC (field-oriented control) spec stub, awaiting
//!   the `@pcb-motor-expert` rewrite.
//!
//! Linear mode only. Radial/axial-flux remains a stub (see PRODUCT_GOALS.md §7.A).

pub mod config;
pub mod foc_spec;
pub mod geometry;
pub mod kicad;
pub mod magnetic;
pub mod magnet_grades;
pub mod physics;
pub mod stackup;
pub mod units;

pub use config::{
    BearingType, CoilTopology, FrictionBudget, HeightStackResult, LinearMotorConfig,
    MagnetArrangement, PowerBudget, StackupResult,
};
pub use units::{mm, mils_to_m, oz_to_m};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
