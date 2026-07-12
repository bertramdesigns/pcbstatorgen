<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";

  let { config }: { config: ConfigStore } = $props();

  const W = 760;
  const H = 220;
  const PAD = 40;
  const trackY = 120;
  const statorH = 40;
  const moverH = 36;

  // Raw drag position (may temporarily exceed travel when params shrink;
  // the derived `moverPosMm` clamps it for rendering).
  let moverPosRaw = $state(0);

  // Effective mover position, clamped to the valid travel range.
  let moverPosMm = $derived(
    Math.max(0, Math.min(moverPosRaw, config.travel_mm)),
  );

  let pxPerMm = $derived((W - 2 * PAD) / Math.max(config.active_area_length_mm, 1));

  let statorPxW = $derived(config.active_area_length_mm * pxPerMm);
  let coilSpanPx = $derived(config.coil_span_mm * pxPerMm);
  let travelPx = $derived(config.travel_mm * pxPerMm);
  let moverPxW = $derived(Math.max(coilSpanPx, 1));

  let statorX = $derived(PAD);
  let moverX = $derived(statorX + moverPosMm * pxPerMm);

  // Magnet rectangles along the mover bar.
  let magnets = $derived.by(() => {
    const arr: { x: number; w: number; pole: number }[] = [];
    const pitch = config.pole_pitch_mm;
    const mw = config.magnet_width_mm;
    for (let i = 0; i < config.magnet_count; i++) {
      arr.push({ x: i * pitch, w: mw, pole: i % 2 === 0 ? 1 : -1 });
    }
    return arr;
  });

  let dragging = $state(false);

  function onPointerDown(e: PointerEvent) {
    dragging = true;
    (e.currentTarget as SVGElement).setPointerCapture(e.pointerId);
    updateMoverFromPointer(e);
  }
  function onPointerMove(e: PointerEvent) {
    if (!dragging) return;
    updateMoverFromPointer(e);
  }
  function onPointerUp() {
    dragging = false;
  }
  function updateMoverFromPointer(e: PointerEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    const rect = svg.getBoundingClientRect();
    const scaleX = W / rect.width;
    const xSvg = (e.clientX - rect.left) * scaleX;
    const xRel = xSvg - statorX - moverPxW / 2;
    const pos = Math.max(0, Math.min(xRel / pxPerMm, config.travel_mm));
    moverPosRaw = pos;
  }

  let invalid = $derived(config.travel_mm <= 0);
</script>

<div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
  <div class="flex items-center justify-between mb-2">
    <h3 class="text-sm font-semibold text-slate-200">Interactive Travel Diagram</h3>
    <span class="text-xs text-slate-400">
      L_active = {config.active_area_length_mm.toFixed(1)} mm ·
      coil_span = {config.coil_span_mm.toFixed(1)} mm ·
      <span class={invalid ? 'text-rose-400' : 'text-sky-300'}>L_travel = {config.travel_mm.toFixed(1)} mm</span>
    </span>
  </div>

  <svg viewBox="0 0 {W} {H}" class="w-full h-auto select-none touch-none" role="img" aria-label="Travel diagram">
    {#if !invalid}
      <rect x={statorX} y={trackY - statorH / 2 - 6} width={travelPx / 2} height={statorH + 12}
            fill="#0ea5e9" fill-opacity="0.12" stroke="#0ea5e9" stroke-opacity="0.4" stroke-dasharray="4 3" rx="3" />
      <rect x={statorX + statorPxW - travelPx / 2} y={trackY - statorH / 2 - 6} width={travelPx / 2} height={statorH + 12}
            fill="#0ea5e9" fill-opacity="0.12" stroke="#0ea5e9" stroke-opacity="0.4" stroke-dasharray="4 3" rx="3" />
    {/if}

    <rect x={statorX} y={trackY - statorH / 2} width={statorPxW} height={statorH}
          fill="#1e293b" stroke="#475569" stroke-width="1.5" rx="4" />
    <text x={statorX + statorPxW / 2} y={trackY - statorH / 2 - 10} text-anchor="middle"
          class="fill-slate-300" style="font-size:13px">Stator (PCB) — L_active</text>

    <g
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      role="slider"
      tabindex="0"
      aria-valuenow={moverPosMm.toFixed(1)}
      aria-valuemin="0"
      aria-valuemax={config.travel_mm.toFixed(1)}
      aria-label="Mover position"
      style:cursor={invalid ? 'not-allowed' : dragging ? 'grabbing' : 'grab'}
    >
      <rect x={moverX} y={trackY + statorH / 2 + 8} width={moverPxW} height={moverH}
            fill={invalid ? '#7f1d1d' : '#065f46'} stroke={invalid ? '#f43f5e' : '#10b981'} stroke-width="1.5" rx="4" />

      {#each magnets as mag, i (i)}
        <rect x={moverX + mag.x * pxPerMm} y={trackY + statorH / 2 + 12}
              width={Math.max(mag.w * pxPerMm - 0.6, 0.5)} height={moverH - 8}
              fill={mag.pole > 0 ? '#f97316' : '#3b82f6'} fill-opacity="0.85" rx="1" />
      {/each}

      <text x={moverX + moverPxW / 2} y={trackY + statorH / 2 + 8 + moverH + 18} text-anchor="middle"
            class={invalid ? 'fill-rose-400' : 'fill-emerald-300'} style="font-size:12px">
        Mover — coil_span {#if !invalid}· drag to move ({moverPosMm.toFixed(1)} mm){/if}
      </text>
    </g>

    {#if !invalid}
      <g stroke="#0ea5e9" stroke-width="1" fill="#0ea5e9">
        <line x1={statorX} y1={trackY + statorH / 2 + 8 + moverH + 34}
              x2={statorX + statorPxW} y2={trackY + statorH / 2 + 8 + moverH + 34} />
        <line x1={statorX} y1={trackY + statorH / 2 + 8 + moverH + 28}
              x2={statorX} y2={trackY + statorH / 2 + 8 + moverH + 40} />
        <line x1={statorX + statorPxW} y1={trackY + statorH / 2 + 8 + moverH + 28}
              x2={statorX + statorPxW} y2={trackY + statorH / 2 + 8 + moverH + 40} />
      </g>
      <text x={statorX + statorPxW / 2} y={trackY + statorH / 2 + 8 + moverH + 52} text-anchor="middle"
            class="fill-sky-300" style="font-size:12px">L_travel = {config.travel_mm.toFixed(1)} mm</text>
    {/if}
  </svg>

  {#if invalid}
    <p class="mt-2 text-xs text-rose-400">
      Travel is zero or negative — increase Active Area Length or reduce Magnet Count / Width / Gap.
    </p>
  {:else}
    <p class="mt-2 text-xs text-slate-500">
      The blue end-zones show where the mover can travel while keeping all magnets over the winding.
      travel = stator_length − mover_length.
    </p>
  {/if}
</div>
