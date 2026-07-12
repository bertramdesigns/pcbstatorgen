<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";
  import MagnetGradeHelper from "./MagnetGradeHelper.svelte";

  let { config }: { config: ConfigStore } = $props();
</script>

<div class="space-y-6">
  <section class="space-y-4">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1">
      Active Area &amp; Board
    </h3>

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
  </section>

  <section class="space-y-4">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1">
      Magnet Array
    </h3>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Magnet Count (even ≥ 2)</span>
      <input type="number" min="2" max="64" step="2" bind:value={config.magnet_count} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
    </label>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Magnet Width (mm)</span>
      <input type="range" min="1" max="40" step="0.5" bind:value={config.magnet_width_mm} class="w-full accent-emerald-500" />
      <input type="number" min="0.1" step="0.1" bind:value={config.magnet_width_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
    </label>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Magnet Gap (mm) — 0 = continuous</span>
      <input type="range" min="0" max="20" step="0.1" bind:value={config.magnet_gap_mm} class="w-full accent-emerald-500" />
      <input type="number" min="0" step="0.1" bind:value={config.magnet_gap_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
    </label>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Magnet Height (mm)</span>
      <input type="number" min="0.1" step="0.1" bind:value={config.magnet_height_mm} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm" />
    </label>

    <MagnetGradeHelper {config} />
  </section>

  <section class="space-y-4">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1">
      Coil &amp; Winding
    </h3>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Coil Topology</span>
      <select bind:value={config.coil_topology} class="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
        <option value="serpentine">Square Serpentine</option>
        <option value="sine_wave">Sine Wave Serpentine</option>
      </select>
    </label>

    <label class="block">
      <span class="block text-xs text-slate-400 mb-1">Spacing Ratio / Vernier</span>
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
  </section>

  <section class="space-y-4">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1">
      Drive &amp; Force Targets
    </h3>

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
  </section>

  <!-- Derived / read-only outputs -->
  <section class="space-y-3 pt-2">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1">
      Derived Geometry (read-only)
    </h3>
    <div class="grid grid-cols-2 gap-2 text-sm">
      <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
        <div class="text-xs text-slate-400">Pole Pitch τ_p</div>
        <div class="font-mono text-emerald-300">{config.pole_pitch_mm.toFixed(2)} mm</div>
      </div>
      <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2">
        <div class="text-xs text-slate-400">Coil Span</div>
        <div class="font-mono text-emerald-300">{config.coil_span_mm.toFixed(2)} mm</div>
      </div>
      <div class="rounded-md bg-slate-800/60 border border-slate-700 px-3 py-2 col-span-2">
        <div class="text-xs text-slate-400">Center-to-Center Travel (active − coil span)</div>
        <div class="font-mono {config.travel_mm > 0 ? 'text-sky-300' : 'text-rose-400'}">{config.travel_mm.toFixed(2)} mm</div>
      </div>
    </div>
  </section>
</div>
