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
    DrillProperties, DrillShape, PadStack, PadStackLayer, PadStackShape, PadStackType, ViaType,
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
/// This is a **pure function** — no socket I/O. It produces a list of
/// `google.protobuf.Any`-wrapped items ready for `CreateItems`.
pub fn coils_to_board_items(coils: &[PhaseCoil], config: &LinearMotorConfig) -> Vec<Any> {
    let trace_width_nm = m_to_nm(config.min_trace_m);
    let drill_nm = m_to_nm(config.min_via_drill_m);
    let pad_diameter_nm = via_pad_diameter_nm(config.min_via_drill_m, config.min_via_annular_ring_m);

    let mut items: Vec<Any> = Vec::new();

    for coil in coils {
        let layer = layer_idx_to_board_layer(coil.layer_idx, config.max_layers);
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
                    x_nm: m_to_nm(seg.start.0),
                    y_nm: m_to_nm(seg.start.1),
                }),
                end: Some(Vector2 {
                    x_nm: m_to_nm(seg.end.0),
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
                pos,
                drill_nm,
                pad_diameter_nm,
                net.clone(),
            );
            items.push(pack_any("kiapi.board.types.Via", &via));
        }
    }

    items
}

/// Build a minimal through-hole [`Via`] proto at `pos` (metres) with the given
/// drill and pad diameters (nanometres).
fn build_through_via(pos: (f64, f64), drill_nm: i64, pad_diameter_nm: i64, net: Net) -> Via {
    let pad_size = Vector2 {
        x_nm: pad_diameter_nm,
        y_nm: pad_diameter_nm,
    };
    let drill_diameter = Vector2 {
        x_nm: drill_nm,
        y_nm: drill_nm,
    };

    let front_pad = PadStackLayer {
        layer: BoardLayer::BlFCu as i32,
        shape: PadStackShape::PssCircle as i32,
        size: Some(pad_size),
        corner_rounding_ratio: 0.0,
        chamfer_ratio: 0.0,
        chamfered_corners: None,
        custom_shapes: Vec::new(),
        custom_anchor_shape: PadStackShape::PssUnknown as i32,
        zone_settings: None,
        trapezoid_delta: None,
        offset: None,
    };
    let back_pad = PadStackLayer {
        layer: BoardLayer::BlBCu as i32,
        shape: PadStackShape::PssCircle as i32,
        size: Some(pad_size),
        corner_rounding_ratio: 0.0,
        chamfer_ratio: 0.0,
        chamfered_corners: None,
        custom_shapes: Vec::new(),
        custom_anchor_shape: PadStackShape::PssUnknown as i32,
        zone_settings: None,
        trapezoid_delta: None,
        offset: None,
    };

    let pad_stack = PadStack {
        r#type: PadStackType::PstNormal as i32,
        layers: vec![BoardLayer::BlFCu as i32, BoardLayer::BlBCu as i32],
        drill: Some(DrillProperties {
            start_layer: BoardLayer::BlFCu as i32,
            end_layer: BoardLayer::BlBCu as i32,
            diameter: Some(drill_diameter),
            shape: DrillShape::DsCircle as i32,
            capped: 0,
            filled: 0,
        }),
        unconnected_layer_removal: 0,
        copper_layers: vec![front_pad, back_pad],
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
        let cfg = test_config(4);
        let coils = WaveWindingGenerator.generate(&cfg, 0);
        let total_segments: usize = coils.iter().map(|c| c.segments.len()).sum();
        let items = coils_to_board_items(&coils, &cfg);
        assert_eq!(items.len(), total_segments, "no vias in this coil set");
    }

    #[test]
    fn test_items_are_tracks_for_no_vias() {
        let cfg = test_config(4);
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
        let track: Track = Track::decode(items[0].value.as_slice()).expect("decode Track");
        let seg0 = &coils.iter().next().unwrap().segments[0];
        let expected_start_x = (seg0.start.0 * 1e9).round() as i64;
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
        for any in phase_b_items {
            let t: Track = Track::decode(any.value.as_slice()).expect("decode");
            if t.start.unwrap().x_nm == (seg0.start.0 * 1e9).round() as i64 {
                assert_eq!(t.net.unwrap().name, "/B");
                return;
            }
        }
        panic!("did not find phase B track");
    }

    #[test]
    fn test_layer_assignment_4_layer_board() {
        let cfg = test_config(4);
        // Generate coils on layer 0 (bottom) and layer 3 (top).
        let mut coils = WaveWindingGenerator.generate(&cfg, 0);
        let top_coils = WaveWindingGenerator.generate(&cfg, 3);
        coils.extend(top_coils);

        let items = coils_to_board_items(&coils, &cfg);

        // First coil is on layer 0 → B_Cu.
        let t0: Track = Track::decode(items[0].value.as_slice()).expect("decode");
        assert_eq!(t0.layer, BoardLayer::BlBCu as i32);

        // Find a coil on layer 3 → F_Cu.
        let top_track_any = items
            .iter()
            .find(|a| {
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
        assert_eq!(pos.x_nm, 1_000_000);
        assert_eq!(pos.y_nm, 2_000_000);
        assert_eq!(via.r#type, ViaType::VtThrough as i32);
        let ps = via.pad_stack.unwrap();
        assert_eq!(ps.r#type, PadStackType::PstNormal as i32);
        assert_eq!(ps.copper_layers.len(), 2);
        let drill = ps.drill.unwrap();
        assert_eq!(drill.shape, DrillShape::DsCircle as i32);
        let drill_d = drill.diameter.unwrap();
        assert_eq!(drill_d.x_nm, m_to_nm(cfg.min_via_drill_m));
        // pad diameter = drill + 2*annular = 0.4mm = 400_000 nm
        let pad = &ps.copper_layers[0];
        assert_eq!(pad.shape, PadStackShape::PssCircle as i32);
        let size = pad.size.unwrap();
        assert_eq!(size.x_nm, via_pad_diameter_nm(cfg.min_via_drill_m, cfg.min_via_annular_ring_m));
    }
}
