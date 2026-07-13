<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";
  import { untrack } from "svelte";
  import { BACK_IRON_ARRANGEMENTS, DEFAULT_BACK_IRON_THICKNESS_MM } from "../stores/config.svelte";
  import MagnetGradeHelper from "./MagnetGradeHelper.svelte";

  let { config }: { config: ConfigStore } = $props();

  /** Back-iron only appears in the geometry when the chosen arrangement
   *  actually uses one (the "…BackIron" variants). The store value is left
   *  untouched across arrangement switches so re-selecting restores it. */
  let showBackIron = $derived(config.magnet_arrangement.endsWith("BackIron"));

  /** Auto-default the back-iron thickness when the user enables a BackIron
   *  arrangement for the first time. Lives in this component (not in the
   *  ConfigStore class) because Svelte 5 `$effect` can only run during
   *  component initialisation, not from inside a class constructor
   *  instantiated at module load. The thickness read is wrapped in
   *  `untrack` so the effect only depends on `magnet_arrangement` and
   *  can't re-run in response to its own write. */
  $effect(() => {
    const arrangement = config.magnet_arrangement;
    if (BACK_IRON_ARRANGEMENTS.has(arrangement)) {
      untrack(() => {
        if (config.back_iron_thickness_mm === 0) {
          config.back_iron_thickness_mm = DEFAULT_BACK_IRON_THICKNESS_MM;
        }
      });
    }
  });

  /** Slot pitch = (pole_pitch / phases) × spacing_ratio [mm]. */
  let slot_pitch_mm = $derived(
    (config.pole_pitch_mm / config.phases) * config.spacing_ratio
  );

  /** Vernier rest offset: phase offset between a coil center and the
   *  nearest pole center [mm]. Zero for 1:1 spacing, positive for Vernier
   *  ratios; clamped at zero to mirror the core's `rest_offset_m()`. */
  let rest_offset_mm = $derived(
    Math.max(0, (config.pole_pitch_mm / config.phases) * (1 - config.spacing_ratio))
  );

  // -------------------------------------------------------------------
  // Collapsible section state (Wish 3 — short-sighted fix).
  //
  // Each section has its own `$state` boolean. Default is `true` (open)
  // so the user sees the same layout as before. Clicking the <h3>
  // header toggles the boolean and the body slides open / closed via
  // a CSS grid-template-rows transition (the canonical Svelte-friendly
  // "animate height: auto" pattern).
  // -------------------------------------------------------------------
  let activeExpanded = $state(true);
  let magnetExpanded = $state(true);
  let coilExpanded = $state(true);
  let driveExpanded = $state(true);
  let derivedExpanded = $state(true);

  function toggle(expanded: boolean): boolean {
    return !expanded;
  }
</script>

<div class="space-y-6">
  <section class="space-y-4">
    <button
      type="button"
      class="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 transition-colors hover:text-emerald-300 focus:outline-none focus:text-emerald-300"
      aria-expanded={activeExpanded}
      aria-controls="param-section-active"
      onclick={() => (activeExpanded = toggle(activeExpanded))}
    >
      <span>Active Area &amp; Board</span>
      <span class="text-xs text-slate-500 font-mono w-4 text-right" aria-hidden="true">
        {activeExpanded ? "▾" : "▸"}
      </span>
    </button>
    <div
      id="param-section-active"
      class="grid transition-all duration-200 ease-in-out"
      style:grid-template-rows={activeExpanded ? "1fr" : "0fr"}
    >
      <div class="overflow-hidden space-y-4 min-h-0">
        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Active Area Length (mm) — primary board constraint</span>
          <input type="range" min="20" max="400" step="1" bind:value={config.active_area_length_mm} class="w-full accent-emerald-500" />
          <input type="number" min="1" step="0.1" bind:value={config.active_area_length_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Active Area Width (mm)</span>
          <input type="range" min="5" max="80" step="0.5" bind:value={config.active_area_width_mm} class="w-full accent-emerald-500" />
          <input type="number" min="1" step="0.1" bind:value={config.active_area_width_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>
      </div>
    </div>
  </section>

  <section class="space-y-4">
    <button
      type="button"
      class="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 transition-colors hover:text-emerald-300 focus:outline-none focus:text-emerald-300"
      aria-expanded={magnetExpanded}
      aria-controls="param-section-magnet"
      onclick={() => (magnetExpanded = toggle(magnetExpanded))}
    >
      <span>Magnet Array</span>
      <span class="text-xs text-slate-500 font-mono w-4 text-right" aria-hidden="true">
        {magnetExpanded ? "▾" : "▸"}
      </span>
    </button>
    <div
      id="param-section-magnet"
      class="grid transition-all duration-200 ease-in-out"
      style:grid-template-rows={magnetExpanded ? "1fr" : "0fr"}
    >
      <div class="overflow-hidden space-y-4 min-h-0">
        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Magnet Count (even ≥ 2)</span>
          <input type="number" min="2" max="64" step="2" bind:value={config.magnet_count} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span
            class="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1"
            title="Alternating = N-S / S-N pole pattern, simple and cheap. Halbach = adds extra magnet pieces that concentrate the B-field on the PCB side, reducing back-side leakage. Append BackIron for a steel keeper that further boosts the working field but adds normal attraction force (raises friction)."
          >
            Magnet Arrangement
          </span>
          <select
            bind:value={config.magnet_arrangement}
            class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
          >
            <option value="Alternating">Alternating (N-S / S-N)</option>
            <option value="AlternatingBackIron">Alternating + Steel back-iron (boosts field)</option>
            <option value="Halbach">Halbach array (concentrates field on one side)</option>
            <option value="HalbachBackIron">Halbach + Steel back-iron (max field)</option>
          </select>
        </label>

        <label class="block">
          <span
            class="block text-xs text-slate-400 mb-1"
            title="Distance the magnet spans along the travel direction (X axis). The pole pitch τ_p depends on this dimension."
          >
            Magnet Length (mm) — along the axis of motion (X)
          </span>
          <input type="range" min="1" max="40" step="0.5" bind:value={config.magnet_width_mm} class="w-full accent-emerald-500" />
          <input type="number" min="0.1" step="0.1" bind:value={config.magnet_width_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span
            class="block text-xs text-slate-400 mb-1"
            title="Perpendicular to the travel axis (Y). Defines the active conductor length L_active_conductor for Lorentz force."
          >
            Magnet Width (mm) — across the stator (Y)
          </span>
          <input type="range" min="1" max="40" step="0.5" bind:value={config.magnet_cross_width_mm} class="w-full accent-emerald-500" />
          <input type="number" min="0.1" step="0.1" bind:value={config.magnet_cross_width_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span
            class="block text-xs text-slate-400 mb-1"
            title="Magnetisation axis / air-gap normal. Sets how strong the B-field is at the PCB."
          >
            Magnet Thickness (mm) — magnetisation axis (Z)
          </span>
          <input type="range" min="0.5" max="20" step="0.5" bind:value={config.magnet_height_mm} class="w-full accent-emerald-500" />
          <input type="number" min="0.1" step="0.1" bind:value={config.magnet_height_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Magnet Gap (mm) — 0 = continuous</span>
          <input type="range" min="0" max="20" step="0.1" bind:value={config.magnet_gap_mm} class="w-full accent-emerald-500" />
          <input type="number" min="0" step="0.1" bind:value={config.magnet_gap_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        {#if showBackIron}
          <label class="block">
            <span
              class="block text-xs text-slate-400 mb-1"
              title="Thickness of the steel keeper behind the magnets. Boosts field on the PCB side but adds normal attraction force (increases friction). Set 0 for none."
            >
              Back-iron thickness (Z)
            </span>
            <input type="range" min="0" max="20" step="0.1" bind:value={config.back_iron_thickness_mm} class="w-full accent-emerald-500" />
            <input type="number" min="0" step="0.1" bind:value={config.back_iron_thickness_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
          </label>
        {/if}

        <MagnetGradeHelper {config} />
      </div>
    </div>
  </section>

  <section class="space-y-4">
    <button
      type="button"
      class="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 transition-colors hover:text-emerald-300 focus:outline-none focus:text-emerald-300"
      aria-expanded={coilExpanded}
      aria-controls="param-section-coil"
      onclick={() => (coilExpanded = toggle(coilExpanded))}
    >
      <span>Coil &amp; Winding</span>
      <span class="text-xs text-slate-500 font-mono w-4 text-right" aria-hidden="true">
        {coilExpanded ? "▾" : "▸"}
      </span>
    </button>
    <div
      id="param-section-coil"
      class="grid transition-all duration-200 ease-in-out"
      style:grid-template-rows={coilExpanded ? "1fr" : "0fr"}
    >
      <div class="overflow-hidden space-y-4 min-h-0">
        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Coil Topology</span>
          <select bind:value={config.coil_topology} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
            <option value="serpentine">Square Serpentine</option>
            <option value="sine_wave">Sine Wave Serpentine</option>
          </select>
        </label>

        <label class="block">
          <span
            class="block text-xs text-slate-400 mb-1"
            title="Ratio of slot pitch to pole pitch. 1:1 → mover rests directly over a coil at zero current. Vernier ratios (e.g. 0.8 = 4:5) offset the slot pitch so the mover rests between coils, increasing step resolution at the cost of a small fundamental force reduction."
          >
            Spacing Ratio / Vernier
          </span>
          <select bind:value={config.spacing_ratio_label} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
            <option value="1:1">1:1 Standard</option>
            <option value="4:5">4:5 Vernier</option>
            <option value="5:6">5:6 Vernier</option>
          </select>
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Number of Layers (even ≥ 2)</span>
          <input type="number" min="2" max="12" step="2" bind:value={config.num_layers} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>
      </div>
    </div>
  </section>

  <section class="space-y-4">
    <button
      type="button"
      class="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 transition-colors hover:text-emerald-300 focus:outline-none focus:text-emerald-300"
      aria-expanded={driveExpanded}
      aria-controls="param-section-drive"
      onclick={() => (driveExpanded = toggle(driveExpanded))}
    >
      <span>Drive &amp; Force Targets</span>
      <span class="text-xs text-slate-500 font-mono w-4 text-right" aria-hidden="true">
        {driveExpanded ? "▾" : "▸"}
      </span>
    </button>
    <div
      id="param-section-drive"
      class="grid transition-all duration-200 ease-in-out"
      style:grid-template-rows={driveExpanded ? "1fr" : "0fr"}
    >
      <div class="overflow-hidden space-y-4 min-h-0">
        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Phase Current (A)</span>
          <input type="number" min="0.01" step="0.05" bind:value={config.max_current_a} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Target Continuous Force (N)</span>
          <input type="number" min="0.001" step="0.01" bind:value={config.target_force_n} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Peak Burst Force (N)</span>
          <input type="number" min="0.001" step="0.01" bind:value={config.peak_force_n} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>

        <label class="block">
          <span class="block text-xs text-slate-400 mb-1">Friction Estimate (N)</span>
          <input type="number" min="0" step="0.005" bind:value={config.friction_n} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
        </label>
      </div>
    </div>
  </section>

  <!-- Derived / read-only outputs -->
  <section class="space-y-3 pt-2">
    <button
      type="button"
      class="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 transition-colors hover:text-emerald-300 focus:outline-none focus:text-emerald-300"
      aria-expanded={derivedExpanded}
      aria-controls="param-section-derived"
      onclick={() => (derivedExpanded = toggle(derivedExpanded))}
    >
      <span>Derived Geometry (read-only)</span>
      <span class="text-xs text-slate-500 font-mono w-4 text-right" aria-hidden="true">
        {derivedExpanded ? "▾" : "▸"}
      </span>
    </button>
    <div
      id="param-section-derived"
      class="grid transition-all duration-200 ease-in-out"
      style:grid-template-rows={derivedExpanded ? "1fr" : "0fr"}
    >
      <div class="overflow-hidden space-y-3 min-h-0">
        <div class="grid grid-cols-2 gap-2 text-sm">
          <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
            <div class="text-xs text-slate-400">Pole Pitch τ_p</div>
            <div class="font-mono text-emerald-300">{config.pole_pitch_mm.toFixed(2)} mm</div>
          </div>
          <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
            <div class="text-xs text-slate-400">Coil Span</div>
            <div class="font-mono text-emerald-300">{config.coil_span_mm.toFixed(2)} mm</div>
          </div>
          <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
            <div class="text-xs text-slate-400">Slot Pitch</div>
            <div class="font-mono text-emerald-300">{slot_pitch_mm.toFixed(2)} mm</div>
          </div>
          <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
            <div class="text-xs text-slate-400">Rest Offset</div>
            <div class="font-mono text-emerald-300">{rest_offset_mm.toFixed(2)} mm</div>
          </div>
          <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2 col-span-2">
            <div class="text-xs text-slate-400">Center-to-Center Travel (active − coil span)</div>
            <div class="font-mono {config.travel_mm > 0 ? 'text-sky-300' : 'text-rose-400'}">{config.travel_mm.toFixed(2)} mm</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</div>
