//! Concentrated, Rhombic, and Spiral coil generators.
//!
//! Ports `pcbstatorgen/geometry/coil_generators.py`.
//! All produce [`PhaseCoil`] objects consumed identically by the force model.

use crate::config::{CoilTopology, LinearMotorConfig};
use crate::geometry::wave_winding::{CoilSegment, PhaseCoil, PHASE_NAMES};

/// Generator trait (Rust equivalent of Python's duck-typed generators).
pub trait CoilGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil>;
}

/// Factory: return the correct generator for a topology.
pub fn make_coil_generator(topology: CoilTopology) -> Box<dyn CoilGenerator> {
    match topology {
        CoilTopology::Serpentine => Box::new(crate::geometry::wave_winding::WaveWindingGenerator),
        CoilTopology::SineWave => Box::new(crate::geometry::wave_winding::SineWaveWindingGenerator),
        CoilTopology::Concentrated => Box::new(ConcentratedCoilGenerator::default()),
        CoilTopology::Rhombic => Box::new(RhombicCoilGenerator::default()),
        CoilTopology::Spiral => Box::new(SpiralCoilGenerator::default()),
    }
}

// ---------------------------------------------------------------------------
// ConcentratedCoilGenerator
// ---------------------------------------------------------------------------

/// Generate discrete rectangular concentrated coil loops.
#[derive(Debug, Clone)]
pub struct ConcentratedCoilGenerator {
    /// Go-to-return conductor separation [m]. None = pole pitch (full-pitch).
    pub coil_pitch_m: Option<f64>,
}

impl Default for ConcentratedCoilGenerator {
    fn default() -> Self {
        Self { coil_pitch_m: None }
    }
}

impl CoilGenerator for ConcentratedCoilGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        (0..config.phases)
            .map(|p| self.generate_phase(config, p, layer_idx))
            .collect()
    }
}

impl ConcentratedCoilGenerator {
    /// Top end-turn length = coil_pitch.
    pub fn top_end_turn_length(coil_pitch_m: f64) -> f64 {
        coil_pitch_m
    }

    /// Bottom inter-coil link length = 2τ − coil_pitch.
    pub fn bottom_link_length(coil_pitch_m: f64, pole_pitch_m: f64) -> f64 {
        2.0 * pole_pitch_m - coil_pitch_m
    }

    pub fn generate_phase(
        &self,
        config: &LinearMotorConfig,
        phase_idx: u32,
        layer_idx: u32,
    ) -> PhaseCoil {
        let coil_pitch = self.coil_pitch_m.unwrap_or(config.pole_pitch_m());
        let pole_pitch = config.pole_pitch_m();
        let slot_pitch = config.slot_pitch_m();
        let board_width = config.board_width_m;
        let x_offset = phase_idx as f64 * slot_pitch;
        let x_max = config.active_area_length_m + (config.phases - 1) as f64 * slot_pitch;
        let phase_name = PHASE_NAMES[(phase_idx as usize) % PHASE_NAMES.len()].to_string();

        let mut segments: Vec<CoilSegment> = Vec::new();
        let mut x = x_offset;

        while x <= x_max + 1e-9 {
            // Go conductor — always upward
            segments.push(CoilSegment {
                start: (x, 0.0),
                end: (x, board_width),
                is_active: true,
            });

            let x_return = x + coil_pitch;
            if x_return <= x_max + 1e-9 {
                // Top end-turn
                segments.push(CoilSegment {
                    start: (x, board_width),
                    end: (x_return, board_width),
                    is_active: false,
                });
                // Return conductor — downward
                segments.push(CoilSegment {
                    start: (x_return, board_width),
                    end: (x_return, 0.0),
                    is_active: true,
                });
                // Bottom inter-coil link
                let x_next = x + 2.0 * pole_pitch;
                if x_next <= x_max + 1e-9 {
                    segments.push(CoilSegment {
                        start: (x_return, 0.0),
                        end: (x_next, 0.0),
                        is_active: false,
                    });
                }
            }
            x += 2.0 * pole_pitch;
        }

        PhaseCoil {
            phase_idx,
            layer_idx,
            segments,
            phase_name,
            topology: CoilTopology::Concentrated,
            ..PhaseCoil::default()
        }
    }
}

// ---------------------------------------------------------------------------
// RhombicCoilGenerator
// ---------------------------------------------------------------------------

/// Generate rhombic (diamond) coils with angled active conductors.
#[derive(Debug, Clone)]
pub struct RhombicCoilGenerator {
    /// Tilt of the active conductor from vertical [degrees]. Range (0, 45].
    pub angle_deg: f64,
}

impl Default for RhombicCoilGenerator {
    fn default() -> Self {
        Self { angle_deg: 30.0 }
    }
}

impl RhombicCoilGenerator {
    /// Force multiplier relative to Concentrated = cos(angle_deg).
    pub fn force_factor(&self) -> f64 {
        self.angle_deg.to_radians().cos()
    }

    /// Conductor length multiplier = 1 / cos(angle_deg).
    pub fn conductor_length_factor(&self) -> f64 {
        1.0 / self.angle_deg.to_radians().cos()
    }
}

impl CoilGenerator for RhombicCoilGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        (0..config.phases)
            .map(|p| self.generate_phase(config, p, layer_idx))
            .collect()
    }
}

impl RhombicCoilGenerator {
    pub fn generate_phase(
        &self,
        config: &LinearMotorConfig,
        phase_idx: u32,
        layer_idx: u32,
    ) -> PhaseCoil {
        let pole_pitch = config.pole_pitch_m();
        let slot_pitch = config.slot_pitch_m();
        let board_width = config.board_width_m;
        let x_offset = phase_idx as f64 * slot_pitch;
        let x_max = config.active_area_length_m + (config.phases - 1) as f64 * slot_pitch;
        let angle_rad = self.angle_deg.to_radians();
        let delta_x = board_width * angle_rad.tan();
        let phase_name = PHASE_NAMES[(phase_idx as usize) % PHASE_NAMES.len()].to_string();

        let mut segments: Vec<CoilSegment> = Vec::new();
        let mut x = x_offset;

        while x <= x_max + 1e-9 {
            // Go conductor: angled from (x, 0) to (x - Δx, W)
            segments.push(CoilSegment {
                start: (x, 0.0),
                end: (x - delta_x, board_width),
                is_active: true,
            });

            let x_top_left = x - delta_x;
            let x_top_right = x_top_left + pole_pitch;

            if x_top_right <= x_max + delta_x + 1e-9 {
                // Top end-turn
                segments.push(CoilSegment {
                    start: (x_top_left, board_width),
                    end: (x_top_right, board_width),
                    is_active: false,
                });
                // Return conductor
                segments.push(CoilSegment {
                    start: (x_top_right, board_width),
                    end: (x + pole_pitch, 0.0),
                    is_active: true,
                });
                // Bottom link
                let x_next = x + 2.0 * pole_pitch;
                if x_next <= x_max + 1e-9 {
                    segments.push(CoilSegment {
                        start: (x + pole_pitch, 0.0),
                        end: (x_next, 0.0),
                        is_active: false,
                    });
                }
            }
            x += 2.0 * pole_pitch;
        }

        PhaseCoil {
            phase_idx,
            layer_idx,
            segments,
            phase_name,
            topology: CoilTopology::Rhombic,
            ..PhaseCoil::default()
        }
    }
}

// ---------------------------------------------------------------------------
// SpiralCoilGenerator
// ---------------------------------------------------------------------------

/// Generate rectangular spiral coils requiring a layer pair.
#[derive(Debug, Clone)]
pub struct SpiralCoilGenerator {
    /// Number of spiral turns per unit. None = auto-compute.
    pub n_turns: Option<u32>,
}

impl Default for SpiralCoilGenerator {
    fn default() -> Self {
        Self { n_turns: None }
    }
}

/// Hard cap on auto-computed turns.
const MAX_AUTO_TURNS: u32 = 10;

impl SpiralCoilGenerator {
    /// Maximum spiral turns that fit in pole_pitch × board_width.
    pub fn max_turns(&self, config: &LinearMotorConfig) -> u32 {
        let pitch = config.min_trace_m + config.min_space_m;
        let half_min = config.pole_pitch_m().min(config.board_width_m) / 2.0;
        let computed = ((half_min / pitch) as i64 - 1).max(1) as u32;
        computed.min(MAX_AUTO_TURNS)
    }

    /// Generate spiral coils for all phases on a layer pair.
    /// Returns 2 × phases coils (primary + secondary per phase).
    pub fn generate_with_layer_pair(
        &self,
        config: &LinearMotorConfig,
        layer_pair: (u32, u32),
    ) -> Vec<PhaseCoil> {
        let mut coils = Vec::new();
        for p in 0..config.phases {
            let (primary, secondary) = self.generate_phase_pair(config, p, layer_pair);
            coils.push(primary);
            coils.push(secondary);
        }
        coils
    }

    fn generate_phase_pair(
        &self,
        config: &LinearMotorConfig,
        phase_idx: u32,
        layer_pair: (u32, u32),
    ) -> (PhaseCoil, PhaseCoil) {
        let n = self.n_turns.unwrap_or_else(|| self.max_turns(config));
        let pole_pitch = config.pole_pitch_m();
        let slot_pitch = config.slot_pitch_m();
        let board_width = config.board_width_m;
        let x_offset = phase_idx as f64 * slot_pitch;
        let x_max = config.active_area_length_m + (config.phases - 1) as f64 * slot_pitch;
        let pitch = config.min_trace_m + config.min_space_m;
        let phase_name = PHASE_NAMES[(phase_idx as usize) % PHASE_NAMES.len()].to_string();

        let mut primary_segments: Vec<CoilSegment> = Vec::new();
        let mut secondary_segments: Vec<CoilSegment> = Vec::new();
        let mut center_vias: Vec<(f64, f64)> = Vec::new();

        let mut x_unit = x_offset;
        let mut is_first = true;

        while x_unit <= x_max + 1e-9 {
            let cx = x_unit + pole_pitch / 2.0;
            let cy = board_width / 2.0;
            center_vias.push((cx, cy));

            let inward = Self::spiral_inward(cx, cy, pole_pitch, board_width, pitch, n);
            let outward = Self::spiral_outward(cx, cy, pole_pitch, board_width, pitch, n);

            // Connect previous unit
            if !is_first && !primary_segments.is_empty() {
                let prev_exit = primary_segments[primary_segments.len() - 1].end;
                if !inward.is_empty() {
                    let entry = inward[0].start;
                    primary_segments.push(CoilSegment {
                        start: prev_exit,
                        end: entry,
                        is_active: false,
                    });
                }
            }

            primary_segments.extend(inward);
            secondary_segments.extend(outward);
            x_unit += 2.0 * pole_pitch;
            is_first = false;
        }

        let primary = PhaseCoil {
            phase_idx,
            layer_idx: layer_pair.0,
            segments: primary_segments,
            phase_name: phase_name.clone(),
            topology: CoilTopology::Spiral,
            layer_pair: Some(layer_pair),
            center_via_positions: center_vias.clone(),
            ..PhaseCoil::default()
        };
        let secondary = PhaseCoil {
            phase_idx,
            layer_idx: layer_pair.1,
            segments: secondary_segments,
            phase_name,
            topology: CoilTopology::Spiral,
            layer_pair: Some(layer_pair),
            center_via_positions: center_vias,
            ..PhaseCoil::default()
        };
        (primary, secondary)
    }

    /// Build segments for a rectangular spiral winding inward.
    fn spiral_inward(
        cx: f64,
        cy: f64,
        tau: f64,
        w: f64,
        pitch: f64,
        n_turns: u32,
    ) -> Vec<CoilSegment> {
        let mut segments: Vec<CoilSegment> = Vec::new();
        let half_tau = tau / 2.0;
        let half_w = w / 2.0;

        for k in 0..n_turns {
            let hx = half_tau - (k as f64 + 0.5) * pitch;
            let hy = half_w - (k as f64 + 0.5) * pitch;
            if hx < pitch * 0.5 || hy < pitch * 0.5 {
                break;
            }

            let x_left = cx - hx;
            let x_right = cx + hx;
            let y_bot = cy - hy;
            let y_top = cy + hy;

            // Left side UP (active)
            segments.push(CoilSegment {
                start: (x_left, y_bot),
                end: (x_left, y_top),
                is_active: true,
            });
            // Top → right (end-turn)
            segments.push(CoilSegment {
                start: (x_left, y_top),
                end: (x_right, y_top),
                is_active: false,
            });
            // Right side DOWN (active)
            segments.push(CoilSegment {
                start: (x_right, y_top),
                end: (x_right, y_bot),
                is_active: true,
            });

            // Connect to next inner turn or centre
            if k < n_turns - 1 {
                let hx_next = half_tau - (k as f64 + 1.5) * pitch;
                let hy_next = half_w - (k as f64 + 1.5) * pitch;
                if hx_next > pitch * 0.5 && hy_next > pitch * 0.5 {
                    let x_left_next = cx - hx_next;
                    let y_bot_next = cy - hy_next;
                    segments.push(CoilSegment {
                        start: (x_right, y_bot),
                        end: (x_left_next, y_bot),
                        is_active: false,
                    });
                    segments.push(CoilSegment {
                        start: (x_left_next, y_bot),
                        end: (x_left_next, y_bot_next),
                        is_active: false,
                    });
                } else {
                    segments.push(CoilSegment {
                        start: (x_right, y_bot),
                        end: (cx, y_bot),
                        is_active: false,
                    });
                    segments.push(CoilSegment {
                        start: (cx, y_bot),
                        end: (cx, cy),
                        is_active: false,
                    });
                    break;
                }
            } else {
                // Last turn — route to centre via
                segments.push(CoilSegment {
                    start: (x_right, y_bot),
                    end: (cx, y_bot),
                    is_active: false,
                });
                segments.push(CoilSegment {
                    start: (cx, y_bot),
                    end: (cx, cy),
                    is_active: false,
                });
            }
        }
        segments
    }

    /// Build segments for the outward spiral (reverse of inward).
    fn spiral_outward(
        cx: f64,
        cy: f64,
        tau: f64,
        w: f64,
        pitch: f64,
        n_turns: u32,
    ) -> Vec<CoilSegment> {
        let inward = Self::spiral_inward(cx, cy, tau, w, pitch, n_turns);
        if inward.is_empty() {
            return vec![];
        }
        inward
            .iter()
            .rev()
            .map(|seg| CoilSegment {
                start: seg.end,
                end: seg.start,
                is_active: seg.is_active,
            })
            .collect()
    }
}

impl CoilGenerator for SpiralCoilGenerator {
    fn generate(&self, config: &LinearMotorConfig, layer_idx: u32) -> Vec<PhaseCoil> {
        // For the trait interface, use (layer_idx, layer_idx+1) as the pair.
        self.generate_with_layer_pair(config, (layer_idx, layer_idx + 1))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::units::mm;

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
            min_trace_m: mm(0.127),
            min_space_m: mm(0.127),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 12,
            ..LinearMotorConfig::default()
        }
    }

    fn small_config() -> LinearMotorConfig {
        LinearMotorConfig {
            active_area_length_m: mm(72.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 4,
            magnet_pitch_m: mm(12.0),
            phases: 3,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mm(0.15),
            min_space_m: mm(0.15),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: 6,
            ..LinearMotorConfig::default()
        }
    }

    // --- Factory ---

    #[test]
    fn test_factory_serpentine() {
        let gen = make_coil_generator(CoilTopology::Serpentine);
        let cfg = default_config();
        let coils = gen.generate(&cfg, 0);
        assert_eq!(coils.len(), cfg.phases as usize);
    }

    #[test]
    fn test_factory_all_topologies() {
        let cfg = small_config();
        for topo in [
            CoilTopology::Serpentine,
            CoilTopology::SineWave,
            CoilTopology::Concentrated,
            CoilTopology::Rhombic,
            CoilTopology::Spiral,
        ] {
            let gen = make_coil_generator(topo);
            let coils = gen.generate(&cfg, 0);
            assert!(!coils.is_empty(), "{:?} produced no coils", topo);
        }
    }

    // --- Concentrated ---

    #[test]
    fn test_concentrated_returns_one_per_phase() {
        let cfg = default_config();
        let coils = ConcentratedCoilGenerator::default().generate(&cfg, 0);
        assert_eq!(coils.len(), cfg.phases as usize);
    }

    #[test]
    fn test_concentrated_tagged() {
        let cfg = default_config();
        for coil in ConcentratedCoilGenerator::default().generate(&cfg, 0) {
            assert_eq!(coil.topology, CoilTopology::Concentrated);
        }
    }

    #[test]
    fn test_concentrated_continuous() {
        let cfg = default_config();
        for coil in ConcentratedCoilGenerator::default().generate(&cfg, 0) {
            assert!(coil.is_continuous(1e-9));
        }
    }

    #[test]
    fn test_concentrated_active_vertical() {
        let cfg = default_config();
        for coil in ConcentratedCoilGenerator::default().generate(&cfg, 0) {
            for seg in coil.active_segments() {
                assert!(seg.is_vert());
            }
        }
    }

    #[test]
    fn test_concentrated_helpers() {
        assert_eq!(ConcentratedCoilGenerator::top_end_turn_length(mm(8.0)), mm(8.0));
        assert_eq!(
            ConcentratedCoilGenerator::bottom_link_length(mm(8.0), mm(12.0)),
            mm(16.0)
        );
    }

    // --- Rhombic ---

    #[test]
    fn test_rhombic_default_angle() {
        assert_eq!(RhombicCoilGenerator::default().angle_deg, 30.0);
    }

    #[test]
    fn test_rhombic_force_factor_30deg() {
        let gen = RhombicCoilGenerator { angle_deg: 30.0 };
        assert!((gen.force_factor() - 30.0_f64.to_radians().cos()).abs() < 1e-6);
    }

    #[test]
    fn test_rhombic_returns_one_per_phase() {
        let cfg = default_config();
        let coils = RhombicCoilGenerator::default().generate(&cfg, 0);
        assert_eq!(coils.len(), cfg.phases as usize);
    }

    #[test]
    fn test_rhombic_tagged() {
        let cfg = default_config();
        for coil in RhombicCoilGenerator::default().generate(&cfg, 0) {
            assert_eq!(coil.topology, CoilTopology::Rhombic);
        }
    }

    #[test]
    fn test_rhombic_active_has_x_displacement() {
        let cfg = default_config();
        for coil in RhombicCoilGenerator::default().generate(&cfg, 0) {
            for seg in coil.active_segments() {
                let dx = (seg.end.0 - seg.start.0).abs();
                assert!(dx > 1e-6, "Active seg has no X displacement");
            }
        }
    }

    #[test]
    fn test_rhombic_continuous() {
        let cfg = default_config();
        for coil in RhombicCoilGenerator::default().generate(&cfg, 0) {
            assert!(coil.is_continuous(1e-9));
        }
    }

    // --- Spiral ---

    #[test]
    fn test_spiral_returns_two_per_phase() {
        let cfg = small_config();
        let coils = SpiralCoilGenerator { n_turns: Some(2) }
            .generate_with_layer_pair(&cfg, (0, 1));
        assert_eq!(coils.len(), cfg.phases as usize * 2);
    }

    #[test]
    fn test_spiral_tagged() {
        let cfg = small_config();
        let coils = SpiralCoilGenerator { n_turns: Some(2) }
            .generate_with_layer_pair(&cfg, (0, 1));
        for coil in &coils {
            assert_eq!(coil.topology, CoilTopology::Spiral);
        }
    }

    #[test]
    fn test_spiral_layer_pair() {
        let cfg = small_config();
        let coils = SpiralCoilGenerator { n_turns: Some(2) }
            .generate_with_layer_pair(&cfg, (2, 3));
        for coil in &coils {
            assert_eq!(coil.layer_pair, Some((2, 3)));
        }
    }

    #[test]
    fn test_spiral_center_vias_populated() {
        let cfg = small_config();
        let coils = SpiralCoilGenerator { n_turns: Some(2) }
            .generate_with_layer_pair(&cfg, (0, 1));
        for coil in &coils {
            assert!(!coil.center_via_positions.is_empty());
        }
    }

    #[test]
    fn test_spiral_primary_has_segments() {
        let cfg = small_config();
        let coils = SpiralCoilGenerator { n_turns: Some(2) }
            .generate_with_layer_pair(&cfg, (0, 1));
        let primaries: Vec<&PhaseCoil> = coils.iter().filter(|c| c.layer_idx == 0).collect();
        assert_eq!(primaries.len(), cfg.phases as usize);
        for coil in &primaries {
            assert!(!coil.segments.is_empty());
        }
    }

    #[test]
    fn test_spiral_max_turns_bounded() {
        let cfg = default_config();
        let gen = SpiralCoilGenerator::default();
        assert!(gen.max_turns(&cfg) <= MAX_AUTO_TURNS);
        assert!(gen.max_turns(&cfg) >= 1);
    }
}
