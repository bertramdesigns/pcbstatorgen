//! Tauri v2 async command handlers — the IPC bridge between the Svelte
//! frontend and the `pcbstatorgen_rs` physics core.
//!
//! ## Command inventory
//!
//! | Command                   | Status  | Notes                                    |
//! |---------------------------|---------|------------------------------------------|
//! | `compute_config_derived`  | REAL    | Uses core `LinearMotorConfig` methods.  |
//! | `get_magnet_grades`       | REAL    | Reads core `magnet_grades::MAGNET_GRADES`.|
//! | `compute_height_stack`    | REAL    | Uses core `HeightStackCalculator`.       |
//! | `generate_coils`          | REAL    | Uses core `make_coil_generator` + trait. |
//! | `evaluate_force_sweep`    | REAL    | Uses core `ForceEvaluator` (Lorentz).    |
//! | `compute_stackup`          | STUB    | No core `StackupCalculator` exists yet.  |
//! | `compute_power_budget`    | REAL    | Uses core `PowerEstimator`.              |
//! | `compute_friction`        | REAL    | Uses core `FrictionEstimator`.           |
//! | `validate_config`         | REAL    | Delegates to core `validate()`.          |
//! | `connect_kicad`           | REAL    | KiCad IPC: connect + query open board.   |
//! | `write_coils_to_board`    | REAL    | KiCad IPC: generate + atomic commit.     |
//! | `ping_kicad`              | REAL    | KiCad IPC: connect + GetVersion.         |
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

use pcbstatorgen_rs::geometry::make_coil_generator;
use pcbstatorgen_rs::magnetic::{CommutationMode as CoreCommutationMode, ForceEvaluator};
use pcbstatorgen_rs::stackup::{FrictionEstimator, HeightStackCalculator, PowerEstimator};
use pcbstatorgen_rs::kicad::{
    BoardHandle, DocumentSpecifier, DocumentType, KiCadClient,
};
use pcbstatorgen_rs::kicad::proto::common::commands::{
    GetOpenDocuments, GetOpenDocumentsResponse, GetVersion, GetVersionResponse,
};

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
// compute_height_stack — REAL (core HeightStackCalculator)
// ===========================================================================

/// Compute the vertical height stack (PCB → air gap → magnet → back-iron).
///
/// Uses the real `pcbstatorgen_rs::stackup::HeightStackCalculator` with its
/// default 1 oz outer copper and 0.3 mm assembly tolerance.
#[tauri::command]
pub async fn compute_height_stack(
    config: LinearMotorConfigIpc,
) -> Result<HeightStackResultIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || {
        let hs = HeightStackCalculator::default().calculate(&core);
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
// generate_coils — REAL (core geometry generators)
// ===========================================================================

/// Generate coil path geometry for all phases/layers.
///
/// Uses `pcbstatorgen_rs::geometry::make_coil_generator` to select the
/// generator for the configured topology, then calls the `CoilGenerator`
/// trait's `generate()` method for each layer. The conversion to IPC DTOs
/// is handled by `CoilPathIpc::from_core`.
#[tauri::command]
pub async fn generate_coils(config: LinearMotorConfigIpc) -> Result<CoilPathIpc, String> {
    let core = config.to_core();
    let num_layers = config.num_layers;
    tauri::async_runtime::spawn_blocking(move || {
        let gen = make_coil_generator(core.coil_topology);
        let mut coils = Vec::new();
        for layer in 0..num_layers {
            coils.extend(gen.generate(&core, layer));
        }
        Ok(CoilPathIpc::from_core(&coils, num_layers))
    })
    .await
    .map_err(|e| format!("generate_coils worker failed: {e}"))?
}

// ===========================================================================
// evaluate_force_sweep — REAL (core ForceEvaluator / Lorentz force)
// ===========================================================================

/// Evaluate force vs mover position along the travel axis.
///
/// Uses the real `pcbstatorgen_rs::magnetic::ForceEvaluator` which integrates
/// the Lorentz force `F = I · Σ(dLᵢ × Bᵢ)` across all active conductors at
/// each mover position. The magnet array is built from the config's
/// `MagnetArrangement` (Alternating / Halbach / back-iron variants).
///
/// Coils are generated for a single layer (layer 0) — sufficient for the
/// force profile since the force scales linearly with layer count.
///
/// Per PRODUCT_GOALS §4.C: `F_mover = -F_stator` — all forces are mover
/// forces. Ripple % = (F_max − F_min) / |F_mean| × 100.
#[tauri::command]
pub async fn evaluate_force_sweep(
    config: LinearMotorConfigIpc,
) -> Result<ForceSweepResultIpc, String> {
    let core = config.to_core();
    let n_positions = config.n_positions.max(2) as usize;
    let meshing = config.meshing.max(1) as usize;
    let commutation = match config.commutation {
        CommutationModeIpc::MaxTorque => CoreCommutationMode::MaxTorque,
        CommutationModeIpc::PhaseAOnly => CoreCommutationMode::PhaseAOnly,
    };
    tauri::async_runtime::spawn_blocking(move || {
        let gen = make_coil_generator(core.coil_topology);
        let coils = gen.generate(&core, 0);

        let mut evaluator = ForceEvaluator::new(n_positions, meshing, commutation, 0.0);
        let result = evaluator.evaluate(&core, &coils);

        let n_phases = result.n_phases;
        let mean = result.mean_thrust_n();
        let peak = result.peak_thrust_n();
        let min = result.min_thrust_n();
        let ripple = result.ripple_pct();
        let per_phase: Vec<Vec<f64>> = result
            .per_phase_force_x
            .chunks(n_phases)
            .map(|c| c.to_vec())
            .collect();

        Ok(ForceSweepResultIpc {
            positions_m: result.positions_m,
            force_x_n: result.force_x_n,
            force_y_n: result.force_y_n,
            force_z_n: result.force_z_n,
            per_phase_force_x: per_phase,
            commutation: match result.commutation {
                CoreCommutationMode::MaxTorque => CommutationModeIpc::MaxTorque,
                CoreCommutationMode::PhaseAOnly => CommutationModeIpc::PhaseAOnly,
            },
            current_a: result.current_a,
            mean_thrust_n: mean,
            peak_thrust_n: peak,
            min_thrust_n: min,
            ripple_pct: ripple,
            n_positions: n_positions as u32,
        })
    })
    .await
    .map_err(|e| format!("force_sweep worker failed: {e}"))?
}

// ===========================================================================
// compute_stackup — STUB (no core StackupCalculator exists)
// ===========================================================================

/// Compute the PCB stackup recommendation (trace widths, copper thicknesses,
/// via grid).
///
/// **STUB**: No core `StackupCalculator` or `LayerOptimizer` exists in
/// `pcbstatorgen_rs::stackup`. The core `StackupResult` struct is used as an
/// *input* to `PowerEstimator::estimate()`, not produced by a calculator.
/// This returns a plausible per-layer allocation (outer layers thinner, inner
/// layers thicker) ported from the frontend mock.
#[tauri::command]
pub async fn compute_stackup(config: LinearMotorConfigIpc) -> Result<StackupResultIpc, String> {
    let cfg = config.clone();
    tauri::async_runtime::spawn_blocking(move || {
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
            notes: vec!["Stub stackup — no core StackupCalculator exists yet".into()],
        })
    })
    .await
    .map_err(|e| format!("stackup worker failed: {e}"))?
}

// ===========================================================================
// compute_power_budget — REAL (core PowerEstimator)
// ===========================================================================

/// Estimate phase resistance, continuous/burst power, and thermal rise.
///
/// Uses the real `pcbstatorgen_rs::stackup::PowerEstimator` with default
/// parameters (2 layers per phase, 2 oz copper approximation when no stackup
/// is provided).
#[tauri::command]
pub async fn compute_power_budget(
    config: LinearMotorConfigIpc,
) -> Result<PowerBudgetIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || {
        let pb = PowerEstimator::default().estimate(&core, None);
        Ok(PowerBudgetIpc {
            phase_resistance_ohm: pb.phase_resistance_ohm,
            continuous_power_w: pb.continuous_power_w,
            burst_power_w: pb.burst_power_w,
            temperature_rise_c: pb.temperature_rise_c,
            capacitor_required_uf: pb.capacitor_required_uf,
            efficiency_pct: pb.efficiency_pct,
        })
    })
    .await
    .map_err(|e| format!("power_budget worker failed: {e}"))?
}

// ===========================================================================
// compute_friction — REAL (core FrictionEstimator)
// ===========================================================================

/// Break down the total friction into bearing, cable drag, wiper, and
/// cogging components.
///
/// Uses the real `pcbstatorgen_rs::stackup::FrictionEstimator` with the
/// `estimate_for_config()` method, which splits `config.friction_n`
/// proportionally based on the default bearing type (PTE-lined).
/// Cogging is always 0 for coreless motors (PRODUCT_GOALS §4.A) — the
/// estimator's proportional split assigns cogging a fraction of the total,
/// but this is overridden to 0 for coreless topologies.
#[tauri::command]
pub async fn compute_friction(config: LinearMotorConfigIpc) -> Result<FrictionBudgetIpc, String> {
    let core = config.to_core();
    tauri::async_runtime::spawn_blocking(move || {
        let fb = FrictionEstimator::default().estimate_for_config(&core);
        Ok(FrictionBudgetIpc {
            bearing_friction_n: fb.bearing_friction_n,
            cable_drag_n: fb.cable_drag_n,
            wiper_contact_n: fb.wiper_contact_n,
            cogging_n: 0.0, // coreless → zero cogging (§4.A)
            total_n: fb.bearing_friction_n + fb.cable_drag_n + fb.wiper_contact_n,
            minimum_drive_force_n: (fb.bearing_friction_n + fb.cable_drag_n + fb.wiper_contact_n) * 1.3,
        })
    })
    .await
    .map_err(|e| format!("friction worker failed: {e}"))?
}

// ===========================================================================
// KiCad IPC commands (Phase 7)
// ===========================================================================

/// KiCad connection result.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct KicadConnectionResult {
    pub connected: bool,
    pub board_name: String,
    pub copper_layers: u32,
}

/// KiCad write result.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct KicadWriteResult {
    pub items_created: u32,
    pub commit_id: String,
}

/// KiCad ping result.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct KicadPingResult {
    pub ok: bool,
    pub version: String,
}

/// Type URL for the `GetOpenDocuments` command.
const GET_OPEN_DOCUMENTS_TYPE_URL: &str =
    "type.googleapis.com/kiapi.common.commands.GetOpenDocuments";

/// Type URL for the `GetVersion` command.
const GET_VERSION_TYPE_URL: &str =
    "type.googleapis.com/kiapi.common.commands.GetVersion";

/// Query the first open PCB document from KiCad.
///
/// Sends a `GetOpenDocuments` command with `DOCTYPE_PCB` and returns the
/// first `DocumentSpecifier` from the response, or an error if no board is
/// open.
fn get_open_pcb_document(
    client: &mut KiCadClient,
) -> Result<DocumentSpecifier, String> {
    let cmd = GetOpenDocuments {
        r#type: DocumentType::DoctypePcb as i32,
    };
    let resp: GetOpenDocumentsResponse = client
        .send(GET_OPEN_DOCUMENTS_TYPE_URL, &cmd)
        .map_err(|e| e.to_string())?;
    resp.documents
        .into_iter()
        .next()
        .ok_or_else(|| "No PCB document open in KiCad".to_string())
}

/// Connect to KiCad and query the open board's name and copper layer count.
///
/// Returns `connected: false` (not an `Err`) if the connection fails, so the
/// frontend can show a graceful "not connected" state.
#[tauri::command]
pub async fn connect_kicad() -> Result<KicadConnectionResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut client = KiCadClient::new(None, None, 2000);
        if let Err(e) = client.connect() {
            return Ok(KicadConnectionResult {
                connected: false,
                board_name: format!("Error: {}", e),
                copper_layers: 0,
            });
        }

        let (board_name, copper_layers) = match get_open_pcb_document(&mut client) {
            Ok(doc) => {
                let mut board = BoardHandle::new(&mut client, doc);
                let name = board.name().unwrap_or_else(|_| "(unknown)".to_string());
                let layers = board.get_copper_layer_count().unwrap_or(0);
                (name, layers)
            }
            Err(e) => (format!("No board open: {}", e), 0),
        };

        Ok(KicadConnectionResult {
            connected: true,
            board_name,
            copper_layers,
        })
    })
    .await
    .map_err(|e| format!("connect_kicad worker failed: {e}"))?
}

/// Generate coils from the config and write them to the open KiCad board.
///
/// Connects to KiCad, queries the open PCB, generates coil geometry using the
/// real `make_coil_generator`, and writes the items atomically via
/// `BoardHandle::write_coils` (single Ctrl+Z undo step).
///
/// Uses `config.num_layers` (not `max_layers`) for the layer count, since the
/// user may select fewer layers than the maximum.
#[tauri::command]
pub async fn write_coils_to_board(
    config: LinearMotorConfigIpc,
) -> Result<KicadWriteResult, String> {
    let core = config.to_core();
    let num_layers = config.num_layers;
    tauri::async_runtime::spawn_blocking(move || {
        let gen = make_coil_generator(core.coil_topology);
        let mut coils = Vec::new();
        for layer in 0..num_layers {
            coils.extend(gen.generate(&core, layer));
        }

        let mut client = KiCadClient::new(None, None, 5000);
        client
            .connect()
            .map_err(|e| format!("KiCad connection failed: {e}"))?;

        let doc = get_open_pcb_document(&mut client)
            .map_err(|e| format!("No open PCB to write to: {e}"))?;

        let mut board = BoardHandle::new(&mut client, doc);
        let items_created = board
            .write_coils(&coils, &core)
            .map_err(|e| format!("KiCad write_coils failed: {e}"))?;

        Ok(KicadWriteResult {
            items_created,
            commit_id: "atomic-commit".to_string(),
        })
    })
    .await
    .map_err(|e| format!("write_coils_to_board worker failed: {e}"))?
}

/// Ping KiCad and return the version string.
///
/// Returns `ok: false` (not an `Err`) if the connection fails, so the
/// frontend can show a graceful "not connected" state.
#[tauri::command]
pub async fn ping_kicad() -> Result<KicadPingResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut client = KiCadClient::new(None, None, 1000);
        if let Err(_) = client.connect() {
            return Ok(KicadPingResult {
                ok: false,
                version: String::new(),
            });
        }

        let version = match client.send::<GetVersion, GetVersionResponse>(
            GET_VERSION_TYPE_URL,
            &GetVersion {},
        ) {
            Ok(resp) => resp
                .version
                .map(|v| v.full_version)
                .unwrap_or_else(|| "connected".to_string()),
            Err(_) => "connected".to_string(),
        };

        Ok(KicadPingResult {
            ok: true,
            version,
        })
    })
    .await
    .map_err(|e| format!("ping_kicad worker failed: {e}"))?
}
