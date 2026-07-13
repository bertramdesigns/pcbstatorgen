//! FOC (field-oriented control) spec — placeholder for the pcb-motor-expert's
//! rewrite.
//!
//! // TODO: FOC-rewrite-pcb-motor-expert
//!
//! The current FOC implementation lives in
//! `crate::magnetic::force_eval::commutation_currents` (see that file for
//! the working cos-FOC law with slot-pitch offset). The
//! `@pcb-motor-expert` agent is producing a refined spec that will:
//!
//! - account for Vernier (non-1:1) spacing ratios with a per-rational
//!   electrical-angle table;
//! - support phase-loss tolerance (run with 2 of 3 phases energised);
//! - surface a closed-form ripple bound for the given (slot_pitch,
//!   pole_pitch) pair so the UI can show a target ripple pre-write;
//! - clean up the 90° cos-vs-sin ambiguity that the self-calibration
//!   guard currently can only flip 0° ↔ 180° for.
//!
//! Until that spec lands, this module exposes the **function signatures
//! only** so the rest of the codebase can start to depend on them. Bodies
//! are `unimplemented!()` — calling them panics. The orchestrator will
//! dispatch a follow-up task that fills these in.
//!
//! Do **not** call these from production code paths yet. The current
//! `commutation_currents` in `force_eval.rs` is the live implementation.

use crate::config::LinearMotorConfig;
use crate::geometry::PhaseCoil;

/// Per-phase current target returned by [`foc_phase_currents`].
///
/// `current_a` is the signed phase current in Amperes (positive = energised
/// in the "forward" sense). `electrical_angle_rad` is the electrical angle
/// for that specific phase, useful for diagnostics and the per-phase
/// ripple-tally the spec will introduce.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FocPhaseCurrent {
    pub phase_idx: u32,
    pub current_a: f64,
    pub electrical_angle_rad: f64,
}

/// Result of a single FOC evaluation at one mover position.
#[derive(Debug, Clone, PartialEq)]
pub struct FocCurrents {
    /// One entry per phase, in phase-index order.
    pub phases: Vec<FocPhaseCurrent>,
    /// Electrical angle at the mover's reference position (phase 0
    /// location) [rad]. Range `[0, 2π)`.
    pub electrical_angle_rad: f64,
    /// Mover position [m] at which the currents were computed.
    pub mover_position_m: f64,
}

/// Compute the FOC phase currents for a given mover position.
///
/// This is the **new** FOC entry point. The legacy implementation in
/// `crate::magnetic::force_eval::commutation_currents` will be deprecated
/// once this lands.
///
/// `phase_shift_rad` is the self-calibration 180° flip set by
/// `ForceEvaluator::self_calibrate`. `config` is the live motor config
/// (for `pole_pitch_m`, `slot_pitch_m`, `max_current_a`, `phases`).
/// `coils.len()` must equal `config.phases`; an error is returned
/// otherwise so the caller can surface a config bug rather than panic.
///
/// // TODO: FOC-rewrite-pcb-motor-expert
pub fn foc_phase_currents(
    config: &LinearMotorConfig,
    coils: &[PhaseCoil],
    mover_position_m: f64,
    phase_shift_rad: f64,
) -> Result<FocCurrents, FocError> {
    if coils.len() != config.phases as usize {
        return Err(FocError::PhaseCountMismatch {
            coils: coils.len(),
            config: config.phases as usize,
        });
    }
    // TODO: FOC-rewrite-pcb-motor-expert — replace this stub with the new
    // closed-form FOC that handles Vernier ratios + phase-loss tolerance.
    let _ = (config, mover_position_m, phase_shift_rad);
    unimplemented!("FOC rewrite pending @pcb-motor-expert spec");
}

/// Compute the predicted peak-to-peak force ripple for a (config, coils)
/// pair, as a percentage of mean thrust.
///
/// The pcb-motor-expert's spec will return a closed-form ripple bound so
/// the UI can show "predicted ripple: 3.2% for 1:1 spacing, 8.7% for 4:5
/// Vernier" before the user clicks "Write to Board". Until the spec lands,
/// this is a stub.
///
/// // TODO: FOC-rewrite-pcb-motor-expert
pub fn predicted_ripple_pct(
    config: &LinearMotorConfig,
    coils: &[PhaseCoil],
) -> Result<f64, FocError> {
    if coils.len() != config.phases as usize {
        return Err(FocError::PhaseCountMismatch {
            coils: coils.len(),
            config: config.phases as usize,
        });
    }
    // TODO: FOC-rewrite-pcb-motor-expert — closed-form ripple bound.
    let _ = (config, coils);
    unimplemented!("FOC ripple prediction pending @pcb-motor-expert spec");
}

/// Errors returned by the FOC stub API.
///
/// Only `PhaseCountMismatch` is concrete; the others are placeholders for
/// the rewrite so callers can `match` on the full error set today.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FocError {
    /// `coils.len()` does not match `config.phases`.
    PhaseCountMismatch { coils: usize, config: usize },
    /// // TODO: FOC-rewrite-pcb-motor-expert — Vernier spacing is not
    /// representable as a rational ratio (placeholder for the rewrite).
    UnsupportedSpacingRatio,
    /// // TODO: FOC-rewrite-pcb-motor-expert — phase-loss mode (run with
    /// N−1 of N phases energised) is not yet supported by the stub.
    PhaseLossNotSupported,
    /// Catch-all for any other rewrite-time failure.
    Internal(String),
}

impl std::fmt::Display for FocError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FocError::PhaseCountMismatch { coils, config } => write!(
                f,
                "FOC phase count mismatch: coils has {coils} entries but config.phases is {config}"
            ),
            FocError::UnsupportedSpacingRatio => {
                write!(f, "FOC: spacing ratio is not representable as a rational")
            }
            FocError::PhaseLossNotSupported => {
                write!(f, "FOC: phase-loss tolerance not yet supported by the stub")
            }
            FocError::Internal(msg) => write!(f, "FOC internal error: {msg}"),
        }
    }
}

impl std::error::Error for FocError {}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::LinearMotorConfig;
    use crate::geometry::{CoilSegment, PhaseCoil};
    use crate::units::mm;

    fn default_config() -> LinearMotorConfig {
        LinearMotorConfig {
            name: Some("foc-stub".into()),
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
            max_layers: 4,
            ..LinearMotorConfig::default()
        }
    }

    fn make_coils(n: usize) -> Vec<PhaseCoil> {
        (0..n)
            .map(|i| PhaseCoil {
                phase_idx: i as u32,
                layer_idx: 0,
                segments: vec![CoilSegment {
                    start: (0.0, 0.0),
                    end: (0.0, 0.02),
                    is_active: true,
                }],
                phase_name: "ABCDEFGHIJKL"[i..i + 1].to_string(),
                topology: crate::config::CoilTopology::Serpentine,
                layer_pair: None,
                center_via_positions: vec![],
            })
            .collect()
    }

    #[test]
    fn test_phase_count_mismatch_returns_error() {
        let cfg = default_config();
        let coils = make_coils(2); // wrong: should be 3
        let err = foc_phase_currents(&cfg, &coils, 0.0, 0.0).unwrap_err();
        match err {
            FocError::PhaseCountMismatch { coils, config } => {
                assert_eq!(coils, 2);
                assert_eq!(config, 3);
            }
            other => panic!("expected PhaseCountMismatch, got {other:?}"),
        }
    }

    #[test]
    fn test_predicted_ripple_phase_count_mismatch_returns_error() {
        let cfg = default_config();
        let coils = make_coils(4);
        let err = predicted_ripple_pct(&cfg, &coils).unwrap_err();
        assert!(matches!(err, FocError::PhaseCountMismatch { .. }));
    }

    /// Target ripple test placeholder — enabled once the
    /// `@pcb-motor-expert` spec lands. Marked `#[ignore]` for now so the
    /// stub build does not panic.
    #[test]
    #[ignore = "FOC rewrite pending @pcb-motor-expert spec"]
    fn test_target_ripple_1_1_under_5pct() {
        // 1:1 spacing should yield < 5% ripple.
        let cfg = default_config(); // spacing_ratio = 1.0
        let coils = make_coils(cfg.phases as usize);
        let ripple = predicted_ripple_pct(&cfg, &coils).unwrap();
        assert!(
            ripple < 5.0,
            "1:1 spacing should yield < 5% ripple, got {ripple:.2}%"
        );
    }

    /// Target ripple test placeholder — Vernier (4:5) target.
    /// // TODO: FOC-rewrite-pcb-motor-expert
    #[test]
    #[ignore = "FOC rewrite pending @pcb-motor-expert spec"]
    fn test_target_ripple_4_5_vernier_under_10pct() {
        // 4:5 Vernier should yield < 10% ripple.
        let mut cfg = default_config();
        cfg.spacing_ratio = 4.0 / 5.0;
        let coils = make_coils(cfg.phases as usize);
        let ripple = predicted_ripple_pct(&cfg, &coils).unwrap();
        assert!(
            ripple < 10.0,
            "4:5 Vernier should yield < 10% ripple, got {ripple:.2}%"
        );
    }
}
