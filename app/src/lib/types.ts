/**
 * pcbstatorgen — IPC contract types for the Svelte frontend.
 *
 * Mirrors the Rust serde DTOs (phase G) and Python dataclasses
 * (pcbstatorgen.config). All physical quantities on the wire are SI
 * (metres, Tesla, Amperes, Ohms, Watts, Newtons). The UI store keeps
 * human-readable mm values and converts at the invoke boundary.
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type MagnetArrangement =
  | "Alternating"
  | "AlternatingBackIron"
  | "Halbach"
  | "HalbachBackIron";

export type CoilTopology = "serpentine" | "sine_wave";

export type SpacingRatio = "1:1" | "4:5" | "5:6";

export type CommutationMode = "max_torque" | "phase_a_only";

export type BearingType = "ball" | "ptfe" | "plastic";

// ---------------------------------------------------------------------------
// Config (IPC wire format — SI units)
// ---------------------------------------------------------------------------

export interface LinearMotorConfig {
  active_area_length_m: number;
  board_width_m: number;
  pcb_thickness_m: number;

  magnet_count: number;
  magnet_width_m: number; // travel-axis dimension
  magnet_cross_width_m: number; // across-stator dimension
  magnet_height_m: number;
  magnet_gap_m: number; // derived: pitch - width (kept for clarity)
  magnet_pitch_m: number; // = magnet_width + magnet_gap

  magnet_remanence_t: number;
  magnet_grade: string;
  magnet_arrangement: MagnetArrangement;
  back_iron_thickness_m: number;
  air_gap_m: number;

  coil_topology: CoilTopology;
  phases: number;
  spacing_ratio: number;

  max_current_a: number;
  supply_voltage_v: number;

  num_layers: number;
  min_trace_m: number;
  min_space_m: number;
  min_via_drill_m: number;
  min_via_annular_ring_m: number;
  max_layers: number;
  drive_frequency_hz: number;
  max_temperature_rise_c: number;

  target_force_n: number;
  peak_force_n: number;
  friction_n: number;
  carriage_mass_kg: number;
  max_accel_m_s2: number;
  capacitor_bank_uf: number;

  commutation: CommutationMode;
  n_positions: number;
  meshing: number;

  name: string | null;
}

// ---------------------------------------------------------------------------
// Derived config values (compute_config_derived)
// ---------------------------------------------------------------------------

export interface ConfigDerived {
  pole_pitch_m: number;
  coil_span_m: number;
  travel_m: number;
  slot_pitch_m: number;
  magnet_gap_m: number;
  min_via_pad_m: number;
  acceleration_force_n: number;
  minimum_drive_force_n: number;
  active_length_m: number;
}

// ---------------------------------------------------------------------------
// Coil path (generate_coils)
// ---------------------------------------------------------------------------

export interface CoilSegmentDto {
  start: [number, number]; // (x, y) [m]
  end: [number, number]; // (x, y) [m]
  is_active: boolean;
}

export interface PhaseCoilDto {
  phase_idx: number;
  layer_idx: number;
  phase_name: string;
  topology: CoilTopology;
  segments: CoilSegmentDto[];
  total_length_m: number;
  active_length_m: number;
  end_turn_length_m: number;
  active_conductor_count: number;
  bounding_box: [number, number, number, number]; // min_x, min_y, max_x, max_y
  terminal_start: [number, number];
  terminal_end: [number, number];
}

export interface CoilPathDto {
  phases: PhaseCoilDto[];
  layer_count: number;
}

// ---------------------------------------------------------------------------
// Force sweep (evaluate_force_sweep)
// ---------------------------------------------------------------------------

export interface ForceSweepResult {
  positions_m: number[];
  force_x_n: number[];
  force_y_n: number[];
  force_z_n: number[];
  per_phase_force_x: number[][];
  commutation: CommutationMode;
  current_a: number;
  mean_thrust_n: number;
  peak_thrust_n: number;
  min_thrust_n: number;
  ripple_pct: number;
  n_positions: number;
}

// ---------------------------------------------------------------------------
// Stackup / power / friction (compute_*)
// ---------------------------------------------------------------------------

export interface StackupResultDto {
  layer_count: number;
  trace_widths_m: number[];
  cu_thickness_m: number[];
  via_drill_m: number;
  via_annular_ring_m: number;
  via_grid_rows: number;
  via_grid_cols: number;
  estimated_force_n: number;
  estimated_dc_resistance_ohm: number;
  notes: string[];
}

export interface HeightStackResultDto {
  pcb_thickness_m: number;
  cu_protrusion_m: number;
  solder_mask_m: number;
  air_gap_m: number;
  magnet_height_m: number;
  back_iron_thickness_m: number;
  tolerance_m: number;
  total_height_m: number;
}

export interface FrictionBudgetDto {
  bearing_friction_n: number;
  cable_drag_n: number;
  wiper_contact_n: number;
  cogging_n: number;
  total_n: number;
  minimum_drive_force_n: number;
}

export interface PowerBudgetDto {
  phase_resistance_ohm: number;
  continuous_power_w: number;
  burst_power_w: number;
  temperature_rise_c: number;
  capacitor_required_uf: number;
  efficiency_pct: number;
}

// ---------------------------------------------------------------------------
// Magnet grade reference table (from PRODUCT_GOALS.md §3.C)
// ---------------------------------------------------------------------------

export interface MagnetGrade {
  name: string;
  br_min_t: number;
  br_typ_t: number;
  br_max_t: number;
  max_temp_c: Record<string, number>;
}

export const CUSTOM_GRADE = "Custom";

export const MAGNET_GRADES: Record<string, MagnetGrade> = {
  N35: { name: "N35", br_min_t: 1.17, br_typ_t: 1.19, br_max_t: 1.21, max_temp_c: { Std: 80, H: 120, SH: 150, UH: 180, EH: 200, AH: 220 } },
  N38: { name: "N38", br_min_t: 1.21, br_typ_t: 1.23, br_max_t: 1.25, max_temp_c: { Std: 80, H: 120, SH: 150, UH: 180, EH: 200, AH: 220 } },
  N42: { name: "N42", br_min_t: 1.28, br_typ_t: 1.30, br_max_t: 1.32, max_temp_c: { Std: 80, H: 120, SH: 150, UH: 180, EH: 200, AH: 220 } },
  N44: { name: "N44", br_min_t: 1.32, br_typ_t: 1.34, br_max_t: 1.36, max_temp_c: { Std: 80, H: 120, SH: 150, UH: 180, EH: 200, AH: 220 } },
  N48: { name: "N48", br_min_t: 1.38, br_typ_t: 1.40, br_max_t: 1.42, max_temp_c: { Std: 80, H: 120, SH: 150, UH: 180, EH: 200, AH: 220 } },
  N52: { name: "N52", br_min_t: 1.43, br_typ_t: 1.45, br_max_t: 1.48, max_temp_c: { Std: 80 } },
};

export const GRADE_NAMES = Object.keys(MAGNET_GRADES);

/** Extract base grade (e.g. "N44H" → "N44"). */
export function extractBaseGrade(grade: string): string {
  const m = grade.trim().match(/^([Nn]\d+)/);
  return m ? m[1].toUpperCase() : grade.trim();
}

/** Typical Br [T] for a grade name (handles thermal suffixes). */
export function getRemanence(grade: string): number {
  const base = extractBaseGrade(grade);
  return MAGNET_GRADES[base].br_typ_t;
}

// ---------------------------------------------------------------------------
// KiCad IPC API (connect_kicad / write_coils_to_board / ping_kicad)
// ---------------------------------------------------------------------------

export interface KicadConnection {
  connected: boolean;
  board_name: string;
  copper_layers: number;
}

export interface KicadWriteResult {
  items_created: number;
  commit_id: string;
}

export interface KicadPingResult {
  ok: boolean;
  version: string;
}
