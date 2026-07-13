/**
 * pcbstatorgen — Tauri invoke wrappers with mock fallback.
 *
 * Every call attempts the real Tauri backend command (phase G). If the
 * Tauri runtime is not available (frontend-only dev mode, e.g. `vite dev`
 * outside of `tauri dev`), a deterministic mock is returned so the
 * dashboard stays interactive.
 *
 * ## Error handling
 *
 * **Critical IPC calls** (the ones the user can act on, e.g. the
 * "Write to Board" button) **surface real errors** to the UI. We do NOT
 * silently swallow them — the historical `try { invoke() } catch { mock }`
 * pattern is what caused the "0 of 0 written" bug, because a real Tauri
 * failure looked identical to "everything worked but produced 0 items".
 * The mock fallback is only used when the Tauri runtime itself is
 * unavailable (see [`isTauriAvailable`]).
 *
 * **Background physics calls** (force sweep, coil generation, etc.) keep
 * the mock fallback because (a) they run on every slider change and (b)
 * their failure is recoverable — the user just sees stale data, not a
 * broken write.
 */

import { invoke } from "@tauri-apps/api/core";
import type {
  LinearMotorConfig,
  ConfigDerived,
  CoilPathDto,
  ForceSweepResult,
  StackupResultDto,
  HeightStackResultDto,
  FrictionBudgetDto,
  PowerBudgetDto,
  KicadConnection,
  KicadWriteResult,
  KicadPingResult,
  BFieldGridDto,
  BoardDiagnostics,
  PreconditionWarning,
  CoilPreview,
} from "./types";

// ---------------------------------------------------------------------------
// Unit helpers (mm ↔ m)
// ---------------------------------------------------------------------------

export const mm = (v: number): number => v / 1000.0;
export const to_mm = (v: number): number => v * 1000.0;

// ---------------------------------------------------------------------------
// Tauri runtime detection
// ---------------------------------------------------------------------------

/**
 * `true` when the page is running inside the Tauri shell, `false` for
 * plain `vite dev` (or any browser without the Tauri IPC bridge).
 *
 * The Tauri v2 runtime injects `window.__TAURI_INTERNALS__`; its mere
 * presence is the canonical "we have a backend" signal. We use this
 * instead of a try/catch around `invoke()` so we can distinguish
 * "no backend available" (return mock) from "backend returned an error"
 * (let the error propagate to the UI).
 */
export function isTauriAvailable(): boolean {
  if (typeof window === "undefined") return false;
  return (window as unknown as { __TAURI_INTERNALS__?: unknown })
    .__TAURI_INTERNALS__ !== undefined;
}

// ---------------------------------------------------------------------------
// Backend commands
//
// All background physics calls use the `isTauriAvailable()` gate: when
// running in a plain browser (vite dev), return the deterministic mock.
// When running inside Tauri, call `invoke()` and let the error propagate
// — the App.svelte `recompute()` has its own try/catch that surfaces the
// error in the UI banner.
// ---------------------------------------------------------------------------

export async function computeConfigDerived(
  config: LinearMotorConfig,
): Promise<ConfigDerived> {
  if (!isTauriAvailable()) return mockConfigDerived(config);
  return await invoke<ConfigDerived>("compute_config_derived", { config });
}

export async function generateCoils(
  config: LinearMotorConfig,
): Promise<CoilPathDto> {
  if (!isTauriAvailable()) return mockCoils(config);
  return await invoke<CoilPathDto>("generate_coils", { config });
}

export async function evaluateForceSweep(
  config: LinearMotorConfig,
): Promise<ForceSweepResult> {
  if (!isTauriAvailable()) return mockForceSweep(config);
  return await invoke<ForceSweepResult>("evaluate_force_sweep", { config });
}

export async function computeHeightStack(
  config: LinearMotorConfig,
): Promise<HeightStackResultDto> {
  if (!isTauriAvailable()) return mockHeightStack(config);
  return await invoke<HeightStackResultDto>("compute_height_stack", { config });
}

export async function computePowerBudget(
  config: LinearMotorConfig,
): Promise<PowerBudgetDto> {
  if (!isTauriAvailable()) return mockPowerBudget(config);
  return await invoke<PowerBudgetDto>("compute_power_budget", { config });
}

export async function computeFriction(
  config: LinearMotorConfig,
): Promise<FrictionBudgetDto> {
  if (!isTauriAvailable()) return mockFriction(config);
  return await invoke<FrictionBudgetDto>("compute_friction", { config });
}

export async function computeStackup(
  config: LinearMotorConfig,
): Promise<StackupResultDto> {
  if (!isTauriAvailable()) return mockStackup(config);
  return await invoke<StackupResultDto>("compute_stackup", { config });
}

// ---------------------------------------------------------------------------
// KiCad IPC API (phase 7 — board write via KiCad 10 IPC socket)
//
// These are user-facing IPC calls (the "Write to Board" / "Connect to
// KiCad" buttons). Real Tauri errors MUST propagate to the UI so the
// "0 of 0 written" bug (and its siblings) can't be silently hidden
// behind a synthetic zero. The mock fallback is only used when the Tauri
// runtime itself is absent (`vite dev` without the Tauri shell).
// ---------------------------------------------------------------------------

export async function connectKicad(): Promise<KicadConnection> {
  if (!isTauriAvailable()) {
    return { connected: false, board_name: "(not connected)", copper_layers: 0 };
  }
  return await invoke<KicadConnection>("connect_kicad");
}

/**
 * Generate coils from the config and write them to the open KiCad board.
 *
 * Pass `dryRun: true` to count the items without sending a commit
 * (`commit_id === "(dry run - no commit)"`, `items_created === 0`). The
 * Rust side still establishes a KiCad connection in dry-run mode — it
 * just skips the `Commit` / `create_items` IPC. Use [`previewCoils`]
 * for a no-IPC dry run (useful when KiCad is not open).
 *
 * **No try/catch here.** A real Tauri error (e.g. "no board open",
 * "connection refused") propagates to the caller — that's the fix for
 * the historical "0 of 0 written" bug.
 */
export async function writeCoilsToBoard(
  config: LinearMotorConfig,
  dryRun: boolean = false,
): Promise<KicadWriteResult> {
  if (!isTauriAvailable()) {
    return {
      items_attempted: 0,
      items_created: 0,
      failures: ["Backend not available — open the Tauri shell to write to KiCad"],
      commit_id: "",
    };
  }
  return await invoke<KicadWriteResult>("write_coils_to_board", {
    config,
    dryRun,
  });
}

export async function pingKicad(): Promise<KicadPingResult> {
  if (!isTauriAvailable()) return { ok: false, version: "" };
  return await invoke<KicadPingResult>("ping_kicad");
}

// ---------------------------------------------------------------------------
// Board diagnostics + preconditions + preview — WP-KiCad
//
// The three new commands added in WP-1.B. They give the UI a clear
// "here's what the board looks like" + "here's what would go wrong"
// signal *before* the user clicks the real "Write to Board" button.
// ---------------------------------------------------------------------------

/**
 * Live snapshot of the open KiCad board (name, layer count, edge-cut
 * bounding box, net classes). Connects to KiCad each call — cache in the
 * UI if you need it more than once per write.
 */
export async function getBoardDiagnostics(): Promise<BoardDiagnostics> {
  if (!isTauriAvailable()) return mockBoardDiagnostics();
  return await invoke<BoardDiagnostics>("get_board_diagnostics");
}

/**
 * Compare the user's `config` against the live `diagnostics` and return
 * a list of pre-condition warnings (info / warning / error). Pure on
 * the Rust side — no IPC. Errors propagate.
 */
export async function validateWritePreconditions(
  config: LinearMotorConfig,
  diagnostics: BoardDiagnostics,
): Promise<PreconditionWarning[]> {
  if (!isTauriAvailable()) return mockValidatePreconditions(config, diagnostics);
  return await invoke<PreconditionWarning[]>("validate_write_preconditions", {
    config,
    diagnostics,
  });
}

/**
 * Dry-run coil preview: builds the same PhaseCoil set the writer would
 * produce, and returns a per-layer tally (phase count, track count, via
 * count). No KiCad roundtrip — safe to call without KiCad running.
 */
export async function previewCoils(
  config: LinearMotorConfig,
): Promise<CoilPreview> {
  if (!isTauriAvailable()) return mockPreviewCoils(config);
  return await invoke<CoilPreview>("preview_coils", { config });
}

// ---------------------------------------------------------------------------
// Mock implementations (deterministic, physics-flavoured)
// ---------------------------------------------------------------------------

function mockConfigDerived(c: LinearMotorConfig): ConfigDerived {
  const pole_pitch_m = c.magnet_pitch_m;
  const coil_span_m = c.magnet_count * c.magnet_pitch_m;
  const travel_m = c.active_area_length_m - coil_span_m;
  const slot_pitch_m = (pole_pitch_m / c.phases) * c.spacing_ratio;
  return {
    pole_pitch_m,
    coil_span_m,
    travel_m,
    slot_pitch_m,
    magnet_gap_m: c.magnet_gap_m,
    min_via_pad_m: c.min_via_drill_m + 2 * c.min_via_annular_ring_m,
    acceleration_force_n: c.carriage_mass_kg * c.max_accel_m_s2,
    minimum_drive_force_n: c.friction_n * 1.3,
    active_length_m: c.active_area_length_m,
  };
}

function mockCoils(c: LinearMotorConfig): CoilPathDto {
  // Build a simple serpentine for phase A on layer 0.
  const phases = [];
  const span = c.magnet_count * c.magnet_pitch_m;
  const width = c.board_width_m;
  const nConductors = Math.max(2, c.magnet_count * 2);
  const segs = [];
  const pitchX = span / (nConductors - 1);
  for (let i = 0; i < nConductors; i++) {
    const x = i * pitchX;
    const yTop = i % 2 === 0 ? 0 : width;
    const yBot = i % 2 === 0 ? width : 0;
    // active (vertical) conductor
    segs.push({ start: [x, yTop], end: [x, yBot], is_active: true });
    if (i < nConductors - 1) {
      // end-turn (horizontal) to next conductor
      segs.push({ start: [x, yBot], end: [x + pitchX, yBot], is_active: false });
    }
  }
  for (let p = 0; p < c.phases; p++) {
    phases.push({
      phase_idx: p,
      layer_idx: 0,
      phase_name: "ABC"[p] ?? String(p),
      topology: c.coil_topology,
      segments: segs,
      total_length_m: segs.reduce((s, sg) => s + Math.hypot(sg.end[0] - sg.start[0], sg.end[1] - sg.start[1]), 0),
      active_length_m: segs.filter((s) => s.is_active).reduce((s, sg) => s + Math.hypot(sg.end[0] - sg.start[0], sg.end[1] - sg.start[1]), 0),
      end_turn_length_m: segs.filter((s) => !s.is_active).reduce((s, sg) => s + Math.hypot(sg.end[0] - sg.start[0], sg.end[1] - sg.start[1]), 0),
      active_conductor_count: segs.filter((s) => s.is_active).length,
      bounding_box: [0, 0, span, width] as [number, number, number, number],
      terminal_start: [0, 0] as [number, number],
      terminal_end: [span, width] as [number, number],
    });
  }
  return { phases, layer_count: c.num_layers };
}

function mockForceSweep(c: LinearMotorConfig): ForceSweepResult {
  const n = c.n_positions;
  const travel = Math.max(0, c.active_area_length_m - c.magnet_count * c.magnet_pitch_m);
  const positions = Array.from({ length: n }, (_, i) => (travel * i) / (n - 1));
  // Sinusoidal-ish force with ripple + a normal-force baseline.
  const br = c.magnet_remanence_t;
  const ipeak = c.max_current_a;
  const baseline = 0.4 * br * ipeak * c.num_layers * (c.magnet_count / 10);
  const ripple = baseline * 0.08;
  const force_x = positions.map(
    (x) => baseline + ripple * Math.sin((x / Math.max(c.magnet_pitch_m, 1e-6)) * 2 * Math.PI * c.phases),
  );
  const force_y = positions.map((_, idx) => 0.01 * Math.sin(idx));
  const force_z = positions.map(() => baseline * 1.6); // pull-in ~ 1.5–1.7× thrust
  const mean = force_x.reduce((a, b) => a + b, 0) / n;
  const peak = Math.max(...force_x);
  const min = Math.min(...force_x);
  const ripplePct = Math.abs(mean) < 1e-12 ? 0 : ((peak - min) / Math.abs(mean)) * 100;
  return {
    positions_m: positions,
    force_x_n: force_x,
    force_y_n: force_y,
    force_z_n: force_z,
    per_phase_force_x: force_x.map((f) => [f / c.phases, f / c.phases, f / c.phases]),
    commutation: c.commutation,
    current_a: ipeak,
    mean_thrust_n: mean,
    peak_thrust_n: peak,
    min_thrust_n: min,
    ripple_pct: ripplePct,
    n_positions: n,
  };
}

function mockHeightStack(c: LinearMotorConfig): HeightStackResultDto {
  return {
    pcb_thickness_m: c.pcb_thickness_m,
    cu_protrusion_m: 35e-6 * (c.num_layers >= 6 ? 2 : 1),
    solder_mask_m: 20e-6,
    air_gap_m: c.air_gap_m,
    magnet_height_m: c.magnet_height_m,
    back_iron_thickness_m: c.back_iron_thickness_m,
    tolerance_m: 0.1e-3,
    total_height_m:
      c.pcb_thickness_m + 35e-6 + 20e-6 + c.air_gap_m + c.magnet_height_m + c.back_iron_thickness_m + 0.1e-3,
  };
}

function mockPowerBudget(c: LinearMotorConfig): PowerBudgetDto {
  // Crude I²R estimate based on coil length.
  const coilLen = c.active_area_length_m * c.board_width_m * c.num_layers * 2;
  const rho = 1.72e-8; // Cu resistivity
  const traceArea = 35e-6 * 0.2e-3; // 1oz, 0.2mm trace
  const r = (rho * coilLen) / traceArea;
  const cont = c.max_current_a ** 2 * r * c.phases;
  const burst = (c.max_current_a * 1.5) ** 2 * r * c.phases;
  return {
    phase_resistance_ohm: r,
    continuous_power_w: cont,
    burst_power_w: burst,
    temperature_rise_c: Math.min(c.max_temperature_rise_c, cont * 4),
    capacitor_required_uf: c.capacitor_bank_uf,
    efficiency_pct: Math.max(2, Math.min(15, (0.25 * 0.1) / (c.supply_voltage_v * c.max_current_a) * 100)),
  };
}

function mockFriction(c: LinearMotorConfig): FrictionBudgetDto {
  const total = c.friction_n;
  return {
    bearing_friction_n: total * 0.5,
    cable_drag_n: total * 0.3,
    wiper_contact_n: total * 0.2,
    cogging_n: 0,
    total_n: total,
    minimum_drive_force_n: total * 1.3,
  };
}

function mockStackup(c: LinearMotorConfig): StackupResultDto {
  const lc = c.num_layers;
  const traceW = Array.from({ length: lc }, (_, i) =>
    0.2e-3 * (1 + Math.abs(i - (lc - 1) / 2) * 0.05),
  );
  const cuT = Array.from({ length: lc }, (_, i) =>
    i === 0 || i === lc - 1 ? 35e-6 : 70e-6,
  );
  return {
    layer_count: lc,
    trace_widths_m: traceW,
    cu_thickness_m: cuT,
    via_drill_m: c.min_via_drill_m,
    via_annular_ring_m: c.min_via_annular_ring_m,
    via_grid_rows: 2,
    via_grid_cols: 4,
    estimated_force_n: 0.4 * c.magnet_remanence_t * c.max_current_a * lc,
    estimated_dc_resistance_ohm: 1.2,
    notes: ["Mock stackup — backend not connected"],
  };
}

// ---------------------------------------------------------------------------
// Board diagnostics / preconditions / preview mocks (frontend-only dev)
// ---------------------------------------------------------------------------

/**
 * Mock board snapshot for `vite dev` (no Tauri). All edge-cut bounds
 * and net classes are 0 / empty (matching the real backend's
 * not-yet-queryable placeholders), and `copper_layer_count` mirrors
 * the user's `num_layers` so the validate/preview flows have
 * something realistic to check against.
 */
function mockBoardDiagnostics(): BoardDiagnostics {
  return {
    board_name: "(mock board — backend not connected)",
    copper_layer_count: 4,
    board_x_min_mm: 0.0,
    board_x_max_mm: 0.0,
    board_y_min_mm: 0.0,
    board_y_max_mm: 0.0,
    available_net_classes: [],
  };
}

/**
 * Mock precondition check. In dev mode we don't have a real board to
 * compare against, so we return an empty list — the UI shows the green
 * "all clear" state. The real Rust validator runs the rule set from
 * `pcbstatorgen_rs::kicad::validate_write_preconditions`.
 */
function mockValidatePreconditions(
  _config: LinearMotorConfig,
  _diagnostics: BoardDiagnostics,
): PreconditionWarning[] {
  return [];
}

/**
 * Mock coil preview. Builds a per-layer tally that mirrors the shape
 * the Rust side would produce, so the UI's preview card has something
 * to render in dev mode.
 */
function mockPreviewCoils(config: LinearMotorConfig): CoilPreview {
  const numLayers = Math.max(1, config.num_layers);
  // Heuristic segment count: ~2 active conductors per magnet per phase,
  // plus one end-turn per conductor pair. Matches the mockCoils() shape
  // closely enough for the "X tracks, Y vias" summary to look real.
  const segsPerLayer =
    Math.max(2, config.magnet_count * 2) * 2 - 1; // conductors + end-turns
  const totalTracks = segsPerLayer * config.phases * numLayers;
  const layers = Array.from({ length: numLayers }, (_, i) => ({
    layer_idx: i,
    phase_count: config.phases,
    segment_count: segsPerLayer * config.phases,
    via_count: 0,
  }));
  return {
    num_layers: numLayers,
    topology: config.coil_topology,
    layers,
    total_tracks: totalTracks,
    total_vias: 0,
  };
}

// ---------------------------------------------------------------------------
// B-field grid (sample_b_field) — WP4 / WP5 flux-viz backend
// ---------------------------------------------------------------------------

/**
 * Sample the B-field on an X–Z grid for the active magnet arrangement.
 * Returns a flat row-major array (Z slow axis) of B-vectors + positions.
 *
 * Defaults: 24×12 grid, x = [0, active_area_length_m],
 * z = [0, air_gap + magnet_height + 2 mm] (a 2 mm window above the magnet top).
 */
export async function sampleBField(
  config: LinearMotorConfig,
  n_x: number = 24,
  n_z: number = 12,
  x_extent_m: [number, number] = [0, config.active_area_length_m],
  z_extent_m: [number, number] = [
    0,
    config.air_gap_m + config.magnet_height_m + 2e-3,
  ],
): Promise<BFieldGridDto> {
  if (!isTauriAvailable()) {
    return mockBFieldGrid(config, n_x, n_z, x_extent_m, z_extent_m);
  }
  return await invoke<BFieldGridDto>("sample_b_field", {
    config,
    nX: n_x,
    nZ: n_z,
    xExtentM: x_extent_m,
    zExtentM: z_extent_m,
  });
}

function mockBFieldGrid(
  c: LinearMotorConfig,
  n_x: number,
  n_z: number,
  x_extent_m: [number, number],
  z_extent_m: [number, number],
): BFieldGridDto {
  const xs = Array.from({ length: n_x }, (_, i) =>
    x_extent_m[0] + (x_extent_m[1] - x_extent_m[0]) * (i / Math.max(n_x - 1, 1)),
  );
  const zs = Array.from({ length: n_z }, (_, i) =>
    z_extent_m[0] + (z_extent_m[1] - z_extent_m[0]) * (i / Math.max(n_z - 1, 1)),
  );
  const samples: BFieldGridDto["samples"] = [];
  for (const z of zs) {
    for (const x of xs) {
      // Mock: sinusoidal Bz, magnitude ∝ Br. Sufficient for visualising
      // arrangement-dependent asymmetry in the absence of a backend.
      const br = c.magnet_remanence_t;
      const k = (2 * Math.PI) / Math.max(c.magnet_pitch_m, 1e-6);
      const bz = 0.4 * br * Math.sin(k * x) * Math.exp(-z / 0.003);
      const bx = 0.05 * br * Math.cos(k * x) * Math.exp(-z / 0.003);
      const by = 0.0;
      const mag = Math.sqrt(bx * bx + by * by + bz * bz);
      samples.push({ x_m: x, z_m: z, bx_t: bx, by_t: by, bz_t: bz, mag_t: mag });
    }
  }
  return {
    samples,
    x_extent_m,
    z_extent_m,
    arrangement: c.magnet_arrangement,
  };
}

// ---------------------------------------------------------------------------
// Debounce helper for throttling slider-driven invokes
// ---------------------------------------------------------------------------

export function debounce<T extends (...args: never[]) => void>(
  fn: T,
  delayMs: number,
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}
