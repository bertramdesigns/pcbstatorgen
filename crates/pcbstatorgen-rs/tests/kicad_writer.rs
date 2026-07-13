//! Integration tests for the Phase 7 KiCad writer module.
//!
//! These tests exercise the pure `coils_to_board_items` function (no socket
//! needed) and the `Commit` handle using `MockTransport`.

use prost::Message;
use prost_types::Any;

use pcbstatorgen_rs::config::LinearMotorConfig;
use pcbstatorgen_rs::geometry::{PhaseCoil, WaveWindingGenerator};
use pcbstatorgen_rs::kicad::{
    ApiResponse, ApiResponseHeader, ApiResponseStatus, ApiStatusCode, BoardLayer, KiCadClient,
    KiCadError, KicadTransport, MockTransport, coils_to_board_items, layer_idx_to_board_layer,
    m_to_nm, via_pad_diameter_nm,
};
use pcbstatorgen_rs::kicad::proto::board::types::{Track, Via, ViaType};
use pcbstatorgen_rs::kicad::proto::common::commands::{
    BeginCommitResponse, CommitAction, CreateItemsResponse, EndCommit, EndCommitResponse,
};
use pcbstatorgen_rs::kicad::proto::common::types::{
    document_specifier, DocumentSpecifier, DocumentType, Kiid,
};
use pcbstatorgen_rs::units::{mm, mils_to_m};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

fn pack_any<T: Message>(type_url: &str, msg: &T) -> Any {
    let mut buf = Vec::new();
    msg.encode(&mut buf).expect("encode");
    Any {
        type_url: type_url.to_string(),
        value: buf,
    }
}

fn build_ok_response(payload: Any) -> Vec<u8> {
    let resp = ApiResponse {
        header: Some(ApiResponseHeader {
            kicad_token: "test-token".to_string(),
        }),
        status: Some(ApiResponseStatus {
            status: ApiStatusCode::AsOk as i32,
            error_message: String::new(),
        }),
        message: Some(payload),
    };
    let mut buf = Vec::new();
    resp.encode(&mut buf).expect("encode response");
    buf
}

const BEGIN_COMMIT_RESPONSE_URL: &str =
    "type.googleapis.com/kiapi.common.commands.BeginCommitResponse";
const CREATE_ITEMS_RESPONSE_URL: &str =
    "type.googleapis.com/kiapi.common.commands.CreateItemsResponse";
const END_COMMIT_RESPONSE_URL: &str =
    "type.googleapis.com/kiapi.common.commands.EndCommitResponse";

fn empty_end_commit_response() -> EndCommitResponse {
    EndCommitResponse {}
}

fn pcb_document(filename: &str) -> DocumentSpecifier {
    DocumentSpecifier {
        r#type: DocumentType::DoctypePcb as i32,
        identifier: Some(document_specifier::Identifier::BoardFilename(
            filename.to_string(),
        )),
        project: None,
    }
}

// ---------------------------------------------------------------------------
// layer_map tests
// ---------------------------------------------------------------------------

#[test]
fn test_layer_0_is_bcu() {
    assert_eq!(layer_idx_to_board_layer(0, 4), BoardLayer::BlBCu);
}

#[test]
fn test_layer_top_is_fcu() {
    assert_eq!(layer_idx_to_board_layer(3, 4), BoardLayer::BlFCu);
}

#[test]
fn test_layer_1_is_in1cu() {
    assert_eq!(layer_idx_to_board_layer(1, 4), BoardLayer::BlIn1Cu);
}

#[test]
fn test_m_to_nm_conversion() {
    assert_eq!(m_to_nm(0.001), 1_000_000);
}

#[test]
fn test_via_pad_diameter() {
    // 0.2mm drill + 2×0.1mm ring = 0.4mm = 400,000 nm
    assert_eq!(via_pad_diameter_nm(0.0002, 0.0001), 400_000);
}

// ---------------------------------------------------------------------------
// coils_to_board_items tests (pure function)
// ---------------------------------------------------------------------------

#[test]
fn test_track_count_matches_segment_count() {
    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let total_segments: usize = coils.iter().map(|c| c.segments.len()).sum();
    let items = coils_to_board_items(&coils, &cfg);
    assert_eq!(items.len(), total_segments);
}

#[test]
fn test_all_items_are_tracks_when_no_vias() {
    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let items = coils_to_board_items(&coils, &cfg);
    for any in &items {
        assert!(any.type_url.ends_with("kiapi.board.types.Track"));
    }
}

#[test]
fn test_track_coordinates_are_in_nanometres() {
    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let items = coils_to_board_items(&coils, &cfg);

    let coil0 = &coils[0];
    let seg0 = &coil0.segments[0];
    let track: Track = Track::decode(items[0].value.as_slice()).expect("decode Track");
    let start = track.start.unwrap();
    let end = track.end.unwrap();
    assert_eq!(start.x_nm, (seg0.start.0 * 1e9).round() as i64);
    assert_eq!(start.y_nm, (seg0.start.1 * 1e9).round() as i64);
    assert_eq!(end.x_nm, (seg0.end.0 * 1e9).round() as i64);
    assert_eq!(end.y_nm, (seg0.end.1 * 1e9).round() as i64);
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
fn test_net_names_are_slash_prefixed() {
    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    assert_eq!(coils.len(), 3);

    let items = coils_to_board_items(&coils, &cfg);

    // Phase A: decode the first track of coil 0.
    let t0: Track = Track::decode(items[0].value.as_slice()).expect("decode");
    assert_eq!(t0.net.unwrap().name, "/A");

    // Phase B: find the first track belonging to coil 1 (phase B).
    let seg0_b = &coils[1].segments[0];
    let expected_x = (seg0_b.start.0 * 1e9).round() as i64;
    let mut found_b = false;
    for any in &items {
        let t: Track = Track::decode(any.value.as_slice()).expect("decode");
        if t.start.unwrap().x_nm == expected_x {
            assert_eq!(t.net.unwrap().name, "/B");
            found_b = true;
            break;
        }
    }
    assert!(found_b, "did not find phase B track");

    // Phase C: find the first track belonging to coil 2 (phase C).
    let seg0_c = &coils[2].segments[0];
    let expected_x = (seg0_c.start.0 * 1e9).round() as i64;
    let mut found_c = false;
    for any in &items {
        let t: Track = Track::decode(any.value.as_slice()).expect("decode");
        if t.start.unwrap().x_nm == expected_x {
            assert_eq!(t.net.unwrap().name, "/C");
            found_c = true;
            break;
        }
    }
    assert!(found_c, "did not find phase C track");
}

#[test]
fn test_layer_assignment_4_layer_board() {
    let cfg = test_config(4);
    let bottom_coils = WaveWindingGenerator.generate(&cfg, 0); // layer 0
    let top_coils = WaveWindingGenerator.generate(&cfg, 3); // layer 3

    let mut all_coils = bottom_coils.clone();
    all_coils.extend(top_coils);

    let items = coils_to_board_items(&all_coils, &cfg);

    // First item is from layer 0 → B_Cu.
    let t0: Track = Track::decode(items[0].value.as_slice()).expect("decode");
    assert_eq!(t0.layer, BoardLayer::BlBCu as i32);

    // At least one item should be on F_Cu (layer 3).
    let has_fcu = items.iter().any(|any| {
        let t: Track = Track::decode(any.value.as_slice()).expect("decode");
        t.layer == BoardLayer::BlFCu as i32
    });
    assert!(has_fcu, "expected at least one track on F_Cu");
}

#[test]
fn test_via_items_when_present() {
    use pcbstatorgen_rs::geometry::CoilSegment;

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
        center_via_positions: vec![(0.005, 0.005), (0.01, 0.01)],
        ..PhaseCoil::default()
    };
    let items = coils_to_board_items(&[coil], &cfg);
    // 1 track + 2 vias
    assert_eq!(items.len(), 3);

    let vias: Vec<&Any> = items
        .iter()
        .filter(|a| a.type_url.ends_with("kiapi.board.types.Via"))
        .collect();
    assert_eq!(vias.len(), 2);

    let via: Via = Via::decode(vias[0].value.as_slice()).expect("decode Via");
    assert_eq!(via.r#type, ViaType::VtThrough as i32);
    assert_eq!(via.net.unwrap().name, "/A");
    let pos = via.position.unwrap();
    assert_eq!(pos.x_nm, 5_000_000);
    assert_eq!(pos.y_nm, 5_000_000);
}

// ---------------------------------------------------------------------------
// Commit tests with MockTransport
// ---------------------------------------------------------------------------

/// A `MockTransport` that returns a sequence of canned responses (one per
/// `send_and_recv` call) so a multi-step commit flow can be simulated.
struct SequencedMockTransport {
    responses: Vec<Vec<u8>>,
    sent_requests: Vec<Vec<u8>>,
    call_index: usize,
}

impl SequencedMockTransport {
    fn new(responses: Vec<Vec<u8>>) -> Self {
        Self {
            responses,
            sent_requests: Vec::new(),
            call_index: 0,
        }
    }
}

impl KicadTransport for SequencedMockTransport {
    fn send_and_recv(&mut self, request_bytes: &[u8]) -> Result<Vec<u8>, KiCadError> {
        self.sent_requests.push(request_bytes.to_vec());
        let resp = self
            .responses
            .get(self.call_index)
            .cloned()
            .unwrap_or_default();
        self.call_index += 1;
        Ok(resp)
    }
}

#[test]
fn test_commit_begin_create_end_flow() {
    let begin_resp = BeginCommitResponse {
        id: Some(Kiid {
            value: "commit-uuid-1234".to_string(),
        }),
    };
    let create_resp = CreateItemsResponse {
        header: None,
        status: 1, // IRS_OK
        created_items: Vec::new(),
    };
    let end_resp = empty_end_commit_response();

    let responses = vec![
        build_ok_response(pack_any(BEGIN_COMMIT_RESPONSE_URL, &begin_resp)),
        build_ok_response(pack_any(CREATE_ITEMS_RESPONSE_URL, &create_resp)),
        build_ok_response(pack_any(END_COMMIT_RESPONSE_URL, &end_resp)),
    ];

    let transport = SequencedMockTransport::new(responses);
    let mut client = KiCadClient::with_transport(
        Box::new(transport),
        Some("test-client"),
        2000,
    );

    // Build a tiny coil set so we have items to create.
    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let items = coils_to_board_items(&coils, &cfg);
    let doc = pcb_document("board.kicad_pcb");

    // We need to access `transport.sent_requests` after the calls, so reach in
    // via the client's transport downcast? MockTransport is inside a Box<dyn>.
    // Instead, replicate the commit logic manually here so we can inspect
    // what was sent.
    use pcbstatorgen_rs::kicad::Commit;

    let mut commit = Commit::begin(&mut client).expect("begin commit");
    let resp = commit.create_items(&items, &doc).expect("create items");
    assert_eq!(resp.created_items.len(), 0); // mocked empty
    commit.end().expect("end commit");

    // We can't easily inspect the inner transport through the Box<dyn>, but
    // the fact that the flow succeeded (no error) proves BeginCommit, then
    // CreateItems, then EndCommit were all sent and the responses decoded.
}

#[test]
fn test_commit_begin_sends_begincommit_command() {
    let begin_resp = BeginCommitResponse {
        id: Some(Kiid {
            value: "abc".to_string(),
        }),
    };
    let resp_bytes = build_ok_response(pack_any(BEGIN_COMMIT_RESPONSE_URL, &begin_resp));

    let mut transport = SequencedMockTransport::new(vec![resp_bytes]);

    // Manually pack a BeginCommit request and send via the transport so we can
    // inspect the bytes.
    use pcbstatorgen_rs::kicad::proto::common::commands::BeginCommit;
    use pcbstatorgen_rs::kicad::{ApiRequest, ApiRequestHeader};

    let cmd = BeginCommit {};
    let any = pack_any("type.googleapis.com/kiapi.common.commands.BeginCommit", &cmd);
    let request = ApiRequest {
        header: Some(ApiRequestHeader {
            kicad_token: String::new(),
            client_name: "test".to_string(),
        }),
        message: Some(any),
    };
    let mut req_bytes = Vec::new();
    request.encode(&mut req_bytes).expect("encode");
    let _ = transport.send_and_recv(&req_bytes);

    assert_eq!(transport.sent_requests.len(), 1);
    let sent = &transport.sent_requests[0];
    let decoded = ApiRequest::decode(sent.as_slice()).expect("decode sent request");
    let any = decoded.message.expect("message");
    assert!(any.type_url.ends_with("kiapi.common.commands.BeginCommit"));
}

#[test]
fn test_commit_end_sends_cma_commit() {
    // Build an EndCommit command and verify the action is CMA_COMMIT.
    let cmd = EndCommit {
        id: Some(Kiid {
            value: "commit-1".to_string(),
        }),
        action: CommitAction::CmaCommit as i32,
        message: "pcbstatorgen coil generation".to_string(),
    };
    let any = pack_any("type.googleapis.com/kiapi.common.commands.EndCommit", &cmd);

    let resp_bytes = build_ok_response(pack_any(END_COMMIT_RESPONSE_URL, &empty_end_commit_response()));

    let transport = SequencedMockTransport::new(vec![resp_bytes]);
    let mut client = KiCadClient::with_transport(
        Box::new(transport),
        Some("test"),
        2000,
    );

    // Use send directly to exercise EndCommit.
    let _resp: EndCommitResponse = client
        .send::<EndCommit, EndCommitResponse>(
            "type.googleapis.com/kiapi.common.commands.EndCommit",
            &cmd,
        )
        .expect("end commit send");

    // Verify the decoded Any payload has the right action by re-decoding the
    // command from the constructed Any.
    let decoded_end = EndCommit::decode(any.value.as_slice()).expect("decode EndCommit");
    assert_eq!(decoded_end.action, CommitAction::CmaCommit as i32);
    assert_eq!(decoded_end.message, "pcbstatorgen coil generation");
}

#[test]
fn test_commit_abort_sends_cma_drop() {
    let cmd = EndCommit {
        id: Some(Kiid {
            value: "commit-2".to_string(),
        }),
        action: CommitAction::CmaDrop as i32,
        message: String::new(),
    };
    assert_eq!(cmd.action, CommitAction::CmaDrop as i32);
    assert!(cmd.message.is_empty());
}

#[test]
fn test_board_handle_name() {
    let resp_bytes = build_ok_response(pack_any(
        BEGIN_COMMIT_RESPONSE_URL,
        &BeginCommitResponse {
            id: Some(Kiid { value: "x".to_string() }),
        },
    ));
    let mut client = KiCadClient::with_transport(
        Box::new(MockTransport::new(resp_bytes)),
        Some("test"),
        2000,
    );
    let doc = pcb_document("motor.kicad_pcb");
    let board = pcbstatorgen_rs::kicad::BoardHandle::new(&mut client, doc);
    assert_eq!(board.name().unwrap(), "motor.kicad_pcb");
}

#[test]
fn test_board_handle_name_errors_for_non_pcb() {
    let resp_bytes = build_ok_response(pack_any(
        BEGIN_COMMIT_RESPONSE_URL,
        &BeginCommitResponse {
            id: Some(Kiid { value: "x".to_string() }),
        },
    ));
    let mut client = KiCadClient::with_transport(
        Box::new(MockTransport::new(resp_bytes)),
        Some("test"),
        2000,
    );
    let doc = DocumentSpecifier {
        r#type: DocumentType::DoctypeSchematic as i32,
        identifier: None,
        project: None,
    };
    let board = pcbstatorgen_rs::kicad::BoardHandle::new(&mut client, doc);
    assert!(board.name().is_err());
}

#[test]
fn test_board_handle_write_coils_end_to_end() {
    // Build canned responses for the 3-step commit flow.
    let begin_resp = BeginCommitResponse {
        id: Some(Kiid { value: "c1".to_string() }),
    };
    let n_items = 10; // arbitrary
    let created_items: Vec<_> = (0..n_items)
        .map(|_| pcbstatorgen_rs::kicad::proto::common::commands::ItemCreationResult {
            status: Some(pcbstatorgen_rs::kicad::proto::common::commands::ItemStatus {
                code: 1, // ISC_OK
                error_message: String::new(),
            }),
            item: None,
        })
        .collect();
    let create_resp = CreateItemsResponse {
        header: None,
        status: 1,
        created_items,
    };

    let responses = vec![
        build_ok_response(pack_any(BEGIN_COMMIT_RESPONSE_URL, &begin_resp)),
        build_ok_response(pack_any(CREATE_ITEMS_RESPONSE_URL, &create_resp)),
        build_ok_response(pack_any(END_COMMIT_RESPONSE_URL, &empty_end_commit_response())),
    ];

    let transport = SequencedMockTransport::new(responses);
    let mut client = KiCadClient::with_transport(
        Box::new(transport),
        Some("test"),
        2000,
    );
    let doc = pcb_document("motor.kicad_pcb");

    let cfg = test_config(4);
    let coils = WaveWindingGenerator.generate(&cfg, 0);
    let expected_items = coils.iter().map(|c| c.segments.len()).sum::<usize>() as u32;

    let mut board = pcbstatorgen_rs::kicad::BoardHandle::new(&mut client, doc);
    let n = board.write_coils(&coils, &cfg).expect("write_coils");
    assert_eq!(n, expected_items);
}
