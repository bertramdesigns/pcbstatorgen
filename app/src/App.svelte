<script lang="ts">
  import { config } from "./lib/stores/config.svelte";
  import {
    evaluateForceSweep,
    generateCoils,
    computeFriction,
    computePowerBudget,
    computeHeightStack,
    computeStackup,
    debounce,
  } from "./lib/tauri";
  import type {
    ForceSweepResult,
    CoilPathDto,
    FrictionBudgetDto,
    PowerBudgetDto,
    HeightStackResultDto,
    StackupResultDto,
  } from "./lib/types";

  import TopologySelector from "./lib/components/TopologySelector.svelte";
  import ParameterPanel from "./lib/components/ParameterPanel.svelte";
  import TravelDiagram from "./lib/components/TravelDiagram.svelte";
  import CoilPreview from "./lib/components/CoilPreview.svelte";
  import MetricsPanel from "./lib/components/MetricsPanel.svelte";
  import ForceSweepPlot from "./lib/components/ForceSweepPlot.svelte";
  import ValidationWarning from "./lib/components/ValidationWarning.svelte";

  // Async result state.
  let sweep = $state<ForceSweepResult | null>(null);
  let coils = $state<CoilPathDto | null>(null);
  let friction = $state<FrictionBudgetDto | null>(null);
  let power = $state<PowerBudgetDto | null>(null);
  let height = $state<HeightStackResultDto | null>(null);
  let stackup = $state<StackupResultDto | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Whether the current config produces a valid travel range.
  let valid = $derived(config.travel_mm > 0);

  // Debounced recompute of all physics. Reads a snapshot of the config so the
  // latest values at call time are used. 150ms throttle per the spec.
  const recompute = debounce(async () => {
    loading = true;
    error = null;
    try {
      const ipc = config.toIpc();
      // Skip heavy sweeps when geometry is invalid; clear stale results.
      if (!valid) {
        sweep = null;
        coils = null;
        friction = null;
        power = null;
        height = null;
        stackup = null;
        return;
      }
      const [s, c, f, p, h, st] = await Promise.all([
        evaluateForceSweep(ipc),
        generateCoils(ipc),
        computeFriction(ipc),
        computePowerBudget(ipc),
        computeHeightStack(ipc),
        computeStackup(ipc),
      ]);
      sweep = s;
      coils = c;
      friction = f;
      power = p;
      height = h;
      stackup = st;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }, 150);

  // Recompute whenever any input the physics depends on changes.
  $effect(() => {
    // Touch every field that affects physics, then recompute.
    void [
      config.active_area_length_mm,
      config.active_area_width_mm,
      config.magnet_count,
      config.magnet_width_mm,
      config.magnet_gap_mm,
      config.magnet_height_mm,
      config.magnet_remanence_t,
      config.magnet_grade,
      config.magnet_arrangement,
      config.back_iron_thickness_mm,
      config.air_gap_mm,
      config.coil_topology,
      config.phases,
      config.spacing_ratio_label,
      config.num_layers,
      config.max_current_a,
      config.supply_voltage_v,
      config.target_force_n,
      config.peak_force_n,
      config.friction_n,
      config.carriage_mass_kg,
      config.max_accel_m_s2,
      config.commutation,
      config.n_positions,
      config.meshing,
    ];
    recompute();
  });
</script>

<main class="min-h-screen bg-slate-900 text-slate-100">
  <!-- Header -->
  <header class="border-b border-slate-800 px-6 py-4 sticky top-0 bg-slate-900/95 backdrop-blur z-10">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-xl font-bold tracking-tight">pcbstatorgen</h1>
        <p class="text-xs text-slate-400">PCB stator motor generator · linear topology · phase 5+6</p>
      </div>
      <div class="flex items-center gap-4">
        <TopologySelector {config} />
        <div class="flex items-center gap-2 text-xs">
          {#if loading}
            <span class="inline-block h-3 w-3 rounded-full bg-amber-400 animate-pulse"></span>
            <span class="text-amber-300">computing…</span>
          {:else}
            <span class="inline-block h-3 w-3 rounded-full bg-emerald-400"></span>
            <span class="text-emerald-300">ready</span>
          {/if}
        </div>
      </div>
    </div>
  </header>

  <!-- Dashboard grid -->
  <div class="grid gap-4 p-4 grid-cols-1 xl:grid-cols-[360px_1fr_380px]">
    <!-- Left: parameters -->
    <aside class="space-y-4">
      <div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
        <ParameterPanel {config} />
      </div>
      <ValidationWarning {config} />
    </aside>

    <!-- Center: diagrams -->
    <section class="space-y-4 min-w-0">
      {#if error}
        <div class="rounded-md border border-rose-500/60 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          Computation error: {error}
        </div>
      {/if}
      <TravelDiagram {config} />
      <CoilPreview {config} {coils} />
      <ForceSweepPlot result={sweep} />
    </section>

    <!-- Right: live metrics -->
    <aside class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
      <MetricsPanel
        {config}
        {sweep}
        {friction}
        {power}
        {height}
        {stackup}
      />
    </aside>
  </div>

  <footer class="px-6 py-3 text-xs text-slate-500 border-t border-slate-800">
    Linear mode only · radial/axial-flux disabled (TODO). Physics via Tauri IPC with mock fallback.
  </footer>
</main>
