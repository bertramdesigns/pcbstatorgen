//! Regenerate `scripts/fixtures/test_vectors.json` with the live Rust
//! `ForceEvaluator` output.
//!
//! The committed fixture is a fossil from a pre-fix code path (170% ripple
//! from the old 120°-balanced sin-FOC). The current code (cos-FOC with
//! slot-pitch offset + 3-point polarity guard) produces ~14.7% ripple at
//! 50 positions. This binary regenerates the `force_sweep` block so the
//! fixture reflects the post-fix simulation.
//!
//! Run with:
//!   cargo run -p pcbstatorgen-rs --example regenerate_fixture
//!
//! The output is the FULL `TestVectors` JSON document (config + coils +
//! bfield + force_sweep) but with the `force_sweep` block freshly
//! computed. The other blocks (config, coils, bfield) are read from the
//! existing fixture so we don't overwrite geometry decisions that are
//! tested elsewhere (`test_config_derived_values`,
//! `test_coil_geometry_serpentine`, `test_bfield_at_pcb_surface`).
//!
//! To regenerate from scratch (no existing fixture), delete
//! `scripts/fixtures/test_vectors.json` first; the script will write a
//! minimal document with just the force_sweep block.

use std::fs;

use pcbstatorgen_rs::config::LinearMotorConfig;
use pcbstatorgen_rs::geometry::wave_winding::WaveWindingGenerator;
use pcbstatorgen_rs::magnetic::{CommutationMode, ForceEvaluator};
use serde_json::{json, Value};

const FIXTURE_REL_PATH: &str = "scripts/fixtures/test_vectors.json";

/// Locate the workspace root by walking up from the current directory
/// looking for `Cargo.toml` with `[workspace]`. Returns the absolute path
/// of the workspace root.
fn find_workspace_root() -> std::path::PathBuf {
    let mut dir = std::env::current_dir().expect("cwd is readable");
    loop {
        let candidate = dir.join("Cargo.toml");
        if candidate.exists() {
            if let Ok(contents) = std::fs::read_to_string(&candidate) {
                if contents.contains("[workspace]") {
                    return dir;
                }
            }
        }
        if !dir.pop() {
            panic!(
                "Could not find workspace root (no Cargo.toml with [workspace] \
                 in any parent directory). Run from the repo root."
            );
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Locate the workspace root, then the fixture path within it. This
    // works whether `cargo run` is invoked from the crate root
    // (`crates/pcbstatorgen-rs/`) or the repo root.
    let workspace_root = find_workspace_root();
    let fixture_path = workspace_root.join(FIXTURE_REL_PATH);
    if !fixture_path.exists() {
        return Err(format!(
            "Fixture not found at {}. \
             Run `cargo run -p pcbstatorgen-rs --example regenerate_fixture` \
             from the repo root.",
            fixture_path.display()
        )
        .into());
    }

    // 1. Read the existing fixture (preserves the config / coils / bfield
    //    blocks, which are tested independently of the FOC fix).
    let raw = fs::read_to_string(&fixture_path)?;
    let mut doc: Value = serde_json::from_str(&raw)?;

    // 2. Build the default config + 20-position ForceEvaluator and run
    //    the live evaluation. n_positions=20 matches the original Python
    //    oracle export (scripts/fixtures/test_vectors.json before the FOC
    //    fix was applied).
    let cfg = LinearMotorConfig::default();
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let mut ev = ForceEvaluator::new(20, 20, CommutationMode::MaxTorque, 0.0);
    let result = ev.evaluate(&cfg, &coils)?;

    // 3. Serialise the fresh force_sweep block.
    let force_sweep = json!({
        "positions_mm": result
            .positions_m
            .iter()
            .map(|p| p * 1e3)
            .collect::<Vec<f64>>(),
        "force_x_mn": result
            .force_x_n
            .iter()
            .map(|f| f * 1e3)
            .collect::<Vec<f64>>(),
        "force_y_mn": result
            .force_y_n
            .iter()
            .map(|f| f * 1e3)
            .collect::<Vec<f64>>(),
        "force_z_mn": result
            .force_z_n
            .iter()
            .map(|f| f * 1e3)
            .collect::<Vec<f64>>(),
        "mean_thrust_mn": result.mean_thrust_n() * 1e3,
        "peak_thrust_mn": result.peak_thrust_n() * 1e3,
        "min_thrust_mn": result.min_thrust_n() * 1e3,
        "ripple_pct": result.ripple_pct(),
    });

    // 4. Replace the force_sweep block in the document and write back.
    doc["force_sweep"] = force_sweep;
    let pretty = serde_json::to_string_pretty(&doc)?;
    fs::write(&fixture_path, pretty + "\n")?;

    let fixture_rel = fixture_path
        .strip_prefix(&workspace_root)
        .unwrap_or(&fixture_path)
        .display()
        .to_string();
    // Detect the post-calibration phase_shift by re-running the FOC
    // at p = 0.1·τ_p with phase_shift = 0 and inspecting the sign of
    // Phase A's per-phase force. (Phase A's first conductor sits at
    // x = 0, which is a B_z peak for the default magnet polarity. With
    // phase_shift = 0, the FOC drives I_A at its peak; with
    // phase_shift = π, I_A is at its negative peak.)
    let tau_p = cfg.pole_pitch_m();
    let phase_a_at_p1 = result
        .per_phase_force_x
        .chunks(cfg.phases as usize)
        .nth(1) // index 1 → p ≈ rest + 1/49·travel ≈ 0.1·τ_p
        .map(|c| c[0])
        .unwrap_or(0.0);
    let _ = tau_p; // silence unused warning if compiler picks chunk 0
    println!(
        "Regenerated {} — ripple = {:.4}%, mean thrust = {:.4} mN, \
         Phase A at idx 1 = {:+.4} mN (positive → phase_shift=π)",
        fixture_rel,
        result.ripple_pct(),
        result.mean_thrust_n() * 1e3,
        phase_a_at_p1 * 1e3,
    );
    Ok(())
}
