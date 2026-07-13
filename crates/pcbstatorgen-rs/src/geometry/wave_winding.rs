//! Wave winding coil path generators for a linear coreless PCB stator.
//!
//! Coordinate system: X = travel axis, Y = perpendicular (board width). All [m].

use serde::{Deserialize, Serialize};

use crate::config::{CoilTopology, LinearMotorConfig};
use crate::geometry::coil_generators::CoilGenerator;

/// Standard phase name labels (A, B, C, D, E, F).
pub const PHASE_NAMES: &[&str] = &["A", "B", "C", "D", "E", "F"];

/// One straight trace segment in a coil path.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct CoilSegment {
    pub start: (f64, f64),
    pub end: (f64, f64),
    pub is_active: bool,
}

impl CoilSegment {
    /// Euclidean length [m].
    pub fn length_m(&self) -> f64 {
        let dx = self.end.0 - self.start.0;
        let dy = self.end.1 - self.start.1;
        (dx * dx + dy * dy).sqrt()
    }

    /// Midpoint of the segment.
    pub fn midpoint(&self) -> (f64, f64) {
        (
            (self.start.0 + self.end.0) / 2.0,
            (self.start.1 + self.end.1) / 2.0,
        )
    }

    /// True if the segment is vertical (active conductor).
    pub fn is_vertical(&self, tol: f64) -> bool {
        (self.end.0 - self.start.0).abs() < tol
    }

    /// True if the segment is horizontal (end-turn).
    pub fn is_horizontal(&self, tol: f64) -> bool {
        (self.end.1 - self.start.1).abs() < tol
    }

    /// Convenience: is_vertical with default tolerance.
    pub fn is_vert(&self) -> bool {
        self.is_vertical(1e-9)
    }

    /// Convenience: is_horizontal with default tolerance.
    pub fn is_horiz(&self) -> bool {
        self.is_horizontal(1e-9)
    }
}

/// Complete serpentine coil path for one phase on one PCB layer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhaseCoil {
    pub phase_idx: u32,
    pub layer_idx: u32,
    pub segments: Vec<CoilSegment>,
    pub phase_name: String,
    #[serde(default = "default_topology")]
    pub topology: CoilTopology,
    #[serde(default)]
    pub layer_pair: Option<(u32, u32)>,
    #[serde(default)]
    pub center_via_positions: Vec<(f64, f64)>,
}

fn default_topology() -> CoilTopology {
    CoilTopology::Serpentine
}

impl PhaseCoil {
    /// Ordered list of all waypoints along the coil path (len = segments + 1).
    pub fn polyline(&self) -> Vec<(f64, f64)> {
        if self.segments.is_empty() {
            return vec![];
        }
        let mut pts = vec![self.segments[0].start];
        for seg in &self.segments {
            pts.push(seg.end);
        }
        pts
    }

    /// All active conductor segments.
    pub fn active_segments(&self) -> Vec<&CoilSegment> {
        self.segments.iter().filter(|s| s.is_active).collect()
    }

    /// All end-turn segments.
    pub fn end_turn_segments(&self) -> Vec<&CoilSegment> {
        self.segments.iter().filter(|s| !s.is_active).collect()
    }

    /// Number of active conductors.
    pub fn active_conductor_count(&self) -> usize {
        self.segments.iter().filter(|s| s.is_active).count()
    }

    /// (min_x, min_y, max_x, max_y) bounding box.
    pub fn bounding_box(&self) -> (f64, f64, f64, f64) {
        let pts = self.polyline();
        if pts.is_empty() {
            return (0.0, 0.0, 0.0, 0.0);
        }
        let (mut min_x, mut min_y) = (f64::INFINITY, f64::INFINITY);
        let (mut max_x, mut max_y) = (f64::NEG_INFINITY, f64::NEG_INFINITY);
        for &(x, y) in &pts {
            if x < min_x { min_x = x; }
            if y < min_y { min_y = y; }
            if x > max_x { max_x = x; }
            if y > max_y { max_y = y; }
        }
        (min_x, min_y, max_x, max_y)
    }

    /// Electrical input terminal (first waypoint).
    pub fn terminal_start(&self) -> (f64, f64) {
        if self.segments.is_empty() {
            (0.0, 0.0)
        } else {
            self.segments[0].start
        }
    }

    /// Electrical output terminal (last waypoint).
    pub fn terminal_end(&self) -> (f64, f64) {
        if self.segments.is_empty() {
            (0.0, 0.0)
        } else {
            self.segments[self.segments.len() - 1].end
        }
    }

    /// Total copper trace length [m].
    pub fn total_length_m(&self) -> f64 {
        self.segments.iter().map(|s| s.length_m()).sum()
    }

    /// Total length of active conductor segments [m].
    pub fn active_length_m(&self) -> f64 {
        self.segments
            .iter()
            .filter(|s| s.is_active)
            .map(|s| s.length_m())
            .sum()
    }

    /// Total length of end-turn segments [m].
    pub fn end_turn_length_m(&self) -> f64 {
        self.segments
            .iter()
            .filter(|s| !s.is_active)
            .map(|s| s.length_m())
            .sum()
    }

    /// Midpoints of all end-turns at y = max_y (top edge).
    pub fn end_turn_midpoints_top(&self) -> Vec<(f64, f64)> {
        let (_, _min_y, _, max_y) = self.bounding_box();
        self.end_turn_segments()
            .iter()
            .filter(|s| (s.start.1 - max_y).abs() < 1e-9)
            .map(|s| s.midpoint())
            .collect()
    }

    /// Midpoints of all end-turns at y = min_y (bottom edge).
    pub fn end_turn_midpoints_bottom(&self) -> Vec<(f64, f64)> {
        let (_, min_y, _, _) = self.bounding_box();
        self.end_turn_segments()
            .iter()
            .filter(|s| (s.start.1 - min_y).abs() < 1e-9)
            .map(|s| s.midpoint())
            .collect()
    }

    /// Return true if every segment starts where the previous ends.
    pub fn is_continuous(&self, tol: f64) -> bool {
        for i in 0..self.segments.len().saturating_sub(1) {
            let ex = self.segments[i].end.0;
            let ey = self.segments[i].end.1;
            let sx = self.segments[i + 1].start.0;
            let sy = self.segments[i + 1].start.1;
            if (ex - sx).abs() > tol || (ey - sy).abs() > tol {
                return false;
            }
        }
        true
    }

    /// X positions of all active conductors, in order [m].
    pub fn active_conductor_x_positions(&self) -> Vec<f64> {
        self.active_segments().iter().map(|s| s.start.0).collect()
    }
}

impl Default for PhaseCoil {
    fn default() -> Self {
        Self {
            phase_idx: 0,
            layer_idx: 0,
            segments: vec![],
            phase_name: "A".into(),
            topology: CoilTopology::Serpentine,
            layer_pair: None,
            center_via_positions: vec![],
        }
    }
}

// ---------------------------------------------------------------------------
// WaveWindingGenerator
// ---------------------------------------------------------------------------

/// Generate rectangular wave winding (serpentine) coil paths.
pub struct WaveWindingGenerator;

impl WaveWindingGenerator {
    /// Generate coil paths for all phases on a single layer.
    pub fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        (0..config.phases)
            .map(|p| self.generate_phase(config, p, layer_idx))
            .collect()
    }

    /// Generate coil paths for all phases on all layers.
    pub fn generate_all_layers(
        &self,
        config: &LinearMotorConfig,
        layer_count: u32,
        phase_layer_map: Option<&Vec<Vec<u32>>>,
    ) -> Result<Vec<PhaseCoil>, String> {
        if layer_count < config.phases {
            return Err(format!(
                "layer_count ({}) must be ≥ phases ({})",
                layer_count, config.phases
            ));
        }
        if layer_count % 2 != 0 {
            return Err(format!("layer_count must be even, got {}", layer_count));
        }

        let default_map = Self::default_phase_layer_map(config.phases, layer_count);
        let map = phase_layer_map.unwrap_or(&default_map);

        let mut coils: Vec<PhaseCoil> = Vec::new();
        for (phase_idx, layer_indices) in map.iter().enumerate() {
            let phase_idx = phase_idx as u32;
            for &layer_idx in layer_indices {
                coils.push(self.generate_phase(config, phase_idx, layer_idx));
            }
        }
        coils.sort_by_key(|c| (c.layer_idx, c.phase_idx));
        Ok(coils)
    }

    /// Build the default interleaved phase→layer assignment (round-robin).
    pub fn default_phase_layer_map(phases: u32, layer_count: u32) -> Vec<Vec<u32>> {
        let mut mapping: Vec<Vec<u32>> = (0..phases).map(|_| vec![]).collect();
        for layer in 0..layer_count {
            mapping[(layer % phases) as usize].push(layer);
        }
        mapping
    }

    /// X positions of all active conductors for a phase [m].
    pub fn conductor_x_positions(config: &LinearMotorConfig, phase_idx: u32) -> Vec<f64> {
        let pole_pitch = config.pole_pitch_m();
        let slot_pitch = config.slot_pitch_m();
        let x_offset = phase_idx as f64 * slot_pitch;
        let x_max = config.active_area_length_m + (config.phases - 1) as f64 * slot_pitch;
        let mut positions = vec![];
        let mut x = x_offset;
        while x <= x_max + 1e-9 {
            positions.push(x);
            x += pole_pitch;
        }
        positions
    }

    /// Build the serpentine path for one phase on one layer.
    pub fn generate_phase(
        &self,
        config: &LinearMotorConfig,
        phase_idx: u32,
        layer_idx: u32,
    ) -> PhaseCoil {
        let board_width = config.board_width_m;
        let x_positions = Self::conductor_x_positions(config, phase_idx);
        let phase_name = PHASE_NAMES[(phase_idx as usize) % PHASE_NAMES.len()].to_string();

        if x_positions.is_empty() {
            return PhaseCoil {
                phase_idx,
                layer_idx,
                segments: vec![],
                phase_name,
                topology: CoilTopology::Serpentine,
                ..PhaseCoil::default()
            };
        }

        let mut segments: Vec<CoilSegment> = Vec::new();
        let mut going_up = true;

        for (k, &x) in x_positions.iter().enumerate() {
            let (y_start, y_end) = if going_up {
                (0.0, board_width)
            } else {
                (board_width, 0.0)
            };

            // Active conductor
            segments.push(CoilSegment {
                start: (x, y_start),
                end: (x, y_end),
                is_active: true,
            });

            // End-turn to next conductor
            if k < x_positions.len() - 1 {
                let x_next = x_positions[k + 1];
                let y_edge = if going_up { board_width } else { 0.0 };
                segments.push(CoilSegment {
                    start: (x, y_edge),
                    end: (x_next, y_edge),
                    is_active: false,
                });
            }

            going_up = !going_up;
        }

        // Inter-layer end-turn vias: one per end-turn, placed at the end of the
        // end-turn (on the same edge as the next active conductor). Only emitted
        // when the phase spans more than one copper layer — single-layer-per-phase
        // designs have no inter-layer connections to make.
        let center_via_positions = serpentine_via_positions(config, phase_idx, &segments);

        PhaseCoil {
            phase_idx,
            layer_idx,
            segments,
            phase_name,
            topology: CoilTopology::Serpentine,
            center_via_positions,
            ..PhaseCoil::default()
        }
    }
}

// ---------------------------------------------------------------------------
// SineWaveWindingGenerator
// ---------------------------------------------------------------------------

/// Generate sinusoidal serpentine wave winding coil paths.
pub struct SineWaveWindingGenerator;

impl SineWaveWindingGenerator {
    /// Generate sine wave coils for all phases on one layer.
    pub fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        (0..config.phases)
            .map(|p| self.generate_phase(config, p, layer_idx))
            .collect()
    }

    pub fn generate_phase(
        &self,
        config: &LinearMotorConfig,
        phase_idx: u32,
        layer_idx: u32,
    ) -> PhaseCoil {
        let board_width = config.board_width_m;
        let pole_pitch = config.pole_pitch_m();
        let slot_pitch = config.slot_pitch_m();
        let x_offset = phase_idx as f64 * slot_pitch;
        let x_max = config.active_area_length_m + (config.phases - 1) as f64 * slot_pitch;
        let phase_name = PHASE_NAMES[(phase_idx as usize) % PHASE_NAMES.len()].to_string();

        let steps_per_pole = 16.0;
        let dx = pole_pitch / steps_per_pole;

        let total_steps = ((x_max - x_offset) / dx).ceil() as i64;
        if total_steps < 1 {
            return PhaseCoil {
                phase_idx,
                layer_idx,
                segments: vec![],
                phase_name,
                topology: CoilTopology::SineWave,
                ..PhaseCoil::default()
            };
        }

        let mut points: Vec<(f64, f64)> = Vec::with_capacity(total_steps as usize + 1);
        for i in 0..=total_steps {
            let x = x_offset + i as f64 * dx;
            let y = (board_width / 2.0)
                * (std::f64::consts::PI * (x - x_offset) / pole_pitch - std::f64::consts::PI / 2.0)
                    .sin()
                + (board_width / 2.0);
            points.push((x, y));
        }

        let mut segments: Vec<CoilSegment> = Vec::with_capacity(points.len() - 1);
        for i in 0..points.len() - 1 {
            segments.push(CoilSegment {
                start: points[i],
                end: points[i + 1],
                is_active: true,
            });
        }

        // Inter-layer vias for a continuous sine wave path: place one via at
        // the start and one at the end of the phase coil, so adjacent layers
        // can chain the continuous path together. Only emitted when the phase
        // spans more than one copper layer.
        let center_via_positions = sine_wave_via_positions(config, phase_idx, &segments);

        PhaseCoil {
            phase_idx,
            layer_idx,
            segments,
            phase_name,
            topology: CoilTopology::SineWave,
            center_via_positions,
            ..PhaseCoil::default()
        }
    }
}


impl CoilGenerator for WaveWindingGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        WaveWindingGenerator.generate(config, layer_idx)
    }
}

impl CoilGenerator for SineWaveWindingGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        SineWaveWindingGenerator.generate(config, layer_idx)
    }
}

// ---------------------------------------------------------------------------
// Inter-layer end-turn via generator (ADR-0001)
//
// The KiCad writer already iterates `coil.center_via_positions` and emits one
// `Via` proto per position. For the two UI-selectable topologies
// (`Serpentine` and `SineWave`) the original generator left that field empty,
// so multi-layer coils exported with no inter-layer connections and tracks
// from different layers visually overlapped. This block populates the field
// for those two topologies, without touching `CoilTopologyIpc` or the writer.
//
// The `drill_diameter < slot_pitch − 2 × annular_ring` guard prevents the
// via pad from spanning adjacent phase slots (which would short the phases).
// ---------------------------------------------------------------------------

/// Default via drill diameter used by the clearance guard [m].
const DEFAULT_VIA_DRILL_M: f64 = 0.0003; // 0.3 mm
/// Default via annular-ring width used by the clearance guard [m].
const DEFAULT_VIA_ANNULAR_RING_M: f64 = 0.00015; // 0.15 mm

/// Number of copper layers assigned to a given phase under the default
/// round-robin phase-layer distribution.
///
/// `default_phase_layer_map` distributes `max_layers` layers across
/// `phases` phases round-robin. A given phase `p` owns every layer
/// `l` with `l % phases == p`. This helper counts how many such
/// layers exist in `[0, max_layers)`.
pub fn phase_layer_count(config: &LinearMotorConfig, phase_idx: u32) -> u32 {
    (0..config.max_layers)
        .filter(|&l| l % config.phases == phase_idx % config.phases)
        .count() as u32
}

/// True if the given phase is distributed across more than one copper
/// layer (and therefore needs inter-layer end-turn vias).
pub fn is_phase_multi_layer(config: &LinearMotorConfig, phase_idx: u32) -> bool {
    phase_layer_count(config, phase_idx) > 1
}

/// Serpentine placement rule (ADR-0001):
/// one through-via at the end of every end-turn segment, on the same edge
/// (y = 0 or y = board_width) as the end-turn. The next active conductor
/// drops from the via position, so the via is a natural inter-layer
/// connection point.
///
/// When the phase is on a single copper layer, no inter-layer connections
/// are needed and an empty vector is returned.
pub fn serpentine_via_positions(
    config: &LinearMotorConfig,
    phase_idx: u32,
    segments: &[CoilSegment],
) -> Vec<(f64, f64)> {
    if !is_phase_multi_layer(config, phase_idx) {
        return vec![];
    }
    segments
        .iter()
        .filter(|s| !s.is_active)
        .map(|s| (s.end.0, s.end.1))
        .collect()
}

/// SineWave placement rule (ADR-0001):
/// the sine path is continuous, so there are no sharp end-turns. The natural
/// inter-layer via locations are at the start and end of the phase coil
/// (the first waypoint and the last waypoint). When the phase is on a
/// single copper layer, no inter-layer connections are needed and an
/// empty vector is returned.
pub fn sine_wave_via_positions(
    config: &LinearMotorConfig,
    phase_idx: u32,
    segments: &[CoilSegment],
) -> Vec<(f64, f64)> {
    if !is_phase_multi_layer(config, phase_idx) {
        return vec![];
    }
    if segments.is_empty() {
        return vec![];
    }
    let start = segments[0].start;
    let end = segments[segments.len() - 1].end;
    vec![start, end]
}

/// Drill-clearance guard: a via pad of diameter
/// `drill + 2 × annular_ring` must fit inside one slot pitch without
/// touching an adjacent phase's slot. Returns `Ok(())` if safe, `Err` if
/// the design parameters would risk a short circuit between phases.
///
/// `via_count` is included in the error message for context; the actual
/// check is purely geometric and depends only on `config`.
///
/// Defaults used for the check: `drill_diameter = 0.3 mm`,
/// `annular_ring = 0.15 mm`. These are hardcoded for now (ADR-0001
/// §"Drill-clearance guard").
pub fn validate_via_clearance(
    config: &LinearMotorConfig,
    via_count: usize,
) -> Result<(), String> {
    let slot_pitch = config.slot_pitch_m();
    let min_required = DEFAULT_VIA_DRILL_M + 2.0 * DEFAULT_VIA_ANNULAR_RING_M;
    if slot_pitch <= min_required {
        return Err(format!(
            "via clearance guard failed: drill + 2*annular_ring = {:.3} mm must be \
             strictly less than slot_pitch = {:.3} mm (via_count={}); \
             tighten the slot pitch or relax drill/annular defaults",
            min_required * 1e3,
            slot_pitch * 1e3,
            via_count,
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::units::{mm, mils_to_m};

    fn default_config() -> LinearMotorConfig {
        LinearMotorConfig {
            name: Some("test".into()),
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
            ..LinearMotorConfig::default()
        }
    }

    fn tiny_config() -> LinearMotorConfig {
        LinearMotorConfig {
            active_area_length_m: mm(48.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(12.0),
            phases: 1,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 4,
            ..LinearMotorConfig::default()
        }
    }

    // --- CoilSegment ---

    #[test]
    fn test_length_vertical() {
        let seg = CoilSegment { start: (0.0, 0.0), end: (0.0, 0.02), is_active: true };
        assert!((seg.length_m() - 0.02).abs() < 1e-12);
    }

    #[test]
    fn test_length_horizontal() {
        let seg = CoilSegment { start: (0.0, 0.0), end: (0.012, 0.0), is_active: false };
        assert!((seg.length_m() - 0.012).abs() < 1e-12);
    }

    #[test]
    fn test_length_diagonal() {
        let seg = CoilSegment { start: (0.0, 0.0), end: (0.003, 0.004), is_active: true };
        assert!((seg.length_m() - 0.005).abs() < 1e-12);
    }

    #[test]
    fn test_midpoint() {
        let seg = CoilSegment { start: (0.0, 0.0), end: (0.0, 0.02), is_active: true };
        let m = seg.midpoint();
        assert!((m.0 - 0.0).abs() < 1e-12);
        assert!((m.1 - 0.01).abs() < 1e-12);
    }

    #[test]
    fn test_is_vertical() {
        let seg = CoilSegment { start: (0.005, 0.0), end: (0.005, 0.02), is_active: true };
        assert!(seg.is_vert());
    }

    #[test]
    fn test_is_horizontal() {
        let seg = CoilSegment { start: (0.0, 0.0), end: (0.012, 0.0), is_active: false };
        assert!(seg.is_horiz());
    }

    // --- Conductor positions ---

    #[test]
    fn test_phase_a_starts_at_zero() {
        let cfg = default_config();
        let positions = WaveWindingGenerator::conductor_x_positions(&cfg, 0);
        assert!((positions[0] - 0.0).abs() < 1e-12);
    }

    #[test]
    fn test_phase_b_starts_at_slot_pitch() {
        let cfg = default_config();
        let positions = WaveWindingGenerator::conductor_x_positions(&cfg, 1);
        assert!((positions[0] - cfg.slot_pitch_m()).abs() < 1e-12);
    }

    #[test]
    fn test_conductor_spacing_equals_pole_pitch() {
        let cfg = default_config();
        let positions = WaveWindingGenerator::conductor_x_positions(&cfg, 0);
        for i in 0..positions.len() - 1 {
            assert!((positions[i + 1] - positions[i] - cfg.pole_pitch_m()).abs() < 1e-12);
        }
    }

    #[test]
    fn test_all_phases_equal_conductor_count() {
        let cfg = default_config();
        let counts: Vec<usize> = (0..cfg.phases)
            .map(|p| WaveWindingGenerator::conductor_x_positions(&cfg, p).len())
            .collect();
        assert!(counts.iter().all(|&c| c == counts[0]));
    }

    // --- generate() ---

    #[test]
    fn test_returns_one_coil_per_phase() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        assert_eq!(coils.len(), cfg.phases as usize);
    }

    #[test]
    fn test_phase_indices_correct() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        for (p, coil) in coils.iter().enumerate() {
            assert_eq!(coil.phase_idx, p as u32);
        }
    }

    #[test]
    fn test_phase_names() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        assert_eq!(coils[0].phase_name, "A");
        assert_eq!(coils[1].phase_name, "B");
        assert_eq!(coils[2].phase_name, "C");
    }

    #[test]
    fn test_layer_idx_assigned() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate(&cfg, 3);
        for coil in &coils {
            assert_eq!(coil.layer_idx, 3);
        }
    }

    #[test]
    fn test_all_phases_same_conductor_count() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let counts: Vec<usize> = coils.iter().map(|c| c.active_conductor_count()).collect();
        assert!(counts.iter().all(|&c| c == counts[0]));
    }

    #[test]
    fn test_coil_is_continuous() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            assert!(coil.is_continuous(1e-9), "Phase {} not continuous", coil.phase_name);
        }
    }

    #[test]
    fn test_active_segments_are_vertical() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            for seg in coil.active_segments() {
                assert!(seg.is_vert(), "Active seg not vertical");
            }
        }
    }

    #[test]
    fn test_end_turns_are_horizontal() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            for seg in coil.end_turn_segments() {
                assert!(seg.is_horiz(), "End-turn not horizontal");
            }
        }
    }

    #[test]
    fn test_end_turn_count_is_active_minus_one() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            assert_eq!(coil.active_conductor_count() - 1, coil.end_turn_segments().len());
        }
    }

    #[test]
    fn test_active_conductors_span_board_width() {
        let cfg = default_config();
        let w = cfg.board_width_m;
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            for seg in coil.active_segments() {
                let ys = [seg.start.1, seg.end.1];
                assert!((ys.iter().fold(f64::INFINITY, |a, &b| a.min(b)) - 0.0).abs() < 1e-12);
                assert!((ys.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b)) - w).abs() < 1e-12);
            }
        }
    }

    #[test]
    fn test_alternating_direction() {
        let cfg = default_config();
        let w = cfg.board_width_m;
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            let active: Vec<&CoilSegment> = coil.active_segments();
            for (k, seg) in active.iter().enumerate() {
                if k % 2 == 0 {
                    assert!((seg.start.1 - 0.0).abs() < 1e-12);
                    assert!((seg.end.1 - w).abs() < 1e-12);
                } else {
                    assert!((seg.start.1 - w).abs() < 1e-12);
                    assert!((seg.end.1 - 0.0).abs() < 1e-12);
                }
            }
        }
    }

    #[test]
    fn test_phase_offsets_slot_pitch() {
        let cfg = default_config();
        let sp = cfg.slot_pitch_m();
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        assert!((coils[0].terminal_start().0 - 0.0).abs() < 1e-12);
        assert!((coils[1].terminal_start().0 - sp).abs() < 1e-12);
        assert!((coils[2].terminal_start().0 - 2.0 * sp).abs() < 1e-12);
    }

    #[test]
    fn test_segments_alternate_active_endturn() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            for (i, seg) in coil.segments.iter().enumerate() {
                if i % 2 == 0 {
                    assert!(seg.is_active, "Seg {} should be active", i);
                } else {
                    assert!(!seg.is_active, "Seg {} should be end-turn", i);
                }
            }
        }
    }

    #[test]
    fn test_large_pole_pitch_few_conductors() {
        let cfg = LinearMotorConfig {
            active_area_length_m: mm(101.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(50.0),
            phases: 1,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 4,
            ..LinearMotorConfig::default()
        };
        let coil = WaveWindingGenerator.generate(&cfg, 0)[0].clone();
        assert_eq!(coil.active_conductor_count(), 3);
        assert_eq!(coil.end_turn_segments().len(), 2);
        assert!(coil.is_continuous(1e-9));
    }

    // --- PhaseCoil properties ---

    #[test]
    fn test_polyline_length() {
        let cfg = default_config();
        let coil = &WaveWindingGenerator.generate(&cfg, 0)[0];
        assert_eq!(coil.polyline().len(), coil.segments.len() + 1);
    }

    #[test]
    fn test_empty_coil_polyline() {
        let coil = PhaseCoil::default();
        assert!(coil.polyline().is_empty());
        assert_eq!(coil.terminal_start(), (0.0, 0.0));
        assert_eq!(coil.terminal_end(), (0.0, 0.0));
    }

    #[test]
    fn test_empty_coil_bounding_box() {
        let coil = PhaseCoil::default();
        assert_eq!(coil.bounding_box(), (0.0, 0.0, 0.0, 0.0));
    }

    #[test]
    fn test_total_length_greater_than_active() {
        let cfg = default_config();
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            assert!(coil.total_length_m() > coil.active_length_m());
        }
    }

    #[test]
    fn test_active_length_is_n_times_width() {
        let cfg = default_config();
        let w = cfg.board_width_m;
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            let expected = coil.active_conductor_count() as f64 * w;
            assert!((coil.active_length_m() - expected).abs() < 1e-12);
        }
    }

    #[test]
    fn test_bounding_box_y_range() {
        let cfg = default_config();
        let w = cfg.board_width_m;
        for coil in WaveWindingGenerator.generate(&cfg, 0) {
            let bb = coil.bounding_box();
            assert!((bb.1 - 0.0).abs() < 1e-12);
            assert!((bb.3 - w).abs() < 1e-12);
        }
    }

    // --- generate_all_layers ---

    #[test]
    fn test_all_layers_count() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate_all_layers(&cfg, 6, None).unwrap();
        assert_eq!(coils.len(), 6);
    }

    #[test]
    fn test_all_layers_sorted() {
        let cfg = default_config();
        let coils = WaveWindingGenerator.generate_all_layers(&cfg, 6, None).unwrap();
        for i in 0..coils.len() - 1 {
            assert!((coils[i].layer_idx, coils[i].phase_idx) <= (coils[i+1].layer_idx, coils[i+1].phase_idx));
        }
    }

    #[test]
    fn test_odd_layer_count_raises() {
        let cfg = default_config();
        assert!(WaveWindingGenerator.generate_all_layers(&cfg, 5, None).is_err());
    }

    #[test]
    fn test_fewer_layers_than_phases_raises() {
        let cfg = default_config();
        assert!(WaveWindingGenerator.generate_all_layers(&cfg, 2, None).is_err());
    }

    // --- default_phase_layer_map ---

    #[test]
    fn test_phase_layer_map_6_3() {
        let m = WaveWindingGenerator::default_phase_layer_map(3, 6);
        assert_eq!(m[0], vec![0, 3]);
        assert_eq!(m[1], vec![1, 4]);
        assert_eq!(m[2], vec![2, 5]);
    }

    #[test]
    fn test_phase_layer_map_4_2() {
        let m = WaveWindingGenerator::default_phase_layer_map(2, 4);
        assert_eq!(m[0], vec![0, 2]);
        assert_eq!(m[1], vec![1, 3]);
    }

    #[test]
    fn test_phase_layer_map_all_layers_covered() {
        let m = WaveWindingGenerator::default_phase_layer_map(3, 6);
        let mut all: Vec<u32> = m.iter().flatten().cloned().collect();
        all.sort();
        assert_eq!(all, vec![0, 1, 2, 3, 4, 5]);
    }

    // --- SineWaveWindingGenerator ---

    #[test]
    fn test_sine_wave_returns_one_per_phase() {
        let cfg = default_config();
        let coils = SineWaveWindingGenerator.generate(&cfg, 0);
        assert_eq!(coils.len(), cfg.phases as usize);
    }

    #[test]
    fn test_sine_wave_tagged() {
        let cfg = default_config();
        let coils = SineWaveWindingGenerator.generate(&cfg, 0);
        for coil in &coils {
            assert_eq!(coil.topology, CoilTopology::SineWave);
        }
    }

    #[test]
    fn test_sine_wave_has_segments() {
        let cfg = default_config();
        let coils = SineWaveWindingGenerator.generate(&cfg, 0);
        for coil in &coils {
            assert!(!coil.segments.is_empty());
        }
    }

    #[test]
    fn test_sine_wave_phase_offsets() {
        let cfg = default_config();
        let sp = cfg.slot_pitch_m();
        let coils = SineWaveWindingGenerator.generate(&cfg, 0);
        assert!((coils[1].segments[0].start.0 - sp).abs() < 1e-9);
    }

    // --- Inter-layer via generator (ADR-0001) ---

    fn multi_layer_config() -> LinearMotorConfig {
        // phases=2, max_layers=4 → each phase spans 2 layers (multi-layer).
        LinearMotorConfig {
            name: Some("multi".into()),
            active_area_length_m: mm(48.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(24.0),
            phases: 2,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 4,
            ..LinearMotorConfig::default()
        }
    }

    fn single_layer_config() -> LinearMotorConfig {
        // phases=3, max_layers=3 → each phase on a single layer.
        LinearMotorConfig {
            name: Some("single".into()),
            active_area_length_m: mm(48.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(24.0),
            phases: 3,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 3,
            ..LinearMotorConfig::default()
        }
    }

    #[test]
    fn test_phase_layer_count_single_layer_per_phase() {
        let cfg = single_layer_config();
        assert_eq!(phase_layer_count(&cfg, 0), 1);
        assert_eq!(phase_layer_count(&cfg, 1), 1);
        assert_eq!(phase_layer_count(&cfg, 2), 1);
        assert!(!is_phase_multi_layer(&cfg, 0));
    }

    #[test]
    fn test_phase_layer_count_multi_layer_per_phase() {
        let cfg = multi_layer_config();
        // phases=2, max_layers=4 → default map: phase 0 → [0, 2], phase 1 → [1, 3]
        assert_eq!(phase_layer_count(&cfg, 0), 2);
        assert_eq!(phase_layer_count(&cfg, 1), 2);
        assert!(is_phase_multi_layer(&cfg, 0));
        assert!(is_phase_multi_layer(&cfg, 1));
    }

    #[test]
    fn test_phase_layer_count_uneven_4_3() {
        // phases=3, max_layers=4 → phase 0 → [0, 3], phase 1 → [1], phase 2 → [2]
        let mut cfg = multi_layer_config();
        cfg.phases = 3;
        cfg.max_layers = 4;
        assert_eq!(phase_layer_count(&cfg, 0), 2);
        assert_eq!(phase_layer_count(&cfg, 1), 1);
        assert_eq!(phase_layer_count(&cfg, 2), 1);
        assert!(is_phase_multi_layer(&cfg, 0));
        assert!(!is_phase_multi_layer(&cfg, 1));
        assert!(!is_phase_multi_layer(&cfg, 2));
    }

    #[test]
    fn test_serpentine_via_positions_multi_layer() {
        let cfg = multi_layer_config();
        let coil = WaveWindingGenerator.generate_phase(&cfg, 0, 0);
        assert!(!coil.center_via_positions.is_empty(),
            "multi-layer serpentine should emit vias");
        // One via per end-turn (N conductors → N-1 end-turns → N-1 vias).
        assert_eq!(coil.center_via_positions.len(),
            coil.end_turn_segments().len());
        // All vias must be on an edge (y=0 or y=board_width).
        for &(x, y) in &coil.center_via_positions {
            assert!((y - 0.0).abs() < 1e-9 || (y - cfg.board_width_m).abs() < 1e-9,
                "via y={y} not on board edge");
            assert!(x >= 0.0, "via x={x} not in board");
        }
    }

    #[test]
    fn test_serpentine_via_positions_single_layer() {
        let cfg = single_layer_config();
        let coil = WaveWindingGenerator.generate_phase(&cfg, 0, 0);
        assert!(coil.center_via_positions.is_empty(),
            "single-layer serpentine should emit no vias");
    }

    #[test]
    fn test_sine_wave_via_positions_multi_layer() {
        let cfg = multi_layer_config();
        let coil = SineWaveWindingGenerator.generate_phase(&cfg, 0, 0);
        assert_eq!(coil.center_via_positions.len(), 2,
            "multi-layer sine wave should emit exactly 2 vias (start + end)");
        let start = coil.terminal_start();
        let end = coil.terminal_end();
        assert!(coil.center_via_positions.contains(&start));
        assert!(coil.center_via_positions.contains(&end));
    }

    #[test]
    fn test_sine_wave_via_positions_single_layer() {
        let cfg = single_layer_config();
        let coil = SineWaveWindingGenerator.generate_phase(&cfg, 0, 0);
        assert!(coil.center_via_positions.is_empty(),
            "single-layer sine wave should emit no vias");
    }

    #[test]
    fn test_validate_via_clearance_passes_for_default() {
        // default_config: phases=3, pole_pitch=12mm → slot_pitch=4mm.
        // 0.3 + 2*0.15 = 0.6mm << 4mm. Should pass.
        let cfg = default_config();
        assert!(validate_via_clearance(&cfg, 16).is_ok());
    }

    #[test]
    fn test_validate_via_clearance_fails_for_tight_pitch() {
        // Construct a config with slot_pitch = 0.5mm (tighter than 0.6mm).
        let cfg = LinearMotorConfig {
            name: Some("tight".into()),
            active_area_length_m: mm(48.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(1.5),  // pole_pitch = 1.5mm
            phases: 3,                 // slot_pitch = 1.5/3 = 0.5mm
            spacing_ratio: 1.0,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 4,
            ..LinearMotorConfig::default()
        };
        assert!((cfg.slot_pitch_m() - 0.0005).abs() < 1e-9,
            "test setup: slot_pitch should be 0.5mm");
        let err = validate_via_clearance(&cfg, 4);
        assert!(err.is_err());
        let msg = err.unwrap_err();
        assert!(msg.contains("via clearance guard failed"));
        assert!(msg.contains("via_count=4"));
    }
}
