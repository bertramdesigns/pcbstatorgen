//! Phase F: Cross-validation of Rust physics core against Python test vectors.
//!
//! Loads `scripts/fixtures/test_vectors.json` (the Python oracle output) and
//! asserts that the Rust port produces matching results within tolerance:
//! - Config derived values: exact
//! - B-field (Bx, By, Bz): ±1% relative or ±1e-6 T absolute
//! - Force sweep (force_x, force_y, force_z): ±2% relative or ±0.1 mN absolute
//! - Ripple percentage: ±0.5 percentage points

use serde::Deserialize;
use serde_json::Value;

use pcbstatorgen_rs::config::LinearMotorConfig;
use pcbstatorgen_rs::geometry::{CoilSegment, PhaseCoil};
use pcbstatorgen_rs::magnetic::{CommutationMode, ForceEvaluator, MagnetArray};

// ---------------------------------------------------------------------------
// Test vector JSON schema
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct TestVectors {
    config: ConfigVector,
    coils_serpentine: Vec<CoilVector>,
    bfield: BFieldVector,
    force_sweep: ForceSweepVector,
}

#[derive(Debug, Deserialize)]
struct ConfigVector {
    active_area_length_mm: f64,
    coil_span_mm: f64,
    travel_mm: f64,
    pole_pitch_mm: f64,
    slot_pitch_mm: f64,
    magnet_gap_mm: f64,
    magnet_count: u32,
    phases: u32,
    board_width_mm: f64,
    air_gap_mm: f64,
}

#[derive(Debug, Deserialize)]
struct CoilVector {
    phase_idx: u32,
    phase_name: String,
    layer_idx: u32,
    topology: String,
    active_conductor_count: u32,
    total_length_mm: f64,
    active_length_mm: f64,
    end_turn_length_mm: f64,
    bounding_box_mm: [f64; 4],
    segments: Vec<SegmentVector>,
}

#[derive(Debug, Deserialize)]
struct SegmentVector {
    start_mm: [f64; 2],
    end_mm: [f64; 2],
    is_active: bool,
}

#[derive(Debug, Deserialize)]
struct BFieldVector {
    x_mm: Vec<f64>,
    bx_t: Vec<f64>,
    by_t: Vec<f64>,
    bz_t: Vec<f64>,
}

#[derive(Debug, Deserialize)]
struct ForceSweepVector {
    positions_mm: Vec<f64>,
    force_x_mn: Vec<f64>,
    force_y_mn: Vec<f64>,
    force_z_mn: Vec<f64>,
    mean_thrust_mn: f64,
    peak_thrust_mn: f64,
    min_thrust_mn: f64,
    ripple_pct: f64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Load test vectors from the fixture file.
fn load_vectors() -> TestVectors {
    let json = std::fs::read_to_string("../../scripts/fixtures/test_vectors.json")
        .or_else(|_| std::fs::read_to_string("scripts/fixtures/test_vectors.json"))
        .expect("test_vectors.json not found — run scripts/export_test_vectors.py first");
    let value: Value = serde_json::from_str(&json).expect("invalid JSON");
    // Use serde_json to handle key case (Python uses Bx_T, Rust expects bx_t)
    let mut v = value;
    // Rename B-field keys to lowercase for serde
    if let Some(bf) = v.get_mut("bfield") {
        if let Some(obj) = bf.as_object_mut() {
            for (old, new) in &[("Bx_T", "bx_t"), ("By_T", "by_t"), ("Bz_T", "bz_t")] {
                if let Some(val) = obj.remove(*old) {
                    obj.insert(new.to_string(), val);
                }
            }
        }
    }
    serde_json::from_value(v).expect("failed to deserialize test vectors")
}

/// Build a `LinearMotorConfig` matching the Python `default_config()` from
/// `export_test_vectors.py`.
fn test_config() -> LinearMotorConfig {
    // The Python defaults match the Rust defaults (N44, Br=1.35T, etc.)
    LinearMotorConfig {
        name: Some("test-vector".to_string()),
        ..LinearMotorConfig::default()
    }
}

/// Convert `CoilVector` from the test vectors to a Rust `PhaseCoil`.
fn coil_vector_to_phase_coil(cv: &CoilVector) -> PhaseCoil {
    let segments = cv
        .segments
        .iter()
        .map(|s| {
            CoilSegment {
                start: (s.start_mm[0] * 1e-3, s.start_mm[1] * 1e-3),
                end: (s.end_mm[0] * 1e-3, s.end_mm[1] * 1e-3),
                is_active: s.is_active,
            }
        })
        .collect();
    let topology = match cv.topology.as_str() {
        "serpentine" => pcbstatorgen_rs::config::CoilTopology::Serpentine,
        "sine_wave" => pcbstatorgen_rs::config::CoilTopology::SineWave,
        "concentrated" => pcbstatorgen_rs::config::CoilTopology::Concentrated,
        "rhombic" => pcbstatorgen_rs::config::CoilTopology::Rhombic,
        "spiral" => pcbstatorgen_rs::config::CoilTopology::Spiral,
        _ => pcbstatorgen_rs::config::CoilTopology::Serpentine,
    };
    PhaseCoil {
        phase_idx: cv.phase_idx,
        layer_idx: cv.layer_idx,
        segments,
        phase_name: cv.phase_name.clone(),
        topology,
        layer_pair: None,
        center_via_positions: vec![],
    }
}

/// Relative error tolerance check: `|actual - expected| / |expected| <= tol`
/// OR absolute error check: `|actual - expected| <= abs_tol`.
fn assert_close(actual: f64, expected: f64, rel_tol: f64, abs_tol: f64, label: &str) {
    let diff = (actual - expected).abs();
    let rel_err = if expected.abs() > 1e-15 {
        diff / expected.abs()
    } else {
        f64::INFINITY
    };
    assert!(
        rel_err <= rel_tol || diff <= abs_tol,
        "{label}: actual={actual:.8e}, expected={expected:.8e}, rel_err={rel_err:.4e}, diff={diff:.8e}"
    );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn test_config_derived_values() {
    let v = load_vectors();
    let cfg = test_config();

    // Exact match for derived values
    assert!((cfg.coil_span_m() * 1e3 - v.config.coil_span_mm).abs() < 1e-6,
        "coil_span: {} vs {}", cfg.coil_span_m() * 1e3, v.config.coil_span_mm);
    assert!((cfg.travel_m() * 1e3 - v.config.travel_mm).abs() < 1e-6,
        "travel: {} vs {}", cfg.travel_m() * 1e3, v.config.travel_mm);
    assert!((cfg.pole_pitch_m() * 1e3 - v.config.pole_pitch_mm).abs() < 1e-9,
        "pole_pitch");
    assert!((cfg.magnet_gap_m() * 1e3 - v.config.magnet_gap_mm).abs() < 1e-9,
        "magnet_gap");
    assert_eq!(cfg.magnet_count, v.config.magnet_count);
    assert_eq!(cfg.phases, v.config.phases);
    assert!((cfg.board_width_m * 1e3 - v.config.board_width_mm).abs() < 1e-9,
        "board_width");
    assert!((cfg.air_gap_m * 1e3 - v.config.air_gap_mm).abs() < 1e-9,
        "air_gap");
    // slot_pitch = pole_pitch / phases × spacing_ratio (spacing_ratio=1.0)
    assert!((cfg.slot_pitch_m() * 1e3 - v.config.slot_pitch_mm).abs() < 1e-9,
        "slot_pitch: {} vs {}", cfg.slot_pitch_m() * 1e3, v.config.slot_pitch_mm);
}

#[test]
fn test_coil_geometry_serpentine() {
    let v = load_vectors();
    let coils: Vec<PhaseCoil> = v.coils_serpentine.iter().map(coil_vector_to_phase_coil).collect();

    assert_eq!(coils.len(), v.coils_serpentine.len(), "phase count mismatch");
    for (i, (coil, cv)) in coils.iter().zip(v.coils_serpentine.iter()).enumerate() {
        assert_eq!(coil.phase_idx, cv.phase_idx, "phase {i} idx");
        assert_eq!(coil.phase_name, cv.phase_name, "phase {i} name");
        assert_eq!(coil.active_conductor_count(), cv.active_conductor_count as usize,
            "phase {i} active conductor count");
        assert_eq!(coil.segments.len(), cv.segments.len(), "phase {i} segment count");

        // Lengths: ±0.1%
        let total_mm = coil.total_length_m() * 1e3;
        assert_close(total_mm, cv.total_length_mm, 0.001, 1e-3, &format!("phase {i} total_length"));

        let active_mm = coil.active_length_m() * 1e3;
        assert_close(active_mm, cv.active_length_mm, 0.001, 1e-3, &format!("phase {i} active_length"));

        let end_mm = coil.end_turn_length_m() * 1e3;
        assert_close(end_mm, cv.end_turn_length_mm, 0.001, 1e-3, &format!("phase {i} end_turn_length"));

        // Bounding box
        let bb = coil.bounding_box();
        let bb_mm = [bb.0 * 1e3, bb.1 * 1e3, bb.2 * 1e3, bb.3 * 1e3];
        for (j, (a, e)) in bb_mm.iter().zip(cv.bounding_box_mm.iter()).enumerate() {
            assert!((a - e).abs() < 1e-3, "phase {i} bbox[{j}]: {a} vs {e}");
        }
    }
}

#[test]
fn test_bfield_at_pcb_surface() {
    let v = load_vectors();
    let cfg = test_config();
    let arr = MagnetArray::new(&cfg);

    // Sample B along the board centre-line at the PCB surface
    let x_sample_m: Vec<f64> = v.bfield.x_mm.iter().map(|&x_mm| x_mm * 1e-3).collect();
    let b = arr.bfield_at_pcb_surface(&x_sample_m, 0.0, 0.0);

    assert_eq!(b.len(), v.bfield.x_mm.len(), "B-field sample count mismatch");

    for i in 0..b.len() {
        // Bx: ±1% relative or ±1e-6 T absolute
        assert_close(
            b[i][0],
            v.bfield.bx_t[i],
            0.01,
            1e-6,
            &format!("Bx at x={:.3}mm", v.bfield.x_mm[i]),
        );
        // By: ±1% relative or ±1e-6 T absolute (should be ~0 on centerline)
        assert_close(
            b[i][1],
            v.bfield.by_t[i],
            0.01,
            1e-6,
            &format!("By at x={:.3}mm", v.bfield.x_mm[i]),
        );
        // Bz: ±1% relative or ±1e-6 T absolute
        assert_close(
            b[i][2],
            v.bfield.bz_t[i],
            0.01,
            1e-6,
            &format!("Bz at x={:.3}mm", v.bfield.x_mm[i]),
        );
    }
}

#[test]
fn test_force_sweep() {
    let v = load_vectors();
    let cfg = test_config();
    let coils: Vec<PhaseCoil> = v.coils_serpentine.iter().map(coil_vector_to_phase_coil).collect();

    // Match the Python ForceEvaluator parameters:
    // n_positions=20, meshing=20, commutation="max_torque", layer_z_m=0.0
    let mut ev = ForceEvaluator::new(20, 20, CommutationMode::MaxTorque, 0.0);
    let result = ev.evaluate(&cfg, &coils);

    assert_eq!(result.n_positions(), v.force_sweep.positions_mm.len(),
        "position count mismatch");

    // Check positions
    for i in 0..result.n_positions() {
        let pos_mm = result.positions_m[i] * 1e3;
        let exp_mm = v.force_sweep.positions_mm[i];
        assert!((pos_mm - exp_mm).abs() < 1e-3,
            "position {i}: {pos_mm:.4} vs {exp_mm:.4} mm");
    }

    // Check forces: ±2% relative or ±0.1 mN absolute
    for i in 0..result.n_positions() {
        let fx_mn = result.force_x_n[i] * 1e3;
        assert_close(
            fx_mn,
            v.force_sweep.force_x_mn[i],
            0.02,
            0.1,
            &format!("force_x at pos {i} ({:.1}mm)", v.force_sweep.positions_mm[i]),
        );

        let fy_mn = result.force_y_n[i] * 1e3;
        assert_close(
            fy_mn,
            v.force_sweep.force_y_mn[i],
            0.02,
            0.1,
            &format!("force_y at pos {i}"),
        );

        let fz_mn = result.force_z_n[i] * 1e3;
        assert_close(
            fz_mn,
            v.force_sweep.force_z_mn[i],
            0.02,
            0.1,
            &format!("force_z at pos {i}"),
        );
    }

    // Check summary statistics
    assert_close(
        result.mean_thrust_n() * 1e3,
        v.force_sweep.mean_thrust_mn,
        0.02,
        0.1,
        "mean_thrust",
    );
    assert_close(
        result.peak_thrust_n() * 1e3,
        v.force_sweep.peak_thrust_mn,
        0.02,
        0.1,
        "peak_thrust",
    );
    assert_close(
        result.min_thrust_n() * 1e3,
        v.force_sweep.min_thrust_mn,
        0.02,
        0.1,
        "min_thrust",
    );
}

#[test]
fn test_ripple_percentage() {
    let v = load_vectors();
    let cfg = test_config();
    let coils: Vec<PhaseCoil> = v.coils_serpentine.iter().map(coil_vector_to_phase_coil).collect();

    let mut ev = ForceEvaluator::new(20, 20, CommutationMode::MaxTorque, 0.0);
    let result = ev.evaluate(&cfg, &coils);

    // Ripple: ±0.5 percentage points
    let ripple = result.ripple_pct();
    let expected_ripple = v.force_sweep.ripple_pct;
    let diff = (ripple - expected_ripple).abs();
    assert!(
        diff <= 0.5,
        "ripple_pct: actual={ripple:.4}, expected={expected_ripple:.4}, diff={diff:.4} (tol=0.5pp)"
    );
}

#[test]
fn test_config_serde_round_trip() {
    let cfg = test_config();
    let json = serde_json::to_string(&cfg).expect("serialize");
    let cfg2: LinearMotorConfig = serde_json::from_str(&json).expect("deserialize");
    assert_eq!(cfg.active_area_length_m, cfg2.active_area_length_m);
    assert_eq!(cfg.magnet_count, cfg2.magnet_count);
    assert_eq!(cfg.magnet_arrangement, cfg2.magnet_arrangement);
    assert_eq!(cfg.phases, cfg2.phases);
    assert!((cfg.magnet_remanence_t - cfg2.magnet_remanence_t).abs() < 1e-12);
    assert!((cfg.air_gap_m - cfg2.air_gap_m).abs() < 1e-12);
    assert!((cfg.board_width_m - cfg2.board_width_m).abs() < 1e-12);
}
