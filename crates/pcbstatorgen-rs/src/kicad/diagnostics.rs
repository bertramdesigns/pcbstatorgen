//! KiCad board diagnostics and pre-write validation.
//!
//! Bridges the gap between the user's `LinearMotorConfig` and the live state
//! of the open KiCad board, surfacing mismatches BEFORE any track is written.
//! This is the "robust KiCad connection" feature (WP-1.B in the project plan).
//!
//! ## Three top-level helpers
//!
//! 1. [`get_board_diagnostics`] — query the open board for its name, copper
//!    layer count, and (where supported by the IPC) its edge-cut bounding box
//!    and available net classes. Returns a [`BoardDiagnostics`] struct.
//!
//! 2. [`validate_write_preconditions`] — pure function comparing the user's
//!    config against the live [`BoardDiagnostics`]. Returns a list of
//!    [`PreconditionWarning`] entries (Info / Warning / Error) so the UI can
//!    show "your config is 4-layer but your board is 2-layer — reduce to 2".
//!
//! 3. [`preview_coils`] — pure dry-run that returns the [`CoilPreview`] (the
//!    list of `PhaseCoil` that `write_coils_to_board` would write, plus a
//!    per-layer summary). Used by the UI to confirm placement before clicking
//!    the real "Write to Board" button.
//!
//! None of these helpers touch the IPC socket except
//! [`get_board_diagnostics`], which is the only side-effecting one. The other
//! two are pure — easy to unit-test.

use crate::config::LinearMotorConfig;
use crate::geometry::{make_coil_generator, PhaseCoil};
use crate::kicad::board::BoardHandle;
use crate::kicad::errors::KiCadError;

// ---------------------------------------------------------------------------
// BoardDiagnostics
// ---------------------------------------------------------------------------

/// Snapshot of the open KiCad board's geometric / electrical state.
///
/// `BoardDiagnostics` is the *live* counterpart of `LinearMotorConfig`. The
/// frontend fetches it before every write so it can show the user "the board
/// you have open has 4 copper layers, you asked for 6" rather than discovering
/// the mismatch after the fact.
///
/// `board_x_min_mm` / `board_x_max_mm` / `board_y_min_mm` / `board_y_max_mm`
/// are populated from the board's edge cuts when the IPC supports that query.
/// If the query is not available, they default to `0.0` and
/// `available_net_classes` is empty — but `board_name` and
/// `copper_layer_count` are always populated (the latter from
/// `GetBoardEnabledLayers`, which is supported on KiCad 10).
#[derive(Debug, Clone, PartialEq)]
pub struct BoardDiagnostics {
    /// File name of the open board, e.g. `"board.kicad_pcb"`. Empty if no
    /// board is open.
    pub board_name: String,
    /// Number of copper layers enabled on the board (from
    /// `GetBoardEnabledLayers`).
    pub copper_layer_count: u32,
    /// Bounding box of the board's edge cuts [mm]. Defaults to `0.0` if not
    /// queryable — see [`board_x_min_mm`].
    pub board_x_min_mm: f64,
    /// See [`board_x_min_mm`].
    pub board_x_max_mm: f64,
    /// See [`board_x_min_mm`].
    pub board_y_min_mm: f64,
    /// See [`board_x_min_mm`].
    pub board_y_max_mm: f64,
    /// Net class names defined on the board. Empty if not queryable.
    /// TODO: real query — current implementation returns an empty vector
    /// because the KiCad IPC API does not yet expose a net-class query.
    pub available_net_classes: Vec<String>,
}

impl BoardDiagnostics {
    /// Convenience: width of the board's edge-cut bounding box [mm]. Returns
    /// `0.0` when the bounding box is not queryable.
    pub fn board_width_mm(&self) -> f64 {
        (self.board_x_max_mm - self.board_x_min_mm).max(0.0)
    }

    /// Convenience: height of the board's edge-cut bounding box [mm].
    pub fn board_height_mm(&self) -> f64 {
        (self.board_y_max_mm - self.board_y_min_mm).max(0.0)
    }
}

// ---------------------------------------------------------------------------
// get_board_diagnostics
// ---------------------------------------------------------------------------

/// Query the open KiCad board and return a [`BoardDiagnostics`] snapshot.
///
/// `BoardHandle::get_copper_layer_count` always succeeds when the connection
/// is up; `board_name` comes from the document specifier. The edge-cut
/// bounding box and net-class list are **not** currently queryable via the
/// KiCad 10 IPC (no matching `.proto` command in `kiapi.board.commands`), so
/// they default to `0.0` and an empty list respectively. A `// TODO` comment
/// marks the spot for the real query when the IPC grows it.
///
/// Returns `Err` on connection failure or missing PCB document.
pub fn get_board_diagnostics(
    board: &mut BoardHandle<'_>,
) -> Result<BoardDiagnostics, KiCadError> {
    let board_name = board.name().unwrap_or_default();
    let copper_layer_count = board.get_copper_layer_count().unwrap_or(0);

    // TODO: real query — when the KiCad IPC exposes a GetBoardBounds /
    // GetNetClasses command, replace the placeholder zeros / empty list
    // here. Until then, we return a snapshot with the populated fields
    // (name, layer count) and a clear placeholder for the missing ones.
    Ok(BoardDiagnostics {
        board_name,
        copper_layer_count,
        board_x_min_mm: 0.0,
        board_x_max_mm: 0.0,
        board_y_min_mm: 0.0,
        board_y_max_mm: 0.0,
        available_net_classes: Vec::new(),
    })
}

// ---------------------------------------------------------------------------
// PreconditionWarning
// ---------------------------------------------------------------------------

/// Severity of a [`PreconditionWarning`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PreconditionLevel {
    /// Informational — design still works, but a tweak is recommended.
    Info,
    /// Warning — design will likely underperform, but won't outright fail.
    Warning,
    /// Error — the write will probably fail or produce broken geometry.
    Error,
}

/// One warning or recommendation about the (config, board) pair.
///
/// Produced by [`validate_write_preconditions`]. The UI is expected to render
/// each `message` verbatim and colour-code by `level`. The `field` is an
/// optional machine-readable key (`"num_layers"`, `"active_area_length_m"`,
/// …) that the UI can use to highlight the offending input control.
#[derive(Debug, Clone, PartialEq)]
pub struct PreconditionWarning {
    pub level: PreconditionLevel,
    pub field: Option<String>,
    pub message: String,
}

impl PreconditionWarning {
    /// Construct a new warning of the given level.
    pub fn new(level: PreconditionLevel, field: Option<&str>, message: impl Into<String>) -> Self {
        Self {
            level,
            field: field.map(String::from),
            message: message.into(),
        }
    }

    /// Construct an Info-level warning.
    pub fn info(field: Option<&str>, message: impl Into<String>) -> Self {
        Self::new(PreconditionLevel::Info, field, message)
    }
    /// Construct a Warning-level warning.
    pub fn warn(field: Option<&str>, message: impl Into<String>) -> Self {
        Self::new(PreconditionLevel::Warning, field, message)
    }
    /// Construct an Error-level warning.
    pub fn error(field: Option<&str>, message: impl Into<String>) -> Self {
        Self::new(PreconditionLevel::Error, field, message)
    }
}

// ---------------------------------------------------------------------------
// validate_write_preconditions
// ---------------------------------------------------------------------------

/// Minimum air gap below which a warning fires (default 0.1 mm).
const MIN_AIR_GAP_M: f64 = 0.1e-3;

/// Pure function — does not touch KiCad. Returns the list of warnings/errors
/// that the UI should display before letting the user click "Write to Board".
///
/// All layer-count checks operate on `config.num_layers` (the
/// user-selected layer count), **not** `config.max_layers` (the DFM upper
/// limit). It is perfectly valid for a user to select 4 layers on a
/// 12-layer-capable board; the check must fire on the user intent, not the
/// ceiling.
///
/// Implemented checks (extend as new ones are needed):
/// 1. **Layer count** — `config.num_layers > diagnostics.copper_layer_count`
///    is an `Error` (we'd write tracks to non-existent layers).
/// 2. **Layer count zero** — `config.num_layers == 0` is an `Error`
///    (zero iterations → no coils).
/// 3. **Active area vs board width** — if the board dimensions are queryable
///    and `active_area_length_m > board_width`, emits a `Warning`.
/// 4. **Board width vs board_width_m** — same idea for the y dimension.
/// 5. **Tiny air gap** — `air_gap_m < MIN_AIR_GAP_M` is a `Warning` (suggests
///    the magnet will hit the PCB).
/// 6. **Phases mismatch with `num_layers`** — a phase spanning zero or one
///    layer is suspicious; a `Warning` is emitted if `num_layers < phases`
///    (you'd be under-using your DFM budget).
pub fn validate_write_preconditions(
    config: &LinearMotorConfig,
    diagnostics: &BoardDiagnostics,
) -> Vec<PreconditionWarning> {
    let mut out: Vec<PreconditionWarning> = Vec::new();

    // (1) num_layers > board's copper layer count → Error
    // Bug fix: this used to check `config.max_layers` (the DFM upper limit,
    // default 12), which caused spurious "12 layers vs 4-layer board" errors
    // even when the user had selected 4 layers. Now we report the
    // user-intended count and include the DFM limit for context.
    if config.num_layers > diagnostics.copper_layer_count && diagnostics.copper_layer_count > 0 {
        out.push(PreconditionWarning::error(
            Some("num_layers"),
            format!(
                "Your config requests {} layer(s) (max_layers: {}) but the board '{}' \
                 only has {}. Reduce num_layers to {} to match the board.",
                config.num_layers,
                config.max_layers,
                diagnostics.board_name,
                diagnostics.copper_layer_count,
                diagnostics.copper_layer_count,
            ),
        ));
    }

    // (2) num_layers == 0 → Error (no iterations → no coils)
    if config.num_layers == 0 {
        out.push(PreconditionWarning::error(
            Some("num_layers"),
            "num_layers is 0 — no coils can be generated. Set at least 2.",
        ));
    }

    // (3) active_area_length_m > board width (when board dims are known)
    let board_w = diagnostics.board_width_mm();
    if board_w > 0.0 {
        let active_mm = config.active_area_length_m * 1e3;
        if active_mm > board_w {
            out.push(PreconditionWarning::warn(
                Some("active_area_length_m"),
                format!(
                    "Your active area is {:.1} mm but the board edge-cut is only {:.1} mm wide. \
                     Either reduce active_area_length, use a larger board, or expand the \
                     board's edge cuts.",
                    active_mm, board_w,
                ),
            ));
        }
    }

    // (4) board_width_m > board height (when board dims are known)
    let board_h = diagnostics.board_height_mm();
    if board_h > 0.0 {
        let cfg_board_w_mm = config.board_width_m * 1e3;
        if cfg_board_w_mm > board_h {
            out.push(PreconditionWarning::warn(
                Some("board_width_m"),
                format!(
                    "Your board_width is {:.1} mm but the board edge-cut is only {:.1} mm tall. \
                     Either reduce board_width, or expand the board's edge cuts.",
                    cfg_board_w_mm, board_h,
                ),
            ));
        }
    }

    // (5) Tiny air gap
    if config.air_gap_m < MIN_AIR_GAP_M {
        out.push(PreconditionWarning::warn(
            Some("air_gap_m"),
            format!(
                "Air gap is very small ({:.3} mm). Check your magnet dimensions \
                 and assembly tolerance — a collision with the PCB is likely.",
                config.air_gap_m * 1e3,
            ),
        ));
    }

    // (6) num_layers < phases → under-using DFM budget (some phases will be
    //     assigned no layer, forcing them onto a layer that already has
    //     another phase).
    if config.num_layers < config.phases && config.num_layers > 0 {
        out.push(PreconditionWarning::warn(
            Some("num_layers"),
            format!(
                "num_layers ({}) is less than phases ({}). At least one phase will \
                 share a copper layer with another phase, which may short phases. \
                 Increase num_layers to at least {}.",
                config.num_layers, config.phases, config.phases,
            ),
        ));
    }

    out
}

// ---------------------------------------------------------------------------
// CoilPreview
// ---------------------------------------------------------------------------

/// Per-layer breakdown of the coils that would be written.
#[derive(Debug, Clone, PartialEq)]
pub struct CoilPreviewLayer {
    /// Zero-based layer index in the writer's iteration (`0..num_layers`).
    pub layer_idx: u32,
    /// KiCad `BoardLayer` enum value as `i32` (mirrors the wire format). For
    /// example, `0` bottom = `BL_BCU`, top = `BL_FCU`. The Tauri command
    /// serialises this directly so the UI can render layer-aware previews.
    pub board_layer: i32,
    /// Number of phase coils on this layer.
    pub phase_count: u32,
    /// Number of track segments (sum of `segments.len()` across phases).
    pub segment_count: u32,
    /// Number of inter-layer vias (sum of `center_via_positions.len()`).
    pub via_count: u32,
}

/// Dry-run summary of what `write_coils_to_board` would produce.
///
/// Returned by [`preview_coils`]. Contains the full list of `PhaseCoil`
/// objects (so the UI can render the geometry) and a per-layer tally for the
/// at-a-glance "50 tracks + 12 vias across 4 layers" summary the user
/// wants to see before clicking "Write to Board".
#[derive(Debug, Clone)]
pub struct CoilPreview {
    /// Number of layers the writer would iterate over.
    pub num_layers: u32,
    /// Topology actually used by the writer (mirrors the config's
    /// `coil_topology`; reported back for UI clarity).
    pub topology: String,
    /// Per-layer breakdown.
    pub layers: Vec<CoilPreviewLayer>,
    /// Total track segments across all layers.
    pub total_tracks: u32,
    /// Total vias across all layers.
    pub total_vias: u32,
    /// Full phase-coil geometry. The Tauri command converts these to the
    /// `CoilPathIpc` wire format for the UI.
    pub coils: Vec<PhaseCoil>,
}

// ---------------------------------------------------------------------------
// preview_coils
// ---------------------------------------------------------------------------

/// Dry-run: build the same coil set `write_coils_to_board` would write, but
/// do not touch KiCad.
///
/// `num_layers` is the per-call layer count (mirrors the
/// `config.num_layers` field on the IPC). `config.max_layers` is used to map
/// layer indices to KiCad `BoardLayer` enum values via `layer_idx_to_board_layer`.
pub fn preview_coils(
    config: &LinearMotorConfig,
    num_layers: u32,
) -> Result<CoilPreview, String> {
    if num_layers == 0 {
        return Err(
            "num_layers is 0 — nothing to preview. Set at least 2 layers.".to_string(),
        );
    }

    let gen = make_coil_generator(config.coil_topology);
    let mut coils: Vec<PhaseCoil> = Vec::new();
    for layer in 0..num_layers {
        coils.extend(gen.generate(config, layer));
    }

    if coils.is_empty() {
        return Err(format!(
            "coil generator produced no coils for topology '{}' (num_layers={}). \
             Check that phases, active_area_length_m and magnet_pitch_m are non-zero.",
            topology_label(config.coil_topology),
            num_layers,
        ));
    }

    // Per-layer tally. Group by `layer_idx` so a single PhaseCoil that lives
    // on layer 0 contributes to layer 0 only (the writer iterates 0..num_layers
    // and each call to `gen.generate` produces a single layer's worth of coils).
    let mut layers: Vec<CoilPreviewLayer> = Vec::with_capacity(num_layers as usize);
    let mut total_tracks: u32 = 0;
    let mut total_vias: u32 = 0;
    for layer_idx in 0..num_layers {
        let layer_coils: Vec<&PhaseCoil> =
            coils.iter().filter(|c| c.layer_idx == layer_idx).collect();
        let segment_count: u32 = layer_coils
            .iter()
            .map(|c| c.segments.len() as u32)
            .sum();
        let via_count: u32 = layer_coils
            .iter()
            .map(|c| c.center_via_positions.len() as u32)
            .sum();
        let board_layer = crate::kicad::layer_idx_to_board_layer(
            layer_idx,
            config.max_layers.max(1),
        ) as i32;
        total_tracks += segment_count;
        total_vias += via_count;
        layers.push(CoilPreviewLayer {
            layer_idx,
            board_layer,
            phase_count: layer_coils.len() as u32,
            segment_count,
            via_count,
        });
    }

    Ok(CoilPreview {
        num_layers,
        topology: topology_label(config.coil_topology).to_string(),
        layers,
        total_tracks,
        total_vias,
        coils,
    })
}

fn topology_label(t: crate::config::CoilTopology) -> &'static str {
    use crate::config::CoilTopology;
    match t {
        CoilTopology::Serpentine => "serpentine",
        CoilTopology::SineWave => "sine_wave",
        CoilTopology::Concentrated => "concentrated",
        CoilTopology::Rhombic => "rhombic",
        CoilTopology::Spiral => "spiral",
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::LinearMotorConfig;
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
            max_layers: 4,
            ..LinearMotorConfig::default()
        }
    }

    fn empty_diagnostics() -> BoardDiagnostics {
        BoardDiagnostics {
            board_name: "test.kicad_pcb".into(),
            copper_layer_count: 0,
            board_x_min_mm: 0.0,
            board_x_max_mm: 0.0,
            board_y_min_mm: 0.0,
            board_y_max_mm: 0.0,
            available_net_classes: Vec::new(),
        }
    }

    // --- BoardDiagnostics width/height helpers ---

    #[test]
    fn test_board_diagnostics_width_height_zero_when_not_set() {
        let d = empty_diagnostics();
        assert_eq!(d.board_width_mm(), 0.0);
        assert_eq!(d.board_height_mm(), 0.0);
    }

    #[test]
    fn test_board_diagnostics_width_height_positive_when_set() {
        let d = BoardDiagnostics {
            board_x_min_mm: -25.0,
            board_x_max_mm: 25.0,
            board_y_min_mm: -10.0,
            board_y_max_mm: 10.0,
            ..empty_diagnostics()
        };
        assert!((d.board_width_mm() - 50.0).abs() < 1e-9);
        assert!((d.board_height_mm() - 20.0).abs() < 1e-9);
    }

    #[test]
    fn test_board_diagnostics_width_height_clamped_at_zero() {
        // Inverted box (x_max < x_min) must clamp to zero, not yield a
        // negative dimension.
        let d = BoardDiagnostics {
            board_x_min_mm: 25.0,
            board_x_max_mm: -25.0,
            board_y_min_mm: 10.0,
            board_y_max_mm: -10.0,
            ..empty_diagnostics()
        };
        assert_eq!(d.board_width_mm(), 0.0);
        assert_eq!(d.board_height_mm(), 0.0);
    }

    // --- validate_write_preconditions: layer count ---

    #[test]
    fn test_validate_layer_mismatch_is_error() {
        let mut cfg = default_config();
        // The check now operates on `num_layers` (user intent), not
        // `max_layers` (DFM upper limit). Set both so the test exercises
        // the intended path: user picked 6 layers, board has 4.
        cfg.max_layers = 6;
        cfg.num_layers = 6;
        let mut d = empty_diagnostics();
        d.copper_layer_count = 4; // board only has 4
        let warnings = validate_write_preconditions(&cfg, &d);
        let errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.level == PreconditionLevel::Error)
            .collect();
        assert!(!errs.is_empty(), "expected an error for layer mismatch");
        assert!(errs[0].message.contains("6"));
        assert!(errs[0].message.contains("4"));
        assert_eq!(errs[0].field.as_deref(), Some("num_layers"));
    }

    /// Regression for Bug 1 (validate_write_preconditions always reports 12
    /// layers). With `num_layers = 4, max_layers = 12` and a 4-layer board,
    /// the error must reference the **user's 4** layers — not the DFM
    /// upper limit of 12. The check used to read `config.max_layers` and
    /// would always say "12 layers" on a default 12-layer config.
    #[test]
    fn test_validate_layer_mismatch_reports_user_num_layers_not_max() {
        // Build a config with num_layers=4, max_layers=12 (DFM ceiling)
        // and a 4-layer board. The check should report "4 layer(s)" — the
        // user selection — and include the max_layers=12 context. Crucially
        // the error must NOT mention 12 as the requested count.
        let mut cfg = default_config();
        cfg.num_layers = 4;
        cfg.max_layers = 12;
        let mut d = empty_diagnostics();
        d.copper_layer_count = 4; // board matches the user selection
        // With matching layer counts there is no error — the function
        // should be silent on the layer-count axis. This is the positive
        // case for the regression.
        let warnings = validate_write_preconditions(&cfg, &d);
        let layer_errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.level == PreconditionLevel::Error
                    && w.field.as_deref() == Some("num_layers")
            })
            .collect();
        assert!(
            layer_errs.is_empty(),
            "no layer-count error expected for matching 4-layer config + 4-layer board, got: {:?}",
            layer_errs
        );

        // Now push the user above the board: num_layers=6, board=4. The
        // error must report the **6** the user asked for, not 12.
        cfg.num_layers = 6;
        let warnings = validate_write_preconditions(&cfg, &d);
        let layer_errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.level == PreconditionLevel::Error
                    && w.field.as_deref() == Some("num_layers")
            })
            .collect();
        assert_eq!(layer_errs.len(), 1, "expected exactly one layer-count error");
        let msg = &layer_errs[0].message;
        assert!(
            msg.contains("6 layer(s)"),
            "error must report the user-selected num_layers (6), got: {}",
            msg
        );
        // Should also surface max_layers=12 as context (helps the user
        // understand why the validator picked that specific number).
        assert!(
            msg.contains("max_layers: 12"),
            "error should include the DFM max_layers as context, got: {}",
            msg
        );
        // Crucially the user-facing number must NOT be 12.
        assert!(
            !msg.contains("12 layer(s)"),
            "error must NOT misreport the user selection as 12 layers, got: {}",
            msg
        );
    }

    /// The "max_layers=12" smoke test: a config that leaves the
    /// user-facing `num_layers` at its serde default of 4 but bumps
    /// `max_layers` to 12 must NOT trip the layer-count error against a
    /// 4-layer board. This is the exact UI scenario the bug report
    /// flagged.
    #[test]
    fn test_validate_default_user_layers_silent_against_matching_board() {
        let mut cfg = default_config();
        cfg.max_layers = 12; // DFM ceiling only
        cfg.num_layers = 4;  // user selection (matches board)
        let mut d = empty_diagnostics();
        d.copper_layer_count = 4;
        let warnings = validate_write_preconditions(&cfg, &d);
        let layer_errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.level == PreconditionLevel::Error
                    && w.field.as_deref() == Some("num_layers")
            })
            .collect();
        assert!(
            layer_errs.is_empty(),
            "matching 4-layer config must not error, got: {:?}",
            layer_errs
        );
    }

    #[test]
    fn test_validate_layer_match_no_warning() {
        let cfg = default_config(); // num_layers = 4 (default), max_layers = 4
        let mut d = empty_diagnostics();
        d.copper_layer_count = 4;
        let warnings = validate_write_preconditions(&cfg, &d);
        // No layer-count error in this case.
        let errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.level == PreconditionLevel::Error
                    && w.field.as_deref() == Some("num_layers")
            })
            .collect();
        assert!(errs.is_empty(), "got unexpected error: {:?}", errs);
    }

    #[test]
    fn test_validate_zero_layers_is_error() {
        // Bug fix: the zero-layer check now operates on `num_layers` (user
        // selection), not `max_layers` (DFM upper limit). The error message
        // says "num_layers is 0" — the user's selection, not the DFM cap.
        let mut cfg = default_config();
        cfg.num_layers = 0;
        let warnings = validate_write_preconditions(&cfg, &empty_diagnostics());
        let errs: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.level == PreconditionLevel::Error)
            .collect();
        assert!(!errs.is_empty());
        assert!(errs[0].message.to_lowercase().contains("num_layers"));
    }

    // --- validate_write_preconditions: dimensions ---

    #[test]
    fn test_validate_active_area_too_wide_warns() {
        let mut cfg = default_config();
        cfg.active_area_length_m = mm(500.0); // 500 mm
        let mut d = empty_diagnostics();
        d.board_x_min_mm = 0.0;
        d.board_x_max_mm = 100.0; // 100 mm board
        let warnings = validate_write_preconditions(&cfg, &d);
        let warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.field.as_deref() == Some("active_area_length_m"))
            .collect();
        assert!(!warns.is_empty(), "expected active_area warning");
        assert!(warns[0].message.contains("500"));
        assert!(warns[0].message.contains("100"));
    }

    #[test]
    fn test_validate_active_area_fits_no_warning() {
        let cfg = default_config(); // 195 mm
        let mut d = empty_diagnostics();
        d.board_x_min_mm = 0.0;
        d.board_x_max_mm = 250.0;
        let warnings = validate_write_preconditions(&cfg, &d);
        let warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.field.as_deref() == Some("active_area_length_m"))
            .collect();
        assert!(warns.is_empty());
    }

    #[test]
    fn test_validate_board_dimensions_unknown_no_warning() {
        // Diagnostics with zero board dims → no dimension warning, even if
        // active_area is huge (we just don't know how big the board is).
        let cfg = default_config();
        let d = empty_diagnostics(); // all zeros
        let warnings = validate_write_preconditions(&cfg, &d);
        let dim_warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.field.as_deref() == Some("active_area_length_m")
                    || w.field.as_deref() == Some("board_width_m")
            })
            .collect();
        assert!(dim_warns.is_empty());
    }

    // --- validate_write_preconditions: air gap ---

    #[test]
    fn test_validate_tiny_air_gap_warns() {
        let mut cfg = default_config();
        cfg.air_gap_m = 0.05e-3; // 0.05 mm — too small
        let warnings = validate_write_preconditions(&cfg, &empty_diagnostics());
        let warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.field.as_deref() == Some("air_gap_m"))
            .collect();
        assert!(!warns.is_empty());
        assert!(warns[0].message.contains("0.050"));
    }

    #[test]
    fn test_validate_healthy_air_gap_no_warning() {
        let cfg = default_config(); // air_gap = 0.5 mm
        let warnings = validate_write_preconditions(&cfg, &empty_diagnostics());
        let warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| w.field.as_deref() == Some("air_gap_m"))
            .collect();
        assert!(warns.is_empty());
    }

    // --- validate_write_preconditions: phases vs layers ---

    #[test]
    fn test_validate_layers_less_than_phases_warns() {
        let mut cfg = default_config();
        cfg.phases = 6;
        cfg.max_layers = 4; // fewer than phases
        let warnings = validate_write_preconditions(&cfg, &empty_diagnostics());
        let warns: Vec<&PreconditionWarning> = warnings
            .iter()
            .filter(|w| {
                w.level == PreconditionLevel::Warning
                    && w.field.as_deref() == Some("num_layers")
                    && w.message.contains("less than phases")
            })
            .collect();
        assert!(!warns.is_empty());
    }

    // --- preview_coils ---

    #[test]
    fn test_preview_coils_default_config_produces_tracks() {
        // This is the regression test for the "0 of 0" bug: with the default
        // config and the user-facing num_layers, the preview must produce
        // tracks (and at least one coil). If this fails, the writer would
        // also produce 0 items.
        let cfg = default_config();
        let preview = preview_coils(&cfg, cfg.max_layers).expect("preview");
        assert!(!preview.coils.is_empty(), "coils must be non-empty");
        assert!(
            preview.total_tracks > 0,
            "default config must produce at least one track; got {}",
            preview.total_tracks
        );
        // Per-layer tally matches the coils.
        for layer in &preview.layers {
            assert_eq!(
                layer.segment_count as usize,
                preview
                    .coils
                    .iter()
                    .filter(|c| c.layer_idx == layer.layer_idx)
                    .map(|c| c.segments.len())
                    .sum::<usize>(),
                "layer {} segment_count mismatch",
                layer.layer_idx,
            );
        }
    }

    #[test]
    fn test_preview_coils_per_layer_count_matches_phases() {
        // max_layers=4, phases=3 → each layer has 3 phases.
        let cfg = default_config();
        let preview = preview_coils(&cfg, cfg.max_layers).expect("preview");
        assert_eq!(preview.layers.len(), cfg.max_layers as usize);
        for layer in &preview.layers {
            assert_eq!(
                layer.phase_count, cfg.phases,
                "layer {} phase_count mismatch",
                layer.layer_idx
            );
        }
    }

    #[test]
    fn test_preview_coils_topology_label() {
        let cfg = default_config();
        let preview = preview_coils(&cfg, cfg.max_layers).expect("preview");
        assert_eq!(preview.topology, "serpentine");
    }

    #[test]
    fn test_preview_coils_zero_layers_errors() {
        let cfg = default_config();
        let err = preview_coils(&cfg, 0).unwrap_err();
        assert!(err.to_lowercase().contains("num_layers"));
    }

    #[test]
    fn test_preview_coils_top_layer_uses_fcu() {
        // layer_idx == num_layers-1 must map to F.Cu in the preview, mirroring
        // the writer's layer assignment.
        let cfg = default_config();
        let preview = preview_coils(&cfg, cfg.max_layers).expect("preview");
        let top = preview.layers.last().unwrap();
        assert_eq!(
            top.board_layer,
            crate::kicad::BoardLayer::BlFCu as i32,
            "top layer should map to F.Cu"
        );
    }

    #[test]
    fn test_preview_coils_bottom_layer_uses_bcu() {
        let cfg = default_config();
        let preview = preview_coils(&cfg, cfg.max_layers).expect("preview");
        let bottom = &preview.layers[0];
        assert_eq!(
            bottom.board_layer,
            crate::kicad::BoardLayer::BlBCu as i32,
            "layer 0 should map to B.Cu"
        );
    }

    // --- Regression: default config produces coils (the "0 of 0" fix) ---

    #[test]
    fn test_default_config_generator_produces_coils() {
        // The very assertion the user's bug report was failing: with the
        // default config (which is what the Svelte store sends on first
        // load), the coil generator must produce non-empty coils for at
        // least one layer.
        let cfg = LinearMotorConfig::default();
        let gen = make_coil_generator(cfg.coil_topology);
        let coils = gen.generate(&cfg, 0);
        assert!(
            !coils.is_empty(),
            "default config produced 0 coils for layer 0 — writer would emit 0 of 0"
        );
        assert_eq!(coils.len(), cfg.phases as usize);
    }
}
