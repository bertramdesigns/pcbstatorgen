//! Tauri v2 async command handlers — the IPC bridge between the Svelte
//! frontend and the `pcbstatorgen_rs` physics core.
//!
//! ## Command inventory
//!
//! | Command                   | Status  | Notes                                    |
//! |---------------------------|---------|------------------------------------------|
//! | `compute_config_derived`  | REAL    | Uses core `LinearMotorConfig` methods.  |
//! | `get_magnet_grades`       | REAL    | Reads core `magnet_grades::MAGNET_GRADES`.|
//! | `compute_height_stack`    | PARTIAL | Trivial field assembly from config.      |
//! | `generate_coils`          | STUB    | Ported frontend mock; core geometry TBD.  |
//! | `evaluate_force_sweep`    | STUB    | Sinusoidal placeholder; core physics TBD.|
//! | `compute_stackup`          | STUB    | Per-layer trace estimate; core TBD.      |
//! | `compute_power_budget`    | STUB    | I²R estimate; core `PowerEstimator` TBD.|
//! | `compute_friction`        | STUB    | Split of `friction_n`; core TBD.         |
//! | `validate_config`         | REAL    | Delegates to core `validate()`.          |
//!
//! ## Threading
//!
//! All commands are `async fn`. Per the Tauri v2 docs, async commands
//! already run on a separate async task (not the main thread). For the
//! heavier computations (force sweep, coil generation) we additionally wrap
//! the body in `tauri::async_runtime::spawn_blocking` so the work moves to
//! the dedicated blocking thread pool — this keeps the async runtime's
//! worker threads free for IPC dispatch.
//!
//! ## Linear-only constraint
//!
//! PRODUCT_GOALS.md §7.A: radial/axial-flux mode is deferred. There is no
//! `topology` argument on these commands because the frontend sends a single
//! `LinearMotorConfigIpc` struct. If a radial variant is ever needed it will
//! be a separate command set returning `"Radial mode not yet implemented."`.

use crate::ipc::*;

// ===========================================================================
// compute_config_derived — REAL (core derived methods)
// ===========================================================================

/// Compute read-only derived geometry values (travel, coil_span, pole_pitch,
/// slot_pitch, magnet_gap, min_via_pad, acceleration/min-drive force).
///
/// This calls the **real** `pcbstatorgen_rs::config::LinearMotorConfig`
/// derived methods — not a stub. The core's math is the authoritative source.
#[tauri::command]
pub async fn compute_config_derived(
    config: LinearMotorConfigIpc,
) -> Result<ConfigDerivedIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || Ok(ConfigDerivedIpc::from_core(&core)))
        .await
        .map_err(|e| format!("config_derived worker failed: {e}"))?
}

// ===========================================================================
// validate_config — REAL (core validate())
// ===========================================================================

/// Validate the config using the core's full validation logic (mirrors
/// Python `_validate_base` + `_validate_linear`). Returns errors/warnings.
#[tauri::command]
pub async fn validate_config(
    config: LinearMotorConfigIpc,
) -> Result<ValidationResultIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || {
        let mut errors = Vec::new();
        let mut warnings = Vec::new();
        match core.validate() {
            Ok(()) => {}
            Err(e) => errors.push(e.to_string()),
        }
        // Extra UI-level warning: travel getting small.
        let travel = core.travel_m();
        if travel <= 0.0 {
            errors.push(format!(
                "Travel is zero or negative ({:.1} mm) — active_area_length must exceed coil_span",
                travel * 1e3
            ));
        } else if travel < 5e-3 {
            warnings.push(format!(
                "Travel is very small ({:.1} mm) — consider a longer active area",
                travel * 1e3
            ));
        }
        let valid = errors.is_empty();
        let derived = DerivedValuesIpc {
            coil_span_mm: core.coil_span_m() * 1e3,
            travel_mm: core.travel_m() * 1e3,
            pole_pitch_mm: core.pole_pitch_m() * 1e3,
            magnet_gap_mm: core.magnet_gap_m() * 1e3,
        };
        Ok(ValidationResultIpc {
            valid,
            errors,
            warnings,
            derived,
        })
    })
    .await
    .map_err(|e| format!("validate_config worker failed: {e}"))?
}

/// Validation result (errors/warnings + derived values in mm for display).
/// This is a bonus command not yet called by the frontend but useful for
/// pre-flight checks.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct ValidationResultIpc {
    pub valid: bool,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub derived: DerivedValuesIpc,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct DerivedValuesIpc {
    pub coil_span_mm: f64,
    pub travel_mm: f64,
    pub pole_pitch_mm: f64,
    pub magnet_gap_mm: f64,
}

// ===========================================================================
// get_magnet_grades — REAL (core static table)
// ===========================================================================

/// Return the standard NdFeB magnet grade table with remanence ranges and
/// max operating temperatures (PRODUCT_GOALS.md §3.C).
///
/// This reads the real `pcbstatorgen_rs::magnet_grades::MAGNET_GRADES` table.
#[tauri::command]
pub async fn get_magnet_grades() -> Result<Vec<MagnetGradeIpc>, String> {
    Ok(magnet_grades())
}

// ===========================================================================
// compute_height_stack — PARTIAL (trivial field assembly)
// ===========================================================================

/// Compute the vertical height stack (PCB → air gap → magnet → back-iron).
///
/// This is a straightforward assembly of config values plus a tolerance
/// budget. The core `HeightStackResult` struct exists but the full
/// `HeightStackCalculator` (with field-sensitivity analysis) is pending
/// Phase E. The `total_height_m` is computed for real via the core struct's
/// `total_height_m()` method.
#[tauri::command]
pub async fn compute_height_stack(
    config: LinearMotorConfigIpc,
) -> Result<HeightStackResultIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs HeightStackCalculator once
        //       Phase E lands. For now we assemble the stack from config fields.
        let hs = pcbstatorgen_rs::config::HeightStackResult {
            pcb_thickness_m: core.pcb_thickness_m,
            cu_protrusion_m: 35e-6 * if config.num_layers >= 6 { 2.0 } else { 1.0 },
            solder_mask_m: 20e-6,
            air_gap_m: core.air_gap_m,
            magnet_height_m: core.magnet_dims_m[2],
            back_iron_thickness_m: core.back_iron_thickness_m,
            tolerance_m: 0.1e-3,
        };
        Ok(HeightStackResultIpc {
            pcb_thickness_m: hs.pcb_thickness_m,
            cu_protrusion_m: hs.cu_protrusion_m,
            solder_mask_m: hs.solder_mask_m,
            air_gap_m: hs.air_gap_m,
            magnet_height_m: hs.magnet_height_m,
            back_iron_thickness_m: hs.back_iron_thickness_m,
            tolerance_m: hs.tolerance_m,
            total_height_m: hs.total_height_m(),
        })
    })
    .await
    .map_err(|e| format!("height_stack worker failed: {e}"))?
}

// ===========================================================================
// generate_coils — STUB (geometry generators pending Phase C restructuring)
// ===========================================================================

/// Generate coil path geometry for all phases/layers.
///
/// **STUB**: The core `geometry` module is undergoing Phase C restructuring.
/// The `WaveWindingGenerator` / `make_coil_generator` are not yet available
/// in the current module exports. This returns a plausible serpentine coil
/// path (ported from the frontend mock in `tauri.ts`) so the SVG preview is
/// fully functional.
///
/// TODO: replace with real `pcbstatorgen_rs::geometry::make_coil_generator`
///       call once Phase C restructuring is complete. The conversion path
///       (`CoilPathIpc::from_core`) is already implemented in `ipc.rs`.
#[tauri::command]
pub async fn generate_coils(config: LinearMotorConfigIpc) -> Result<CoilPathIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs geometry generator call
        //       once Phase C (WaveWindingGenerator port) restructuring completes.
        let span = cfg.magnet_count as f64 * cfg.magnet_pitch_m;
        let width = cfg.board_width_m;
        let n_conductors = std::cmp::max(2, cfg.magnet_count as usize * 2);
        let pitch_x = span / (n_conductors - 1) as f64;

        let mut segments: Vec<CoilSegmentIpc> = Vec::with_capacity(n_conductors * 2);
        for i in 0..n_conductors {
            let x = i as f64 * pitch_x;
            let (y_top, y_bot) = if i % 2 == 0 {
                (0.0, width)
            } else {
                (width, 0.0)
            };
            segments.push(CoilSegmentIpc {
                start: [x, y_top],
                end: [x, y_bot],
                is_active: true,
            });
            if i < n_conductors - 1 {
                segments.push(CoilSegmentIpc {
                    start: [x, y_bot],
                    end: [x + pitch_x, y_bot],
                    is_active: false,
                });
            }
        }

        let total_len: f64 = segments
            .iter()
            .map(|s| ((s.end[0] - s.start[0]).powi(2) + (s.end[1] - s.start[1]).powi(2)).sqrt())
            .sum();
        let active_len: f64 = segments
            .iter()
            .filter(|s| s.is_active)
            .map(|s| ((s.end[0] - s.start[0]).powi(2) + (s.end[1] - s.start[1]).powi(2)).sqrt())
            .sum();
        let end_turn_len = total_len - active_len;
        let active_count = segments.iter().filter(|s| s.is_active).count() as u32;

        let phase_names = ["A", "B", "C", "D", "E", "F"];
        let phases: Vec<PhaseCoilIpc> = (0..cfg.phases as usize)
            .map(|p| PhaseCoilIpc {
                phase_idx: p as u32,
                layer_idx: 0,
                phase_name: phase_names.get(p).unwrap_or(&"?").to_string(),
                topology: cfg.coil_topology,
                segments: segments.clone(),
                total_length_m: total_len,
                active_length_m: active_len,
                end_turn_length_m: end_turn_len,
                active_conductor_count: active_count,
                bounding_box: [0.0, 0.0, span, width],
                terminal_start: [0.0, 0.0],
                terminal_end: [span, width],
            })
            .collect();

        Ok(CoilPathIpc {
            phases,
            layer_count: cfg.num_layers,
        })
    })
    .await
    .map_err(|e| format!("generate_coils worker failed: {e}"))?
}

// ===========================================================================
// evaluate_force_sweep — STUB (sinusoidal placeholder)
// ===========================================================================

/// Evaluate force vs mover position along the travel axis.
///
/// **STUB**: The core `magnetic` module (magnet array + Lorentz force
/// evaluator) is pending Phase D. This returns a sinusoidal-ish force profile
/// (ported from the frontend mock) so the live metrics panel and ripple
/// calculation are functional. The profile shape is physically motivated:
/// - Baseline thrust ∝ Br × I × layers × magnet_count
/// - Ripple at `phases × electrical frequency` per pole pitch
/// - Normal force (z) ≈ 1.6 × thrust (typical pull-in ratio)
///
/// Per PRODUCT_GOALS §4.C: `F_mover = -F_stator` — the sign is already
/// flipped to the mover's frame. Ripple % = (F_max − F_min) / |F_mean| × 100.
#[tauri::command]
pub async fn evaluate_force_sweep(
    config: LinearMotorConfigIpc,
) -> Result<ForceSweepResultIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs ForceEvaluator once Phase D
        //       (magba adapter + MagnetArray + Lorentz force) lands.
        let n = cfg.n_positions as usize;
        let n = n.max(2);
        let travel = (cfg.active_area_length_m - cfg.magnet_count as f64 * cfg.magnet_pitch_m)
            .max(0.0);
        let positions: Vec<f64> = (0..n)
            .map(|i| travel * i as f64 / (n - 1) as f64)
            .collect();

        let br = cfg.magnet_remanence_t;
        let i_peak = cfg.max_current_a;
        let baseline = 0.4 * br * i_peak * cfg.num_layers as f64 * (cfg.magnet_count as f64 / 10.0);
        let ripple_amp = baseline * 0.08;
        let pitch = cfg.magnet_pitch_m.max(1e-6);

        let force_x: Vec<f64> = positions
            .iter()
            .map(|&x| {
                baseline
                    + ripple_amp
                        * ((x / pitch) * 2.0 * std::f64::consts::PI * cfg.phases as f64).sin()
            })
            .collect();
        let force_y: Vec<f64> = (0..n).map(|i| 0.01 * (i as f64).sin()).collect();
        let force_z: Vec<f64> = positions.iter().map(|_| baseline * 1.6).collect();
        let per_phase: Vec<Vec<f64>> = force_x
            .iter()
            .map(|&f| (0..cfg.phases as usize).map(|_| f / cfg.phases as f64).collect())
            .collect();

        let mean = force_x.iter().sum::<f64>() / n as f64;
        let peak = force_x.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let min = force_x.iter().cloned().fold(f64::INFINITY, f64::min);
        let ripple_pct = if mean.abs() < 1e-12 {
            0.0
        } else {
            (peak - min) / mean.abs() * 100.0
        };

        Ok(ForceSweepResultIpc {
            positions_m: positions,
            force_x_n: force_x,
            force_y_n: force_y,
            force_z_n: force_z,
            per_phase_force_x: per_phase,
            commutation: cfg.commutation,
            current_a: i_peak,
            mean_thrust_n: mean,
            peak_thrust_n: peak,
            min_thrust_n: min,
            ripple_pct: ripple_pct,
            n_positions: n as u32,
        })
    })
    .await
    .map_err(|e| format!("force_sweep worker failed: {e}"))?
}

// ===========================================================================
// compute_stackup — STUB (per-layer trace estimate)
// ===========================================================================

/// Compute the PCB stackup recommendation (trace widths, copper thicknesses,
/// via grid).
///
/// **STUB**: The core `LayerOptimizer` is pending Phase E. This returns a
/// plausible per-layer allocation (outer layers thinner, inner layers thicker)
/// ported from the frontend mock.
#[tauri::command]
pub async fn compute_stackup(config: LinearMotorConfigIpc) -> Result<StackupResultIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs LayerOptimizer once Phase E lands.
        let lc = cfg.num_layers as usize;
        let trace_widths: Vec<f64> = (0..lc)
            .map(|i| 0.2e-3 * (1.0 + (i as f64 - (lc as f64 - 1.0) / 2.0).abs() * 0.05))
            .collect();
        let cu_thicknesses: Vec<f64> = (0..lc)
            .map(|i| if i == 0 || i == lc - 1 { 35e-6 } else { 70e-6 })
            .collect();
        let est_force = 0.4 * cfg.magnet_remanence_t * cfg.max_current_a * cfg.num_layers as f64;
        Ok(StackupResultIpc {
            layer_count: cfg.num_layers,
            trace_widths_m: trace_widths,
            cu_thickness_m: cu_thicknesses,
            via_drill_m: cfg.min_via_drill_m,
            via_annular_ring_m: cfg.min_via_annular_ring_m,
            via_grid_rows: 2,
            via_grid_cols: 4,
            estimated_force_n: est_force,
            estimated_dc_resistance_ohm: 1.2,
            notes: vec!["Stub stackup — real LayerOptimizer pending Phase E".into()],
        })
    })
    .await
    .map_err(|e| format!("stackup worker failed: {e}"))?
}

// ===========================================================================
// compute_power_budget — STUB (I²R estimate)
// ===========================================================================

/// Estimate phase resistance, continuous/burst power, and thermal rise.
///
/// **STUB**: The core `PowerEstimator` is pending Phase E. This uses a crude
/// I²R estimate based on an approximate coil length and 1 oz copper trace.
#[tauri::command]
pub async fn compute_power_budget(
    config: LinearMotorConfigIpc,
) -> Result<PowerBudgetIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs PowerEstimator once Phase E lands.
        let coil_len = cfg.active_area_length_m * cfg.board_width_m * cfg.num_layers as f64 * 2.0;
        let rho = 1.724e-8; // Cu resistivity [Ω·m]
        let trace_area = 35e-6 * 0.2e-3; // 1 oz, 0.2 mm trace
        let r = (rho * coil_len) / trace_area;
        let cont = cfg.max_current_a.powi(2) * r * cfg.phases as f64;
        let burst = (cfg.max_current_a * 1.5).powi(2) * r * cfg.phases as f64;
        let temp_rise = cfg.max_temperature_rise_c.min(cont * 4.0);
        let efficiency = ((0.25 * 0.1) / (cfg.supply_voltage_v * cfg.max_current_a) * 100.0)
            .clamp(2.0, 15.0);
        Ok(PowerBudgetIpc {
            phase_resistance_ohm: r,
            continuous_power_w: cont,
            burst_power_w: burst,
            temperature_rise_c: temp_rise,
            capacitor_required_uf: cfg.capacitor_bank_uf,
            efficiency_pct: efficiency,
        })
    })
    .await
    .map_err(|e| format!("power_budget worker failed: {e}"))?
}

// ===========================================================================
// compute_friction — STUB (split of friction_n)
// ===========================================================================

/// Break down the total friction into bearing, cable drag, wiper, and
/// cogging components.
///
/// **STUB**: The core `FrictionEstimator` is pending Phase E. This splits the
/// config's `friction_n` into plausible proportions (ported from the frontend
/// mock). Cogging is always 0 for coreless motors (PRODUCT_GOALS §4.A).
#[tauri::command]
pub async fn compute_friction(config: LinearMotorConfigIpc) -> Result<FrictionBudgetIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // TODO: replace with real pcbstatorgen-rs FrictionEstimator once Phase E lands.
        let total = cfg.friction_n;
        Ok(FrictionBudgetIpc {
            bearing_friction_n: total * 0.5,
            cable_drag_n: total * 0.3,
            wiper_contact_n: total * 0.2,
            cogging_n: 0.0, // coreless → zero cogging (§4.A)
            total_n: total,
            minimum_drive_force_n: total * 1.3,
        })
    })
    .await
    .map_err(|e| format!("friction worker failed: {e}"))?
}
