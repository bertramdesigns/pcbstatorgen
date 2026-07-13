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
    /// Returns the total number of items created.
    pub fn write_coils(
        &mut self,
        coils: &[PhaseCoil],
        config: &LinearMotorConfig,
    ) -> Result<u32, KiCadError> {
        let items = coils_to_board_items(coils, config);
        let n_items = items.len() as u32;

        let mut commit = Commit::begin(self.client)?;
        let create_resp = commit.create_items(&items, &self.document)?;
        commit.end()?;

        // Surface per-item creation failures if any occurred.
        for result in &create_resp.created_items {
            if let Some(status) = &result.status {
                // ISC_OK = 1
                if status.code != 1 {
                    return Err(KiCadError::Protocol(format!(
                        "item creation failed (code={}): {}",
                        status.code, status.error_message
                    )));
                }
            }
        }

        Ok(n_items)
    }
}

// Keep the response type URL around for documentation/forward-compat.
#[allow(dead_code)]
const _RESPONSE_TYPE_URLS: &[&str] = &[BOARD_ENABLED_LAYERS_RESPONSE_TYPE_URL];
