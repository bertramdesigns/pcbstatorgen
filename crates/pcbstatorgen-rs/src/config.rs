//! Configuration structs and result types (serde-serializable).
//!
//! Linear mode only — `AxialMotorConfig`
//! remains a stub (PRODUCT_GOALS.md §7.A).
//!
//! All quantities in SI units: metres, Tesla, Amperes, Ohms, Watts.
//! Use [`crate::units`] helpers (mm, mils_to_m, oz_to_m) for human-readable input.

use serde::{Deserialize, Serialize};

/// Safety margin for minimum drive force calculation.
const SAFETY_MARGIN: f64 = 1.3;

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/// Permanent magnet arrangement on the carriage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MagnetArrangement {
    Alternating,
    AlternatingBackIron,
    Halbach,
    HalbachBackIron,
}

/// PCB stator conductor path topology.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoilTopology {
    Serpentine,
    SineWave,
    Concentrated,
    Rhombic,
    Spiral,
}

/// Mover linear bearing / guide type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BearingType {
    PlasticChannel,
    PteLined,
    BallBearing,
}

// ---------------------------------------------------------------------------
// LinearMotorConfig
// ---------------------------------------------------------------------------

/// Linear PCB coreless motor configuration (flying mover).
///
/// All quantities in SI units. `active_area_length_m` is the primary INPUT;
/// `travel` is derived: `active_area_length - coil_span`.
///
/// Ports Python `BaseMotorConfig` + `LinearMotorConfig` as a single flat struct
/// (Rust has no dataclass inheritance).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinearMotorConfig {
    // --- Magnet parameters ---
    /// (width_travel, width_cross, height) of one magnet [m].
    pub magnet_dims_m: [f64; 3],
    /// Number of magnets in the array (must be even, ≥ 2).
    pub magnet_count: u32,
    /// Centre-to-centre magnet spacing = pole pitch [m].
    pub magnet_pitch_m: f64,
    /// Remnant flux density Br at 20 °C [T].
    pub magnet_remanence_t: f64,
    /// Standard NdFeB grade name (N35–N52) or "Custom".
    pub magnet_grade: String,
    /// Pole/flux-concentrator arrangement.
    pub magnet_arrangement: MagnetArrangement,
    /// CRS steel keeper thickness on rear face of magnets [m]. 0.0 = none.
    pub back_iron_thickness_m: f64,

    // --- Geometry ---
    /// Physical length of the stator copper trace region [m]. PRIMARY INPUT.
    pub active_area_length_m: f64,
    /// PCB dimension perpendicular to the travel axis [m].
    pub board_width_m: f64,
    /// PCB substrate thickness [m].
    pub pcb_thickness_m: f64,
    /// Magnet face to PCB copper clearance [m].
    pub air_gap_m: f64,

    // --- Coil ---
    /// PCB stator conductor path topology.
    pub coil_topology: CoilTopology,
    /// Number of electrical phases.
    pub phases: u32,
    /// Vernier slot pitch spacing ratio. 1.0 = standard 1:1.
    pub spacing_ratio: f64,

    // --- Drive electronics ---
    /// Peak phase current [A].
    pub max_current_a: f64,
    /// Drive electronics supply voltage [V].
    pub supply_voltage_v: f64,

    // --- DFM rules ---
    /// Minimum manufacturable trace width [m].
    pub min_trace_m: f64,
    /// Minimum trace-to-trace clearance [m].
    pub min_space_m: f64,
    /// Minimum via drill diameter [m].
    pub min_via_drill_m: f64,
    /// Minimum via annular ring width [m].
    pub min_via_annular_ring_m: f64,
    /// Maximum copper layer count (must be even).
    pub max_layers: u32,
    /// Nominal electrical drive frequency for skin-depth [Hz].
    pub drive_frequency_hz: f64,
    /// Maximum acceptable PCB temperature rise [°C].
    pub max_temperature_rise_c: f64,

    // --- Force / motion targets ---
    /// Minimum continuous thrust [N].
    pub target_force_n: f64,
    /// Burst thrust target [N] (must be ≥ target_force_n).
    pub peak_force_n: f64,
    /// Estimated total mechanical friction [N].
    pub friction_n: f64,
    /// Moving carriage mass [kg].
    pub carriage_mass_kg: f64,
    /// Maximum carriage acceleration [m/s²].
    pub max_accel_m_s2: f64,
    /// Burst-current capacitor bank size [µF].
    pub capacitor_bank_uf: f64,

    // --- Metadata ---
    /// Optional human-readable label.
    pub name: Option<String>,
}

impl Default for LinearMotorConfig {
    fn default() -> Self {
        use crate::units::{mm, mils_to_m};
        Self {
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 10,
            magnet_pitch_m: mm(12.0),
            magnet_remanence_t: 1.35,
            magnet_grade: "N44".to_string(),
            magnet_arrangement: MagnetArrangement::Alternating,
            back_iron_thickness_m: 0.0,
            active_area_length_m: mm(195.0),
            board_width_m: mm(20.0),
            pcb_thickness_m: 0.0016,
            air_gap_m: mm(0.5),
            coil_topology: CoilTopology::Serpentine,
            phases: 3,
            spacing_ratio: 1.0,
            max_current_a: 1.0,
            supply_voltage_v: 5.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            max_layers: 12,
            drive_frequency_hz: 500.0,
            max_temperature_rise_c: 20.0,
            target_force_n: 0.5,
            peak_force_n: 1.0,
            friction_n: 0.05,
            carriage_mass_kg: 0.015,
            max_accel_m_s2: 2.0,
            capacitor_bank_uf: 1000.0,
            name: None,
        }
    }
}

/// Configuration validation error.
#[derive(Debug, Clone, PartialEq)]
pub struct ConfigError(pub String);

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for ConfigError {}

impl LinearMotorConfig {
    /// Create a validated config, syncing magnet grade and checking all invariants.
    pub fn new(mut self) -> Result<Self, ConfigError> {
        self.sync_magnet_grade();
        self.validate()?;
        Ok(self)
    }

    /// Sync `magnet_remanence_t` from `magnet_grade` unless Custom.
    pub fn sync_magnet_grade(&mut self) {
        if self.magnet_grade == crate::magnet_grades::CUSTOM_GRADE {
            return;
        }
        if let Some(br) = crate::magnet_grades::get_remanence(&self.magnet_grade) {
            self.magnet_remanence_t = br;
        }
    }

    /// Validate all fields (mirrors Python `_validate_base` + `_validate_linear`).
    pub fn validate(&self) -> Result<(), ConfigError> {
        // --- Base validation ---
        if self.magnet_dims_m.len() != 3 {
            return Err(ConfigError(
                "magnet_dims_m must be a 3-tuple (width, length, height)".into(),
            ));
        }
        if self.magnet_dims_m.iter().any(|&d| d <= 0.0) {
            return Err(ConfigError(format!(
                "All magnet dimensions must be positive, got {:?}",
                self.magnet_dims_m
            )));
        }
        if self.magnet_count < 2 {
            return Err(ConfigError(format!(
                "magnet_count must be ≥ 2, got {}",
                self.magnet_count
            )));
        }
        if self.magnet_count % 2 != 0 {
            return Err(ConfigError(format!(
                "magnet_count must be even for alternating poles, got {}",
                self.magnet_count
            )));
        }
        if self.magnet_pitch_m <= 0.0 {
            return Err(ConfigError(format!(
                "magnet_pitch_m must be positive, got {}",
                self.magnet_pitch_m
            )));
        }
        let assembly_gap = self.magnet_pitch_m - self.magnet_dims_m[0];
        if assembly_gap < -1e-10 {
            return Err(ConfigError(format!(
                "magnet_pitch_m ({:.3} mm) must be ≥ magnet width ({:.3} mm) — \
                 inter-magnet gap cannot be negative (current gap: {:.3} mm)",
                self.magnet_pitch_m * 1e3,
                self.magnet_dims_m[0] * 1e3,
                assembly_gap * 1e3
            )));
        }
        if self.magnet_remanence_t <= 0.0 || self.magnet_remanence_t > 2.5 {
            return Err(ConfigError(format!(
                "magnet_remanence_t must be in (0, 2.5] T, got {}",
                self.magnet_remanence_t
            )));
        }
        if self.phases < 1 {
            return Err(ConfigError(format!(
                "phases must be ≥ 1, got {}",
                self.phases
            )));
        }
        if self.spacing_ratio <= 0.0 || self.spacing_ratio > 2.0 {
            return Err(ConfigError(format!(
                "spacing_ratio must be in (0.0, 2.0], got {}",
                self.spacing_ratio
            )));
        }
        if self.max_current_a <= 0.0 {
            return Err(ConfigError(format!(
                "max_current_a must be positive, got {}",
                self.max_current_a
            )));
        }
        if self.supply_voltage_v <= 0.0 {
            return Err(ConfigError(format!(
                "supply_voltage_v must be positive, got {}",
                self.supply_voltage_v
            )));
        }
        if self.min_trace_m <= 0.0 {
            return Err(ConfigError(format!(
                "min_trace_m must be positive, got {}",
                self.min_trace_m
            )));
        }
        if self.min_space_m <= 0.0 {
            return Err(ConfigError(format!(
                "min_space_m must be positive, got {}",
                self.min_space_m
            )));
        }
        if self.min_via_drill_m <= 0.0 {
            return Err(ConfigError(format!(
                "min_via_drill_m must be positive, got {}",
                self.min_via_drill_m
            )));
        }
        if self.min_via_annular_ring_m <= 0.0 {
            return Err(ConfigError(format!(
                "min_via_annular_ring_m must be positive, got {}",
                self.min_via_annular_ring_m
            )));
        }
        if self.air_gap_m < 0.0 {
            return Err(ConfigError(format!(
                "air_gap_m must be ≥ 0, got {}",
                self.air_gap_m
            )));
        }
        if self.back_iron_thickness_m < 0.0 {
            return Err(ConfigError(format!(
                "back_iron_thickness_m must be ≥ 0, got {}",
                self.back_iron_thickness_m
            )));
        }
        if self.max_layers < 2 || self.max_layers % 2 != 0 {
            return Err(ConfigError(format!(
                "max_layers must be an even number ≥ 2, got {}",
                self.max_layers
            )));
        }
        if self.drive_frequency_hz <= 0.0 {
            return Err(ConfigError(format!(
                "drive_frequency_hz must be positive, got {}",
                self.drive_frequency_hz
            )));
        }
        if self.max_temperature_rise_c <= 0.0 {
            return Err(ConfigError(format!(
                "max_temperature_rise_c must be positive, got {}",
                self.max_temperature_rise_c
            )));
        }

        // --- Linear validation ---
        if self.active_area_length_m <= 0.0 {
            return Err(ConfigError(format!(
                "active_area_length_m must be positive, got {}",
                self.active_area_length_m
            )));
        }
        if self.active_area_length_m <= self.coil_span_m() {
            return Err(ConfigError(format!(
                "active_area_length_m ({:.1} mm) must be > coil_span ({:.1} mm = \
                 {} magnets × {:.1} mm) — travel would be zero or negative",
                self.active_area_length_m * 1e3,
                self.coil_span_m() * 1e3,
                self.magnet_count,
                self.magnet_pitch_m * 1e3
            )));
        }
        if self.board_width_m <= 0.0 {
            return Err(ConfigError(format!(
                "board_width_m must be positive, got {}",
                self.board_width_m
            )));
        }
        if self.pcb_thickness_m <= 0.0 {
            return Err(ConfigError(format!(
                "pcb_thickness_m must be positive, got {}",
                self.pcb_thickness_m
            )));
        }
        if self.target_force_n <= 0.0 {
            return Err(ConfigError(format!(
                "target_force_n must be positive, got {}",
                self.target_force_n
            )));
        }
        if self.peak_force_n < self.target_force_n {
            return Err(ConfigError(format!(
                "peak_force_n ({:.3} N) must be ≥ target_force_n ({:.3} N)",
                self.peak_force_n, self.target_force_n
            )));
        }
        if self.friction_n < 0.0 {
            return Err(ConfigError(format!(
                "friction_n must be ≥ 0, got {}",
                self.friction_n
            )));
        }
        if self.carriage_mass_kg <= 0.0 {
            return Err(ConfigError(format!(
                "carriage_mass_kg must be positive, got {}",
                self.carriage_mass_kg
            )));
        }
        if self.max_accel_m_s2 <= 0.0 {
            return Err(ConfigError(format!(
                "max_accel_m_s2 must be positive, got {}",
                self.max_accel_m_s2
            )));
        }
        if self.capacitor_bank_uf <= 0.0 {
            return Err(ConfigError(format!(
                "capacitor_bank_uf must be positive, got {}",
                self.capacitor_bank_uf
            )));
        }
        Ok(())
    }

    // --- Derived geometry ---

    /// Full span of the mover's magnet array [m]: `magnet_count × magnet_pitch`.
    pub fn coil_span_m(&self) -> f64 {
        self.magnet_count as f64 * self.magnet_pitch_m
    }

    /// Derived center-to-center travel [m]: `active_area_length - coil_span`.
    pub fn travel_m(&self) -> f64 {
        self.active_area_length_m - self.coil_span_m()
    }

    /// Minimum PCB length required [m] (= active_area_length_m).
    pub fn active_length_m(&self) -> f64 {
        self.active_area_length_m
    }

    /// Magnet pole pitch [m] (= magnet_pitch for alternating arrays).
    pub fn pole_pitch_m(&self) -> f64 {
        self.magnet_pitch_m
    }

    /// Coil slot pitch = (pole_pitch / phases) × spacing_ratio [m].
    pub fn slot_pitch_m(&self) -> f64 {
        (self.pole_pitch_m() / self.phases as f64) * self.spacing_ratio
    }

    /// Gap between adjacent magnets [m]: `magnet_pitch - magnet_width`.
    pub fn magnet_gap_m(&self) -> f64 {
        self.magnet_pitch_m - self.magnet_dims_m[0]
    }

    /// Minimum via pad diameter [m] = drill + 2 × annular ring.
    pub fn min_via_pad_m(&self) -> f64 {
        self.min_via_drill_m + 2.0 * self.min_via_annular_ring_m
    }

    /// Peak inertial force [N] = `carriage_mass × max_accel`.
    pub fn acceleration_force_n(&self) -> f64 {
        self.carriage_mass_kg * self.max_accel_m_s2
    }

    /// Minimum motor force to overcome friction with safety margin [N].
    pub fn minimum_drive_force_n(&self) -> f64 {
        self.friction_n * SAFETY_MARGIN
    }

    /// Compact human-readable summary.
    pub fn summary(&self) -> String {
        let arr_label = match self.magnet_arrangement {
            MagnetArrangement::Alternating => "alternating poles",
            MagnetArrangement::AlternatingBackIron => "alternating + back-iron",
            MagnetArrangement::Halbach => "Halbach array",
            MagnetArrangement::HalbachBackIron => "Halbach + back-iron",
        };
        let topo_label = match self.coil_topology {
            CoilTopology::Serpentine => "serpentine",
            CoilTopology::SineWave => "sine_wave",
            CoilTopology::Concentrated => "concentrated",
            CoilTopology::Rhombic => "rhombic",
            CoilTopology::Spiral => "spiral",
        };
        let name = self.name.as_deref().unwrap_or("(unnamed)");
        format!(
            "LinearMotorConfig: {name}\n\
             \x20 Active area len:  {active:.1} mm\n\
             \x20 Travel (derived): {travel:.1} mm\n\
             \x20 Coil span:        {span:.1} mm\n\
             \x20 Magnet:          {count}× {w:.0}×{l:.0}×{h:.0} mm  Br={br:.2} T\n\
             \x20 Arrangement:     {arr}\n\
             \x20 Coil topology:   {topo}\n\
             \x20 Pole pitch:      {pp:.1} mm\n\
             \x20 Slot pitch:      {sp:.2} mm  ({phases}-phase)\n\
             \x20 Air gap:         {ag:.2} mm\n\
             \x20 Board width:     {bw:.1} mm\n\
             \x20 Target force:    {tf:.0} mN / {pk:.0} mN peak\n\
             \x20 Friction est.:   {fr:.0} mN (min drive: {md:.0} mN)\n\
             \x20 Accel. budget:   {af:.0} mN ({mass:.0} g × {accel:.1} m/s²)\n\
             \x20 Current:         {curr:.1} A @ {volt:.1} V\n\
             \x20 Cap. bank:       {cap:.0} µF\n\
             \x20 Min trace/space: {mt:.3} / {ms:.3} mm\n\
             \x20 Via drill/ring:  {vd:.2} / {vr:.2} mm\n\
             \x20 Drive freq:      {df:.0} Hz\n\
             \x20 Max ΔT:          {dt:.0} °C",
            name = name,
            active = self.active_area_length_m * 1e3,
            travel = self.travel_m() * 1e3,
            span = self.coil_span_m() * 1e3,
            count = self.magnet_count,
            w = self.magnet_dims_m[0] * 1e3,
            l = self.magnet_dims_m[1] * 1e3,
            h = self.magnet_dims_m[2] * 1e3,
            br = self.magnet_remanence_t,
            arr = arr_label,
            topo = topo_label,
            pp = self.pole_pitch_m() * 1e3,
            sp = self.slot_pitch_m() * 1e3,
            phases = self.phases,
            ag = self.air_gap_m * 1e3,
            bw = self.board_width_m * 1e3,
            tf = self.target_force_n * 1e3,
            pk = self.peak_force_n * 1e3,
            fr = self.friction_n * 1e3,
            md = self.minimum_drive_force_n() * 1e3,
            af = self.acceleration_force_n() * 1e3,
            mass = self.carriage_mass_kg * 1e3,
            accel = self.max_accel_m_s2,
            curr = self.max_current_a,
            volt = self.supply_voltage_v,
            cap = self.capacitor_bank_uf,
            mt = self.min_trace_m * 1e3,
            ms = self.min_space_m * 1e3,
            vd = self.min_via_drill_m * 1e3,
            vr = self.min_via_annular_ring_m * 1e3,
            df = self.drive_frequency_hz,
            dt = self.max_temperature_rise_c,
        )
    }
}

// ---------------------------------------------------------------------------
// StackupResult
// ---------------------------------------------------------------------------

/// Computed PCB stackup recommendation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StackupResult {
    pub layer_count: u32,
    pub trace_widths_m: Vec<f64>,
    pub cu_thickness_m: Vec<f64>,
    pub via_drill_m: f64,
    pub via_annular_ring_m: f64,
    pub via_grid_rows: u32,
    pub via_grid_cols: u32,
    pub estimated_force_n: f64,
    pub estimated_dc_resistance_ohm: f64,
    #[serde(default)]
    pub notes: Vec<String>,
}

impl StackupResult {
    /// Validate all fields.
    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.layer_count < 2 || self.layer_count % 2 != 0 {
            return Err(ConfigError(format!(
                "layer_count must be even and ≥ 2, got {}",
                self.layer_count
            )));
        }
        if self.trace_widths_m.len() != self.layer_count as usize {
            return Err(ConfigError(format!(
                "trace_widths_m must have {} entries, got {}",
                self.layer_count,
                self.trace_widths_m.len()
            )));
        }
        if self.cu_thickness_m.len() != self.layer_count as usize {
            return Err(ConfigError(format!(
                "cu_thickness_m must have {} entries, got {}",
                self.layer_count,
                self.cu_thickness_m.len()
            )));
        }
        if self.trace_widths_m.iter().any(|&w| w <= 0.0) {
            return Err(ConfigError("All trace widths must be positive".into()));
        }
        if self.cu_thickness_m.iter().any(|&t| t <= 0.0) {
            return Err(ConfigError("All copper thicknesses must be positive".into()));
        }
        if self.via_drill_m <= 0.0 {
            return Err(ConfigError(format!(
                "via_drill_m must be positive, got {}",
                self.via_drill_m
            )));
        }
        if self.via_annular_ring_m <= 0.0 {
            return Err(ConfigError(format!(
                "via_annular_ring_m must be positive, got {}",
                self.via_annular_ring_m
            )));
        }
        if self.via_grid_rows < 1 {
            return Err(ConfigError(format!(
                "via_grid_rows must be ≥ 1, got {}",
                self.via_grid_rows
            )));
        }
        if self.via_grid_cols < 1 {
            return Err(ConfigError(format!(
                "via_grid_cols must be ≥ 1, got {}",
                self.via_grid_cols
            )));
        }
        Ok(())
    }

    /// (0, layer_count - 1)
    pub fn outer_layer_ids(&self) -> (usize, usize) {
        (0, (self.layer_count - 1) as usize)
    }

    /// 1 .. layer_count-1
    pub fn inner_layer_ids(&self) -> Vec<usize> {
        (1..(self.layer_count - 1) as usize).collect()
    }

    /// Via pad diameter = drill + 2 × annular ring.
    pub fn via_pad_m(&self) -> f64 {
        self.via_drill_m + 2.0 * self.via_annular_ring_m
    }

    /// Total number of vias per end-turn.
    pub fn via_grid_count(&self) -> u32 {
        self.via_grid_rows * self.via_grid_cols
    }

    /// Human-readable summary.
    pub fn summary(&self) -> String {
        let mut lines = vec![
            format!("StackupResult: {} layers", self.layer_count),
            format!("  Estimated force:  {:.3} N", self.estimated_force_n),
            format!(
                "  DC resistance:    {:.3} Ω / phase",
                self.estimated_dc_resistance_ohm
            ),
            format!(
                "  Via grid:         {}×{} ({} vias/end-turn)",
                self.via_grid_rows,
                self.via_grid_cols,
                self.via_grid_count()
            ),
            format!(
                "  Via drill/pad:    {:.2} / {:.2} mm",
                self.via_drill_m * 1e3,
                self.via_pad_m() * 1e3
            ),
            "  Layer trace widths and copper weights:".to_string(),
        ];
        let (outer0, outer1) = self.outer_layer_ids();
        for (i, (&w, &t)) in self
            .trace_widths_m
            .iter()
            .zip(self.cu_thickness_m.iter())
            .enumerate()
        {
            let role = if i == outer0 || i == outer1 {
                "outer"
            } else {
                "inner"
            };
            let oz = t / 35e-6;
            lines.push(format!(
                "    L{:>2} ({}): trace={:.3} mm  Cu={:.0} µm (~{:.1} oz)",
                i + 1,
                role,
                w * 1e3,
                t * 1e6,
                oz
            ));
        }
        if !self.notes.is_empty() {
            lines.push("  Notes:".to_string());
            for note in &self.notes {
                lines.push(format!("    • {}", note));
            }
        }
        lines.join("\n")
    }
}

// ---------------------------------------------------------------------------
// HeightStackResult
// ---------------------------------------------------------------------------

/// Explicit vertical stack from PCB bottom to magnet top.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeightStackResult {
    pub pcb_thickness_m: f64,
    pub cu_protrusion_m: f64,
    pub solder_mask_m: f64,
    pub air_gap_m: f64,
    pub magnet_height_m: f64,
    pub back_iron_thickness_m: f64,
    pub tolerance_m: f64,
}

impl HeightStackResult {
    /// Total stack height from PCB bottom to magnet top [m].
    pub fn total_height_m(&self) -> f64 {
        self.pcb_thickness_m
            + self.cu_protrusion_m
            + self.solder_mask_m
            + self.air_gap_m
            + self.magnet_height_m
            + self.back_iron_thickness_m
            + self.tolerance_m
    }

    /// True if the total stack fits within `budget_m`.
    pub fn fits_in_budget(&self, budget_m: f64) -> bool {
        self.total_height_m() <= budget_m
    }

    /// Remaining height headroom [m] (negative = over budget).
    pub fn headroom_m(&self, budget_m: f64) -> f64 {
        budget_m - self.total_height_m()
    }

    /// Human-readable summary.
    pub fn summary(&self) -> String {
        let mut lines = vec![
            "HeightStackResult:".to_string(),
            format!("  PCB substrate:    {:.2} mm", self.pcb_thickness_m * 1e3),
            format!("  Cu protrusion:    {:.0} µm", self.cu_protrusion_m * 1e6),
            format!("  Solder mask:      {:.0} µm", self.solder_mask_m * 1e6),
            format!("  Air gap:          {:.2} mm", self.air_gap_m * 1e3),
            format!("  Magnet height:    {:.2} mm", self.magnet_height_m * 1e3),
        ];
        if self.back_iron_thickness_m > 0.0 {
            lines.push(format!(
                "  Back-iron:        {:.2} mm",
                self.back_iron_thickness_m * 1e3
            ));
        }
        lines.push(format!("  Tolerance:        {:.2} mm", self.tolerance_m * 1e3));
        lines.push("  ─────────────────────────────".to_string());
        lines.push(format!(
            "  Total height:     {:.2} mm",
            self.total_height_m() * 1e3
        ));
        lines.join("\n")
    }
}

// ---------------------------------------------------------------------------
// FrictionBudget
// ---------------------------------------------------------------------------

/// Breakdown of mechanical friction contributors.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrictionBudget {
    pub bearing_friction_n: f64,
    pub cable_drag_n: f64,
    #[serde(default)]
    pub wiper_contact_n: f64,
    #[serde(default)]
    pub cogging_n: f64,
}

impl FrictionBudget {
    /// Total friction force [N].
    pub fn total_n(&self) -> f64 {
        self.bearing_friction_n + self.cable_drag_n + self.wiper_contact_n + self.cogging_n
    }

    /// Minimum motor force to start motion with 1.3× safety margin [N].
    pub fn minimum_drive_force_n(&self) -> f64 {
        self.total_n() * SAFETY_MARGIN
    }

    /// Human-readable summary.
    pub fn summary(&self) -> String {
        format!(
            "FrictionBudget:\n\
             \x20 Bearing friction: {:.1} mN\n\
             \x20 Cable drag:       {:.1} mN\n\
             \x20 Wiper contact:    {:.1} mN\n\
             \x20 Cogging:          {:.1} mN\n\
             \x20 ─────────────────────────────\n\
             \x20 Total:            {:.1} mN\n\
             \x20 Min drive force:  {:.1} mN  (×{:.1} margin)",
            self.bearing_friction_n * 1e3,
            self.cable_drag_n * 1e3,
            self.wiper_contact_n * 1e3,
            self.cogging_n * 1e3,
            self.total_n() * 1e3,
            self.minimum_drive_force_n() * 1e3,
            SAFETY_MARGIN,
        )
    }
}

// ---------------------------------------------------------------------------
// PowerBudget
// ---------------------------------------------------------------------------

/// Continuous and burst power analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PowerBudget {
    pub phase_resistance_ohm: f64,
    pub continuous_power_w: f64,
    pub burst_power_w: f64,
    pub temperature_rise_c: f64,
    pub capacitor_required_uf: f64,
    pub efficiency_pct: f64,
}

impl PowerBudget {
    /// Human-readable summary.
    pub fn summary(&self) -> String {
        format!(
            "PowerBudget:\n\
             \x20 Phase resistance:  {:.3} Ω\n\
             \x20 Continuous loss:   {:.0} mW\n\
             \x20 Burst loss:        {:.0} mW\n\
             \x20 Temperature rise:  +{:.1} °C\n\
             \x20 Capacitor needed:  {:.0} µF\n\
             \x20 Efficiency (peak): {:.1} %",
            self.phase_resistance_ohm,
            self.continuous_power_w * 1e3,
            self.burst_power_w * 1e3,
            self.temperature_rise_c,
            self.capacitor_required_uf,
            self.efficiency_pct,
        )
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::units::{mm, mils_to_m, oz_to_m};

    fn default_config() -> LinearMotorConfig {
        LinearMotorConfig {
            name: Some("test-config".into()),
            active_area_length_m: mm(195.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 10,
            magnet_pitch_m: mm(12.0),
            phases: 3,
            target_force_n: 0.5,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 12,
            drive_frequency_hz: 500.0,
            ..LinearMotorConfig::default()
        }
    }

    // --- Construction ---

    #[test]
    fn test_default_config_validates() {
        assert!(default_config().validate().is_ok());
    }

    #[test]
    fn test_name_stored() {
        let cfg = LinearMotorConfig {
            name: Some("my-actuator".into()),
            ..LinearMotorConfig::default()
        };
        assert_eq!(cfg.name.as_deref(), Some("my-actuator"));
    }

    #[test]
    fn test_name_optional() {
        let cfg = LinearMotorConfig::default();
        assert!(cfg.name.is_none());
    }

    #[test]
    fn test_default_phases() {
        assert_eq!(LinearMotorConfig::default().phases, 3);
    }

    #[test]
    fn test_default_magnet_count() {
        assert_eq!(LinearMotorConfig::default().magnet_count, 10);
    }

    #[test]
    fn test_default_max_layers_even() {
        assert!(LinearMotorConfig::default().max_layers % 2 == 0);
    }

    // --- Validation ---

    #[test]
    fn test_zero_active_area_raises() {
        let cfg = LinearMotorConfig { active_area_length_m: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_negative_active_area_raises() {
        let cfg = LinearMotorConfig { active_area_length_m: -mm(10.0), ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_active_area_le_coil_span_raises() {
        let cfg = LinearMotorConfig {
            active_area_length_m: mm(120.0),
            magnet_count: 10,
            magnet_pitch_m: mm(12.0),
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_magnet_dim_raises() {
        let cfg = LinearMotorConfig {
            magnet_dims_m: [0.0, mm(10.0), mm(4.0)],
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_odd_magnet_count_raises() {
        let cfg = LinearMotorConfig { magnet_count: 9, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_magnet_count_one_raises() {
        let cfg = LinearMotorConfig { magnet_count: 1, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_pitch_smaller_than_magnet_width_raises() {
        let cfg = LinearMotorConfig {
            magnet_dims_m: [mm(15.0), mm(10.0), mm(4.0)],
            magnet_pitch_m: mm(12.0),
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_unrealistic_remanence_raises() {
        let cfg = LinearMotorConfig {
            magnet_grade: "Custom".into(),
            magnet_remanence_t: 3.0,
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_remanence_raises() {
        let cfg = LinearMotorConfig {
            magnet_grade: "Custom".into(),
            magnet_remanence_t: 0.0,
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_target_force_raises() {
        let cfg = LinearMotorConfig { target_force_n: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_current_raises() {
        let cfg = LinearMotorConfig { max_current_a: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_trace_raises() {
        let cfg = LinearMotorConfig { min_trace_m: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_via_drill_raises() {
        let cfg = LinearMotorConfig { min_via_drill_m: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_negative_air_gap_raises() {
        let cfg = LinearMotorConfig { air_gap_m: -mm(0.1), ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_odd_max_layers_raises() {
        let cfg = LinearMotorConfig { max_layers: 5, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_max_layers_raises() {
        let cfg = LinearMotorConfig { max_layers: 0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_drive_frequency_raises() {
        let cfg = LinearMotorConfig { drive_frequency_hz: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_zero_board_width_raises() {
        let cfg = LinearMotorConfig { board_width_m: 0.0, ..LinearMotorConfig::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_peak_below_target_raises() {
        let cfg = LinearMotorConfig {
            target_force_n: 1.0,
            peak_force_n: 0.5,
            ..LinearMotorConfig::default()
        };
        assert!(cfg.validate().is_err());
    }

    // --- Derived properties ---

    #[test]
    fn test_pole_pitch_equals_magnet_pitch() {
        let cfg = default_config();
        assert_eq!(cfg.pole_pitch_m(), cfg.magnet_pitch_m);
    }

    #[test]
    fn test_slot_pitch_three_phase() {
        let cfg = default_config();
        let expected = cfg.magnet_pitch_m / 3.0;
        assert!((cfg.slot_pitch_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_coil_span() {
        let cfg = default_config();
        let expected = cfg.magnet_count as f64 * cfg.magnet_pitch_m;
        assert!((cfg.coil_span_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_travel() {
        let cfg = default_config();
        let expected = cfg.active_area_length_m - cfg.coil_span_m();
        assert!((cfg.travel_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_min_via_pad() {
        let cfg = default_config();
        let expected = cfg.min_via_drill_m + 2.0 * cfg.min_via_annular_ring_m;
        assert!((cfg.min_via_pad_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_active_length_greater_than_travel() {
        let cfg = default_config();
        assert!(cfg.active_length_m() > cfg.travel_m());
    }

    #[test]
    fn test_acceleration_force() {
        let cfg = default_config();
        let expected = cfg.carriage_mass_kg * cfg.max_accel_m_s2;
        assert!((cfg.acceleration_force_n() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_minimum_drive_force() {
        let cfg = default_config();
        let expected = cfg.friction_n * 1.3;
        assert!((cfg.minimum_drive_force_n() - expected).abs() < 1e-12);
    }

    // --- Magnet grade sync ---

    #[test]
    fn test_sync_magnet_grade_n44() {
        let mut cfg = LinearMotorConfig {
            magnet_grade: "N44".into(),
            magnet_remanence_t: 0.0,
            ..LinearMotorConfig::default()
        };
        cfg.sync_magnet_grade();
        assert!((cfg.magnet_remanence_t - 1.34).abs() < 1e-6);
    }

    #[test]
    fn test_sync_magnet_grade_n44h_suffix() {
        let mut cfg = LinearMotorConfig {
            magnet_grade: "N44H".into(),
            magnet_remanence_t: 0.0,
            ..LinearMotorConfig::default()
        };
        cfg.sync_magnet_grade();
        assert!((cfg.magnet_remanence_t - 1.34).abs() < 1e-6);
    }

    #[test]
    fn test_sync_magnet_grade_custom_unchanged() {
        let mut cfg = LinearMotorConfig {
            magnet_grade: "Custom".into(),
            magnet_remanence_t: 1.50,
            ..LinearMotorConfig::default()
        };
        cfg.sync_magnet_grade();
        assert!((cfg.magnet_remanence_t - 1.50).abs() < 1e-6);
    }

    // --- Summary ---

    #[test]
    fn test_summary_is_string() {
        let cfg = default_config();
        let s = cfg.summary();
        assert!(!s.is_empty());
    }

    #[test]
    fn test_summary_contains_travel() {
        let cfg = default_config();
        let s = cfg.summary();
        // travel = 195 - 120 = 75 mm
        assert!(s.contains("75"));
    }

    #[test]
    fn test_summary_contains_name() {
        let cfg = LinearMotorConfig {
            name: Some("custom-name".into()),
            ..LinearMotorConfig::default()
        };
        assert!(cfg.summary().contains("custom-name"));
    }

    #[test]
    fn test_summary_unnamed_placeholder() {
        let cfg = LinearMotorConfig::default();
        assert!(cfg.summary().contains("(unnamed)"));
    }

    // --- StackupResult ---

    fn base_4layer() -> StackupResult {
        StackupResult {
            layer_count: 4,
            trace_widths_m: vec![mm(0.15), mm(0.25), mm(0.25), mm(0.15)],
            cu_thickness_m: vec![oz_to_m(1.0), oz_to_m(2.0), oz_to_m(2.0), oz_to_m(1.0)],
            via_drill_m: mm(0.2),
            via_annular_ring_m: mm(0.1),
            via_grid_rows: 2,
            via_grid_cols: 3,
            estimated_force_n: 0.42,
            estimated_dc_resistance_ohm: 3.1,
            notes: vec!["4-layer stackup chosen by test fixture".into()],
        }
    }

    #[test]
    fn test_stackup_4layer_validates() {
        assert!(base_4layer().validate().is_ok());
    }

    #[test]
    fn test_stackup_odd_layer_count_raises() {
        let mut s = base_4layer();
        s.layer_count = 3;
        assert!(s.validate().is_err());
    }

    #[test]
    fn test_stackup_trace_width_count_mismatch() {
        let mut s = base_4layer();
        s.trace_widths_m = vec![mm(0.15), mm(0.25), mm(0.15)];
        assert!(s.validate().is_err());
    }

    #[test]
    fn test_stackup_outer_layer_ids() {
        let s = base_4layer();
        assert_eq!(s.outer_layer_ids(), (0, 3));
    }

    #[test]
    fn test_stackup_inner_layer_ids() {
        let s = base_4layer();
        assert_eq!(s.inner_layer_ids(), vec![1, 2]);
    }

    #[test]
    fn test_stackup_via_pad() {
        let s = base_4layer();
        let expected = mm(0.2) + 2.0 * mm(0.1);
        assert!((s.via_pad_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_stackup_via_grid_count() {
        assert_eq!(base_4layer().via_grid_count(), 6);
    }

    #[test]
    fn test_stackup_summary() {
        let s = base_4layer();
        let summary = s.summary();
        assert!(summary.contains("4 layers"));
    }

    // --- HeightStackResult ---

    #[test]
    fn test_height_stack_total() {
        let hs = HeightStackResult {
            pcb_thickness_m: 0.0016,
            cu_protrusion_m: 35e-6,
            solder_mask_m: 20e-6,
            air_gap_m: 0.0005,
            magnet_height_m: 0.004,
            back_iron_thickness_m: 0.0,
            tolerance_m: 0.0003,
        };
        let expected = 0.0016 + 35e-6 + 20e-6 + 0.0005 + 0.004 + 0.0 + 0.0003;
        assert!((hs.total_height_m() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_height_stack_fits_in_budget() {
        let hs = HeightStackResult {
            pcb_thickness_m: 0.0016,
            cu_protrusion_m: 35e-6,
            solder_mask_m: 20e-6,
            air_gap_m: 0.0005,
            magnet_height_m: 0.004,
            back_iron_thickness_m: 0.0,
            tolerance_m: 0.0003,
        };
        assert!(hs.fits_in_budget(0.010));
        assert!(!hs.fits_in_budget(0.001));
    }

    #[test]
    fn test_height_stack_headroom() {
        let hs = HeightStackResult {
            pcb_thickness_m: 0.0016,
            cu_protrusion_m: 35e-6,
            solder_mask_m: 20e-6,
            air_gap_m: 0.0005,
            magnet_height_m: 0.004,
            back_iron_thickness_m: 0.0,
            tolerance_m: 0.0003,
        };
        let total = hs.total_height_m();
        assert!((hs.headroom_m(0.010) - (0.010 - total)).abs() < 1e-12);
    }

    // --- FrictionBudget ---

    #[test]
    fn test_friction_total() {
        let fb = FrictionBudget {
            bearing_friction_n: 0.03,
            cable_drag_n: 0.52,
            wiper_contact_n: 0.055,
            cogging_n: 0.0,
        };
        assert!((fb.total_n() - 0.605).abs() < 1e-12);
    }

    #[test]
    fn test_friction_minimum_drive_force() {
        let fb = FrictionBudget {
            bearing_friction_n: 0.1,
            cable_drag_n: 0.0,
            wiper_contact_n: 0.0,
            cogging_n: 0.0,
        };
        assert!((fb.minimum_drive_force_n() - 0.13).abs() < 1e-12);
    }

    // --- PowerBudget ---

    #[test]
    fn test_power_budget_summary() {
        let pb = PowerBudget {
            phase_resistance_ohm: 3.1,
            continuous_power_w: 0.5,
            burst_power_w: 1.0,
            temperature_rise_c: 7.5,
            capacitor_required_uf: 500.0,
            efficiency_pct: 5.0,
        };
        let s = pb.summary();
        assert!(s.contains("3.100"));
        assert!(s.contains("500"));
    }

    // --- Serde round-trip ---

    #[test]
    fn test_config_serde_roundtrip() {
        let cfg = default_config();
        let json = serde_json::to_string(&cfg).unwrap();
        let cfg2: LinearMotorConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(cfg2.active_area_length_m, cfg.active_area_length_m);
        assert_eq!(cfg2.magnet_count, cfg.magnet_count);
        assert_eq!(cfg2.coil_topology, cfg.coil_topology);
        assert_eq!(cfg2.magnet_arrangement, cfg.magnet_arrangement);
    }

    #[test]
    fn test_enum_serde_snake_case() {
        let json = r#""serpentine""#;
        let topo: CoilTopology = serde_json::from_str(json).unwrap();
        assert_eq!(topo, CoilTopology::Serpentine);

        let json = r#""sine_wave""#;
        let topo: CoilTopology = serde_json::from_str(json).unwrap();
        assert_eq!(topo, CoilTopology::SineWave);

        let json = r#""halbach""#;
        let arr: MagnetArrangement = serde_json::from_str(json).unwrap();
        assert_eq!(arr, MagnetArrangement::Halbach);
    }
}
