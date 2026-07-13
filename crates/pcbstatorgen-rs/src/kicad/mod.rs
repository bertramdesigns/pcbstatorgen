//! KiCad IPC API protobuf types and client.
//!
//! This module wraps the `prost`-generated code for the vendored KiCad 10 IPC
//! `.proto` files (compiled at build time by `build.rs`). The full generated
//! tree lives under the `proto` submodule and is organised by KiCad package:
//!
//! - `proto::common` — `ApiRequest`, `ApiResponse`, `ApiStatusCode`, headers
//! - `proto::common::types` — `Vector2`, `Distance`, `Kiid`, `DocumentSpecifier`,
//!   `ItemHeader`, `KiCadVersion`, `LockedState`, ...
//! - `proto::common::commands` — `BeginCommit`, `EndCommit`, `CreateItems`,
//!   `CreateItemsResponse`, `GetItems`, `Ping`, `GetVersion`, ...
//! - `proto::common::project` — `NetClass`, `TextVariables`
//! - `proto::board` — `BoardStackup`, `BoardSettings`, `BoardDesignRules`
//! - `proto::board::types` — `Track`, `Via`, `Net`, `BoardLayer`, `PadStack`, ...
//! - `proto::board::commands` — board-level commands
//! - `proto::schematic::types` — schematic-level types
//!
//! Key types are re-exported at the module root for convenience.
//!
//! ## Submodules
//! - [`client`] — [`KiCadClient`], [`KicadTransport`] trait, [`MockTransport`]
//! - [`errors`] — [`KiCadError`]
//! - [`layer_map`] — layer-index → [`BoardLayer`] mapping + unit conversion
//! - [`writer`] — pure `coils_to_board_items()` converter
//! - [`commit`] — [`Commit`] atomic commit handle
//! - [`board`] — [`BoardHandle`] high-level board operations
//! - [`diagnostics`] — board-diagnostics + pre-write validation + dry-run
//!   preview (the "robust KiCad connection" feature).

pub mod board;
pub mod client;
pub mod commit;
pub mod diagnostics;
pub mod errors;
pub mod layer_map;
pub mod writer;

/// Raw generated protobuf modules for the KiCad IPC API.
///
/// The `include!` pulls in `OUT_DIR/kiapi.rs`, which prost-build emits as the
/// top-level umbrella module for the `kiapi.*` package tree.
pub mod proto {
    include!(concat!(env!("OUT_DIR"), "/kiapi.rs"));
}

pub use client::{KiCadClient, KicadTransport, MockTransport};
pub use errors::KiCadError;
pub use proto::common::{
    ApiRequest, ApiRequestHeader, ApiResponse, ApiResponseHeader, ApiResponseStatus, ApiStatusCode,
};
pub use proto::common::commands::{
    BeginCommit, BeginCommitResponse, CommitAction, CreateItems, CreateItemsResponse, EndCommit,
    EndCommitResponse,
};
pub use proto::common::types::{
    AxisAlignment, DocumentSpecifier, DocumentType, Distance, ItemHeader, ItemRequestStatus, Kiid,
    KiCadVersion, LibraryIdentifier, LockedState, ProjectSpecifier, Vector2, Vector3,
};
pub use proto::board::types::{BoardLayer, Net, Track, Via};

// Phase 7 re-exports.
pub use board::BoardHandle;
pub use commit::Commit;
pub use diagnostics::{
    get_board_diagnostics, preview_coils, validate_write_preconditions, BoardDiagnostics,
    CoilPreview, CoilPreviewLayer, PreconditionLevel, PreconditionWarning,
};
pub use layer_map::{layer_idx_to_board_layer, m_to_nm, via_pad_diameter_nm};
pub use writer::coils_to_board_items;
