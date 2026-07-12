//! `ForceEvaluator` — evaluates the linear thrust force and torque on the
//! PCB stator coil as a function of mover position.
//!
//! Ports `pcbstatorgen/magnetic/force_eval.py`.
//!
//! ## Physical model
//!
//! The mover carriage (magnet array) slides in the +X direction over the
//! stationary PCB stator. At each carriage position the 3-phase winding is
//! energised according to a *commutation* strategy that maximises continuous
//! thrust.
//!
//! ## Lorentz force integration
//!
//! Unlike the Python oracle (which uses `magpy.getFT`), the Rust port
//! implements the Lorentz force natively with nalgebra:
//!
//! ```text
//! F = I · Σ(dLᵢ × Bᵢ)
//! τ = Σ(rᵢ × Fᵢ)
//! ```
//!
//! where `dLᵢ` is the sub-segment direction-length vector, `Bᵢ` is the
//! magnetic field at the sub-segment midpoint, and `rᵢ` is the position
//! vector from the coil origin to the sub-segment midpoint.
//!
//! ## Newton's Third Law (PRODUCT_GOALS.md §4.C)
//!
//! `magpy.getFT` computes the force on the *stationary coils* (`F_stator`).
//! The force acting on the mover is equal and opposite: `F_mover = -F_stator`.
//! All returned forces are mover forces.
//!
//! ## Self-calibration guard (PRODUCT_GOALS.md §4.C)
//!
//! At startup, the evaluator executes a single test step of `+0.1·τ_p`
//! forward. If the resulting `F_mover.x` is negative, the phase currents
//! are inverted (180° phase shift) to align the FOC electrical angle with
//! positive mechanical motion.

use nalgebra::Vector3;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};

use crate::config::LinearMotorConfig;
use crate::geometry::PhaseCoil;
use crate::magnetic::coil_model::{CoilCurrentModel, ConductorSample};
use crate::magnetic::magnet_model::MagnetArray;
use crate::physics;

/// Commutation strategy for phase current selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommutationMode {
    /// Sinusoidal FOC: `I_A = I_pk·sin(θ_e)`, `I_B = sin(θ_e - 2π/3)`, etc.
    MaxTorque,
    /// Only Phase A energised at full peak current; B and C zero.
    PhaseAOnly,
}

impl Default for CommutationMode {
    fn default() -> Self {
        Self::MaxTorque
    }
}

/// Force sweep results across the mover travel range.
///
/// All force values are **mover** forces (Newton's Third Law corrected).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForceResult {
    /// Mover positions at which force was evaluated [m].
    pub positions_m: Vec<f64>,
    /// Total X (thrust) force at each position [N].
    pub force_x_n: Vec<f64>,
    /// Total Y (lateral) force at each position [N].
    pub force_y_n: Vec<f64>,
    /// Total Z (normal, pull-out) force at each position [N].
    pub force_z_n: Vec<f64>,
    /// Per-phase X thrust [N] — flat vec of `n_positions × n_phases`.
    pub per_phase_force_x: Vec<f64>,
    /// Number of phases.
    pub n_phases: usize,
    /// The commutation mode used for this result.
    pub commutation: CommutationMode,
    /// Applied peak current [A].
    pub current_a: f64,
}

impl ForceResult {
    /// Mean X thrust force over the sweep [N].
    pub fn mean_thrust_n(&self) -> f64 {
        if self.force_x_n.is_empty() {
            return 0.0;
        }
        self.force_x_n.iter().sum::<f64>() / self.force_x_n.len() as f64
    }

    /// Peak X thrust force [N].
    pub fn peak_thrust_n(&self) -> f64 {
        self.force_x_n.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
    }

    /// Minimum X thrust force [N].
    pub fn min_thrust_n(&self) -> f64 {
        self.force_x_n.iter().cloned().fold(f64::INFINITY, f64::min)
    }

    /// Peak-to-peak force ripple as a percentage of mean thrust.
    ///
    /// `Ripple % = (F_max - F_min) / |F_mean| × 100`
    pub fn ripple_pct(&self) -> f64 {
        let mean = self.mean_thrust_n();
        if mean.abs() < 1e-12 {
            return 0.0;
        }
        (self.peak_thrust_n() - self.min_thrust_n()) / mean.abs() * 100.0
    }

    /// Number of sweep positions.
    pub fn n_positions(&self) -> usize {
        self.positions_m.len()
    }
}

/// Evaluate thrust force across the mover travel range.
///
/// See module-level docs for the physics model and sign conventions.
pub struct ForceEvaluator {
    /// Number of uniformly-spaced mover positions to evaluate.
    pub n_positions: usize,
    /// Sub-segment meshing density for force integration.
    pub meshing: usize,
    /// Commutation mode.
    pub commutation: CommutationMode,
    /// Z depth of the conductor plane [m]. 0 = PCB top surface.
    pub layer_z_m: f64,
    /// Dynamic phase shift set by the self-calibration guard [rad].
    /// 0.0 or π (180°).
    phase_shift: f64,
    /// Whether self-calibration has been performed.
    calibrated: bool,
}

impl Default for ForceEvaluator {
    fn default() -> Self {
        Self {
            n_positions: 50,
            meshing: 20,
            commutation: CommutationMode::MaxTorque,
            layer_z_m: 0.0,
            phase_shift: 0.0,
            calibrated: false,
        }
    }
}

impl ForceEvaluator {
    /// Create a new `ForceEvaluator`.
    ///
    /// # Panics
    /// Panics if `n_positions < 2` or `meshing < 1`.
    pub fn new(
        n_positions: usize,
        meshing: usize,
        commutation: CommutationMode,
        layer_z_m: f64,
    ) -> Self {
        assert!(n_positions >= 2, "n_positions must be >= 2, got {n_positions}");
        assert!(meshing >= 1, "meshing must be >= 1, got {meshing}");
        Self {
            n_positions,
            meshing,
            commutation,
            layer_z_m,
            phase_shift: 0.0,
            calibrated: false,
        }
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /// Sweep mover position from 0 to `config.travel_m` and compute force.
    ///
    /// All returned forces are **mover** forces (Newton's Third Law corrected).
    pub fn evaluate(
        &mut self,
        config: &LinearMotorConfig,
        coils: &[PhaseCoil],
    ) -> ForceResult {
        // Self-calibration guard (PRODUCT_GOALS.md §4.C):
        // Test step at +0.1τ_p; if F_mover < 0, invert phase currents.
        if !self.calibrated {
            self.self_calibrate(config, coils);
        }

        let positions = linspace(0.0, config.travel_m(), self.n_positions);
        let n_phases = coils.len();
        let magnet_array = MagnetArray::new(config);

        // Build all conductor samples once (geometry doesn't change with position)
        let coil_model = CoilCurrentModel::new(self.meshing, false, self.layer_z_m);
        let phase_geom: Vec<(usize, Vec<ConductorSample>)> = coils
            .iter()
            .enumerate()
            .map(|(i, coil)| (i, coil_model.build_phase_samples(coil)))
            .collect();

        // Parallel sweep over positions
        let results: Vec<(f64, f64, f64, f64, Vec<f64>)> = positions
            .par_iter()
            .map(|&pos| {
                let currents = commutation_currents(
                    self.commutation,
                    self.phase_shift,
                    config,
                    pos,
                    n_phases,
                );
                let assembly = magnet_array.build_assembly(pos);

                // Collect all observation points (sub-segment midpoints)
                let mut all_points = Vec::new();
                let mut phase_ranges = Vec::new(); // (start, end) into all_points
                for (_, samples) in &phase_geom {
                    let start = all_points.len();
                    for s in samples {
                        all_points.push(nalgebra::Point3::new(
                            s.midpoint_3d[0],
                            s.midpoint_3d[1],
                            s.midpoint_3d[2],
                        ));
                    }
                    phase_ranges.push((start, all_points.len()));
                }

                // Sample B at all points in parallel (point-parallel rayon)
                let b_fields = physics::compute_b_batch_parallel(&assembly, &all_points);

                // Compute Lorentz force per phase
                let mut force = Vector3::zeros();
                let mut per_phase_x = vec![0.0f64; n_phases];

                for (phase_i, ((_, samples), &(start, _end))) in phase_geom
                    .iter()
                    .zip(phase_ranges.iter())
                    .enumerate()
                {
                    let i_current = currents[phase_i];
                    let mut phase_force = Vector3::zeros();
                    for (j, sample) in samples.iter().enumerate() {
                        let b = &b_fields[start + j];
                        let dl = Vector3::new(
                            sample.dl_3d[0],
                            sample.dl_3d[1],
                            sample.dl_3d[2],
                        );
                        // F_segment = I * (dL × B)
                        phase_force += dl.cross(b) * i_current;
                    }
                    per_phase_x[phase_i] = phase_force.x;
                    force += phase_force;
                }

                // Newton's Third Law: F_mover = -F_stator
                let fx = -force.x;
                let fy = -force.y;
                let fz = -force.z;
                let per_phase_mover_x: Vec<f64> = per_phase_x.iter().map(|&px| -px).collect();

                (fx, fy, fz, pos, per_phase_mover_x)
            })
            .collect();

        let mut force_x = Vec::with_capacity(results.len());
        let mut force_y = Vec::with_capacity(results.len());
        let mut force_z = Vec::with_capacity(results.len());
        let mut positions_out = Vec::with_capacity(results.len());
        let mut per_phase_flat = Vec::with_capacity(results.len() * n_phases);

        for (fx, fy, fz, pos, ppx) in results {
            force_x.push(fx);
            force_y.push(fy);
            force_z.push(fz);
            positions_out.push(pos);
            per_phase_flat.extend(ppx);
        }

        ForceResult {
            positions_m: positions_out,
            force_x_n: force_x,
            force_y_n: force_y,
            force_z_n: force_z,
            per_phase_force_x: per_phase_flat,
            n_phases,
            commutation: self.commutation,
            current_a: config.max_current_a,
        }
    }

    /// Compute force and torque at a single mover position.
    ///
    /// Returns `(F_total, T_total)` — total mover force [N] and torque [N·m],
    /// each `[f64; 3]`.
    pub fn evaluate_at(
        &mut self,
        config: &LinearMotorConfig,
        coils: &[PhaseCoil],
        mover_position_m: f64,
    ) -> ([f64; 3], [f64; 3]) {
        if !self.calibrated {
            self.self_calibrate(config, coils);
        }

        let (f, t) = self.evaluate_force_raw(config, coils, mover_position_m);
        (f, t)
    }

    // ------------------------------------------------------------------
    // Self-calibration guard (PRODUCT_GOALS.md §4.C)
    // ------------------------------------------------------------------

    /// Newton's Third Law calibration guard.
    ///
    /// Evaluates a single test step at `+0.1·τ_p` forward. If the resulting
    /// mover force is negative, inverts phase currents (180° shift).
    fn self_calibrate(&mut self, config: &LinearMotorConfig, coils: &[PhaseCoil]) {
        let test_pos = 0.1 * config.pole_pitch_m();
        self.phase_shift = 0.0;

        let (f_mover, _) = self.evaluate_force_raw(config, coils, test_pos);

        if f_mover[0] < 0.0 {
            self.phase_shift = std::f64::consts::PI;
        } else {
            self.phase_shift = 0.0;
        }
        self.calibrated = true;
    }

    /// Raw force computation (no calibration check) for internal use.
    /// Returns (F_mover, T_mover) as [f64;3] each.
    fn evaluate_force_raw(
        &self,
        config: &LinearMotorConfig,
        coils: &[PhaseCoil],
        mover_position_m: f64,
    ) -> ([f64; 3], [f64; 3]) {
        let n_phases = coils.len();
        let currents = commutation_currents(
            self.commutation,
            self.phase_shift,
            config,
            mover_position_m,
            n_phases,
        );
        let magnet_array = MagnetArray::new(config);
        let coil_model = CoilCurrentModel::new(self.meshing, false, self.layer_z_m);
        let assembly = magnet_array.build_assembly(mover_position_m);

        let mut force = Vector3::zeros();
        let mut torque = Vector3::zeros();

        for (phase_i, coil) in coils.iter().enumerate() {
            let samples = coil_model.build_phase_samples(coil);
            let i_current = currents[phase_i];

            let points: Vec<nalgebra::Point3<f64>> = samples
                .iter()
                .map(|s| nalgebra::Point3::new(s.midpoint_3d[0], s.midpoint_3d[1], s.midpoint_3d[2]))
                .collect();
            let b_fields = physics::compute_b_batch_parallel(&assembly, &points);

            for (j, sample) in samples.iter().enumerate() {
                let b = &b_fields[j];
                let dl = Vector3::new(sample.dl_3d[0], sample.dl_3d[1], sample.dl_3d[2]);
                let r = Vector3::new(sample.midpoint_3d[0], sample.midpoint_3d[1], sample.midpoint_3d[2]);
                // F_segment = I * (dL × B)
                let f_seg = dl.cross(b) * i_current;
                // τ_segment = r × F_segment
                torque += r.cross(&f_seg);
                force += f_seg;
            }
        }

        // Newton's Third Law: F_mover = -F_stator, T_mover = -T_stator
        ([-force.x, -force.y, -force.z], [-torque.x, -torque.y, -torque.z])
    }

    /// Electrical angle in radians for a given mover position.
    ///
    /// One full electrical cycle completes over two pole pitches.
    pub fn electrical_angle(config: &LinearMotorConfig, mover_position_m: f64) -> f64 {
        2.0 * std::f64::consts::PI * mover_position_m / (2.0 * config.pole_pitch_m())
    }
}

/// Return the signed phase currents [A] for the given mover position.
///
/// Free function so it can be called from parallel closures without borrowing
/// `self` (which would require `&self` to be `Sync` — it is, but extracting
/// the logic avoids the borrow entirely).
fn commutation_currents(
    commutation: CommutationMode,
    phase_shift: f64,
    config: &LinearMotorConfig,
    mover_position_m: f64,
    n_phases: usize,
) -> Vec<f64> {
    let i_pk = config.max_current_a;

    if commutation == CommutationMode::PhaseAOnly {
        let mut currents = vec![0.0; n_phases];
        currents[0] = i_pk;
        return currents;
    }

    // MaxTorque: sinusoidal FOC
    // θ_e = 2π · p / (2τ) + phase_shift
    let theta_e =
        2.0 * std::f64::consts::PI * mover_position_m / (2.0 * config.pole_pitch_m())
            + phase_shift;
    let phase_offset = 2.0 * std::f64::consts::PI / n_phases as f64;

    (0..n_phases)
        .map(|p| i_pk * (theta_e - p as f64 * phase_offset).sin())
        .collect()
}

/// Linear space from `start` to `end` with `n` points (inclusive both ends).
fn linspace(start: f64, end: f64, n: usize) -> Vec<f64> {
    if n == 1 {
        return vec![start];
    }
    let step = (end - start) / (n as f64 - 1.0);
    (0..n).map(|i| start + i as f64 * step).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::MagnetArrangement;
    use crate::geometry::{CoilSegment, PhaseCoil};

    fn make_test_coil(phase_idx: u32, phase_name: &str, x_offset: f64) -> PhaseCoil {
        let segments = vec![
            CoilSegment { start: (x_offset, 0.0), end: (x_offset, 0.020), is_active: true },
            CoilSegment { start: (x_offset, 0.020), end: (x_offset + 0.012, 0.020), is_active: false },
            CoilSegment { start: (x_offset + 0.012, 0.020), end: (x_offset + 0.012, 0.0), is_active: true },
        ];
        PhaseCoil {
            phase_idx,
            layer_idx: 0,
            segments,
            phase_name: phase_name.to_string(),
            topology: crate::config::CoilTopology::Serpentine,
            layer_pair: None,
            center_via_positions: vec![],
        }
    }

    #[test]
    fn test_evaluate_basic() {
        let cfg = LinearMotorConfig::default();
        let coils = vec![
            make_test_coil(0, "A", 0.0),
            make_test_coil(1, "B", 0.004),
            make_test_coil(2, "C", 0.008),
        ];
        let mut ev = ForceEvaluator::new(5, 5, CommutationMode::MaxTorque, 0.0);
        let result = ev.evaluate(&cfg, &coils);
        assert_eq!(result.n_positions(), 5);
        assert_eq!(result.force_x_n.len(), 5);
        assert_eq!(result.n_phases, 3);
        for f in &result.force_x_n {
            assert!(f.is_finite(), "force_x not finite: {f}");
        }
    }

    #[test]
    fn test_ripple_pct() {
        let result = ForceResult {
            positions_m: vec![0.0, 0.01, 0.02],
            force_x_n: vec![10.0, 12.0, 8.0],
            force_y_n: vec![0.0, 0.0, 0.0],
            force_z_n: vec![0.0, 0.0, 0.0],
            per_phase_force_x: vec![0.0; 3],
            n_phases: 1,
            commutation: CommutationMode::MaxTorque,
            current_a: 1.0,
        };
        // mean = 10, max = 12, min = 8, ripple = (12-8)/10 * 100 = 40%
        assert!((result.ripple_pct() - 40.0).abs() < 1e-9);
        assert!((result.mean_thrust_n() - 10.0).abs() < 1e-9);
    }

    #[test]
    fn test_ripple_zero_mean() {
        let result = ForceResult {
            positions_m: vec![0.0],
            force_x_n: vec![0.0],
            force_y_n: vec![0.0],
            force_z_n: vec![0.0],
            per_phase_force_x: vec![],
            n_phases: 0,
            commutation: CommutationMode::MaxTorque,
            current_a: 1.0,
        };
        assert!(result.ripple_pct() == 0.0);
    }

    #[test]
    fn test_linspace() {
        let xs = linspace(0.0, 1.0, 5);
        assert_eq!(xs, vec![0.0, 0.25, 0.5, 0.75, 1.0]);
    }

    #[test]
    fn test_electrical_angle() {
        let cfg = LinearMotorConfig::default();
        // At p=0, θ_e=0; at p=2τ=0.024, θ_e=2π
        assert!((ForceEvaluator::electrical_angle(&cfg, 0.0)).abs() < 1e-9);
        let angle_at_2tau = ForceEvaluator::electrical_angle(&cfg, 0.024);
        assert!((angle_at_2tau - 2.0 * std::f64::consts::PI).abs() < 1e-9);
    }

    #[test]
    fn test_self_calibration_sets_phase_shift() {
        let cfg = LinearMotorConfig::default();
        let coils = vec![
            make_test_coil(0, "A", 0.0),
            make_test_coil(1, "B", 0.004),
            make_test_coil(2, "C", 0.008),
        ];
        let mut ev = ForceEvaluator::new(5, 5, CommutationMode::MaxTorque, 0.0);
        assert!(!ev.calibrated);
        ev.evaluate(&cfg, &coils);
        assert!(ev.calibrated);
        assert!(
            (ev.phase_shift - 0.0).abs() < 1e-9
                || (ev.phase_shift - std::f64::consts::PI).abs() < 1e-9
        );
    }

    #[test]
    fn test_phase_a_only_commutation() {
        let currents = commutation_currents(
            CommutationMode::PhaseAOnly,
            0.0,
            &LinearMotorConfig::default(),
            0.0,
            3,
        );
        assert!((currents[0] - 1.0).abs() < 1e-9);
        assert!((currents[1] - 0.0).abs() < 1e-9);
        assert!((currents[2] - 0.0).abs() < 1e-9);
    }

    #[test]
    fn test_max_torque_commutation_at_zero() {
        // At p=0 with phase_shift=0: θ_e=0
        // I_A = sin(0) = 0, I_B = sin(-2π/3) = -√3/2, I_C = sin(-4π/3) = √3/2
        let currents = commutation_currents(
            CommutationMode::MaxTorque,
            0.0,
            &LinearMotorConfig::default(),
            0.0,
            3,
        );
        assert!(currents[0].abs() < 1e-9, "I_A should be ~0, got {}", currents[0]);
        assert!((currents[1] - (-3.0_f64.sqrt() / 2.0)).abs() < 1e-6, "I_B = {}", currents[1]);
        assert!((currents[2] - (3.0_f64.sqrt() / 2.0)).abs() < 1e-6, "I_C = {}", currents[2]);
        // Sum of 3-phase currents should be zero (balanced)
        let sum: f64 = currents.iter().sum();
        assert!(sum.abs() < 1e-9, "3-phase sum should be 0, got {sum}");
    }

    #[test]
    fn test_max_torque_commutation_at_quarter_pitch() {
        // At p=τ/2=0.006 with phase_shift=0: θ_e=π/2, sin(π/2)=1
        // I_A = 1.0, I_B = sin(π/2 - 2π/3) = sin(-π/6) = -0.5
        // I_C = sin(π/2 + 2π/3) = sin(7π/6) = -0.5
        let currents = commutation_currents(
            CommutationMode::MaxTorque,
            0.0,
            &LinearMotorConfig::default(),
            0.006,
            3,
        );
        assert!((currents[0] - 1.0).abs() < 1e-6, "I_A = {}, expected 1.0", currents[0]);
        assert!((currents[1] - (-0.5)).abs() < 1e-6, "I_B = {}, expected -0.5", currents[1]);
        assert!((currents[2] - (-0.5)).abs() < 1e-6, "I_C = {}, expected -0.5", currents[2]);
    }
}
