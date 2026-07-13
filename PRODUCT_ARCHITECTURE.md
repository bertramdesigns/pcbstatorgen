# Generalized PCB Stator Motor Generator: Product Architecture

This document captures the system architecture, module boundaries, transport
protocols, and data-flow contracts for `pcbstatorgen`. It is the authoritative
reference for all technical handoff. For product vision see `PRODUCT_GOALS.md`;
for implementation roadmap see `PRODUCT_PLAN.md`.

---

## 1. High-Level System Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                         pcbstatorgen Desktop App                    │
│  (single compiled binary — Tauri v2 host)                           │
│                                                                     │
│  ┌───────────────┐   Tauri IPC    ┌──────────────────────────────┐  │
│  │  Svelte 5 UI  │ ─────────────▶ │  Rust Core (app/src-tauri)    │  │
│  │  (WebView)     │ ◀─────────────│  #[tauri::command] handlers  │  │
│  └───────────────┘   async JSON   └─────────────┬────────────────┘  │
│                                                    │ depends-on       │
│                                                    ▼                  │
│                              ┌──────────────────────────────────┐    │
│                              │  pcbstatorgen-rs  (pure crate)   │    │
│                              │  ├── config   (serde structs)    │    │
│                              │  ├── geometry (coil generators)  │    │
│                              │  ├── magnetic (B, F, τ)         │    │
│                              │  ├── physics  (magba adapter)    │    │
│                              │  ├── stackup  (height, power)    │    │
│                              │  └── kicad    (IPC writer)  ◀── NEW │
│                              └──────────────┬───────────────────┘    │
│                                             │                        │
└─────────────────────────────────────────────┼────────────────────────┘
                                              │ NNG req/rep
                                              │ ipc:///tmp/kicad/api.sock
                                              ▼
                              ┌──────────────────────────────┐
                              │  KiCad 10 (running instance)  │
                              │  PCB editor + IPC API server  │
                              └──────────────────────────────┘
```

### Process Boundaries

| Boundary        | Transport                          | Serialization      | Ownership                     |
| --------------- | ---------------------------------- | ------------------ | ----------------------------- |
| Svelte → Rust   | Tauri IPC (`invoke()`)             | JSON (serde)       | Tauri host process            |
| Rust → KiCad    | NNG req/rep over Unix domain socket | Protobuf (prost)  | Separate OS process (KiCad)   |
| Rust → Physics  | In-process function calls          | Rust types         | Same binary, no serialization |

---

## 2. KiCad 10 IPC Protocol — Native Rust Implementation

### 2.1 Transport Layer

KiCad 10 exposes its scripting/board API via the **NNG (nanomsg next
generation)** `req0` protocol over an IPC socket. The Python reference
implementation (`kipy/client.py`) uses `pynng.Req0`.

**Rust equivalent:** The `nng` crate (or `nng-sys` FFI bindings if a pure-Rust
wrapper is unavailable for the required version) provides `Req0` with
`dial()`, `send()`, and `recv()` semantics matching `pynng` exactly.

| Parameter          | Default                              | Overridable by                |
| ------------------ | ------------------------------------ | ----------------------------- |
| Socket path        | `ipc:///tmp/kicad/api.sock`          | `KICAD_API_SOCKET` env var    |
| Client name        | `pcbstatorgen-<random-8-char>`      | Constructor argument          |
| KiCad token        | `""` (empty — auto-negotiated)       | `KICAD_API_TOKEN` env var     |
| Timeout            | 2000 ms                              | Constructor argument          |

### 2.2 Wire Protocol

Every request/response is a length-prefixed protobuf envelope:

```
┌──────────────────────────────────────────────────┐
│  ApiRequest                                       │
│  ├── header { kicad_token, client_name }          │
│  └── message: google.protobuf.Any (packed cmd)   │
└──────────────────────────────────────────────────┘
                        │ NNG req0.send()
                        ▼
┌──────────────────────────────────────────────────┐
│  ApiResponse                                      │
│  ├── header { kicad_token }                       │
│  ├── status { status: ApiStatusCode, error_msg }  │
│  └── message: google.protobuf.Any (packed reply)  │
└──────────────────────────────────────────────────┘
```

**Status handling:** If `status != AS_OK`, raise `ApiError` with the
`error_message` and `status_code`. On first successful response, cache the
returned `kicad_token` for all subsequent requests.

### 2.3 Protobuf Code Generation

The `.proto` schema files live in the `kicad-python` reference repo under
`kipy/proto/`. The Rust port **does not hand-roll protobuf structs** — instead
it uses `prost-build` to compile the canonical `.proto` files at build time.

| Proto Package                | Source path (kicad-python repo)        | Rust module             |
| ---------------------------- | -------------------------------------- | ----------------------- |
| `kipy.proto.common`          | `kipy/proto/common/`                   | `kicad::proto::common`  |
| `kipy.proto.board`           | `kipy/proto/board/`                    | `kicad::proto::board`   |
| `kipy.proto.common.commands` | `kipy/proto/common/commands/`          | `kicad::proto::commands`|
| `kipy.proto.common.types`    | `kipy/proto/common/types/`             | `kicad::proto::types`   |

**Build-time convention:**
- `build.rs` in the `pcbstatorgen-rs` crate invokes `prost_build` against the
  vendored `.proto` files (committed under `crates/pcbstatorgen-rs/proto/`).
- Generated code is emitted to `OUT_DIR` and re-exported via a `kicad::proto`
  module. No runtime `.proto` loading.
- `tonic` is **not** used (this is a req/rep socket, not gRPC/HTTP2).

---

## 3. KiCad Writer Module (`pcbstatorgen_rs::kicad`)

This is the new Phase 7 module. It lives in the pure library crate
(`crates/pcbstatorgen-rs/src/kicad/`) with **no Tauri dependency** — it must be
testable offline without a live socket.

### 3.1 Module Layout

```
crates/pcbstatorgen-rs/src/kicad/
├── mod.rs              — public API surface
├── client.rs           — NNG socket wrapper (connect, send, recv, envelope)
├── board.rs            — high-level Board handle (get_copper_layer_count, etc.)
├── writer.rs           — CoilSegment → Track proto, via_grid → Via proto
├── commit.rs           — BeginCommit/EndCommit atomic transaction wrapper
├── layer_map.rs        — layer_idx (0..N) → KiCad BoardLayer enum mapping
└── errors.rs           — ApiError, ConnectionError, ProtocolError
```

### 3.2 Core Types

```rust
/// Connection to a running KiCad 10 instance.
pub struct KiCadClient {
    socket: nng::Req0,
    socket_path: String,
    client_name: String,
    kicad_token: String,
    timeout_ms: u32,
    connected: bool,
}

/// High-level handle to the open board document.
pub struct BoardHandle<'a> {
    client: &'a KiCadClient,
    document: DocumentSpecifier,
}

/// Atomic commit — all items created between BeginCommit and EndCommit
/// appear as a single Ctrl+Z undo step in the KiCad editor.
pub struct Commit<'a> {
    board: &'a BoardHandle<'a>,
    // token from BeginCommitResponse
}

/// Error hierarchy.
pub enum KiCadError {
    Connection(String),   // socket unreachable
    Api { code: i32, message: String },  // KiCad returned non-OK status
    Protocol(String),     // protobuf pack/unpack failure
    NotConnected,
}
```

### 3.3 Track/Via Writer — Data Flow

```
PhaseCoil (from geometry::wave_winding)
  ├── segments: Vec<CoilSegment { start, end, is_active }>
  ├── layer_idx: u32
  └── center_via_positions: Vec<(f64, f64)>
        │
        ▼
writer::coils_to_board_items(coils, config) → Vec<BoardItem>
        │
        ├── straight segment → Track {
        │       start: Vector2 { x_nm, y_nm },
        │       end:   Vector2 { x_nm, y_nm },
        │       width:  config.min_trace_m → nm,
        │       layer:  layer_map(layer_idx),
        │       net:   phase_net(phase_name),
        │   }
        │
        └── via position → Via {
                position: Vector2 { x_nm, y_nm },
                drill:    config.min_via_drill_m → nm,
                width:    config.min_via_pad_m → nm,  // drill + 2×annular
                layer_set: via_layer_span(config.max_layers),
                net:      phase_net(phase_name),
            }
        │
        ▼
Commit::create_items(board_items) → Vec<KIID>
        │
        ▼
Commit::end()  → atomic, single Ctrl+Z
```

**Unit conversions:** All pcbstatorgen-rs geometry is in **metres (SI)**. KiCad
proto uses **nanometres (nm)** as `value_nm` fields. The writer applies
`m_to_nm(f64) -> i64` = `(f64 * 1e9).round() as i64`.

**Coordinate system:** Identical. Both use X = travel axis, Y = board width.
No rotation or offset transform is needed for linear mode.

### 3.4 Layer Mapping

KiCad BoardLayer enum values (from `board_types_pb2`):
- `B_Cu` = 0 (bottom copper)
- `F_Cu` = 35 (top copper — KiCad 10 default for 2-layer)
- Inner layers: `In1_Cu` .. `In34_Cu`

`layer_map.rs` provides:
```rust
pub fn layer_idx_to_board_layer(idx: u32, total_layers: u32) -> BoardLayer
```
- `idx == 0` → `B_Cu` (bottom)
- `idx == total_layers - 1` → `F_Cu` (top)
- else → `In{idx}_Cu` (inner)

### 3.5 Net Assignment

Each phase coil gets a KiCad net named `/<phase_name>` (e.g. `/A`, `/B`, `/C`).
The writer creates nets via `CreateItems` with `Net` proto messages before
creating tracks. If a net already exists (idempotent re-run), KiCad returns the
existing KIID — no error.

### 3.6 Offline Testability

The writer module **must** be testable without a live KiCad socket:
- `writer::coils_to_board_items()` is a pure function — test its output proto
  structs directly.
- `client.rs` is behind a `KicadTransport` trait with a `MockTransport`
  implementation that records sent bytes and returns canned responses.
- Integration tests (`tests/integration/`) that require a live socket are
  gated behind a `#[cfg(feature = "kicad-live")]` feature flag and skipped in
  CI by default.

---

## 4. Tauri Command Surface (Phase 7 Additions)

Three new `#[tauri::command]` handlers are added to `app/src-tauri/src/commands.rs`:

| Command              | Status     | Returns                          |
| -------------------- | ---------- | -------------------------------- |
| `connect_kicad`      | **NEW**    | `{ connected: bool, board_name: String, copper_layers: u32 }` |
| `write_coils_to_board` | **NEW** | `{ items_created: u32, commit_id: String }` |
| `ping_kicad`         | **NEW**    | `{ ok: bool, version: String }`  |

All three are `async fn` with `spawn_blocking` for socket I/O (same pattern as
existing commands). The Svelte frontend gains a "KiCad" panel with connect
status, a "Write to Board" button, and a dry-run preview toggle.

**Command stubs from Phase 6 (§6.A):** The 6 existing stubs
(`generate_coils`, `evaluate_force_sweep`, `compute_stackup`,
`compute_power_budget`, `compute_friction`, `compute_height_stack`) are
**wired to real pcbstatorgen-rs calls** as a prerequisite of Phase 7 — the
KiCad writer needs real coil geometry, not placeholder paths.

---

## 5. Streamlit Deprecation (Stage 5)

### 5.1 Deletion Targets

| Path                    | Action        | Rationale                                |
| ----------------------- | ------------- | ---------------------------------------- |
| `gui/streamlit_app.py`  | **DELETE**    | Superseded by Tauri+Svelte desktop app.  |
| `scripts/run_headless.py` | **DELETE**  | Streamlit launcher; no longer needed.    |

### 5.2 Retention Targets

| Path                      | Action          | Rationale                                    |
| ------------------------- | --------------- | -------------------------------------------- |
| `pcbstatorgen/` (Python)  | **RETAIN**      | Test oracle for Rust physics validation.     |
| `tests/` (Python pytest)  | **RETAIN**      | Oracle test suite — runs in CI alongside Rust. |
| `scripts/export_test_vectors.py` | **RETAIN** | Generates fixtures for Rust tests.       |
| `plugin_entry.py`         | **RETAIN (reference)** | Documents the kipy Python API. Not deleted — serves as protocol reference for the Rust port. May be moved to `docs/reference/`. |

### 5.3 Parallel Verification Gate

Before deletion, run the full Python oracle test suite AND the Rust test suite
in CI. The Streamlit files are only deleted once:
1. All 179 Rust tests pass.
2. All Python oracle tests pass.
3. The 6 Tauri command stubs are wired to real core calls.
4. The KiCad writer end-to-end test passes (live or mock).

---

## 6. Dependency Additions (Phase 7)

### 6.1 New Workspace Crates

| Crate     | Version | Role                                          | Added to            |
| --------- | ------- | --------------------------------------------- | ------------------- |
| `nng`     | `1.0`   | NNG socket transport (req/rep over IPC).       | `pcbstatorgen-rs`   |
| `prost`   | `0.13`  | Protobuf runtime (generated code decoder).     | `pcbstatorgen-rs`   |
| `prost-build` | `0.13` | Build-time proto compilation (dev-dep).   | `pcbstatorgen-rs`   |

### 6.2 Vendored Protobuf Schema

The `.proto` files from the `kicad-python` reference repo are copied into
`crates/pcbstatorgen-rs/proto/` at the start of Phase 7. This avoids a build-time
dependency on an external repo path. A `scripts/sync_protos.sh` script
re-copies from the reference repo if the schema is updated upstream.

---

## 7. Validation Requirements

### 7.1 Offline Unit Tests (mandatory, no live KiCad)

- `writer::coils_to_board_items` produces correct Track/Via proto structs for
  serpentine and sine wave topologies.
- `layer_map::layer_idx_to_board_layer` maps all layer indices correctly.
- `client::KiCadClient` with `MockTransport` sends/receives envelopes correctly.
- `commit::Commit` wraps BeginCommit/CreateItems/EndCommit in correct order.
- Unit conversion: `m_to_nm` round-trips within 1 nm tolerance.

### 7.2 Integration Tests (gated, live KiCad)

- `#[cfg(feature = "kicad-live")]` end-to-end test: connect to running KiCad,
  write a small test coil set, verify item count via `GetItems`, then Ctrl+Z
  rolls back cleanly.
- Requires a scratch `.kicad_pcb` open in KiCad 10 with IPC API enabled.
- Skipped in CI by default; run manually before releases.

### 7.3 Oracle Parity

- Python `test_kicad_writer.py` (existing) defines the expected track/via
  geometry. The Rust writer's `coils_to_board_items` output must match the
  Python writer's proto field-for-field (coordinates within 1 nm).

---

## 8. Scope Boundaries (Phase 7)

**In scope:**
- NNG socket client in Rust.
- Protobuf code generation via prost-build against vendored kipy `.proto` files.
- `kicad::writer` module: CoilSegment → Track, via_grid → Via.
- Atomic commit (BeginCommit/EndCommit) — single Ctrl+Z undo step.
- 3 new Tauri commands: `connect_kicad`, `write_coils_to_board`, `ping_kicad`.
- Wiring 6 existing Tauri command stubs to real pcbstatorgen-rs calls.
- Svelte frontend KiCad panel (connect status, write button, dry-run toggle).
- Streamlit deprecation (delete `gui/`, `scripts/run_headless.py`).
- Offline unit tests + gated live integration test.

**Out of scope (deferred):**
- Radial/axial-flux board writing (linear only — PRODUCT_GOALS.md §7.A).
- Board stackup/layer setup via IPC (assume user pre-configures stackup in
  KiCad; the writer only places tracks/vias).
- Board outline generation (circular or rectangular).
- Read-back/sync loop (one-way pipeline — PRODUCT_GOALS.md §1 anti-scope).
- KiCad PCM packaging (PRODUCT_GOALS.md §1 anti-scope).
