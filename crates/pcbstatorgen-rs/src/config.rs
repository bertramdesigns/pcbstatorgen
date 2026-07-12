//! Configuration structs and result types (serde-serializable).
//!
//! Ports `pcbstatorgen/config.py`. Linear mode only — `AxialMotorConfig`
//! remains a stub (PRODUCT_GOALS.md §7.A).
//!
//! TODO(magnetics-sim-expert): full port from Python `config.py`.
//!       See .opencode/active_task.json — Phase B.

use serde::{Deserialize, Serialize};

/// Permanent magnet arrangement on the carriage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MagnetArrangement {
    Alternating,
    AlternatingBackIron,
    Halbach,
    HalbachBackIron,
}

/// PCB stator conductor path topology.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CoilTopology {
    Serpentine,
    SineWave,
    Concentrated,
    Rhombic,
    Spiral,
}

/// Linear PCB coreless motor configuration (flying mover).
///
/// All quantities in SI units. `active_area_length_m` is the primary INPUT;
/// `travel` is derived: `active_area_length - coil_span`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinearMotorConfig {
    // TODO: full field port from Python LinearMotorConfig
    pub active_area_length_m: f64,
    pub magnet_dims_m: [f64; 3],
    pub magnet_count: u32,
    pub magnet_pitch_m: f64,
    pub magnet_remanence_t: f64,
    pub magnet_grade: String,
    pub magnet_arrangement: MagnetArrangement,
    pub back_iron_thickness_m: f64,
    pub air_gap_m: f64,
    pub coil_topology: CoilTopology,
    pub phases: u32,
    pub spacing_ratio: f64,
    pub max_current_a: f64,
    pub supply_voltage_v: f64,
    pub board_width_m: f64,
    pub pcb_thickness_m: f64,
    pub target_force_n: f64,
    pub peak_force_n: f64,
    pub friction_n: f64,
    pub carriage_mass_kg: f64,
    pub max_accel_m_s2: f64,
    pub capacitor_bank_uf: f64,
    pub name: Option<String>,
}

impl LinearMotorConfig {
    /// Full span of the mover's magnet array [m]: `magnet_count × magnet_pitch`.
    pub fn coil_span_m(&self) -> f64 {
        self.magnet_count as f64 * self.magnet_pitch_m
    }
    /// Derived center-to-center travel [m]: `active_area_length - coil_span`.
    pub fn travel_m(&self) -> f64 {
        self.active_area_length_m - self.coil_span_m()
    }
    /// Magnet pole pitch [m] (= magnet_pitch for alternating arrays).
    pub fn pole_pitch_m(&self) -> f64 {
        self.magnet_pitch_m
    }
    /// Gap between adjacent magnets [m]: `magnet_pitch - magnet_width`.
    pub fn magnet_gap_m(&self) -> f64 {
        self.magnet_pitch_m - self.magnet_dims_m[0]
    }
}

// TODO: StackupResult, HeightStackResult, FrictionBudget, PowerBudget ports.

/// Placeholder — full port pending (see active_task.json Phase E).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StackupResult;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeightStackResult;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrictionBudget;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PowerBudget;

/// Mover linear bearing / guide type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BearingType {
    PlasticChannel,
    PteLined,
    BallBearing,
}
