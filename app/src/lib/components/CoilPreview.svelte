<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";
  import type { CoilPathDto, PhaseCoilDto } from "../types";

  let { config, coils }: { config: ConfigStore; coils: CoilPathDto | null } = $props();

  const W = 760;
  const H = 260;
  const PAD = 30;

  const PHASE_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ec4899", "#8b5cf6"];

  // Plot bounds in metres → pixel transform.
  let bbox = $derived.by(() => {
    if (!coils || coils.phases.length === 0) {
      return { minX: 0, minY: 0, maxX: 0.001, maxY: 0.001 };
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const ph of coils.phases) {
      const [bx0, by0, bx1, by1] = ph.bounding_box;
      minX = Math.min(minX, bx0);
      minY = Math.min(minY, by0);
      maxX = Math.max(maxX, bx1);
      maxY = Math.max(maxY, by1);
    }
    return { minX, minY, maxX: Math.max(maxX, minX + 1e-6), maxY: Math.max(maxY, minY + 1e-6) };
  });

  let scaleX = $derived((W - 2 * PAD) / (bbox.maxX - bbox.minX));
  let scaleY = $derived((H - 2 * PAD) / (bbox.maxY - bbox.minY));
  let scale = $derived(Math.min(scaleX, scaleY));

  function px(x: number, y: number): [number, number] {
    return [PAD + (x - bbox.minX) * scale, H - PAD - (y - bbox.minY) * scale];
  }

  function segmentsPath(ph: PhaseCoilDto): string {
    if (ph.segments.length === 0) return "";
    let d = "";
    for (const seg of ph.segments) {
      const [sx, sy] = px(seg.start[0], seg.start[1]);
      const [ex, ey] = px(seg.end[0], seg.end[1]);
      d += `M ${sx} ${sy} L ${ex} ${ey} `;
    }
    return d.trim();
  }

  // Magnet array overlay (positions in metres → px).
  let magnets = $derived.by(() => {
    const arr: { x: number; w: number; pole: number }[] = [];
    const pitch = (config.magnet_width_mm + config.magnet_gap_mm) / 1000;
    const mw = config.magnet_width_mm / 1000;
    for (let i = 0; i < config.magnet_count; i++) {
      arr.push({ x: i * pitch, w: mw, pole: i % 2 === 0 ? 1 : -1 });
    }
    return arr;
  });
</script>

<div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
  <div class="flex items-center justify-between mb-2">
    <h3 class="text-sm font-semibold text-slate-200">SVG Coil Preview</h3>
    <span class="text-xs text-slate-400">
      {coils ? `${coils.phases.length} phase(s) · ${coils.layer_count} layer(s)` : "no coils yet"}
    </span>
  </div>

  <svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="Coil preview">
    <!-- Background PCB -->
    <rect x={PAD - 8} y={PAD - 8} width={W - 2 * PAD + 16} height={H - 2 * PAD + 16}
          fill="#0f172a" stroke="#334155" stroke-width="1" rx="6" />

    {#if coils}
      <!-- Active conductors (drawn first, thicker) -->
      {#each coils.phases as ph, pi (ph.phase_idx + "-" + ph.layer_idx)}
        {#each ph.segments.filter((s) => s.is_active) as seg, si (pi + "-a-" + si)}
          {@const [sx, sy] = px(seg.start[0], seg.start[1])}
          {@const [ex, ey] = px(seg.end[0], seg.end[1])}
          <line x1={sx} y1={sy} x2={ex} y2={ey}
                stroke={PHASE_COLORS[pi % PHASE_COLORS.length]} stroke-width="2.4" />
        {/each}
        <!-- End-turns (thinner, dashed) -->
        {#each ph.segments.filter((s) => !s.is_active) as seg, si (pi + "-e-" + si)}
          {@const [sx, sy] = px(seg.start[0], seg.start[1])}
          {@const [ex, ey] = px(seg.end[0], seg.end[1])}
          <line x1={sx} y1={sy} x2={ex} y2={ey}
                stroke={PHASE_COLORS[pi % PHASE_COLORS.length]} stroke-width="1" stroke-dasharray="3 2" opacity="0.6" />
        {/each}
      {/each}

      <!-- Magnet array overlay along top -->
      {#each magnets as mag, i (i)}
        {@const [mx] = px(mag.x, bbox.minY)}
        {@const [, myTop] = px(0, bbox.maxY)}
        <rect x={mx} y={myTop - 14} width={Math.max(mag.w * scale - 0.5, 0.5)} height="10"
              fill={mag.pole > 0 ? "#f97316" : "#3b82f6"} fill-opacity="0.7" rx="1" />
      {/each}
    {:else}
      <text x={W / 2} y={H / 2} text-anchor="middle" class="fill-slate-500" style="font-size:14px">
        Awaiting coil generation…
      </text>
    {/if}

    <!-- Legend -->
    <g transform="translate({PAD}, {H - 12})">
      <line x1="0" y1="0" x2="20" y2="0" stroke="#94a3b8" stroke-width="2.4" />
      <text x="26" y="4" class="fill-slate-400" style="font-size:11px">active conductor</text>
      <line x1="170" y1="0" x2="190" y2="0" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 2" opacity="0.6" />
      <text x="196" y="4" class="fill-slate-400" style="font-size:11px">end-turn</text>
    </g>
  </svg>

  {#if coils && coils.phases.length > 0}
    <p class="mt-2 text-xs text-slate-500">
      Solid lines = active conductors (force-generating, ⊥ to travel). Dashed = end-turns. Magnet poles overlay shown along the top edge.
    </p>
  {/if}
</div>
