<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";
  import { GRADE_NAMES, CUSTOM_GRADE, MAGNET_GRADES, extractBaseGrade } from "../types";

  let { config }: { config: ConfigStore } = $props();

  let selected = $derived(config.magnet_grade);

  let gradeInfo = $derived.by(() => {
    if (selected === CUSTOM_GRADE) return null;
    const base = extractBaseGrade(selected);
    return MAGNET_GRADES[base] ?? null;
  });

  let tempSuffixes = $derived(
    gradeInfo ? Object.entries(gradeInfo.max_temp_c) : [],
  );

  function onChange(e: Event) {
    const target = e.currentTarget as HTMLSelectElement;
    config.magnet_grade = target.value;
    config.syncGrade();
  }
</script>

<div class="space-y-2">
  <label class="block text-xs uppercase tracking-wider text-slate-400">
    Magnet Grade
    <select
      class="mt-1 w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
      value={selected}
      onchange={onChange}
    >
      {#each GRADE_NAMES as name (name)}
        <option value={name}>{name}</option>
      {/each}
      <option value={CUSTOM_GRADE}>{CUSTOM_GRADE}</option>
    </select>
  </label>

  {#if gradeInfo}
    <div class="text-xs text-slate-400 space-y-1">
      <p>
        Remanence Br: {gradeInfo.br_min_t.toFixed(2)}–{gradeInfo.br_max_t.toFixed(2)} T
        <span class="text-slate-500">(typ {gradeInfo.br_typ_t.toFixed(2)} T)</span>
      </p>
      <div class="flex flex-wrap gap-x-3 gap-y-0.5">
        {#each tempSuffixes as [suffix, temp] (suffix)}
          <span class="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700">
            {suffix}: {temp}°C
          </span>
        {/each}
      </div>
      <p class="text-emerald-400/80">Auto-filled Br = {config.magnet_remanence_t.toFixed(2)} T</p>
    </div>
  {:else}
    <div class="text-xs text-slate-400 space-y-1">
      <p>Custom grade — set Br manually below.</p>
      <label class="block text-slate-500">
        Br [T]
        <input
          type="number"
          step="0.01"
          min="0"
          max="2.5"
          class="mt-1 w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm"
          bind:value={config.magnet_remanence_t}
        />
      </label>
    </div>
  {/if}
</div>
