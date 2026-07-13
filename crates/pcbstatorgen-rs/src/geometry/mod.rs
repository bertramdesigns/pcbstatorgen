//! Coil path generators.
//!
//! ## Module layout
//! - [`wave_winding`] — `CoilSegment`, `PhaseCoil`, `WaveWindingGenerator`,
//!   `SineWaveWindingGenerator`, `PHASE_NAMES`
//! - [`coil_generators`] — `ConcentratedCoilGenerator`, `RhombicCoilGenerator`,
//!   `SpiralCoilGenerator`, `make_coil_generator` factory, `CoilGenerator` trait
//!
//! All coordinates in metres. Coordinate system:
//! - X-axis: travel direction (along PCB length)
//! - Y-axis: perpendicular to travel (across PCB width)

pub mod coil_generators;
pub mod wave_winding;

// Re-export the core types from wave_winding (canonical definitions)
pub use wave_winding::{CoilSegment, PhaseCoil, PHASE_NAMES};
pub use wave_winding::{WaveWindingGenerator, SineWaveWindingGenerator};
pub use coil_generators::{
    make_coil_generator, ConcentratedCoilGenerator, RhombicCoilGenerator,
    SpiralCoilGenerator, CoilGenerator,
};
