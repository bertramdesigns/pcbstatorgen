<script lang="ts">
  import type { ConfigStore } from "../stores/config.svelte";
  import type { CoilPathDto, CoilSegmentDto } from "../types";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";

  let { config, coils }: { config: ConfigStore; coils: CoilPathDto | null } = $props();

  const W = 760;
  const H = 260;
  const PAD = 30;

  const PHASE_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ec4899", "#8b5cf6"];
  const PHASE_LABELS = ["A", "B", "C", "D", "E"] as const;

  // -------------------------------------------------------------------
  // Zoom + section controls (Wish 5).
  //
  // `zoom` multiplies the apparent scale of the rendered coils. We use
  // a `<g transform>` on a world-coordinate group so the world → pixel
  // mapping is done in ONE place (the transform), and individual
  // segments/magnets draw in their natural metres units. Stroke widths
  // are kept constant in screen space via `vector-effect="non-scaling-stroke"`.
  //
  // `oneSection` clips the rendered conductors / end-turns to the
  // first pole pair (or 6 conductors, whichever is fewer) so the user
  // can see one repeating unit instead of the full pattern. Default is
  // OFF so the first thing the user sees is the full winding.
  // -------------------------------------------------------------------
  const ZOOM_STEPS = [0.5, 1, 1.5, 2, 3, 4] as const;
  let zoomIdx = $state(1); // index into ZOOM_STEPS (start at 1×)
  let zoom = $derived(ZOOM_STEPS[zoomIdx]);
  let oneSection = $state(false); // Bug B fix: default to OFF (show all)

  function zoomIn() {
    zoomIdx = Math.min(zoomIdx + 1, ZOOM_STEPS.length - 1);
  }
  function zoomOut() {
    zoomIdx = Math.max(zoomIdx - 1, 0);
  }
  function zoomReset() {
    zoomIdx = 1;
  }

  /**
   * One repeating unit of the winding = max(6, 2 × phases) conductors.
   * Mirrors the 3-phase / 1-pole-pair minimum needed to see the full
   * ABC phase interleave. Used when `oneSection` is on.
   */
  let oneSectionConductorCount = $derived(
    Math.max(6, 2 * config.phases),
  );

  // Bounding box of all phases (in metres).
  //
  // Defensive: take the min/max of the two x-components and the two
  // y-components separately so the result is correct regardless of
  // whether the bbox is stored as `[min_x, min_y, max_x, max_y]` or
  // `[max_x, max_y, min_x, min_y]`. The naïve "minX = min(bx0),
  // maxX = max(bx1)" form collapses to bboxW ≈ 1e-6 in the inverted
  // case, which then blows the fit-scale up to ~2e8 and squashes the
  // whole winding into a hairline off-screen — i.e. the "blank SVG"
  // symptom.
  let bbox = $derived.by(() => {
    if (!coils || coils.phases.length === 0) {
      return { minX: 0, minY: 0, maxX: 0.001, maxY: 0.001 };
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const ph of coils.phases) {
      const [b0, b1, b2, b3] = ph.bounding_box;
      minX = Math.min(minX, b0, b2);
      minY = Math.min(minY, b1, b3);
      maxX = Math.max(maxX, b0, b2);
      maxY = Math.max(maxY, b1, b3);
    }
    return { minX, minY, maxX: Math.max(maxX, minX + 1e-6), maxY: Math.max(maxY, minY + 1e-6) };
  });

  // World → outer-SVG-pixel transform with zoom and centering.
  //
  // The drawing area inside the background rect is (W − 2·PAD) wide and
  // (H − 2·PAD) tall. We fit the bbox into that area at the natural
  // (zoom = 1) scale, with the `meet` aspect behaviour (use the
  // smaller of the two scales so the bbox never overflows). The user's
  // zoom multiplies that base scale; we translate so the bbox stays
  // centred when zooming in. The y-flip is baked into the transform
  // (scale(1, −1)) so the caller can draw in physical metres (y up)
  // while the SVG screen stays in its native y-down orientation.
  let worldTransform = $derived.by(() => {
    const bboxW = bbox.maxX - bbox.minX;
    const bboxH = bbox.maxY - bbox.minY;
    const drawW = W - 2 * PAD;
    const drawH = H - 2 * PAD;
    const fitScale = Math.min(drawW / bboxW, drawH / bboxH);
    const s = fitScale * zoom;
    const renderedW = bboxW * s;
    const renderedH = bboxH * s;
    const cx = PAD + (drawW - renderedW) / 2;
    const cy = PAD + (drawH - renderedH) / 2;
    return {
      s,
      // After scale(1, -1) the y-axis is flipped; ty shifts so the
      // bbox top (world maxY) lands at `cy` and the bbox bottom
      // (world minY) lands at `cy + bboxH*s`.
      tx: cx - bbox.minX * s,
      ty: cy + bbox.maxY * s,
    };
  });

  // Magnet array overlay (in metres — drawn inside the transformed group).
  let magnets = $derived.by(() => {
    const arr: { x: number; w: number; pole: number }[] = [];
    const pitch = (config.magnet_width_mm + config.magnet_gap_mm) / 1000;
    const mw = config.magnet_width_mm / 1000;
    for (let i = 0; i < config.magnet_count; i++) {
      arr.push({ x: i * pitch, w: mw, pole: i % 2 === 0 ? 1 : -1 });
    }
    return arr;
  });

  // Layer schematic offset (in metres). 1 mm keeps the layers
  // visually separated on the schematic without overlapping the actual
  // winding, regardless of the zoom factor.
  const LAYER_OFFSET_M = 0.001;

  // Filter segments to the first N active conductors when "one section"
  // is on. End-turns that bridge to a conductor inside the window are
  // kept (so the section looks visually complete); end-turns that
  // bridge OUT of the window are dropped.
  let visibleSegments = $derived.by(() => {
    if (!coils) return new SvelteMap<number, CoilSegmentDto[]>();
    if (!oneSection) {
      // Fast path: all segments, keyed by phase+layer index.
      const m = new SvelteMap<number, CoilSegmentDto[]>();
      for (const ph of coils.phases) {
        m.set(ph.phase_idx * 1000 + ph.layer_idx, ph.segments);
      }
      return m;
    }
    // Build a set of "active conductor indices" in [0, N) per phase+layer.
    const m = new SvelteMap<number, CoilSegmentDto[]>();
    for (const ph of coils.phases) {
      const key = ph.phase_idx * 1000 + ph.layer_idx;
      const active = ph.segments.filter((s) => s.is_active);
      const keepIdx = new SvelteSet<number>();
      for (let i = 0; i < Math.min(oneSectionConductorCount, active.length); i++) {
        keepIdx.add(ph.segments.indexOf(active[i]));
      }
      // Also keep end-turns whose BOTH endpoints are inside the kept
      // active set (so the section forms a closed sub-loop visually).
      const keptSegs: CoilSegmentDto[] = [];
      for (let i = 0; i < ph.segments.length; i++) {
        if (ph.segments[i].is_active) {
          if (keepIdx.has(i)) keptSegs.push(ph.segments[i]);
        } else {
          // End-turn: keep if both neighbouring active conductors are kept.
          // Cheap proxy: keep end-turns whose index falls inside the
          // range covered by the kept actives.
          const firstKept = Math.min(...keepIdx);
          const lastKept = Math.max(...keepIdx);
          if (i > firstKept && i < lastKept) keptSegs.push(ph.segments[i]);
        }
      }
      m.set(key, keptSegs);
    }
    return m;
  });

  // -------------------------------------------------------------------
  // Phase visibility (per-phase show/hide).
  //
  // `coils.phases` is a flat list of `PhaseCoilDto` entries — one per
  // (phase, layer) pair, so a 3-phase / 4-layer board has 12 entries
  // and labels A, B, C, D, E… would cycle and produce duplicate
  // toggles. We first compute `uniquePhases`: a deduplicated list keyed
  // by `phase_idx`, sorted by that key, with the original `phase_name`
  // pulled from the data (e.g. "A", "B", "C"). The toggle loop
  // iterates over `uniquePhases`, and the segment rendering loop
  // checks visibility against `phase_idx` so both views stay in sync.
  // `phaseVisibility` is sized to 6 entries (one per potential phase);
  // out-of-bounds entries default to visible in `isPhaseVisible`.
  // -------------------------------------------------------------------
  let uniquePhases = $derived.by(() => {
    if (!coils) return [] as { idx: number; name: string; colorIdx: number }[];
    const byIdx: Record<number, { idx: number; name: string; colorIdx: number }> = {};
    for (const ph of coils.phases) {
      if (!(ph.phase_idx in byIdx)) {
        byIdx[ph.phase_idx] = {
          idx: ph.phase_idx,
          name: ph.phase_name,
          colorIdx: ph.phase_idx,
        };
      }
    }
    return Object.values(byIdx).sort((a, b) => a.idx - b.idx);
  });

  let phaseVisibility = $state<boolean[]>([true, true, true, true, true, true]);

  function isPhaseVisible(phaseIdx: number): boolean {
    return phaseVisibility[phaseIdx] !== false;
  }

  // -------------------------------------------------------------------
  // Pan support.
  //
  // When zoomed in the user can drag the SVG to pan the world around.
  // The pan is stored in SVG user-units (`panX`, `panY`) and added to
  // the inner `<g>` transform on top of the world→pixel mapping. The
  // drag origin is captured on `pointerdown`; the delta is computed
  // from `clientX`/`clientY` and converted from screen pixels to SVG
  // units using the ratio of the viewBox to the rendered size. We
  // `setPointerCapture` so the drag continues even if the pointer
  // leaves the SVG.
  // -------------------------------------------------------------------
  let svgRef: SVGSVGElement | undefined = $state();
  let panX = $state(0);
  let panY = $state(0);
  let isPanning = $state(false);
  let panStartClientX = 0;
  let panStartClientY = 0;
  let panStartPanX = 0;
  let panStartPanY = 0;

  function onSvgPointerDown(e: PointerEvent) {
    // Only start panning for the primary mouse button (or touch/pen).
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    isPanning = true;
    panStartClientX = e.clientX;
    panStartClientY = e.clientY;
    panStartPanX = panX;
    panStartPanY = panY;
    if (svgRef) {
      try {
        svgRef.setPointerCapture(e.pointerId);
      } catch {
        // Pointer capture can fail if the pointer is already released;
        // the move/up handlers will still run, so it's safe to ignore.
      }
    }
  }

  function onSvgPointerMove(e: PointerEvent) {
    if (!isPanning || !svgRef) return;
    // Convert the screen-space pixel delta to SVG user-units. With a
    // viewBox of (W, H) and a rendered size of (rect.width,
    // rect.height) the scale factor is W / rect.width.
    const rect = svgRef.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const scaleX = W / rect.width;
    const scaleY = H / rect.height;
    panX = panStartPanX + (e.clientX - panStartClientX) * scaleX;
    panY = panStartPanY + (e.clientY - panStartClientY) * scaleY;
  }

  function onSvgPointerEnd(e: PointerEvent) {
    if (!isPanning) return;
    isPanning = false;
    if (svgRef) {
      try {
        svgRef.releasePointerCapture(e.pointerId);
      } catch {
        // ignore
      }
    }
  }

  /** Reset both zoom and pan to their defaults. */
  function resetView() {
    zoomIdx = 1;
    panX = 0;
    panY = 0;
  }
</script>

<div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
  <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
    <h3 class="text-sm font-semibold text-slate-200">SVG Coil Preview</h3>
    <div class="flex items-center gap-3 flex-wrap">
      <span class="text-xs text-slate-400">
        {coils
          ? `${uniquePhases.length} phase${uniquePhases.length === 1 ? "" : "s"} · ${coils.layer_count} layer${coils.layer_count === 1 ? "" : "s"} · ${coils.phases.length} item${coils.phases.length === 1 ? "" : "s"}`
          : "no coils yet"}
      </span>
      <!-- Phase visibility toggles (per phase). A coloured dot + label
           for each phase, with a checkbox to show/hide that phase's
           traces. The label and dot dim when the phase is hidden. -->
      {#if coils && uniquePhases.length > 0}
        <div class="flex items-center gap-2 flex-wrap" role="group" aria-label="Phase visibility">
          {#each uniquePhases as ph (ph.idx)}
            <label
              class="flex items-center gap-1 text-xs select-none cursor-pointer"
              class:text-slate-500={!isPhaseVisible(ph.idx)}
              class:text-slate-300={isPhaseVisible(ph.idx)}
            >
              <input
                type="checkbox"
                bind:checked={phaseVisibility[ph.idx]}
                class="accent-emerald-500"
                aria-label={"Show phase " + ph.name}
              />
              <span
                class="inline-block w-2.5 h-2.5 rounded-full"
                style="background-color: {PHASE_COLORS[ph.colorIdx % PHASE_COLORS.length]}; opacity: {isPhaseVisible(ph.idx) ? 1 : 0.35}"
              ></span>
              <span>Phase {ph.name}</span>
            </label>
          {/each}
        </div>
      {/if}
      <!-- Zoom controls (Wish 5) -->
      <div class="flex items-center gap-1" role="group" aria-label="Zoom controls">
        <button
          type="button"
          class="px-2 py-0.5 text-xs rounded bg-slate-800 border border-slate-700 text-slate-300 hover:text-emerald-300 hover:border-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          aria-label="Zoom out"
          disabled={zoomIdx === 0}
          onclick={zoomOut}
        >−</button>
        <button
          type="button"
          class="px-2 py-0.5 text-xs font-mono rounded bg-slate-800 border border-slate-700 text-slate-300 hover:text-emerald-300 hover:border-emerald-600 transition-colors"
          aria-label="Reset zoom"
          title="Reset zoom"
          onclick={zoomReset}
        >{zoom}×</button>
        <button
          type="button"
          class="px-2 py-0.5 text-xs rounded bg-slate-800 border border-slate-700 text-slate-300 hover:text-emerald-300 hover:border-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          aria-label="Zoom in"
          disabled={zoomIdx === ZOOM_STEPS.length - 1}
          onclick={zoomIn}
        >+</button>
      </div>
      <!-- One-section toggle (Wish 5) -->
      <label class="flex items-center gap-1.5 text-xs text-slate-300 select-none cursor-pointer">
        <input
          type="checkbox"
          bind:checked={oneSection}
          class="accent-emerald-500"
          aria-label="Show only one repeating section of the pattern"
        />
        <span>one section</span>
      </label>
      <!-- Reset view (zoom + pan) -->
      <button
        type="button"
        class="px-2 py-0.5 text-xs rounded bg-slate-800 border border-slate-700 text-slate-300 hover:text-emerald-300 hover:border-emerald-600 transition-colors"
        aria-label="Reset zoom and pan"
        title="Reset zoom and pan"
        onclick={resetView}
      >Reset View</button>
    </div>
  </div>

  <svg
    bind:this={svgRef}
    viewBox="0 0 {W} {H}"
    class="w-full h-auto touch-none select-none {isPanning ? 'cursor-grabbing' : 'cursor-grab'}"
    role="img"
    aria-label="Coil preview"
    onpointerdown={onSvgPointerDown}
    onpointermove={onSvgPointerMove}
    onpointerup={onSvgPointerEnd}
    onpointercancel={onSvgPointerEnd}
  >
    <!-- Background PCB -->
    <rect x={PAD - 8} y={PAD - 8} width={W - 2 * PAD + 16} height={H - 2 * PAD + 16}
          fill="#0f172a" stroke="#334155" stroke-width="1" rx="6" />

    {#if coils}
      <!-- World-coordinate group. The transform maps (x, y) metres to
           outer-SVG pixels, with the y-axis flipped to match the SVG's
           y-down convention. Everything inside draws in natural metres
           — no per-element px() math required. -->
      <g transform="translate({worldTransform.tx + panX} {worldTransform.ty + panY}) scale({worldTransform.s} {-worldTransform.s})">
        {#each coils.phases as ph, pi (ph.phase_idx + "-" + ph.layer_idx)}
          {#if isPhaseVisible(ph.phase_idx)}
            {@const yOffset = ph.layer_idx * LAYER_OFFSET_M}
            {@const layerOpacity = Math.max(0.35, 1.0 - ph.layer_idx * 0.15)}
            {@const phaseColor = PHASE_COLORS[ph.phase_idx % PHASE_COLORS.length]}
            {@const segs = visibleSegments.get(ph.phase_idx * 1000 + ph.layer_idx) ?? ph.segments}
            <!-- Active conductors (drawn first, thicker) -->
            {#each segs.filter((s) => s.is_active) as seg, si (pi + "-a-" + si)}
              <line x1={seg.start[0]} y1={seg.start[1] + yOffset}
                    x2={seg.end[0]} y2={seg.end[1] + yOffset}
                    stroke={phaseColor} stroke-width="2.4" stroke-opacity={layerOpacity}
                    vector-effect="non-scaling-stroke" />
            {/each}
            <!-- End-turns (thinner, dashed) -->
            {#each segs.filter((s) => !s.is_active) as seg, si (pi + "-e-" + si)}
              <line x1={seg.start[0]} y1={seg.start[1] + yOffset}
                    x2={seg.end[0]} y2={seg.end[1] + yOffset}
                    stroke={phaseColor} stroke-width="1" stroke-dasharray="3 2" stroke-opacity={layerOpacity * 0.6}
                    vector-effect="non-scaling-stroke" />
            {/each}
          {/if}
        {/each}

        <!-- Magnet array overlay along the top edge of the bbox.
             3 mm wide × 5 mm tall, placed 1 mm above the top of the coils. -->
        {#each magnets as mag, i (i)}
          <rect x={mag.x} y={bbox.maxY + 0.001}
                width={Math.max(mag.w - 0.0005, 0.0005)} height="0.003"
                fill={mag.pole > 0 ? "#f97316" : "#3b82f6"} fill-opacity="0.7" />
        {/each}
      </g>

      <!-- Schematic disclaimer (outside the transformed group, in outer
           SVG pixel coords so it stays at the same place on zoom). -->
      <text x={W - 8} y={H - 4} text-anchor="end" class="fill-slate-500" style="font-size:9px">
        Schematic — layer offsets are for readability, not physical scale.
      </text>
    {:else}
      <text x={W / 2} y={H / 2} text-anchor="middle" class="fill-slate-500" style="font-size:14px">
        Awaiting coil generation…
      </text>
    {/if}

    <!-- Legend (outside the transformed group, in outer SVG pixel coords) -->
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
      <span class="text-slate-600">Drag the preview to pan when zoomed in.</span>
      {#if oneSection}
        <span class="text-amber-300">Showing only the first {oneSectionConductorCount} conductors (one repeating section).</span>
      {/if}
    </p>
  {/if}
</div>
