<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";

  let { config }: { config: ConfigStore } = $props();

  // Local over-short warnings beyond the active-area check.
  let magnetGapInvalid = $derived(config.magnet_gap_mm < 0);
  let countInvalid = $derived(config.magnet_count < 2 || config.magnet_count % 2 !== 0);
  let travelNegative = $derived(config.travel_mm <= 0);
</script>

{#if travelNegative || countInvalid || magnetGapInvalid}
  <div class="rounded-md border border-amber-500/60 bg-amber-500/10 px-4 py-3 text-sm text-amber-200 space-y-1">
    {#if travelNegative}
      <p>
        Active area must be longer than the mover array
        (coil span = {config.coil_span_mm.toFixed(1)} mm).
        Current travel = {config.travel_mm.toFixed(1)} mm.
      </p>
    {/if}
    {#if countInvalid}
      <p>
        Magnet count must be an even number ≥ 2 (alternating poles).
        Got {config.magnet_count}.
      </p>
    {/if}
    {#if magnetGapInvalid}
      <p>Magnet gap must be ≥ 0 mm (0 = continuous array). Got {config.magnet_gap_mm} mm.</p>
    {/if}
  </div>
{/if}
