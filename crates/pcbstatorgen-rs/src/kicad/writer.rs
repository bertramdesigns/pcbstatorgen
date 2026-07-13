//! Pure conversion of coil geometry into KiCad board items (Tracks + Vias).
//!
//! The core function [`coils_to_board_items`] is **pure** — it does not touch
//! any socket or client. This makes it trivially testable offline.
//!
//! ## Output
//! Each [`crate::geometry::PhaseCoil`] is converted into:
//! - one [`Track`] proto per [`crate::geometry::CoilSegment`], and
//! - one [`Via`] proto per `center_via_positions` entry.
//!
//! All items are packed into `google.protobuf.Any` messages ready for
//! `CreateItems`.

use prost::Message;
use prost_types::Any;

use crate::config::LinearMotorConfig;
use crate::geometry::PhaseCoil;
use crate::kicad::proto::board::types::{
    DrillProperties, DrillShape, PadStack, PadStackLayer, PadStackShape, PadStackType,
    UnconnectedLayerRemoval, ViaDrillCappingMode, ViaDrillFillingMode, ViaType,
};
use crate::kicad::{BoardLayer, Distance, Kiid, LockedState, Net, Track, Vector2, Via};
use crate::kicad::layer_map::{layer_idx_to_board_layer, m_to_nm, via_pad_diameter_nm};

/// Type URL prefix used when packing items into `google.protobuf.Any`.
const TYPE_URL_PREFIX: &str = "type.googleapis.com";

/// Pack a prost message into a `google.protobuf.Any` with the given short
/// protobuf type name (e.g. `"kiapi.board.types.Track"`).
fn pack_any<T: Message>(full_name: &str, msg: &T) -> Any {
    let mut buf = Vec::new();
    msg.encode(&mut buf)
        .expect("encoding a KiCad board item should never fail");
    Any {
        type_url: format!("{TYPE_URL_PREFIX}/{full_name}"),
        value: buf,
    }
}

/// Convert coil geometry into KiCad board items (Tracks and Vias).
///
/// Each `CoilSegment` becomes a [`Track`] proto message. Each
/// `center_via_position` becomes a [`Via`] proto message. All coordinates are
/// converted from metres to nanometres. Phase nets are named `"/A"`, `"/B"`,
/// `"/C"`, etc.
///
/// ## Centering
/// The coil generators emit geometry with x = 0 at the start of the active
/// area (i.e. extending from 0 to `active_area_length_m`). A typical KiCad
/// board is centered on the origin, so writing those coordinates verbatim
/// pushes the right half of the coil set off-board. To avoid that we
/// subtract `active_area_length_m / 2` from every x coordinate so the
/// coils straddle x = 0 (active area runs from
/// `-active_area_length_m / 2` to `+active_area_length_m / 2`). Y coordinates
/// are passed through unchanged — the board is already centered on y = 0,
/// and y in `[0, board_width_m / 2]` is the "active" half of the coil.
///
/// This is a **pure function** — no socket I/O. It produces a list of
/// `google.protobuf.Any`-wrapped items ready for `CreateItems`.
pub fn coils_to_board_items(coils: &[PhaseCoil], config: &LinearMotorConfig) -> Vec<Any> {
    let trace_width_nm = m_to_nm(config.min_trace_m);
    let drill_nm = m_to_nm(config.min_via_drill_m);
    let pad_diameter_nm = via_pad_diameter_nm(config.min_via_drill_m, config.min_via_annular_ring_m);

    // Centering offset: shift the whole active area so it sits symmetrically
    // about x = 0. Coils are generated starting at x = 0; we move them to
    // x ∈ [-active_area_length_m/2, +active_area_length_m/2] so a centered
    // KiCad board shows the full coil set instead of only the leftmost half.
    let x_offset_m = config.active_area_length_m / 2.0;
    let x_offset_nm = m_to_nm(x_offset_m);

    // For a through via, the `PadStack.layers` field is the set of copper
    // layers the via passes through. KiCad's own `PCB_VIA::GetLayerSet()`
    // returns `LSET::AllCuMask(copper_layer_count)` for a through via, so
    // we mirror that here. The set is used by KiCad to know which layers
    // the via's annular rings may appear on, so an incomplete set could
    // produce a via that doesn't show up on inner copper layers. See
    // `PadStack.layers` validation in `api_pcb_utils.cpp::UnpackLayerSet`.
    //
    // **IMPORTANT:** This list MUST match the layers the *board actually
    // has*, not the DFM upper limit. `config.num_layers` is the user's
    // actual layer selection (e.g. 4 on a 4-layer board); `config.max_layers`
    // is the DFM ceiling (e.g. 12 — the upper limit the user's fabricator
    // supports, which may exceed the board's actual layer count). If we
    // populated `board_layers` from `max_layers`, the emitted via's
    // `PadStack.layers` would include entries like `In3_Cu..In11_Cu` that
    // the live board does not have. KiCad's `CreateItems` validator
    // (`UnpackLayerSet`) rejects any item whose layer set is not a subset
    // of the board's actual layer set with `ISC_INVALID_DATA` (code 7)
    // and the message "attempted to add item with no overlapping layers
    // with the board". We therefore use `config.num_layers` here so the
    // emitted set always matches the live board.
    let board_layers: Vec<i32> = (0..config.num_layers)
        .map(|idx| layer_idx_to_board_layer(idx, config.num_layers) as i32)
        .collect();

    let mut items: Vec<Any> = Vec::new();

    for coil in coils {
        // **Track layer assignment (round-5 fix):** the track's `layer`
        // field MUST be derived from `config.num_layers` (the actual board
        // the user is writing to), NOT `config.max_layers` (the DFM upper
        // limit). The previous code used `config.max_layers` here, which
        // caused a secondary form of the "no overlapping layers with the
        // board" rejection that the round-4 fix only addressed for VIAS.
        //
        // Failure mode: a `coil.layer_idx = num_layers - 1` (the top
        // layer) would be mapped to `In{num_layers-1}_Cu` (an inner
        // layer of a `max_layers`-capable board) when `max_layers >
        // num_layers`, instead of the correct `F_Cu` (= the top layer of
        // the `num_layers`-layer board). For example, on a 4-layer board
        // (`num_layers=4, max_layers=12`), a top-layer coil at
        // `layer_idx=3` was being mapped to `In3_Cu`, which the live
        // 4-layer board does not have. KiCad's `UnpackLayerSet` then
        // rejected every top-layer track with `ISC_INVALID_DATA` (code 7)
        // and "attempted to add item with no overlapping layers with the
        // board".
        //
        // The fix mirrors the round-4 via-layer fix: use `num_layers` so
        // `layer_idx == num_layers - 1` is correctly recognised as the
        // top of the actual board and mapped to `F_Cu` via
        // `layer_idx_to_board_layer`'s `idx == total_layers - 1` branch.
        let layer = layer_idx_to_board_layer(coil.layer_idx, config.num_layers);
        let net_name = format!("/{}", coil.phase_name);
        let net = Net {
            code: None,
            name: net_name,
        };

        // --- Tracks: one per CoilSegment ---
        for seg in &coil.segments {
            let track = Track {
                id: Some(Kiid { value: String::new() }),
                start: Some(Vector2 {
                    x_nm: m_to_nm(seg.start.0) - x_offset_nm,
                    y_nm: m_to_nm(seg.start.1),
                }),
                end: Some(Vector2 {
                    x_nm: m_to_nm(seg.end.0) - x_offset_nm,
                    y_nm: m_to_nm(seg.end.1),
                }),
                width: Some(Distance { value_nm: trace_width_nm }),
                locked: LockedState::LsUnlocked as i32,
                layer: layer as i32,
                net: Some(net.clone()),
            };
            items.push(pack_any("kiapi.board.types.Track", &track));
        }

        // --- Vias: one per center_via_position ---
        for &pos in &coil.center_via_positions {
            let via = build_through_via(
                (pos.0 - x_offset_m, pos.1),
                drill_nm,
                pad_diameter_nm,
                net.clone(),
                &board_layers,
            );
            items.push(pack_any("kiapi.board.types.Via", &via));
        }
    }

    items
}

/// Build a minimal through-hole [`Via`] proto at `pos` (metres) with the given
/// drill and pad diameters (nanometres).
///
/// `board_layers` is the list of copper layers the via passes through, in
/// ascending order (B_Cu first, F_Cu last). It is used to populate
/// `PadStack.layers` — KiCad's own `PCB_VIA::GetLayerSet()` returns
/// `LSET::AllCuMask(copper_layer_count)` for a through via, so we mirror
/// that here.
///
/// ## Bug 5 fix (round 1: `unconnected_layer_removal`)
///
/// Pre-fix, this function set `unconnected_layer_removal: 0`, which maps
/// to the proto enum variant `UnconnectedLayerRemoval::UlrUnknown`
/// (`ULR_UNKNOWN = 0` in `board_types.proto`). KiCad's IPC API treats
/// `ULR_UNKNOWN` as an invalid value for the field (it is a sentinel
/// "not set" marker, not a real configuration) and rejects the entire
/// `Via` proto with `could not unpack PCB_VIA from request`.
///
/// The fix sets the field to a real, valid variant —
/// `UlrKeep` (`ULR_KEEP = 1`, "Keep annular rings on all layers") — which
/// is the correct behaviour for a basic through-hole via on a plain
/// two-layer board. KiCad accepts this round-trip cleanly.
///
/// ## Bug 5 fix (round 2: `capped`, `filled`, `custom_anchor_shape`)
///
/// The round-1 fix was insufficient — the same `could not unpack PCB_VIA`
/// error persisted. The root cause was that the `PadStack` carries several
/// other singular proto3 enum fields whose `_UNKNOWN = 0` sentinel is also
/// rejected by KiCad's `PCB_VIA` unpacker:
///
/// - `DrillProperties.capped` (`ViaDrillCappingMode`): the round-1 code
///   passed the bare `i32` literal `0`, which is `VDCM_UNKNOWN` (the
///   proto's "not set" sentinel). KiCad rejects UNKNOWN. The fix sets
///   `VdcmUncapped` (2), the natural choice for an uncapped PTH via.
/// - `DrillProperties.filled` (`ViaDrillFillingMode`): same issue, the
///   round-1 code passed `0` = `VDFM_UNKNOWN`. The fix sets
///   `VdfmUnfilled` (2), the natural choice for an unfilled PTH via.
/// - `PadStackLayer.custom_anchor_shape` (`PadStackShape`): the field is
///   only meaningful when `shape == PSS_CUSTOM`, so in principle
///   `PssUnknown` should be a benign sentinel. However KiCad's strict
///   unpacker rejects the UNKNOWN value, so we now set it to
///   `PssCircle` (1) to match the per-layer `shape`.
///
/// ## Bug 5 fix (round 3: `PadStackLayer.layer` for `PadStackType::PstNormal`)
///
/// The previous "round 1" and "round 2" fixes still did not address the
/// root cause of the `could not unpack PCB_VIA from request` error. The
/// actual culprit is `PadStack.copper_layers[*].layer` for a
/// `PadStackType::PstNormal` padstack.
///
/// In KiCad's C++ side (`pcbnew/padstack.h:177`):
///
/// ```cpp
/// static constexpr PCB_LAYER_ID ALL_LAYERS = F_Cu;
/// ```
///
/// And in `pcbnew/padstack.cpp:185-194`:
/// ```cpp
/// bool PADSTACK::unpackCopperLayer( const PadStackLayer& aProto )
/// {
///     PCB_LAYER_ID layer = FromProtoEnum<PCB_LAYER_ID, BoardLayer>( aProto.layer() );
///
///     if( m_mode == MODE::NORMAL && layer != ALL_LAYERS )
///         return false;
///
///     if( m_mode == MODE::FRONT_INNER_BACK && layer != F_Cu && layer != INNER_LAYERS && layer != B_Cu )
///         return false;
///     ...
/// }
/// ```
///
/// The pre-fix code emitted TWO `PadStackLayer` entries (one for `F_Cu`
/// and one for `B_Cu`). Since `ALL_LAYERS = F_Cu`, the C++ deserializer
/// rejected the `B_Cu` entry and returned `false`. This propagated up
/// through `PADSTACK::Deserialize` (which iterates over `copper_layers` and
/// returns `false` if any entry fails) and `PCB_VIA::Deserialize` (which
/// returns `false` on `m_padStack.Deserialize` failure), surfacing as the
/// envelope-level `could not unpack PCB_VIA from request` error.
///
/// The fix emits a SINGLE `PadStackLayer` with `layer = BlFCu` (= C++
/// `ALL_LAYERS`). For `PadStackType::PstNormal` (i.e. `PADSTACK::MODE::NORMAL`),
/// a single padstack layer is the correct representation — KiCad's own
/// `PADSTACK::ForEachUniqueLayer()` invokes the serializer callback exactly
/// once with `ALL_LAYERS` for `MODE::NORMAL` (see
/// `pcbnew/padstack.cpp:1241-1246`), so the round-trip representation is
/// also a single entry with `layer = F_Cu`.
fn build_through_via(
    pos: (f64, f64),
    drill_nm: i64,
    pad_diameter_nm: i64,
    net: Net,
    board_layers: &[i32],
) -> Via {
    let pad_size = Vector2 {
        x_nm: pad_diameter_nm,
        y_nm: pad_diameter_nm,
    };
    let drill_diameter = Vector2 {
        x_nm: drill_nm,
        y_nm: drill_nm,
    };

    // For `PadStackType::PstNormal` (= C++ `PADSTACK::MODE::NORMAL`), a
    // padstack has a SINGLE shape that is applied to all copper layers. The
    // `PadStackLayer.layer` field therefore carries the C++ `ALL_LAYERS`
    // sentinel, which is defined as `static constexpr PCB_LAYER_ID ALL_LAYERS = F_Cu`
    // in `pcbnew/padstack.h:177`. Any value other than `F_Cu` is rejected by
    // `PADSTACK::unpackCopperLayer` with `return false`, which causes
    // `PCB_VIA::Deserialize` to fail with "could not unpack PCB_VIA from
    // request" (see function-level doc for details).
    let pad_layer = PadStackLayer {
        layer: BoardLayer::BlFCu as i32,
        shape: PadStackShape::PssCircle as i32,
        size: Some(pad_size),
        corner_rounding_ratio: 0.0,
        chamfer_ratio: 0.0,
        chamfered_corners: None,
        custom_shapes: Vec::new(),
        // custom_anchor_shape is set to PssCircle (1) to match `shape`;
        // KiCad rejects the proto3 `PssUnknown` sentinel here just like it
        // does for DrillProperties.capped/filled.
        custom_anchor_shape: PadStackShape::PssCircle as i32,
        zone_settings: None,
        trapezoid_delta: None,
        offset: None,
    };

    let pad_stack = PadStack {
        r#type: PadStackType::PstNormal as i32,
        // The `layers` field is the set of copper layers the via passes
        // through. For a through via, this is every copper layer of the
        // board — KiCad's own `PCB_VIA::GetLayerSet()` returns
        // `LSET::AllCuMask(copper_layer_count)` for `VIATYPE::THROUGH`. The
        // value is consumed by `PADSTACK::Deserialize::SetLayerSet` and
        // then immediately reset by `PCB_VIA::Deserialize`, but having the
        // full set is more faithful to KiCad's own output and ensures the
        // padstack's layer set is correct if the via is later reused.
        layers: board_layers.to_vec(),
        drill: Some(DrillProperties {
            start_layer: BoardLayer::BlFCu as i32,
            end_layer: BoardLayer::BlBCu as i32,
            diameter: Some(drill_diameter),
            shape: DrillShape::DsCircle as i32,
            // VdcmUncapped (2): a stock PTH via is not capped. The proto3
            // default `0` = `VdcmUnknown` is the "not set" sentinel and
            // KiCad's PCB_VIA unpacker rejects it.
            capped: ViaDrillCappingMode::VdcmUncapped as i32,
            // VdfmUnfilled (2): a stock PTH via is not filled. Same
            // sentinel-rejection issue as `capped`.
            filled: ViaDrillFillingMode::VdfmUnfilled as i32,
        }),
        // ULR_KEEP = 1 ("Keep annular rings on all layers"). Valid
        // round-trip value; ULR_UNKNOWN (0) is the proto's "not set"
        // sentinel and KiCad's IPC rejects it.
        unconnected_layer_removal: UnconnectedLayerRemoval::UlrKeep as i32,
        // Single entry for `MODE::NORMAL` — see the function-level doc and
        // `PadStackLayer.layer` field comment above for why this must be
        // exactly one entry with `layer = BlFCu`.
        copper_layers: vec![pad_layer],
        angle: None,
        front_outer_layers: None,
        back_outer_layers: None,
        zone_settings: None,
        secondary_drill: None,
        tertiary_drill: None,
        front_post_machining: None,
        back_post_machining: None,
    };

    Via {
        id: Some(Kiid { value: String::new() }),
        position: Some(Vector2 {
            x_nm: m_to_nm(pos.0),
            y_nm: m_to_nm(pos.1),
        }),
        pad_stack: Some(pad_stack),
        locked: LockedState::LsUnlocked as i32,
        net: Some(net),
        r#type: ViaType::VtThrough as i32,
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::LinearMotorConfig;
    use crate::geometry::{PhaseCoil, WaveWindingGenerator};
    use crate::units::{mm, mils_to_m};

    fn test_config(layers: u32) -> LinearMotorConfig {
        LinearMotorConfig {
            name: Some("test".into()),
            active_area_length_m: mm(48.0),
            magnet_dims_m: [mm(10.0), mm(10.0), mm(4.0)],
            magnet_count: 2,
            magnet_pitch_m: mm(24.0),
            phases: 3,
            target_force_n: 0.1,
            max_current_a: 1.0,
            min_trace_m: mils_to_m(5.0),
            min_space_m: mils_to_m(5.0),
            min_via_drill_m: mm(0.2),
            min_via_annular_ring_m: mm(0.1),
            board_width_m: mm(20.0),
            air_gap_m: mm(0.5),
            max_layers: layers,
            ..LinearMotorConfig::default()
        }
    }

    #[test]
    fn test_item_count_matches_segments() {
        // max_layers=3, phases=3 → each phase on a single layer; no vias.
        let cfg = test_config(3);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let total_segments: usize = coils.iter().map(|c| c.segments.len()).sum();
        let items = coils_to_board_items(&coils, &cfg);
        assert_eq!(items.len(), total_segments, "no vias in this coil set");
    }

    #[test]
    fn test_items_are_tracks_for_no_vias() {
        // max_layers=3, phases=3 → each phase on a single layer; no vias.
        let cfg = test_config(3);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let items = coils_to_board_items(&coils, &cfg);
        for any in &items {
            assert!(
                any.type_url.ends_with("kiapi.board.types.Track"),
                "expected Track, got: {}",
                any.type_url
            );
        }
    }

    #[test]
    fn test_track_coordinates_in_nanometres() {
        let cfg = test_config(4);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let items = coils_to_board_items(&coils, &cfg);

        // Decode the first item back to a Track and verify coordinate scaling.
        // Coils are centered on x = 0, so the wire x_nm = (m * 1e9) - offset_nm.
        let track: Track = Track::decode(items[0].value.as_slice()).expect("decode Track");
        let seg0 = &coils.iter().next().unwrap().segments[0];
        let offset_nm = m_to_nm(cfg.active_area_length_m / 2.0);
        let expected_start_x = (seg0.start.0 * 1e9).round() as i64 - offset_nm;
        assert_eq!(track.start.unwrap().x_nm, expected_start_x);
    }

    #[test]
    fn test_track_width_matches_config() {
        let cfg = test_config(4);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let items = coils_to_board_items(&coils, &cfg);
        let expected = (cfg.min_trace_m * 1e9).round() as i64;
        let track: Track = Track::decode(items[0].value.as_slice()).expect("decode Track");
        assert_eq!(track.width.unwrap().value_nm, expected);
    }

    #[test]
    fn test_net_names() {
        let cfg = test_config(4);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let items = coils_to_board_items(&coils, &cfg);

        let track_a: Track = Track::decode(items[0].value.as_slice()).expect("decode A");
        assert_eq!(track_a.net.unwrap().name, "/A");

        // Find a phase-B track: coils[1] is phase B.
        let phase_b_items: Vec<&Any> = items
            .iter()
            .filter(|a| a.type_url.ends_with("Track"))
            .collect();
        // coils[1]'s first segment is somewhere in the item list; iterate to find it.
        let coils_b = &coils[1];
        let seg0 = &coils_b.segments[0];
        let offset_nm = m_to_nm(cfg.active_area_length_m / 2.0);
        let target_x_nm = (seg0.start.0 * 1e9).round() as i64 - offset_nm;
        for any in phase_b_items {
            let t: Track = Track::decode(any.value.as_slice()).expect("decode");
            if t.start.unwrap().x_nm == target_x_nm {
                assert_eq!(t.net.unwrap().name, "/B");
                return;
            }
        }
        panic!("did not find phase B track");
    }

    /// Net-name regression test for the user's reported scenario:
    /// `test/MagneticFader.kicad_pcb` had 588 board items — all on `(net "/A")`,
    /// short-circuiting the three phases. The root cause investigation traced
    /// through:
    ///
    /// 1. [`WaveWindingGenerator::generate_phase`] (wave_winding.rs:288) sets
    ///    `phase_name = PHASE_NAMES[phase_idx % 6]` — A, B, C, D, E, F.
    /// 2. [`CoilGenerator::generate`] (wave_winding.rs:226) maps over
    ///    `0..config.phases` so each call sees a distinct `phase_idx`.
    /// 3. [`coils_to_board_items`] (writer.rs:125) reads
    ///    `coil.phase_name` per coil and emits
    ///    `Net { name: format!("/{}", coil.phase_name) }`.
    ///
    /// All three sites produce the correct per-phase value, so the current
    /// source code already produces three distinct nets `/A`, `/B`, `/C` for
    /// a 3-phase config. The user's saved board file must therefore have
    /// been produced by a build of the code that pre-dated this round's
    /// net-name integration test (or a stale build artifact).
    ///
    /// This test is the regression guard. It walks the same code path as
    /// `write_coils_to_board` (the Tauri command in
    /// `app/src-tauri/src/commands.rs:512`) — `gen.generate(&core, layer)`
    /// for every `layer in 0..num_layers`, then `coils_to_board_items` —
    /// and asserts:
    ///
    /// - Exactly three distinct net names appear in the emitted board items.
    /// - The three net names are exactly `/A`, `/B`, `/C`.
    /// - The same three net names appear in the Via items (the writer
    ///   passes the same `Net` to both the per-coil `Track` items and the
    ///   per-coil `Via` items, so the invariant must hold for both).
    /// - The total number of items is the same as the 588 the user observed
    ///   in their board file (396 tracks + 192 vias = 588), confirming the
    ///   test scenario matches the reported one.
    #[test]
    fn test_distinct_phase_nets_for_three_phase_config() {
        // The user's actual scenario: 3 phases, 4 layers, 12 magnets,
        // 12 mm magnet pitch, 195 mm active area. This is also
        // `LinearMotorConfig::default()`.
        let cfg = LinearMotorConfig {
            name: Some("MagneticFader".into()),
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
            max_layers: 12,
            ..LinearMotorConfig::default()
        };

        // Same generation flow as the Tauri command:
        //   for layer in 0..num_layers {
        //       coils.extend(gen.generate(&core, layer));
        //   }
        let mut coils = Vec::new();
        for layer in 0..cfg.num_layers {
            coils.extend(WaveWindingGenerator.generate(&cfg, layer));
        }
        // 3 phases × 4 layers = 12 PhaseCoils, each with a distinct
        // (phase_idx, layer_idx) — the writer does not deduplicate.
        assert_eq!(coils.len(), 12);

        // Sanity: the generator assigns a distinct `phase_name` per
        // `phase_idx` (A, B, C in cycle 0..phases).
        let phase_names: std::collections::BTreeSet<&str> =
            coils.iter().map(|c| c.phase_name.as_str()).collect();
        assert_eq!(
            phase_names,
            std::collections::BTreeSet::from(["A", "B", "C"]),
            "generator must assign distinct phase names A, B, C across 3 phases"
        );

        // The user reported 588 items; this is the expected count for the
        // default config (396 tracks + 192 vias, with all 3 phases
        // multi-layer because max_layers=12). The exact number isn't the
        // critical assertion — the net distribution is — but matching it
        // confirms the test exercises the same scenario.
        let items = coils_to_board_items(&coils, &cfg);
        assert_eq!(
            items.len(),
            588,
            "expected 588 items (396 tracks + 192 vias) for the user's 3-phase, \
             4-layer, 12-magnet, 195-mm config; got {}",
            items.len()
        );

        // Count Track + Via net-name occurrences and assert the three
        // expected nets are present and no others.
        let mut track_net_counts: std::collections::BTreeMap<String, u32> =
            std::collections::BTreeMap::new();
        let mut via_net_counts: std::collections::BTreeMap<String, u32> =
            std::collections::BTreeMap::new();
        for any in &items {
            if any.type_url.ends_with("kiapi.board.types.Track") {
                let t: Track = Track::decode(any.value.as_slice()).expect("decode Track");
                let net = t.net.expect("Track must carry a net");
                *track_net_counts.entry(net.name).or_insert(0) += 1;
            } else if any.type_url.ends_with("kiapi.board.types.Via") {
                let v: Via = Via::decode(any.value.as_slice()).expect("decode Via");
                let net = v.net.expect("Via must carry a net");
                *via_net_counts.entry(net.name).or_insert(0) += 1;
            }
        }

        // Critical assertion: the 3-phase config must produce 3 distinct
        // nets across both tracks and vias. The pre-fix code (or a stale
        // build) would have collapsed everything onto a single net — the
        // exact symptom the user reported in their board file.
        let expected_track_keys: std::collections::BTreeSet<String> =
            ["/A".to_string(), "/B".to_string(), "/C".to_string()]
                .into_iter()
                .collect();
        let track_keys: std::collections::BTreeSet<String> =
            track_net_counts.keys().cloned().collect();
        assert_eq!(
            track_keys, expected_track_keys,
            "track nets must be exactly {{/A, /B, /C}} for 3-phase config; got {:?}",
            track_net_counts
        );
        let via_keys: std::collections::BTreeSet<String> =
            via_net_counts.keys().cloned().collect();
        assert_eq!(
            via_keys, expected_track_keys,
            "via nets must be exactly {{/A, /B, /C}} for 3-phase config; got {:?}",
            via_net_counts
        );

        // Each phase must own a non-zero share of both tracks and vias.
        // For the 3-phase, 4-layer, default-pitch config: 33 segments /
        // phase / layer × 4 layers = 132 tracks per phase; 16 vias /
        // phase / layer × 4 layers = 64 vias per phase (all 3 phases
        // are multi-layer because max_layers=12).
        for net_name in ["/A", "/B", "/C"] {
            let track_count = track_net_counts.get(net_name).copied().unwrap_or(0);
            assert!(
                track_count > 0,
                "phase {} must own at least one Track; got 0 (net_counts={:?})",
                net_name, track_net_counts
            );
            let via_count = via_net_counts.get(net_name).copied().unwrap_or(0);
            assert!(
                via_count > 0,
                "phase {} must own at least one Via; got 0 (net_counts={:?})",
                net_name, via_net_counts
            );
        }
        // And the per-phase counts must be exactly equal — every phase
        // gets the same number of segments and the same number of vias
        // under the default round-robin / uniform-pitch configuration.
        let track_counts: std::collections::BTreeSet<u32> =
            track_net_counts.values().copied().collect();
        assert_eq!(
            track_counts.len(),
            1,
            "all 3 phases must own the same number of Tracks; got {:?}",
            track_net_counts
        );
        let via_counts: std::collections::BTreeSet<u32> =
            via_net_counts.values().copied().collect();
        assert_eq!(
            via_counts.len(),
            1,
            "all 3 phases must own the same number of Vias; got {:?}",
            via_net_counts
        );
    }

    /// Stricter version of the regression test: instead of just checking
    /// that the three nets are distinct, assert that the `coil.phase_name`
    /// field on every generated coil is exactly the per-phase letter
    /// (A, B, C) — i.e. catches any future regression where
    /// `generate_phase` accidentally emits the same `phase_name` for
    /// every `phase_idx` (the root cause of the user's "all /A" symptom).
    #[test]
    fn test_phase_name_per_phase_idx_is_distinct() {
        // 3-phase config (small magnet count so the test is fast).
        let cfg = test_config(4);
        // Iterate one layer at a time so we catch per-layer or
        // per-phase_idx aliasing independently.
        for layer in 0..cfg.num_layers {
            let coils = WaveWindingGenerator.generate(&cfg, layer);
            assert_eq!(
                coils.len() as u32,
                cfg.phases,
                "layer {}: expected {} coils, got {}",
                layer,
                cfg.phases,
                coils.len()
            );
            for (i, coil) in coils.iter().enumerate() {
                let expected = crate::geometry::PHASE_NAMES[i];
                assert_eq!(
                    coil.phase_name, expected,
                    "layer {} coil[{}]: phase_name must be {:?} (phase_idx={}); got {:?}",
                    layer, i, expected, coil.phase_idx, coil.phase_name
                );
            }
        }
    }

    #[test]
    fn test_layer_assignment_4_layer_board() {
        let cfg = test_config(4);
        // Generate coils on layer 0 (bottom) and layer 3 (top).
        let mut coils = WaveWindingGenerator.generate(&cfg, 0);
        let top_coils = WaveWindingGenerator.generate(&cfg, 3);
        coils.extend(top_coils);

        let items = coils_to_board_items(&coils, &cfg);

        // First item is a Track from layer 0 → B_Cu.
        let t0: Track = Track::decode(items[0].value.as_slice()).expect("decode");
        assert_eq!(t0.layer, BoardLayer::BlBCu as i32);

        // Find a Track on layer 3 → F_Cu. Filter to Track items only — some
        // multi-layer coils emit inter-layer end-turn vias (ADR-0001), which
        // cannot be decoded as Track protos.
        let top_track_any = items
            .iter()
            .find(|a| {
                if !a.type_url.ends_with("kiapi.board.types.Track") {
                    return false;
                }
                let t: Track = Track::decode(a.value.as_slice()).expect("decode");
                t.layer == BoardLayer::BlFCu as i32
            })
            .expect("expected at least one F_Cu track");
        let t_top: Track = Track::decode(top_track_any.value.as_slice()).expect("decode");
        assert_eq!(t_top.layer, BoardLayer::BlFCu as i32);
    }

    #[test]
    fn test_via_construction() {
        use crate::geometry::CoilSegment;

        let cfg = test_config(4);
        // Note: the via center is offset by the same centering shift as the
        // track x coordinates — see `coils_to_board_items`.
        let x_offset_m = cfg.active_area_length_m / 2.0;
        let coil = PhaseCoil {
            phase_idx: 0,
            layer_idx: 0,
            segments: vec![CoilSegment {
                start: (0.0, 0.0),
                end: (0.0, 0.02),
                is_active: true,
            }],
            phase_name: "A".into(),
            center_via_positions: vec![(0.001, 0.002)],
            ..PhaseCoil::default()
        };
        let items = coils_to_board_items(&[coil], &cfg);
        // 1 track + 1 via
        assert_eq!(items.len(), 2);
        let via_any = items
            .iter()
            .find(|a| a.type_url.ends_with("kiapi.board.types.Via"))
            .expect("expected a Via");
        let via: Via = Via::decode(via_any.value.as_slice()).expect("decode Via");
        let pos = via.position.unwrap();
        let expected_x_nm = m_to_nm(0.001 - x_offset_m);
        assert_eq!(pos.x_nm, expected_x_nm);
        assert_eq!(pos.y_nm, 2_000_000);
        assert_eq!(via.r#type, ViaType::VtThrough as i32);
        let ps = via.pad_stack.unwrap();
        assert_eq!(ps.r#type, PadStackType::PstNormal as i32);
        // Round-3 fix: `PadStackType::PstNormal` (= C++ `PADSTACK::MODE::NORMAL`)
        // requires exactly one `PadStackLayer` in `copper_layers`, with
        // `layer = BlFCu` (= C++ `ALL_LAYERS`). The C++ deserializer rejects
        // any other layer for `MODE::NORMAL`.
        assert_eq!(
            ps.copper_layers.len(),
            1,
            "PstNormal padstack must have exactly one PadStackLayer (round 3 fix); got {}",
            ps.copper_layers.len()
        );
        let pad = &ps.copper_layers[0];
        assert_eq!(
            pad.layer,
            BoardLayer::BlFCu as i32,
            "PstNormal PadStackLayer.layer must be BlFCu (= C++ ALL_LAYERS) for KiCad to accept the via"
        );
        assert_eq!(pad.shape, PadStackShape::PssCircle as i32);
        let drill = ps.drill.unwrap();
        assert_eq!(drill.shape, DrillShape::DsCircle as i32);
        let drill_d = drill.diameter.unwrap();
        assert_eq!(drill_d.x_nm, m_to_nm(cfg.min_via_drill_m));
        // pad diameter = drill + 2*annular = 0.4mm = 400_000 nm
        let size = pad.size.unwrap();
        assert_eq!(size.x_nm, via_pad_diameter_nm(cfg.min_via_drill_m, cfg.min_via_annular_ring_m));
        // For a 4-layer board, PadStack.layers should contain all 4 copper
        // layers (B_Cu, In1_Cu, In2_Cu, F_Cu) — matching what KiCad's own
        // `PCB_VIA::GetLayerSet()` returns for `VIATYPE::THROUGH`.
        assert_eq!(
            ps.layers.len(),
            4,
            "PadStack.layers should contain all 4 copper layers for a 4-layer board; got {:?}",
            ps.layers
        );
    }

    // --- Bug 5 regression: Via proto round-trips cleanly ---

    /// `build_through_via` must produce a `Via` proto that encodes and
    /// decodes without error and whose `unconnected_layer_removal` field
    /// is a valid enum variant. Pre-fix, the field was set to `0`
    /// (`UnconnectedLayerRemoval::UlrUnknown`), which KiCad's IPC
    /// rejected with `could not unpack PCB_VIA from request` at
    /// CreateItems time. The fix sets it to `UlrKeep` (= 1).
    #[test]
    fn test_via_proto_round_trips() {
        use crate::kicad::proto::board::types::{
            UnconnectedLayerRemoval, ViaDrillCappingMode, ViaDrillFillingMode,
        };

        let net = Net {
            code: None,
            name: "/A".to_string(),
        };
        // Round-3 fix: pass the copper layer set for a 4-layer board so the
        // `PadStack.layers` field matches KiCad's own `PCB_VIA::GetLayerSet()`
        // output for a through via.
        let board_layers = vec![
            BoardLayer::BlBCu as i32,
            BoardLayer::BlIn1Cu as i32,
            BoardLayer::BlIn2Cu as i32,
            BoardLayer::BlFCu as i32,
        ];
        let via = build_through_via((0.001, 0.002), 200_000, 400_000, net, &board_layers);
        let mut buf = Vec::new();
        via.encode(&mut buf).expect("encode Via");
        // Round-trip: decode the bytes back into a fresh `Via` proto.
        let via2 = Via::decode(buf.as_slice()).expect("decode Via");
        assert_eq!(via2.r#type, ViaType::VtThrough as i32);
        let ps = via2.pad_stack.expect("pad_stack present");
        // The critical assertion: unconnected_layer_removal must NOT be
        // the proto's `UlrUnknown` sentinel (0), which KiCad rejects.
        // The fix uses UlrKeep (1).
        assert_eq!(
            ps.unconnected_layer_removal,
            UnconnectedLayerRemoval::UlrKeep as i32,
            "unconnected_layer_removal must be UlrKeep (1) for KiCad to accept the via; got {}",
            ps.unconnected_layer_removal
        );
        assert_ne!(
            ps.unconnected_layer_removal,
            UnconnectedLayerRemoval::UlrUnknown as i32,
            "unconnected_layer_removal must NOT be UlrUnknown (0) — KiCad rejects it"
        );
        // Bug 5 round 2: DrillProperties.capped and .filled must also be
        // real, non-sentinel values — KiCad's PCB_VIA unpacker rejects
        // VDCM_UNKNOWN / VDFM_UNKNOWN just like ULR_UNKNOWN.
        let drill = ps.drill.as_ref().expect("drill");
        assert_eq!(
            drill.capped,
            ViaDrillCappingMode::VdcmUncapped as i32,
            "drill.capped must be VdcmUncapped (2); got {} (VdcmUnknown = 0 is the rejected sentinel)",
            drill.capped
        );
        assert_ne!(
            drill.capped,
            ViaDrillCappingMode::VdcmUnknown as i32,
            "drill.capped must NOT be VdcmUnknown (0)"
        );
        assert_eq!(
            drill.filled,
            ViaDrillFillingMode::VdfmUnfilled as i32,
            "drill.filled must be VdfmUnfilled (2); got {} (VdfmUnknown = 0 is the rejected sentinel)",
            drill.filled
        );
        assert_ne!(
            drill.filled,
            ViaDrillFillingMode::VdfmUnknown as i32,
            "drill.filled must NOT be VdfmUnknown (0)"
        );
        // Bug 5 round 2: PadStackLayer.custom_anchor_shape must also be
        // a real, non-sentinel value to match the per-layer `shape`.
        for (i, layer) in ps.copper_layers.iter().enumerate() {
            assert_eq!(
                layer.custom_anchor_shape, PadStackShape::PssCircle as i32,
                "copper_layers[{}].custom_anchor_shape must be PssCircle (1); got {} \
                 (PssUnknown = 0 is the rejected sentinel)",
                i, layer.custom_anchor_shape
            );
        }
        // Bug 5 round 3: For `PadStackType::PstNormal` (= C++
        // `PADSTACK::MODE::NORMAL`), `PadStackLayer.layer` must be
        // `BlFCu` (= C++ `ALL_LAYERS`). The pre-fix code emitted two entries
        // (one for F_Cu, one for B_Cu), and the B_Cu entry was rejected by
        // `PADSTACK::unpackCopperLayer` with `return false`, which caused
        // `PCB_VIA::Deserialize` to return false and surface as
        // "could not unpack PCB_VIA from request".
        assert_eq!(
            ps.copper_layers.len(),
            1,
            "PstNormal padstack must have exactly one PadStackLayer (round 3 fix); got {}",
            ps.copper_layers.len()
        );
        assert_eq!(
            ps.copper_layers[0].layer,
            BoardLayer::BlFCu as i32,
            "PstNormal PadStackLayer.layer must be BlFCu (= C++ ALL_LAYERS); got {}",
            ps.copper_layers[0].layer
        );
        // Other enum fields must be valid (regression guard).
        assert_eq!(ps.r#type, PadStackType::PstNormal as i32);
        assert_eq!(ps.drill.as_ref().unwrap().shape, DrillShape::DsCircle as i32);
        assert_eq!(ps.copper_layers[0].shape, PadStackShape::PssCircle as i32);
        // PadStack.layers carries the via's layer set, mirroring KiCad's
        // own `PCB_VIA::GetLayerSet()` for `VIATYPE::THROUGH`.
        assert_eq!(
            ps.layers,
            vec![
                BoardLayer::BlBCu as i32,
                BoardLayer::BlIn1Cu as i32,
                BoardLayer::BlIn2Cu as i32,
                BoardLayer::BlFCu as i32,
            ],
            "PadStack.layers must be the full copper layer set for a through via on a 4-layer board"
        );
        assert_eq!(via2.locked, LockedState::LsUnlocked as i32);
    }

    /// The via `coils_to_board_items` emits for a real coil set must also
    /// round-trip and carry the valid `UlrKeep` value. This is the
    /// end-to-end check — it walks the same path as the failing KiCad
    /// write: encode → decode → verify.
    #[test]
    fn test_coils_to_board_items_via_round_trip() {
        use crate::kicad::proto::board::types::{
            UnconnectedLayerRemoval, ViaDrillCappingMode, ViaDrillFillingMode,
        };
        use crate::geometry::CoilSegment;

        let cfg = test_config(4);
        let coil = PhaseCoil {
            phase_idx: 0,
            layer_idx: 0,
            segments: vec![CoilSegment {
                start: (0.0, 0.0),
                end: (0.0, 0.02),
                is_active: true,
            }],
            phase_name: "A".into(),
            center_via_positions: vec![(0.001, 0.002), (0.005, 0.007), (0.01, 0.01)],
            ..PhaseCoil::default()
        };
        let items = coils_to_board_items(&[coil], &cfg);
        let via_items: Vec<&Any> = items
            .iter()
            .filter(|a| a.type_url.ends_with("kiapi.board.types.Via"))
            .collect();
        assert_eq!(via_items.len(), 3, "expected 3 vias in this coil");
        for any in &via_items {
            let via = Via::decode(any.value.as_slice()).expect("decode Via via Any");
            let ps = via.pad_stack.as_ref().expect("pad_stack");
            assert_eq!(
                ps.unconnected_layer_removal,
                UnconnectedLayerRemoval::UlrKeep as i32,
                "every via emitted by coils_to_board_items must use UlrKeep"
            );
            // Round-2 fix: drill.capped / drill.filled must also be real values.
            let drill = ps.drill.as_ref().expect("drill");
            assert_eq!(
                drill.capped,
                ViaDrillCappingMode::VdcmUncapped as i32,
                "every via's drill.capped must be VdcmUncapped; got {}",
                drill.capped
            );
            assert_eq!(
                drill.filled,
                ViaDrillFillingMode::VdfmUnfilled as i32,
                "every via's drill.filled must be VdfmUnfilled; got {}",
                drill.filled
            );
            // Round-2 fix: copper_layers[*].custom_anchor_shape must be PssCircle.
            for layer in &ps.copper_layers {
                assert_eq!(
                    layer.custom_anchor_shape,
                    PadStackShape::PssCircle as i32,
                    "every PadStackLayer.custom_anchor_shape must be PssCircle; got {}",
                    layer.custom_anchor_shape
                );
            }
            assert_eq!(via.r#type, ViaType::VtThrough as i32);
        }
    }

    /// Bug 5 round-2 regression: every singular proto3 enum field in the
    /// `Via` payload must be a real, non-sentinel variant. KiCad's
    /// `PCB_VIA` unpacker rejects any `*_UNKNOWN = 0` sentinel value
    /// (the same class of error that caused the round-1 bug for
    /// `unconnected_layer_removal`). This test walks every enum field in
    /// the encoded `Via` and asserts no field equals 0.
    ///
    /// If a future proto revision adds a new singular enum field that
    /// this builder forgets to set, this test will fail (with a clear
    /// "field X is the *_UNKNOWN sentinel — KiCad rejects it" message)
    /// and the fix is simply to set the field to a real value here.
    #[test]
    fn test_via_proto_has_no_unknown_enum_sentinels() {
        // Check every singular enum field on the Via + PadStack + DrillProperties
        // + PadStackLayer payload. Repeated fields (layers) and message fields
        // (position, diameter, net) are not enums and so not checked here.
        let net = Net {
            code: None,
            name: "/A".to_string(),
        };
        let board_layers = vec![
            BoardLayer::BlBCu as i32,
            BoardLayer::BlFCu as i32,
        ];
        let via = build_through_via((0.001, 0.002), 200_000, 400_000, net, &board_layers);
        let ps = via.pad_stack.as_ref().expect("pad_stack");
        let drill = ps.drill.as_ref().expect("drill");

        // Format (name, value) for a clear diagnostic if a field slips to 0.
        let enum_fields: &[(&str, i32)] = &[
            ("Via.type", via.r#type),
            ("Via.locked", via.locked),
            ("PadStack.type", ps.r#type),
            ("PadStack.unconnected_layer_removal", ps.unconnected_layer_removal),
            ("DrillProperties.start_layer", drill.start_layer),
            ("DrillProperties.end_layer", drill.end_layer),
            ("DrillProperties.shape", drill.shape),
            ("DrillProperties.capped", drill.capped),
            ("DrillProperties.filled", drill.filled),
        ];
        for (name, value) in enum_fields {
            assert_ne!(
                *value, 0,
                "{} = 0 is the *_UNKNOWN proto3 sentinel; KiCad's PCB_VIA unpacker \
                 rejects this. Set the field to a real, non-sentinel variant.",
                name
            );
        }
        for (i, layer) in ps.copper_layers.iter().enumerate() {
            assert_ne!(
                layer.layer, 0,
                "PadStackLayer[{}].layer = 0 is BL_UNKNOWN; KiCad rejects this.",
                i
            );
            assert_ne!(
                layer.shape, 0,
                "PadStackLayer[{}].shape = 0 is PSS_UNKNOWN; KiCad rejects this.",
                i
            );
            assert_ne!(
                layer.custom_anchor_shape, 0,
                "PadStackLayer[{}].custom_anchor_shape = 0 is PSS_UNKNOWN; \
                 KiCad rejects this.",
                i
            );
        }
    }

    /// Bug 5 round-3 regression: for `PadStackType::PstNormal` (= C++
    /// `PADSTACK::MODE::NORMAL`), the `PadStack.copper_layers` field must
    /// contain exactly ONE `PadStackLayer`, and its `layer` must be
    /// `BlFCu` (= C++ `ALL_LAYERS`, the only layer `PADSTACK::unpackCopperLayer`
    /// accepts for `MODE::NORMAL`).
    ///
    /// The pre-fix code emitted two `PadStackLayer` entries (one for
    /// `BlFCu` and one for `BlBCu`). The `BlBCu` entry was rejected by
    /// `PADSTACK::unpackCopperLayer` with `return false` (see
    /// `pcbnew/padstack.cpp:190-191`). This propagated up through
    /// `PADSTACK::Deserialize` and `PCB_VIA::Deserialize`, both of which
    /// return `false`, surfacing as the envelope-level error
    /// `could not unpack PCB_VIA from request` and a
    /// `KiCad API error (code=3)` at the Tauri command layer.
    ///
    /// This test is a strict regression guard — it asserts the exact shape
    /// required by KiCad's C++ deserializer, so any future change that
    /// re-introduces a second `PadStackLayer` (or that sets the single
    /// entry's `layer` to anything other than `BlFCu`) will fail this
    /// test with a clear diagnostic pointing at the round-3 fix.
    #[test]
    fn test_via_pst_normal_copper_layers_uses_all_layers_sentinel() {
        let net = Net {
            code: None,
            name: "/A".to_string(),
        };
        // Use a 4-layer board's copper layer set to match the realistic
        // call path from `coils_to_board_items`.
        let board_layers = vec![
            BoardLayer::BlBCu as i32,
            BoardLayer::BlIn1Cu as i32,
            BoardLayer::BlIn2Cu as i32,
            BoardLayer::BlFCu as i32,
        ];
        let via = build_through_via((0.001, 0.002), 200_000, 400_000, net, &board_layers);
        let ps = via.pad_stack.as_ref().expect("pad_stack");

        // The padstack type must be PST_NORMAL for a basic through via.
        assert_eq!(
            ps.r#type,
            PadStackType::PstNormal as i32,
            "precondition: via padstack type must be PstNormal for this test to apply"
        );

        // Exactly one PadStackLayer entry — `MODE::NORMAL` only ever has
        // a single padstack layer (see `PADSTACK::ForEachUniqueLayer` in
        // `pcbnew/padstack.cpp:1241-1246`).
        assert_eq!(
            ps.copper_layers.len(),
            1,
            "PstNormal padstack must have exactly one PadStackLayer; got {} \
             (KiCad's PADSTACK::unpackCopperLayer rejects any extra entries)",
            ps.copper_layers.len()
        );

        // The single entry's `layer` must be `BlFCu` (= C++ `ALL_LAYERS`).
        // `PADSTACK::unpackCopperLayer` returns `false` for any other
        // value when `m_mode == MODE::NORMAL`.
        assert_eq!(
            ps.copper_layers[0].layer,
            BoardLayer::BlFCu as i32,
            "PstNormal PadStackLayer.layer must be BlFCu (= C++ ALL_LAYERS); \
             got {} (any other value causes KiCad's PCB_VIA deserializer \
             to fail with `could not unpack PCB_VIA from request`)",
            ps.copper_layers[0].layer
        );

        // And the size must still be the requested pad diameter.
        let pad = &ps.copper_layers[0];
        let size = pad.size.expect("size present");
        assert_eq!(size.x_nm, 400_000, "pad x size = drill + 2*annular");
        assert_eq!(size.y_nm, 400_000, "pad y size = drill + 2*annular");

        // PadStack.layers must be the full copper layer set, matching
        // what KiCad's own `PCB_VIA::GetLayerSet()` returns for
        // `VIATYPE::THROUGH` (`LSET::AllCuMask(copper_layer_count)`).
        assert_eq!(
            ps.layers, board_layers,
            "PadStack.layers must equal the full board copper layer set for a through via"
        );
    }

    /// Bug 5 round-3 end-to-end: every via emitted by `coils_to_board_items`
    /// for a real coil set must satisfy the round-3 invariants
    /// (single `PadStackLayer` with `layer = BlFCu` and `PadStack.layers`
    /// equal to the full copper layer set). This is the end-to-end check
    /// the user can use to verify the KiCad write path without needing a
    /// live KiCad instance.
    ///
    /// **Round 4 (current):** the test now uses a config where
    /// `max_layers (12)` exceeds `num_layers (4)` — the realistic case
    /// where the user's DFM upper limit is larger than the board they are
    /// writing to. The test asserts `PadStack.layers` has exactly
    /// `num_layers` entries (4), NOT `max_layers` entries (12), because
    /// KiCad's `UnpackLayerSet` rejects any via whose layer set is not a
    /// subset of the live board's actual layer set with `ISC_INVALID_DATA`
    /// (code 7) and "attempted to add item with no overlapping layers
    /// with the board". This is the regression guard for the round-4 fix.
    #[test]
    fn test_coils_to_board_items_via_round_trip_pst_normal_invariants() {
        use crate::geometry::CoilSegment;

        // Build a config that mirrors the user's actual scenario:
        // `max_layers=12` (DFM upper limit, 12-layer-capable fabricator)
        // and `num_layers=4` (the board the user is writing to).
        let mut cfg = test_config(12);
        cfg.num_layers = 4;
        let coil = PhaseCoil {
            phase_idx: 0,
            layer_idx: 0,
            segments: vec![CoilSegment {
                start: (0.0, 0.0),
                end: (0.0, 0.02),
                is_active: true,
            }],
            phase_name: "A".into(),
            center_via_positions: vec![(0.001, 0.002), (0.005, 0.007), (0.01, 0.01)],
            ..PhaseCoil::default()
        };
        let items = coils_to_board_items(&[coil], &cfg);
        let via_items: Vec<&Any> = items
            .iter()
            .filter(|a| a.type_url.ends_with("kiapi.board.types.Via"))
            .collect();
        assert_eq!(via_items.len(), 3, "expected 3 vias in this coil");

        // Round 4: the via's `PadStack.layers` must reflect the user's
        // ACTUAL layer count (`num_layers = 4`), NOT the DFM upper limit
        // (`max_layers = 12`). The 4-entry set is what the live 4-layer
        // board's `BoardCopperLayerCount` accepts; the 12-entry set would
        // include `In3_Cu..In11_Cu` which the board does not have, and
        // KiCad's `UnpackLayerSet` would reject each via with
        // `ISC_INVALID_DATA` (code 7).
        let expected_board_layers: Vec<i32> = vec![
            BoardLayer::BlBCu as i32,
            BoardLayer::BlIn1Cu as i32,
            BoardLayer::BlIn2Cu as i32,
            BoardLayer::BlFCu as i32,
        ];

        for any in &via_items {
            let via = Via::decode(any.value.as_slice()).expect("decode Via via Any");
            let ps = via.pad_stack.as_ref().expect("pad_stack");
            assert_eq!(
                ps.r#type,
                PadStackType::PstNormal as i32,
                "every via's padstack type must be PstNormal"
            );
            assert_eq!(
                ps.copper_layers.len(),
                1,
                "every PstNormal via must have exactly one PadStackLayer (round 3 fix); got {}",
                ps.copper_layers.len()
            );
            assert_eq!(
                ps.copper_layers[0].layer,
                BoardLayer::BlFCu as i32,
                "every PstNormal via's PadStackLayer.layer must be BlFCu (= C++ ALL_LAYERS); got {}",
                ps.copper_layers[0].layer
            );
            // Round 4: `PadStack.layers` must have exactly `num_layers`
            // entries, NOT `max_layers` entries. The pre-fix code emitted
            // 12 entries on a 4-layer board, which KiCad's
            // `UnpackLayerSet` rejected at CreateItems time with
            // `ISC_INVALID_DATA` (code 7).
            assert_eq!(
                ps.layers.len(),
                cfg.num_layers as usize,
                "PadStack.layers.len() must equal config.num_layers ({}), not config.max_layers ({}); got {} entries: {:?}",
                cfg.num_layers, cfg.max_layers, ps.layers.len(), ps.layers
            );
            assert_eq!(
                ps.layers, expected_board_layers,
                "every via's PadStack.layers must equal the live board's actual copper layer set, \
                 not the DFM upper limit"
            );
        }
    }

    /// Round-4 regression: when `config.num_layers` differs from
    /// `config.max_layers`, the `PadStack.layers` produced by
    /// `coils_to_board_items` must reflect `num_layers` (the actual coil /
    /// board layer count) and NOT `max_layers` (the DFM upper limit).
    ///
    /// **Pre-fix behavior:** the writer populated `board_layers` from
    /// `config.max_layers`. With `max_layers=12` and a 4-layer board, the
    /// emitted via's `PadStack.layers` was a 12-entry set
    /// `[B_Cu, In1_Cu, In2_Cu, In3_Cu, ..., In11_Cu, F_Cu]`. KiCad's
    /// `CreateItems` validator (`api_pcb_utils.cpp::UnpackLayerSet`)
    /// rejects any item whose `LayerSet` is not a subset of the live
    /// board's actual layer set, returning `ISC_INVALID_DATA` (code 7)
    /// with the message "attempted to add item with no overlapping
    /// layers with the board". 99 of 588 vias were rejected with this
    /// error in the previous round.
    ///
    /// **Post-fix behavior:** `board_layers` is built from
    /// `config.num_layers` (the user-selected, board-matching layer
    /// count). For `num_layers=4` the emitted set is
    /// `[B_Cu, In1_Cu, In2_Cu, F_Cu]`, which matches the live 4-layer
    /// board and is accepted by KiCad.
    ///
    /// This test exercises a single via and asserts the exact length and
    /// contents of `PadStack.layers` for several `(num_layers, max_layers)`
    /// pairs where the two values differ.
    #[test]
    fn test_pad_stack_layers_reflect_num_layers_not_max_layers() {
        use crate::geometry::CoilSegment;

        // (num_layers, max_layers, expected_layer_set) — the
        // representative (num, max) combinations the writer must handle.
        // In every case, `PadStack.layers` must equal the
        // `num_layers`-entry set, never the `max_layers`-entry set.
        //
        // We deliberately include a case where `num_layers != max_layers`
        // (the bug) and a case where `num_layers == max_layers` (the
        // no-mismatch case, which must keep working). The `assert_ne!`
        // below is only checked when the two values differ, so the
        // equal-values case is not a false-positive trigger.
        let cases: &[(u32, u32, &[BoardLayer])] = &[
            // User scenario from the bug report: DFM cap is 12, board is 4.
            (4, 12, &[
                BoardLayer::BlBCu,
                BoardLayer::BlIn1Cu,
                BoardLayer::BlIn2Cu,
                BoardLayer::BlFCu,
            ]),
            // Small board, very large DFM cap.
            (2, 12, &[
                BoardLayer::BlBCu,
                BoardLayer::BlFCu,
            ]),
            // num_layers == max_layers (no mismatch) — must still work
            // and produce exactly num_layers entries.
            (6, 6, &[
                BoardLayer::BlBCu,
                BoardLayer::BlIn1Cu,
                BoardLayer::BlIn2Cu,
                BoardLayer::BlIn3Cu,
                BoardLayer::BlIn4Cu,
                BoardLayer::BlFCu,
            ]),
        ];

        for &(num_layers, max_layers, expected_layers) in cases {
            let mut cfg = test_config(max_layers);
            cfg.num_layers = num_layers;

            // Build a minimal coil with exactly one center via so the test
            // can introspect a single `Via` payload.
            let coil = PhaseCoil {
                phase_idx: 0,
                layer_idx: 0,
                segments: vec![CoilSegment {
                    start: (0.0, 0.0),
                    end: (0.0, 0.02),
                    is_active: true,
                }],
                phase_name: "A".into(),
                center_via_positions: vec![(0.001, 0.002)],
                ..PhaseCoil::default()
            };
            let items = coils_to_board_items(&[coil], &cfg);
            let via_any = items
                .iter()
                .find(|a| a.type_url.ends_with("kiapi.board.types.Via"))
                .unwrap_or_else(|| panic!(
                    "expected a Via in items for (num_layers={}, max_layers={})",
                    num_layers, max_layers
                ));
            let via = Via::decode(via_any.value.as_slice()).expect("decode Via");
            let ps = via.pad_stack.as_ref().expect("pad_stack");

            // Round 4 invariant: `PadStack.layers` length equals
            // `num_layers`, NOT `max_layers`. This is the property the
            // pre-fix code violated.
            assert_eq!(
                ps.layers.len(),
                num_layers as usize,
                "(num_layers={}, max_layers={}): PadStack.layers must have exactly \
                 num_layers entries, got {} (full set: {:?})",
                num_layers, max_layers, ps.layers.len(), ps.layers
            );
            // Only assert `len() != max_layers` when the two values
            // differ — otherwise the equality is trivially satisfied and
            // the assertion is meaningless (and would be a false
            // positive failure for the (num == max) case).
            if num_layers != max_layers {
                assert_ne!(
                    ps.layers.len(),
                    max_layers as usize,
                    "(num_layers={}, max_layers={}): PadStack.layers must NOT have \
                     max_layers entries — this was the pre-fix bug (KiCad rejects \
                     layer sets that include layers the board does not have)",
                    num_layers, max_layers
                );
            }

            // Round 4 invariant: the contents of `PadStack.layers` must
            // match the expected `num_layers`-entry set.
            let expected: Vec<i32> = expected_layers
                .iter()
                .map(|l| *l as i32)
                .collect();
            assert_eq!(
                ps.layers, expected,
                "(num_layers={}, max_layers={}): PadStack.layers contents must \
                 match the num_layers-entry set, got {:?}",
                num_layers, max_layers, ps.layers
            );

            // Round 3 invariants: the single PadStackLayer + PstNormal +
            // BlFCu (= C++ ALL_LAYERS) shape must still hold.
            assert_eq!(ps.r#type, PadStackType::PstNormal as i32);
            assert_eq!(ps.copper_layers.len(), 1);
            assert_eq!(ps.copper_layers[0].layer, BoardLayer::BlFCu as i32);
        }
    }

    /// Round-5 regression: the track's `Track.layer` field (used by every
    /// [`Track`] emitted from a coil) MUST be derived from
    /// `config.num_layers` (the actual board the user is writing to), NOT
    /// `config.max_layers` (the DFM upper limit).
    ///
    /// **Pre-fix behavior:** the writer used `config.max_layers` for the
    /// track layer mapping. With `num_layers=4, max_layers=12` and a
    /// top-layer coil at `coil.layer_idx=3`, the function
    /// `layer_idx_to_board_layer(3, 12)` returned `In3_Cu` (an inner
    /// layer of a 12-layer board), not `F_Cu` (the top of the 4-layer
    /// board). KiCad's `UnpackLayerSet` rejected each such track with
    /// `ISC_INVALID_DATA` (code 7) and "attempted to add item with no
    /// overlapping layers with the board". In the user's run, 99 of 588
    /// items (all top-layer tracks across 3 phases) were rejected with
    /// this error — the round-4 via-layer fix had already removed the
    /// corresponding via-layer rejection, but tracks were unaffected
    /// because they were computed from a different call site.
    ///
    /// **Post-fix behavior:** the writer uses `config.num_layers` so a
    /// top-layer coil at `coil.layer_idx=num_layers-1` is correctly
    /// recognised as the top of the actual board and mapped to `F_Cu`.
    /// All other layer indices (`0 → B_Cu`, `1..num_layers-1 → In{n}_Cu`)
    /// are also derived from the actual board's layer set.
    ///
    /// This test exercises a representative (num_layers, max_layers)
    /// pair (4, 12) — the user's scenario — and asserts that every Track
    /// emitted for coils at the top of the live board lands on a layer
    /// the board actually has. The (4, 4) "no mismatch" case is also
    /// exercised to ensure the fix does not regress the
    /// `num_layers == max_layers` path.
    #[test]
    fn test_track_layer_uses_num_layers_not_max_layers() {
        use crate::geometry::PhaseCoil;
        use crate::geometry::CoilSegment;

        // (num_layers, max_layers, expected_layer_set) — for each case the
        // emitted tracks must land on layers in the expected set.
        let cases: &[(u32, u32, &[BoardLayer])] = &[
            // The user's actual scenario: 4-layer board, 12-layer DFM cap.
            // The pre-fix code emitted tracks at In3_Cu for top-layer
            // coils, which the 4-layer board does not have.
            (4, 12, &[
                BoardLayer::BlBCu,
                BoardLayer::BlIn1Cu,
                BoardLayer::BlIn2Cu,
                BoardLayer::BlFCu,
            ]),
            // Small board, very large DFM cap.
            (2, 12, &[
                BoardLayer::BlBCu,
                BoardLayer::BlFCu,
            ]),
            // num_layers == max_layers (no mismatch) — must still work.
            (6, 6, &[
                BoardLayer::BlBCu,
                BoardLayer::BlIn1Cu,
                BoardLayer::BlIn2Cu,
                BoardLayer::BlIn3Cu,
                BoardLayer::BlIn4Cu,
                BoardLayer::BlFCu,
            ]),
        ];

        for &(num_layers, max_layers, expected_layers) in cases {
            let mut cfg = test_config(max_layers);
            cfg.num_layers = num_layers;

            // Build a minimal coil with a top-layer segment (the bug is
            // triggered for any layer index, but is most visible at the
            // top because that's where the "idx == total - 1" branch
            // changes its answer between num and max).
            let coil = PhaseCoil {
                phase_idx: 0,
                layer_idx: num_layers - 1, // top layer of the live board
                segments: vec![CoilSegment {
                    start: (0.0, 0.0),
                    end: (0.0, 0.02),
                    is_active: true,
                }],
                phase_name: "A".into(),
                center_via_positions: Vec::new(),
                ..PhaseCoil::default()
            };
            let items = coils_to_board_items(&[coil], &cfg);
            let track_any = items
                .iter()
                .find(|a| a.type_url.ends_with("kiapi.board.types.Track"))
                .unwrap_or_else(|| panic!(
                    "expected a Track in items for (num_layers={}, max_layers={})",
                    num_layers, max_layers
                ));
            let track: Track = Track::decode(track_any.value.as_slice()).expect("decode Track");

            // The track's layer MUST be in the expected `num_layers`-entry
            // set. The pre-fix code mapped it to an inner layer of a
            // `max_layers`-capable board (e.g. In3_Cu for (4, 12)), which
            // the live `num_layers`-layer board does not have.
            let valid_layers: Vec<i32> = expected_layers
                .iter()
                .map(|l| *l as i32)
                .collect();
            assert!(
                valid_layers.contains(&track.layer),
                "(num_layers={}, max_layers={}): top-layer track must land on a \
                 layer the live board has (one of {:?}); got {} (= {:?}). \
                 Pre-fix this was the source of the 99-of-588 'no overlapping \
                 layers with the board' rejections — the track was mapped \
                 using max_layers instead of num_layers.",
                num_layers, max_layers, valid_layers, track.layer,
                BoardLayer::try_from(track.layer).unwrap_or(BoardLayer::BlUnknown)
            );
            // For the specific (num, max) mismatch case, also assert the
            // top-layer track specifically lands on F_Cu (not just any
            // valid layer). This is the precise property the pre-fix code
            // violated.
            if num_layers != max_layers {
                assert_eq!(
                    track.layer,
                    BoardLayer::BlFCu as i32,
                    "(num_layers={}, max_layers={}): top-layer track MUST be F_Cu, \
                     not In{}_Cu. Pre-fix this was the 'no overlapping layers \
                     with the board' rejection source.",
                    num_layers, max_layers, num_layers - 1
                );
            }
        }
    }
}
