//! IPC contract layer between the Svelte frontend and the Rust physics core.
//!
//! These DTOs are the *only* types that cross the Tauri IPC bridge. They are
//! intentionally decoupled from `pcbstatorgen_rs::config::LinearMotorConfig`
//! (the internal SI representation) because:
//!
//! 1. The frontend (`app/src/lib/types.ts`) speaks **snake_case** field names
//!    with SI units (metres, Tesla, Amperes) — every struct here carries
//!    `#[serde(rename_all = "snake_case")]` to match exactly.
//! 2. The enum wire formats differ from the core: `MagnetArrangement` is
//!    PascalCase on the wire (`"Alternating"`) but snake_case in the core
//!    (`"alternating"`); `CoilTopology` exposes only the 2 UI-selectable
//!    variants (`"serpentine"`, `"sine_wave"`) while the core has 5.
//! 3. The IPC config is a **superset** of the core config — it carries
//!    UI-only fields (`num_layers`, `commutation`, `n_positions`, `meshing`,
//!    `magnet_gap_m`, `magnet_cross_width_m`) that the core does not yet
//!    model. These are consumed directly by the stub handlers; once Phases
//!    C/D/E land they will flow into the real core calculators.
//!
//! Conversions to/from `pcbstatorgen_rs` live in this module (`to_core()` /
//! `From<&LinearMotorConfig>`).

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use pcbstatorgen_rs::config::LinearMotorConfig as CoreConfig;
use pcbstatorgen_rs::config::{
    CoilTopology as CoreCoilTopology, MagnetArrangement as CoreMagnetArrangement,
};

// ===========================================================================
// Enums
// ===========================================================================

/// Permanent magnet arrangement on the carriage.
///
/// Wire format is **PascalCase** to match `types.ts`:
/// `"Alternating" | "AlternatingBackIron" | "Halbach" | "HalbachBackIron"`.
///
/// (The core enum serializes as snake_case, hence this separate IPC enum.)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub enum MagnetArrangementIpc {
    Alternating,
    AlternatingBackIron,
    Halbach,
    HalbachBackIron,
}

impl From<MagnetArrangementIpc> for CoreMagnetArrangement {
    fn from(a: MagnetArrangementIpc) -> Self {
        match a {
            MagnetArrangementIpc::Alternating => CoreMagnetArrangement::Alternating,
            MagnetArrangementIpc::AlternatingBackIron => {
                CoreMagnetArrangement::AlternatingBackIron
            }
            MagnetArrangementIpc::Halbach => CoreMagnetArrangement::Halbach,
            MagnetArrangementIpc::HalbachBackIron => CoreMagnetArrangement::HalbachBackIron,
        }
    }
}

impl From<CoreMagnetArrangement> for MagnetArrangementIpc {
    fn from(a: CoreMagnetArrangement) -> Self {
        match a {
            CoreMagnetArrangement::Alternating => MagnetArrangementIpc::Alternating,
            CoreMagnetArrangement::AlternatingBackIron => {
                MagnetArrangementIpc::AlternatingBackIron
            }
            CoreMagnetArrangement::Halbach => MagnetArrangementIpc::Halbach,
            CoreMagnetArrangement::HalbachBackIron => MagnetArrangementIpc::HalbachBackIron,
        }
    }
}

/// PCB stator conductor path topology.
///
/// Wire format is **snake_case** to match `types.ts`:
/// `"serpentine" | "sine_wave"`. Only the 2 UI-selectable topologies are
/// exposed; the core's `Concentrated` / `Rhombic` / `Spiral` variants are
/// not reachable from the frontend (PRODUCT_GOALS.md §5 restricts the UI to
/// these two).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoilTopologyIpc {
    Serpentine,
    SineWave,
}

impl From<CoilTopologyIpc> for CoreCoilTopology {
    fn from(t: CoilTopologyIpc) -> Self {
        match t {
            CoilTopologyIpc::Serpentine => CoreCoilTopology::Serpentine,
            CoilTopologyIpc::SineWave => CoreCoilTopology::SineWave,
        }
    }
}

impl From<CoreCoilTopology> for CoilTopologyIpc {
    fn from(t: CoreCoilTopology) -> Self {
        match t {
            CoreCoilTopology::Serpentine => CoilTopologyIpc::Serpentine,
            // Concentrated/Rhombic/Spiral are not UI-selectable; fall back to
            // sine_wave if they ever surface from the core.
            _ => CoilTopologyIpc::SineWave,
        }
    }
}

/// FOC commutation strategy. Wire format: `"max_torque" | "phase_a_only"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommutationModeIpc {
    MaxTorque,
    PhaseAOnly,
}

// ===========================================================================
// LinearMotorConfig (IPC wire format — SI units, snake_case)
// ===========================================================================

/// Linear PCB coreless motor configuration — IPC / frontend contract.
///
/// Mirrors `app/src/lib/types.ts` `LinearMotorConfig` **exactly** (field names,
/// order, units). All lengths in metres, electrical in SI. Per PRODUCT_GOALS.md
/// §3: `active_area_length_m` is the primary INPUT; `travel` is DERIVED.
///
/// Magnet axis convention (matches the frontend store):
/// - `magnet_width_m`       — along the travel (x) axis.
/// - `magnet_cross_width_m` — across the stator (y, board-width axis).
/// - `magnet_height_m`      — vertical thickness (z, magnetisation axis).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct LinearMotorConfigIpc {
    pub active_area_length_m: f64,
    pub board_width_m: f64,
    pub pcb_thickness_m: f64,

    pub magnet_count: u32,
    pub magnet_width_m: f64,
    pub magnet_cross_width_m: f64,
    pub magnet_height_m: f64,
    /// Gap between adjacent magnets along the travel axis [m]. Derived
    /// (`pitch - width`) but kept on the wire for UI clarity.
    pub magnet_gap_m: f64,
    /// Pole pitch τ_p = magnet_width + magnet_gap [m] (PRODUCT_GOALS §3.D).
    pub magnet_pitch_m: f64,

    pub magnet_remanence_t: f64,
    pub magnet_grade: String,
    pub magnet_arrangement: MagnetArrangementIpc,
    pub back_iron_thickness_m: f64,
    pub air_gap_m: f64,

    pub coil_topology: CoilTopologyIpc,
    pub phases: u32,
    /// Vernier spacing ratio as a raw f64 (1.0, 0.8, 0.8333…).
    pub spacing_ratio: f64,

    pub max_current_a: f64,
    pub supply_voltage_v: f64,

    /// Current copper layer count selection (UI-controlled).
    pub num_layers: u32,
    pub min_trace_m: f64,
    pub min_space_m: f64,
    pub min_via_drill_m: f64,
    pub min_via_annular_ring_m: f64,
    /// DFM limit on layer count (must be even).
    pub max_layers: u32,
    pub drive_frequency_hz: f64,
    pub max_temperature_rise_c: f64,

    pub target_force_n: f64,
    pub peak_force_n: f64,
    pub friction_n: f64,
    pub carriage_mass_kg: f64,
    pub max_accel_m_s2: f64,
    pub capacitor_bank_uf: f64,

    pub commutation: CommutationModeIpc,
    pub n_positions: u32,
    pub meshing: u32,

    pub name: Option<String>,
}

impl LinearMotorConfigIpc {
    /// Convert to the core SI representation.
    ///
    /// Maps the IPC superset onto the core's compact fields:
    /// - `magnet_dims_m = [magnet_width, magnet_cross_width, magnet_height]`
    /// - `magnet_pitch_m` passed through (core stores pitch, not gap).
    /// - UI-only fields (`num_layers`, `commutation`, `n_positions`,
    ///   `meshing`, `magnet_gap_m`, `magnet_cross_width_m`) are NOT carried
    ///   into the core config — they are consumed directly by the stub
    ///   handlers until Phases C/D/E port the full calculators.
    pub fn to_core(&self) -> CoreConfig {
        CoreConfig {
            magnet_dims_m: [
                self.magnet_width_m,
                self.magnet_cross_width_m,
                self.magnet_height_m,
            ],
            magnet_count: self.magnet_count,
            magnet_pitch_m: self.magnet_pitch_m,
            magnet_remanence_t: self.magnet_remanence_t,
            magnet_grade: self.magnet_grade.clone(),
            magnet_arrangement: self.magnet_arrangement.into(),
            back_iron_thickness_m: self.back_iron_thickness_m,
            active_area_length_m: self.active_area_length_m,
            board_width_m: self.board_width_m,
            pcb_thickness_m: self.pcb_thickness_m,
            air_gap_m: self.air_gap_m,
            coil_topology: self.coil_topology.into(),
            phases: self.phases,
            spacing_ratio: self.spacing_ratio,
            max_current_a: self.max_current_a,
            supply_voltage_v: self.supply_voltage_v,
            min_trace_m: self.min_trace_m,
            min_space_m: self.min_space_m,
            min_via_drill_m: self.min_via_drill_m,
            min_via_annular_ring_m: self.min_via_annular_ring_m,
            max_layers: self.max_layers,
            num_layers: self.num_layers,
            drive_frequency_hz: self.drive_frequency_hz,
            max_temperature_rise_c: self.max_temperature_rise_c,
            target_force_n: self.target_force_n,
            peak_force_n: self.peak_force_n,
            friction_n: self.friction_n,
            carriage_mass_kg: self.carriage_mass_kg,
            max_accel_m_s2: self.max_accel_m_s2,
            capacitor_bank_uf: self.capacitor_bank_uf,
            name: self.name.clone(),
        }
    }
}

impl From<&CoreConfig> for LinearMotorConfigIpc {
    fn from(c: &CoreConfig) -> Self {
        LinearMotorConfigIpc {
            active_area_length_m: c.active_area_length_m,
            board_width_m: c.board_width_m,
            pcb_thickness_m: c.pcb_thickness_m,
            magnet_count: c.magnet_count,
            magnet_width_m: c.magnet_dims_m[0],
            magnet_cross_width_m: c.magnet_dims_m[1],
            magnet_height_m: c.magnet_dims_m[2],
            magnet_gap_m: c.magnet_gap_m(),
            magnet_pitch_m: c.magnet_pitch_m,
            magnet_remanence_t: c.magnet_remanence_t,
            magnet_grade: c.magnet_grade.clone(),
            magnet_arrangement: c.magnet_arrangement.into(),
            back_iron_thickness_m: c.back_iron_thickness_m,
            air_gap_m: c.air_gap_m,
            coil_topology: c.coil_topology.into(),
            phases: c.phases,
            spacing_ratio: c.spacing_ratio,
            max_current_a: c.max_current_a,
            supply_voltage_v: c.supply_voltage_v,
            // The core has no "current layer count" field — default to max.
            num_layers: c.max_layers,
            min_trace_m: c.min_trace_m,
            min_space_m: c.min_space_m,
            min_via_drill_m: c.min_via_drill_m,
            min_via_annular_ring_m: c.min_via_annular_ring_m,
            max_layers: c.max_layers,
            drive_frequency_hz: c.drive_frequency_hz,
            max_temperature_rise_c: c.max_temperature_rise_c,
            target_force_n: c.target_force_n,
            peak_force_n: c.peak_force_n,
            friction_n: c.friction_n,
            carriage_mass_kg: c.carriage_mass_kg,
            max_accel_m_s2: c.max_accel_m_s2,
            capacitor_bank_uf: c.capacitor_bank_uf,
            commutation: CommutationModeIpc::MaxTorque,
            n_positions: 50,
            meshing: 20,
            name: c.name.clone(),
        }
    }
}

// ===========================================================================
// ConfigDerived (compute_config_derived)
// ===========================================================================

/// Derived geometry values — READ-ONLY outputs (PRODUCT_GOALS.md §3.A).
///
/// Mirrors `types.ts` `ConfigDerived` exactly.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct ConfigDerivedIpc {
    pub pole_pitch_m: f64,
    pub coil_span_m: f64,
    pub travel_m: f64,
    pub slot_pitch_m: f64,
    /// Vernier rest offset [m] — phase offset between a coil center and the
    /// nearest pole center. Zero for 1:1 spacing, positive for Vernier ratios.
    pub rest_offset_m: f64,
    pub magnet_gap_m: f64,
    pub min_via_pad_m: f64,
    pub acceleration_force_n: f64,
    pub minimum_drive_force_n: f64,
    pub active_length_m: f64,
}

impl ConfigDerivedIpc {
    /// Build from the **core** config using its real derived methods.
    /// This is a REAL implementation (not a stub) — the core's
    /// `LinearMotorConfig` carries all the math.
    pub fn from_core(c: &CoreConfig) -> Self {
        Self {
            pole_pitch_m: c.pole_pitch_m(),
            coil_span_m: c.coil_span_m(),
            travel_m: c.travel_m(),
            slot_pitch_m: c.slot_pitch_m(),
            rest_offset_m: c.rest_offset_m(),
            magnet_gap_m: c.magnet_gap_m(),
            min_via_pad_m: c.min_via_pad_m(),
            acceleration_force_n: c.acceleration_force_n(),
            minimum_drive_force_n: c.minimum_drive_force_n(),
            active_length_m: c.active_length_m(),
        }
    }
}

// ===========================================================================
// B-field grid (sample_b_field) — WP4 / WP5 flux-viz backend
// ===========================================================================

/// One B-field sample on the X–Z flux-viz grid.
///
/// All units SI: positions in metres, B-field in Tesla. `mag_t` is the
/// precomputed `sqrt(bx² + by² + bz²)` — the Svelte renderer uses it to
/// colour-code arrows by magnitude without recomputing.
///
/// Field naming on the wire: every field has an explicit `#[serde(rename)]`
/// so the unit suffix (`_m`, `_t`) is preserved end-to-end and stable
/// across Rust → JSON → TypeScript.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BFieldSampleIpc {
    #[serde(rename = "x_m")]
    pub x_m: f64,
    #[serde(rename = "z_m")]
    pub z_m: f64,
    #[serde(rename = "bx_t")]
    pub bx_t: f64,
    #[serde(rename = "by_t")]
    pub by_t: f64,
    #[serde(rename = "bz_t")]
    pub bz_t: f64,
    #[serde(rename = "mag_t")]
    pub mag_t: f64,
}

impl BFieldSampleIpc {
    /// Convert a core `pcbstatorgen_rs::magnetic::BFieldSample2D` to the
    /// IPC wire form, computing the magnitude on the way out.
    pub fn from_core(s: &pcbstatorgen_rs::magnetic::BFieldSample2D) -> Self {
        Self {
            x_m: s.x,
            z_m: s.z,
            bx_t: s.bx,
            by_t: s.by,
            bz_t: s.bz,
            mag_t: (s.bx * s.bx + s.by * s.by + s.bz * s.bz).sqrt(),
        }
    }
}

/// Full 2D B-field grid response for the `sample_b_field` Tauri command.
///
/// `samples` is **row-major** with Z as the slow axis:
/// `samples[i_z * n_x + i_x]`. The Svelte `FluxDiagram` reshapes the flat
/// `samples` into a 2D `n_z × n_x` arrow grid using `x_extent_m` /
/// `z_extent_m` to recover the physical axes.
///
/// `arrangement` is the **PascalCase** arrangement name
/// (`"Alternating"`, `"HalbachBackIron"`, …) — exposed for UI diagnostics.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct BFieldGridIpc {
    pub samples: Vec<BFieldSampleIpc>,
    /// `[x_min, x_max]` over which the grid was sampled [m].
    pub x_extent_m: [f64; 2],
    /// `[z_min, z_max]` over which the grid was sampled [m].
    pub z_extent_m: [f64; 2],
    /// PascalCase arrangement label (matches the IPC enum wire format).
    pub arrangement: String,
}

/// Convert a core `MagnetArrangement` to its PascalCase wire label.
pub fn arrangement_pascal_case(
    a: pcbstatorgen_rs::config::MagnetArrangement,
) -> String {
    use pcbstatorgen_rs::config::MagnetArrangement as A;
    match a {
        A::Alternating => "Alternating".to_string(),
        A::AlternatingBackIron => "AlternatingBackIron".to_string(),
        A::Halbach => "Halbach".to_string(),
        A::HalbachBackIron => "HalbachBackIron".to_string(),
    }
}

// ===========================================================================
// Coil path (generate_coils)
// ===========================================================================

/// One straight segment of a coil path. `start`/`end` are `(x, y)` [m].
/// `is_active` distinguishes active vertical conductors from end-turn
/// connectors (PRODUCT_GOALS.md §5) for SVG colour-coding.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct CoilSegmentIpc {
    pub start: [f64; 2],
    pub end: [f64; 2],
    pub is_active: bool,
}

/// A single phase coil on a single PCB layer.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct PhaseCoilIpc {
    pub phase_idx: u32,
    pub layer_idx: u32,
    pub phase_name: String,
    pub topology: CoilTopologyIpc,
    pub segments: Vec<CoilSegmentIpc>,
    pub total_length_m: f64,
    pub active_length_m: f64,
    pub end_turn_length_m: f64,
    pub active_conductor_count: u32,
    /// `[min_x, min_y, max_x, max_y]` [m].
    pub bounding_box: [f64; 4],
    pub terminal_start: [f64; 2],
    pub terminal_end: [f64; 2],
}

/// Complete coil geometry for all phases/layers.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct CoilPathIpc {
    pub phases: Vec<PhaseCoilIpc>,
    pub layer_count: u32,
}

// ===========================================================================
// Force sweep (evaluate_force_sweep)
// ===========================================================================

/// Force vs mover position along the travel axis.
///
/// Per PRODUCT_GOALS §4.C the sign convention is `F_mover = -F_stator`;
/// `force_x_n` already reflects the mover's reference frame.
/// Ripple % = `(F_max - F_min) / |F_mean| × 100` (§4.A).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct ForceSweepResultIpc {
    pub positions_m: Vec<f64>,
    pub force_x_n: Vec<f64>,
    pub force_y_n: Vec<f64>,
    pub force_z_n: Vec<f64>,
    /// Per-phase x-force at each position: `[position][phase]`.
    pub per_phase_force_x: Vec<Vec<f64>>,
    pub commutation: CommutationModeIpc,
    pub current_a: f64,
    pub mean_thrust_n: f64,
    pub peak_thrust_n: f64,
    pub min_thrust_n: f64,
    pub ripple_pct: f64,
    pub n_positions: u32,
}

// ===========================================================================
// Stackup / height / power / friction (compute_*)
// ===========================================================================

/// PCB stackup recommendation (trace widths, copper, vias).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct StackupResultIpc {
    pub layer_count: u32,
    pub trace_widths_m: Vec<f64>,
    pub cu_thickness_m: Vec<f64>,
    pub via_drill_m: f64,
    pub via_annular_ring_m: f64,
    pub via_grid_rows: u32,
    pub via_grid_cols: u32,
    pub estimated_force_n: f64,
    pub estimated_dc_resistance_ohm: f64,
    pub notes: Vec<String>,
}

/// Explicit vertical stack from PCB bottom to magnet top.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct HeightStackResultIpc {
    pub pcb_thickness_m: f64,
    pub cu_protrusion_m: f64,
    pub solder_mask_m: f64,
    pub air_gap_m: f64,
    pub magnet_height_m: f64,
    pub back_iron_thickness_m: f64,
    pub tolerance_m: f64,
    pub total_height_m: f64,
}

/// Mechanical friction breakdown.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct FrictionBudgetIpc {
    pub bearing_friction_n: f64,
    pub cable_drag_n: f64,
    pub wiper_contact_n: f64,
    /// Coreless motor → zero cogging (PRODUCT_GOALS §4.A).
    pub cogging_n: f64,
    pub total_n: f64,
    pub minimum_drive_force_n: f64,
}

/// Continuous and burst power / thermal analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct PowerBudgetIpc {
    pub phase_resistance_ohm: f64,
    pub continuous_power_w: f64,
    pub burst_power_w: f64,
    pub temperature_rise_c: f64,
    pub capacitor_required_uf: f64,
    pub efficiency_pct: f64,
}

// ===========================================================================
// Magnet grade reference (get_magnet_grades)
// ===========================================================================

/// NdFeB magnet grade specification (PRODUCT_GOALS.md §3.C).
/// `max_temp_c` maps thermal-suffix labels to °C.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MagnetGradeIpc {
    pub name: String,
    pub br_min_t: f64,
    pub br_typ_t: f64,
    pub br_max_t: f64,
    pub max_temp_c: BTreeMap<String, f64>,
}

/// Standard thermal-suffix table (PRODUCT_GOALS.md §3.C).
/// Applied to all grades except N52 (Std only).
fn standard_temp_table() -> BTreeMap<String, f64> {
    let mut m = BTreeMap::new();
    m.insert("Std".into(), 80.0);
    m.insert("H".into(), 120.0);
    m.insert("SH".into(), 150.0);
    m.insert("UH".into(), 180.0);
    m.insert("EH".into(), 200.0);
    m.insert("AH".into(), 220.0);
    m
}

/// N52 only carries the standard (no high-temp suffixes).
fn n52_temp_table() -> BTreeMap<String, f64> {
    let mut m = BTreeMap::new();
    m.insert("Std".into(), 80.0);
    m
}

/// Build the full magnet-grade list from the core's static table + the
/// PRODUCT_GOALS thermal-suffix data. This is a REAL implementation (not a
/// stub) — it reads `pcbstatorgen_rs::magnet_grades::MAGNET_GRADES`.
pub fn magnet_grades() -> Vec<MagnetGradeIpc> {
    pcbstatorgen_rs::magnet_grades::MAGNET_GRADES
        .iter()
        .map(|(name, br_min, br_typ, br_max)| MagnetGradeIpc {
            name: name.to_string(),
            br_min_t: *br_min,
            br_typ_t: *br_typ,
            br_max_t: *br_max,
            max_temp_c: if *name == "N52" {
                n52_temp_table()
            } else {
                standard_temp_table()
            },
        })
        .collect()
}

// ===========================================================================
// Board diagnostics (get_board_diagnostics / validate_write_preconditions)
// ===========================================================================

/// Snapshot of the open KiCad board — IPC wire format.
///
/// Mirrors `pcbstatorgen_rs::kicad::BoardDiagnostics` exactly. `board_*_mm`
/// are populated from the board's edge cuts when the IPC supports that query
/// (currently 0.0 — TODO: real query). `available_net_classes` is empty for
/// the same reason. `board_name` and `copper_layer_count` are always
/// populated by `get_board_diagnostics`.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct BoardDiagnosticsIpc {
    pub board_name: String,
    pub copper_layer_count: u32,
    /// Bounding box of the board edge cuts, in mm. Defaults to 0.0 when
    /// the KiCad 10 IPC does not yet expose the edge-cut query (TODO).
    pub board_x_min_mm: f64,
    pub board_x_max_mm: f64,
    pub board_y_min_mm: f64,
    pub board_y_max_mm: f64,
    pub available_net_classes: Vec<String>,
}

impl BoardDiagnosticsIpc {
    /// Convert a core `BoardDiagnostics` to the IPC wire format.
    pub fn from_core(b: &pcbstatorgen_rs::kicad::BoardDiagnostics) -> Self {
        Self {
            board_name: b.board_name.clone(),
            copper_layer_count: b.copper_layer_count,
            board_x_min_mm: b.board_x_min_mm,
            board_x_max_mm: b.board_x_max_mm,
            board_y_min_mm: b.board_y_min_mm,
            board_y_max_mm: b.board_y_max_mm,
            available_net_classes: b.available_net_classes.clone(),
        }
    }
}

/// Severity of a [`PreconditionWarningIpc`]. Wire format is **snake_case**
/// (`"info" | "warning" | "error"`) so the UI can colour-code by value.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PreconditionLevelIpc {
    Info,
    Warning,
    Error,
}

/// One warning or recommendation about the (config, board) pair.
///
/// Produced by `validate_write_preconditions`. The UI is expected to render
/// `message` verbatim and colour-code by `level`. `field` is an optional
/// machine-readable key (`"num_layers"`, `"active_area_length_m"`, …) the
/// UI can use to highlight the offending input control.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct PreconditionWarningIpc {
    pub level: PreconditionLevelIpc,
    pub field: Option<String>,
    pub message: String,
}

impl PreconditionWarningIpc {
    /// Convert a core `PreconditionWarning` to the IPC wire format.
    pub fn from_core(w: &pcbstatorgen_rs::kicad::PreconditionWarning) -> Self {
        let level = match w.level {
            pcbstatorgen_rs::kicad::PreconditionLevel::Info => PreconditionLevelIpc::Info,
            pcbstatorgen_rs::kicad::PreconditionLevel::Warning => {
                PreconditionLevelIpc::Warning
            }
            pcbstatorgen_rs::kicad::PreconditionLevel::Error => PreconditionLevelIpc::Error,
        };
        Self {
            level,
            field: w.field.clone(),
            message: w.message.clone(),
        }
    }
}

// ===========================================================================
// Coil preview (preview_coils)
// ===========================================================================

/// Per-layer breakdown of the coils that would be written.
///
/// Mirrors `pcbstatorgen_rs::kicad::CoilPreviewLayer` minus `board_layer` —
/// the UI infers the layer assignment from `layer_idx` (the writer maps
/// `layer_idx == 0` → B.Cu, `layer_idx == num_layers-1` → F.Cu).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct CoilPreviewLayerIpc {
    pub layer_idx: u32,
    pub phase_count: u32,
    pub segment_count: u32,
    pub via_count: u32,
}

/// Dry-run summary of what `write_coils_to_board` would produce.
///
/// Returned by `preview_coils`. Contains the per-layer tally and the
/// topology label. Pre-condition warnings are *not* included here — the
/// UI calls `validate_write_preconditions` separately for those. The full
/// `PhaseCoil` geometry is *not* carried on the wire here either — the
/// UI calls `generate_coils` separately if it needs the raw segments.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct CoilPreviewIpc {
    pub num_layers: u32,
    /// Topology label — `"serpentine" | "sine_wave" | "concentrated" |
    /// "rhombic" | "spiral"`. Matches the core's `topology_label()` output.
    pub topology: String,
    pub layers: Vec<CoilPreviewLayerIpc>,
    pub total_tracks: u32,
    pub total_vias: u32,
}

impl CoilPreviewIpc {
    /// Convert a core `CoilPreview` to the IPC wire format.
    ///
    /// Note: `p.topology` is already a `String` (set by the core's
    /// `topology_label()`), so we just clone it — no enum match needed.
    /// The core's `CoilPreview` does not carry a `warnings` field; the UI
    /// calls `validate_write_preconditions` separately for those.
    pub fn from_core(p: &pcbstatorgen_rs::kicad::CoilPreview) -> Self {
        let layers = p
            .layers
            .iter()
            .map(|l| CoilPreviewLayerIpc {
                layer_idx: l.layer_idx,
                phase_count: l.phase_count,
                segment_count: l.segment_count,
                via_count: l.via_count,
            })
            .collect();
        Self {
            num_layers: p.num_layers,
            topology: p.topology.clone(),
            layers,
            total_tracks: p.total_tracks,
            total_vias: p.total_vias,
        }
    }
}

// ===========================================================================
// Geometry conversions (core PhaseCoil → IPC)
// ===========================================================================

use pcbstatorgen_rs::geometry::{
    CoilSegment as CoreCoilSegment, PhaseCoil as CorePhaseCoil,
};

#[allow(dead_code)]
impl CoilSegmentIpc {
    /// Convert a core `CoilSegment` (array coords) to the IPC form.
    /// Both already use `[f64; 2]` — this is a 1:1 passthrough.
    pub fn from_core(s: &CoreCoilSegment) -> Self {
        Self {
            start: [s.start.0, s.start.1],
            end: [s.end.0, s.end.1],
            is_active: s.is_active,
        }
    }
}

#[allow(dead_code)]
impl PhaseCoilIpc {
    /// Convert a core `PhaseCoil` to the IPC wire format.
    ///
    /// The current core `PhaseCoil` (Phase C in progress) does not yet expose
    /// `terminal_start()` / `terminal_end()` methods, so we derive them from
    /// the first/last segment endpoints. Once Phase C adds those methods this
    /// can switch to calling them directly.
    pub fn from_core(coil: &CorePhaseCoil) -> Self {
        let segments: Vec<CoilSegmentIpc> =
            coil.segments.iter().map(CoilSegmentIpc::from_core).collect();
        let bbox = coil.bounding_box();
        let terminal_start = coil.segments.first().map(|s| [s.start.0, s.start.1]).unwrap_or([0.0, 0.0]);
        let terminal_end = coil.segments.last().map(|s| [s.end.0, s.end.1]).unwrap_or([0.0, 0.0]);
        Self {
            phase_idx: coil.phase_idx,
            layer_idx: coil.layer_idx,
            phase_name: coil.phase_name.clone(),
            topology: coil.topology.into(),
            segments,
            total_length_m: coil.total_length_m(),
            active_length_m: coil.active_length_m(),
            end_turn_length_m: coil.end_turn_length_m(),
            active_conductor_count: coil.active_conductor_count() as u32,
            bounding_box: [bbox.0, bbox.1, bbox.2, bbox.3],
            terminal_start,
            terminal_end,
        }
    }
}

#[allow(dead_code)]
impl CoilPathIpc {
    /// Build the IPC coil path from a list of core `PhaseCoil`s.
    pub fn from_core(coils: &[CorePhaseCoil], layer_count: u32) -> Self {
        Self {
            phases: coils.iter().map(PhaseCoilIpc::from_core).collect(),
            layer_count,
        }
    }
}
