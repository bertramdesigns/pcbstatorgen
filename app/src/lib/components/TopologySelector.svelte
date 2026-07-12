<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";

  let { config }: { config: ConfigStore } = $props();

  let radialHover = $state(false);
</script>

<div class="flex items-center gap-3">
  <div class="text-xs uppercase tracking-wider text-slate-400 mr-1">Topology</div>

  <!-- Linear (active) -->
  <button
    type="button"
    onclick={() => (config.topology = "linear")}
    class="px-4 py-2 rounded-md text-sm font-medium transition-colors {config.topology === 'linear'
      ? 'bg-emerald-600 text-white shadow'
      : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}"
  >
    <span class="mr-1.5" aria-hidden="true">●</span> Linear Motion
  </button>

  <!-- Radial (disabled / TODO) -->
  <button
    type="button"
    disabled
    onpointerenter={() => (radialHover = true)}
    onpointerleave={() => (radialHover = false)}
    class="px-4 py-2 rounded-md text-sm font-medium cursor-not-allowed bg-slate-800 text-slate-500 border border-slate-700 relative"
    aria-disabled="true"
    title="Radial (axial-flux) motor mode is not yet implemented. Tracked for a future phase."
  >
    <span class="mr-1.5" aria-hidden="true">◯</span> Radial — TODO
  </button>

  {#if radialHover}
    <span class="text-xs text-amber-400 ml-1">
      Radial (axial-flux) motor mode is not yet implemented. Tracked for a future phase.
    </span>
  {/if}
</div>
