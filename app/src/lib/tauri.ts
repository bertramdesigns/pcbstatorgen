/**
 * pcbstatorgen — Tauri invoke wrappers with mock fallback.
 *
 * Every call attempts the real Tauri backend command (phase G). If the
 * command is unavailable (dev without backend, or not yet wired), a
 * deterministic mock is returned so the dashboard is fully interactive
 * during frontend-only development.
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
} from "./types";

// ---------------------------------------------------------------------------
// Unit helpers (mm ↔ m)
// ---------------------------------------------------------------------------

export const mm = (v: number): number => v / 1000.0;
export const to_mm = (v: number): number => v * 1000.0;

// ---------------------------------------------------------------------------
// Backend commands
// ---------------------------------------------------------------------------

export async function computeConfigDerived(
  config: LinearMotorConfig,
): Promise<ConfigDerived> {
  try {
    return await invoke<ConfigDerived>("compute_config_derived", { config });
  } catch {
    return mockConfigDerived(config);
  }
}

export async function generateCoils(
  config: LinearMotorConfig,
): Promise<CoilPathDto> {
  try {
    return await invoke<CoilPathDto>("generate_coils", { config });
  } catch {
    return mockCoils(config);
  }
}

export async function evaluateForceSweep(
  config: LinearMotorConfig,
): Promise<ForceSweepResult> {
  try {
    return await invoke<ForceSweepResult>("evaluate_force_sweep", { config });
  } catch {
    return mockForceSweep(config);
  }
}

export async function computeHeightStack(
  config: LinearMotorConfig,
): Promise<HeightStackResultDto> {
  try {
    return await invoke<HeightStackResultDto>("compute_height_stack", {
      config,
    });
  } catch {
    return mockHeightStack(config);
  }
}

export async function computePowerBudget(
  config: LinearMotorConfig,
): Promise<PowerBudgetDto> {
  try {
    return await invoke<PowerBudgetDto>("compute_power_budget", { config });
  } catch {
    return mockPowerBudget(config);
  }
}

export async function computeFriction(
  config: LinearMotorConfig,
): Promise<FrictionBudgetDto> {
  try {
    return await invoke<FrictionBudgetDto>("compute_friction", { config });
  } catch {
    return mockFriction(config);
  }
}

export async function computeStackup(
  config: LinearMotorConfig,
): Promise<StackupResultDto> {
  try {
    return await invoke<StackupResultDto>("compute_stackup", { config });
  } catch {
    return mockStackup(config);
  }
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
