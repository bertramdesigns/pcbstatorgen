//! High-level handle to an open KiCad board document.
//!
//! [`BoardHandle`] wraps a borrowed [`KiCadClient`] and a target
//! [`DocumentSpecifier`] (the open board). It provides convenience methods for
//! querying board properties and writing coil geometry atomically.

use crate::config::LinearMotorConfig;
use crate::geometry::PhaseCoil;
use crate::kicad::commit::Commit;
use crate::kicad::errors::KiCadError;
use crate::kicad::proto::common::types::document_specifier::Identifier;
use crate::kicad::proto::common::types::DocumentSpecifier;
use crate::kicad::writer::coils_to_board_items;
use crate::kicad::KiCadClient;

// Type URLs for board-level queries.
const GET_BOARD_ENABLED_LAYERS_TYPE_URL: &str =
    "type.googleapis.com/kiapi.board.commands.GetBoardEnabledLayers";
const BOARD_ENABLED_LAYERS_RESPONSE_TYPE_URL: &str =
    "type.googleapis.com/kiapi.board.commands.BoardEnabledLayersResponse";

/// KiCad `ItemStatusCode::ISC_OK` (from the `.proto` enum). Per-item
/// `ItemStatus.code == ISC_OK` is the only success indicator — the outer
/// `ItemRequestStatus` reports the *request* status, not the per-item
/// outcomes.
const ITEM_STATUS_OK: i32 = 1;

/// Maximum number of per-item failure messages to surface to the caller.
///
/// Set high enough that, for any realistic failure count, every individual
/// rejection message fits in the IPC response. The previous value of 10
/// silently dropped 89 of the user's 99 failures — the user only saw the
/// first 10 strings and had no way to know what the other 89 were
/// (grouped by error code, message shape, etc.). 1000 is effectively
/// unbounded for any real KiCad write (a typical coil set has a few
/// hundred items at most; even a worst-case 50k-item write would
/// only hit the cap if *every* item failed, in which case the cap is
/// the right behaviour to keep the IPC payload bounded).
const MAX_FAILURES_TO_REPORT: usize = 1000;

/// Result of a [`BoardHandle::write_coils`] call.
///
/// `items_attempted` is the number of items we sent to KiCad;
/// `items_created` is the number KiCad actually accepted (i.e. returned
/// `ISC_OK` in their `ItemStatus`). The two can differ if KiCad rejects
/// individual items (e.g. invalid data, missing layer).
///
/// `failures` contains the first [`MAX_FAILURES_TO_REPORT`] rejection
/// messages verbatim. The total failure count is always recoverable as
/// `items_attempted - items_created`, even if some were truncated.
///
/// `failure_summary` is a compact, **code-grouped** summary of all
/// rejections (not just the surfaced ones): each entry is `(code, count)`
/// where `code` is the `ItemStatus.code` value KiCad returned (e.g. 7 for
/// `ISC_INVALID_DATA`, 2 for `ISC_INVALID_TYPE`) and `count` is the
/// number of items rejected with that code. This is the most useful
/// diagnostic for the UI: instead of listing 99 individual messages that
/// all say the same thing, the UI can render
/// `"99× code=7 (no overlapping layers with the board)"` and the user
/// immediately sees the root cause. Sorted by `(code, count)` descending
/// so the most common failure appears first.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WriteCoilsResult {
    pub items_attempted: u32,
    pub items_created: u32,
    pub failures: Vec<String>,
    /// `(ItemStatus.code, count)` pairs, one entry per distinct
    /// rejection code seen. Sorted by count descending (most-frequent
    /// failure first); ties broken by `code` ascending. Empty when
    /// `items_created == items_attempted`.
    pub failure_summary: Vec<(i32, u32)>,
}

/// High-level handle to the open board document.
pub struct BoardHandle<'a> {
    client: &'a mut KiCadClient,
    document: DocumentSpecifier,
}

impl<'a> BoardHandle<'a> {
    /// Create a handle bound to the given document.
    pub fn new(client: &'a mut KiCadClient, document: DocumentSpecifier) -> Self {
        Self { client, document }
    }

    /// Returns a reference to the underlying document specifier.
    pub fn document(&self) -> &DocumentSpecifier {
        &self.document
    }

    /// Get the board name (filename), e.g. `"board.kicad_pcb"`.
    pub fn name(&self) -> Result<String, KiCadError> {
        match &self.document.identifier {
            Some(Identifier::BoardFilename(name)) => Ok(name.clone()),
            _ => Err(KiCadError::Protocol(
                "document is not a PCB (no board_filename identifier)".to_string(),
            )),
        }
    }

    /// Get the number of copper layers in the board.
    ///
    /// Sends a `GetBoardEnabledLayers` command and reads
    /// `BoardEnabledLayersResponse.copper_layer_count`.
    pub fn get_copper_layer_count(&mut self) -> Result<u32, KiCadError> {
        use crate::kicad::proto::board::commands::{
            BoardEnabledLayersResponse, GetBoardEnabledLayers,
        };

        let cmd = GetBoardEnabledLayers {
            board: Some(self.document.clone()),
        };
        let resp: BoardEnabledLayersResponse = self
            .client
            .send::<GetBoardEnabledLayers, BoardEnabledLayersResponse>(
                GET_BOARD_ENABLED_LAYERS_TYPE_URL,
                &cmd,
            )?;
        Ok(resp.copper_layer_count)
    }

    /// Write coils to the board atomically.
    ///
    /// Converts the coil geometry to KiCad board items via
    /// [`coils_to_board_items`], then opens a [`Commit`], creates the items,
    /// and ends the commit so all items appear as a single Ctrl+Z undo step.
    ///
    /// Returns a [`WriteCoilsResult`] with the per-item creation counts. The
    /// overall request may succeed (IRS_OK) even if KiCad rejected some
    /// individual items — those rejections are surfaced in `failures` rather
    /// than being turned into an `Err`, since the user can see them in the
    /// UI and a partial write is still useful diagnostic information.
    ///
    /// ## Logging
    /// Diagnostic lines are emitted to **stderr** via `eprintln!` so they
    /// surface in the Tauri dev console and the OS console. The lines are
    /// tagged with the prefix `[pcbstatorgen::write_coils]` and include the
    /// coil count, the per-layer breakdown, the items-attempted count, and
    /// the items-created count. This is the diagnostic channel the user
    /// needs to debug "0 of 0 written" issues — if you see
    /// `[pcbstatorgen::write_coils] coils=0` in the console, the bug is
    /// upstream (in coil generation), not in the KiCad IPC layer.
    ///
    /// ## Dry-run
    /// For a dry-run path that does NOT touch KiCad, see
    /// [`BoardHandle::write_coils_dry_run`]. The Tauri command layer
    /// dispatches to the dry-run method when the user passes
    /// `dry_run: true`, so the public signature of `write_coils` remains
    /// stable for callers that always want a real write.
    pub fn write_coils(
        &mut self,
        coils: &[PhaseCoil],
        config: &LinearMotorConfig,
    ) -> Result<WriteCoilsResult, KiCadError> {
        self.write_coils_inner(coils, config, /* dry_run = */ false)
    }

    /// Dry-run path: convert the coil geometry to items and return a
    /// synthetic [`WriteCoilsResult`] reporting `items_attempted = items.len()`
    /// and `items_created = 0`. The KiCad commit / create flow is **not**
    /// executed, so no tracks land on the board.
    ///
    /// This is used by the UI's "preview" workflow so the user can see what
    /// *would* be written before clicking the real "Write" button. The
    /// [`super::diagnostics::preview_coils`] function is the full-fidelity
    /// preview (with per-layer breakdown) — this method is the lightweight
    /// "I just want the item count" path that reuses the writer.
    pub fn write_coils_dry_run(
        &mut self,
        coils: &[PhaseCoil],
        config: &LinearMotorConfig,
    ) -> Result<WriteCoilsResult, KiCadError> {
        self.write_coils_inner(coils, config, /* dry_run = */ true)
    }

    /// Shared body for [`write_coils`](Self::write_coils) and
    /// [`write_coils_dry_run`](Self::write_coils_dry_run). The `dry_run`
    /// flag short-circuits before the commit/create IPC calls.
    fn write_coils_inner(
        &mut self,
        coils: &[PhaseCoil],
        config: &LinearMotorConfig,
        dry_run: bool,
    ) -> Result<WriteCoilsResult, KiCadError> {
        let items = coils_to_board_items(coils, config);
        let items_attempted = items.len() as u32;

        // --- Diagnostic logging -------------------------------------------
        // Per-layer breakdown so the user can see WHY coils are empty (or
        // not). Tagged with the writer name so it's easy to grep in the
        // Tauri dev console output.
        let mut per_layer: Vec<(u32, usize, usize)> = Vec::new(); // (layer, phases, segs)
        for layer_idx in 0..config.max_layers {
            let layer_coils: Vec<&PhaseCoil> =
                coils.iter().filter(|c| c.layer_idx == layer_idx).collect();
            let segs: usize = layer_coils.iter().map(|c| c.segments.len()).sum();
            if !layer_coils.is_empty() {
                per_layer.push((layer_idx, layer_coils.len(), segs));
            }
        }
        let board_name = self.name().unwrap_or_else(|_| "<unknown>".to_string());
        eprintln!(
            "[pcbstatorgen::write_coils] coils={} board={} topology={:?} \
             phases={} max_layers={} items_attempted={} dry_run={}",
            coils.len(),
            board_name,
            config.coil_topology,
            config.phases,
            config.max_layers,
            items_attempted,
            dry_run,
        );
        if per_layer.is_empty() {
            eprintln!(
                "[pcbstatorgen::write_coils] WARNING: per_layer breakdown is empty — \
                 coil set produced 0 coils. Check phases / max_layers / active_area_length_m."
            );
        } else {
            for (l, n, s) in &per_layer {
                eprintln!(
                    "[pcbstatorgen::write_coils]   layer {l}: {n} phase(s), {s} segment(s)"
                );
            }
        }

        if dry_run {
            // No commit, no socket round-trip. Return the preview.
            eprintln!(
                "[pcbstatorgen::write_coils] dry_run: returning preview with \
                 {items_attempted} item(s), 0 created (no board write performed)"
            );
            return Ok(WriteCoilsResult {
                items_attempted,
                items_created: 0,
                failures: Vec::new(),
                // Dry-run never round-trips with KiCad, so there are no
                // rejection codes to summarise. The UI's preview path
                // does not consult this field.
                failure_summary: Vec::new(),
            });
        }

        let mut commit = Commit::begin(self.client)?;
        let create_resp = commit.create_items(&items, &self.document)?;
        commit.end()?;

        // Tally per-item outcomes. KiCad returns one `ItemCreationResult`
        // per submitted item; we treat `status.code == ISC_OK` as success
        // and capture the first MAX_FAILURES_TO_REPORT error messages for
        // the caller. We do NOT error out on individual rejections — those
        // are surfaced via the result struct so the UI can show them.
        //
        // We also build a code-grouped `failure_summary` so the UI can
        // render a one-line diagnostic like
        // `"99× code=7 (no overlapping layers with the board)"`
        // instead of (or alongside) the first MAX_FAILURES_TO_REPORT
        // individual messages. The summary is computed from **all**
        // per-item outcomes, not just the surfaced ones — so even if
        // MAX_FAILURES_TO_REPORT truncates `failures`, the summary is
        // always complete. This is the property the user needs to debug
        // the 99-of-588 case from the bug report: with the previous
        // MAX_FAILURES_TO_REPORT=10 cap, the user only saw 10 of the 99
        // individual messages and had no way to tell whether the other
        // 89 were the same error or a different one.
        let mut items_created: u32 = 0;
        let mut failures: Vec<String> = Vec::new();
        // `BTreeMap` so the final ordering is deterministic: ties on
        // `count` are broken by `code` ascending, which makes the
        // rendered output stable across runs (good for snapshot tests
        // and easier to diff when debugging).
        let mut failure_codes: std::collections::BTreeMap<i32, u32> =
            std::collections::BTreeMap::new();
        for (i, result) in create_resp.created_items.iter().enumerate() {
            let status = result.status.as_ref();
            let code = status.map(|s| s.code).unwrap_or(0);
            if code == ITEM_STATUS_OK {
                items_created += 1;
            } else {
                // Count this rejection for the summary regardless of
                // whether we surface the individual message below.
                *failure_codes.entry(code).or_insert(0) += 1;
                if failures.len() < MAX_FAILURES_TO_REPORT {
                    let msg = status
                        .map(|s| s.error_message.clone())
                        .filter(|m| !m.is_empty())
                        .unwrap_or_else(|| format!("<no error message>"));
                    failures.push(format!("item {i}: code={code}: {msg}"));
                }
            }
        }

        // Materialise the summary as a Vec sorted by count descending
        // (most-frequent failure first), ties broken by code ascending.
        // This is the most useful ordering for the UI: the dominant
        // error appears at the top of the warning banner.
        let mut failure_summary: Vec<(i32, u32)> = failure_codes
            .into_iter()
            .map(|(code, count)| (code, count))
            .collect();
        failure_summary.sort_by(|(code_a, count_a), (code_b, count_b)| {
            // Primary: count descending (b.count.cmp(&a.count))
            // Secondary: code ascending (a.code.cmp(&b.code))
            count_b.cmp(count_a).then(code_a.cmp(code_b))
        });

        eprintln!(
            "[pcbstatorgen::write_coils] done: items_attempted={} items_created={} \
             failures={} failure_codes={:?}",
            items_attempted,
            items_created,
            failures.len(),
            failure_summary,
        );

        Ok(WriteCoilsResult {
            items_attempted,
            items_created,
            failures,
            failure_summary,
        })
    }
}

// Keep the response type URL around for documentation/forward-compat.
#[allow(dead_code)]
const _RESPONSE_TYPE_URLS: &[&str] = &[BOARD_ENABLED_LAYERS_RESPONSE_TYPE_URL];
