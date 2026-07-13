/**
 * pcbstatorgen — central configuration store (Svelte 5 runes class).
 *
 * Keeps user-facing values in mm (the natural unit for PCB design) and
 * exposes a `toIpc()` builder that converts to the SI LinearMotorConfig
 * expected by the Tauri backend. Derived geometry (pole pitch, coil span,
 * travel) is computed with `$derived` so every consumer updates live.
 */

import type {
  LinearMotorConfig,
  CoilTopology,
  SpacingRatio,
  MagnetArrangement,
  CommutationMode,
} from "../types";
import { getRemanence } from "../types";
import { mm } from "../tauri";

const SPACING_RATIO_MAP: Record<SpacingRatio, number> = {
  "1:1": 1.0,
  "4:5": 4 / 5,
  "5:6": 5 / 6,
};

/** Default back-iron thickness applied when the user enables a BackIron
 *  magnet arrangement for the first time. Only used when the user has
 *  not already configured a non-zero value. Exported so the auto-default
 *  behavior (in ParameterPanel.svelte) can reference the same value. */
export const DEFAULT_BACK_IRON_THICKNESS_MM = 1.0;

export const BACK_IRON_ARRANGEMENTS: ReadonlySet<MagnetArrangement> = new Set([
  "AlternatingBackIron",
  "HalbachBackIron",
]);

export class ConfigStore {
  // --- Topology ----------------------------------------------------------
  topology = $state<"linear" | "radial">("linear");

  // --- Active area (mm) --------------------------------------------------
  active_area_length_mm = $state(195);
  active_area_width_mm = $state(20);

  // --- Magnet array (mm) -------------------------------------------------
  magnet_count = $state(10);
  magnet_width_mm = $state(10);
  magnet_cross_width_mm = $state(10);
  magnet_gap_mm = $state(2);
  magnet_height_mm = $state(4);
  magnet_grade = $state("N44");
  magnet_remanence_t = $state(1.34);
  magnet_arrangement = $state<MagnetArrangement>("Alternating");
  back_iron_thickness_mm = $state(0);
  air_gap_mm = $state(0.5);

  // --- Coil --------------------------------------------------------------
  coil_topology = $state<CoilTopology>("serpentine");
  phases = $state(3);
  spacing_ratio_label = $state<SpacingRatio>("1:1");
  num_layers = $state(4);

  // --- Drive / electrical ------------------------------------------------
  max_current_a = $state(1.0);
  supply_voltage_v = $state(5.0);

  // --- Force targets / mechanical ---------------------------------------
  target_force_n = $state(0.5);
  peak_force_n = $state(1.0);
  friction_n = $state(0.05);
  carriage_mass_kg = $state(0.015);
  max_accel_m_s2 = $state(2.0);
  capacitor_bank_uf = $state(1000);

  // --- Solver -----------------------------------------------------------
  commutation = $state<CommutationMode>("max_torque");
  n_positions = $state(50);
  meshing = $state(20);

  // --- PCB manufacturing defaults (mm) ---------------------------------
  min_trace_mm = $state(0.127);
  min_space_mm = $state(0.127);
  min_via_drill_mm = $state(0.2);
  min_via_annular_ring_mm = $state(0.1);
  pcb_thickness_mm = $state(1.6);
  max_layers = $state(12);
  drive_frequency_hz = $state(500);
  max_temperature_rise_c = $state(20);

  // ---------------------------------------------------------------------
  // Derived geometry (mm, for the UI)
  // ---------------------------------------------------------------------

  pole_pitch_mm = $derived(this.magnet_width_mm + this.magnet_gap_mm);
  coil_span_mm = $derived(this.magnet_count * this.pole_pitch_mm);
  travel_mm = $derived(this.active_area_length_mm - this.coil_span_mm);
  spacing_ratio = $derived(SPACING_RATIO_MAP[this.spacing_ratio_label]);

  /** True when the active area is too short to cover the mover coil span. */
  is_active_area_invalid = $derived(this.active_area_length_mm <= this.coil_span_mm);

  /** Sync remanence from the selected grade unless "Custom". */
  syncGrade(): void {
    if (this.magnet_grade === "Custom") return;
    try {
      this.magnet_remanence_t = getRemanence(this.magnet_grade);
    } catch {
      // unknown grade — leave remanence untouched
    }
  }

  /** Build the SI LinearMotorConfig for the Tauri backend. */
  toIpc(): LinearMotorConfig {
    return {
      active_area_length_m: mm(this.active_area_length_mm),
      board_width_m: mm(this.active_area_width_mm),
      pcb_thickness_m: mm(this.pcb_thickness_mm),

      magnet_count: this.magnet_count,
      magnet_width_m: mm(this.magnet_width_mm),
      magnet_cross_width_m: mm(this.magnet_cross_width_mm),
      magnet_height_m: mm(this.magnet_height_mm),
      magnet_gap_m: mm(this.magnet_gap_mm),
      magnet_pitch_m: mm(this.pole_pitch_mm),

      magnet_remanence_t: this.magnet_remanence_t,
      magnet_grade: this.magnet_grade,
      magnet_arrangement: this.magnet_arrangement,
      back_iron_thickness_m: mm(this.back_iron_thickness_mm),
      air_gap_m: mm(this.air_gap_mm),

      coil_topology: this.coil_topology,
      phases: this.phases,
      spacing_ratio: this.spacing_ratio,

      max_current_a: this.max_current_a,
      supply_voltage_v: this.supply_voltage_v,

      num_layers: this.num_layers,
      min_trace_m: mm(this.min_trace_mm),
      min_space_m: mm(this.min_space_mm),
      min_via_drill_m: mm(this.min_via_drill_mm),
      min_via_annular_ring_m: mm(this.min_via_annular_ring_mm),
      max_layers: this.max_layers,
      drive_frequency_hz: this.drive_frequency_hz,
      max_temperature_rise_c: this.max_temperature_rise_c,

      target_force_n: this.target_force_n,
      peak_force_n: this.peak_force_n,
      friction_n: this.friction_n,
      carriage_mass_kg: this.carriage_mass_kg,
      max_accel_m_s2: this.max_accel_m_s2,
      capacitor_bank_uf: this.capacitor_bank_uf,

      commutation: this.commutation,
      n_positions: this.n_positions,
      meshing: this.meshing,

      name: null,
    };
  }
}

export const config = new ConfigStore();
