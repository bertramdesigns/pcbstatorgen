<script lang="ts">
  /**
   * TravelDiagram.svelte — two views of the stator / mover assembly.
   *
   *   1. 3/4 isometric view: axonometric projection of the assembly
   *      (PCB wireframe + magnet wireframe + optional back-iron). Z is
   *      exaggerated so the thin stackup is visible. The magnet block
   *      sits at the current `moverPosMm` along the travel axis.
   *
   *   2. Front-on orthographic view (Y–Z cross-section): SVG X-axis is
   *      the board WIDTH (Y in the config), SVG Y-axis is Z+ UP. Each
   *      layer is rendered as a full-width rectangle. The N·S pole
   *      alternation happens along the TRAVEL direction (X), which is
   *      perpendicular to this view, so the magnet block is uniform. A
   *      "N · S" label makes the alternation axis explicit. Real mm
   *      thicknesses are shown on the dim line; the four small number
   *      inputs beneath the SVG are bound to the config so the stackup
   *      re-flows in real time.
   *
   *   `moverPosRaw` is shared state for the mover position (mm along
   *   travel). It is currently initialized to 0; a dedicated slider
   *   widget will write to it in a follow-up task. The 3/4 view's
   *   magnet placement reads from it via the derived `moverPosMm`
   *   (clamped to `config.travel_mm`).
   *
   *   Every shape here is a plain SVG primitive driven by the
   *   `ConfigStore` (see `stores/config.svelte.ts`).
   */
  import type { ConfigStore } from "../stores/config.svelte";

  let { config }: { config: ConfigStore } = $props();

  // ====================================================================
  // Shared mover position (mm along travel, CENTER of magnet array)
  // ====================================================================
  // `moverPosRaw` is shared state consumed by the 3/4 view's `isoGeom`
  // (via the clamped `moverPosMm` derived below) AND by the slider
  // widget below the views. The slider value represents the CENTER of
  // the magnet array — the magnet extends from
  // `(moverPosMm - coilSpan/2)` to `(moverPosMm + coilSpan/2)`. The
  // clamp keeps the magnet fully inside the active area:
  // `[coilSpan/2, active_area_length - coilSpan/2]`.
  let moverPosRaw = $state(0);
  let coilSpanMm = $derived(config.magnet_count * config.pole_pitch_mm);
  let moverPosMm = $derived.by(() => {
    const min = coilSpanMm / 2;
    const max = config.active_area_length_mm - coilSpanMm / 2;
    return Math.max(min, Math.min(moverPosRaw, max));
  });
  // Magnet extent in mm (used by the 3/4 view AND the display row).
  let magnetStartMm = $derived(moverPosMm - coilSpanMm / 2);
  let magnetEndMm = $derived(moverPosMm + coilSpanMm / 2);

  // ====================================================================
  // 1. 3/4 ISOMETRIC VIEW
  // ====================================================================
  // Axonometric projection:
  //     sx = cx + (x + 0.45·y) · sXY
  //     sy = cy + (-z·Z_EXAG + 0.45·y) · sXY
  // Z is exaggerated so the thin stackup is visible at this canvas
  // size. The 0.45 Y-coupling gives a ~24° "3/4" look from above-front.
  // ====================================================================

  const ISO_W = 220;
  const ISO_H = 220;
  const ISO_PAD = 14;
  const Z_EXAG = 10; // vertical exaggeration factor for the iso view

  let isoScale = $derived(
    (ISO_W - 2 * ISO_PAD) / Math.max(config.active_area_length_mm * 1.45, 1),
  );

  function isoProject(
    x: number, y: number, z: number, cx: number, cy: number,
  ): [number, number] {
    const sxy = isoScale;
    const sz = isoScale * Z_EXAG;
    return [
      cx + (x + 0.45 * y) * sxy,
      cy + (-z * sz + 0.45 * y * sxy),
    ];
  }

  // Center the assembly's bounding box in the iso canvas.
  let isoCenter = $derived.by(() => {
    const L = config.active_area_length_mm;
    const W = config.active_area_width_mm;
    const pcbT = config.pcb_thickness_mm;
    const ag = config.air_gap_mm;
    const mh = config.magnet_height_mm;
    const bi = config.back_iron_thickness_mm;
    const totalH = pcbT + ag + mh + bi;
    const corners: [number, number, number][] = [
      [0, 0, 0], [L, 0, 0], [L, W, 0], [0, W, 0],
      [0, 0, totalH], [L, 0, totalH], [L, W, totalH], [0, W, totalH],
    ];
    let minSx = Infinity, minSy = Infinity, maxSx = -Infinity, maxSy = -Infinity;
    const tmpCx = ISO_W / 2, tmpCy = ISO_H / 2;
    for (const [x, y, z] of corners) {
      const [sx, sy] = isoProject(x, y, z, tmpCx, tmpCy);
      if (sx < minSx) minSx = sx;
      if (sy < minSy) minSy = sy;
      if (sx > maxSx) maxSx = sx;
      if (sy > maxSy) maxSy = sy;
    }
    const dx = (minSx + maxSx) / 2;
    const dy = (minSy + maxSy) / 2;
    return {
      cx: ISO_W / 2 + (tmpCx - dx),
      cy: ISO_H / 2 + (tmpCy - dy),
    };
  });

  // Back-iron visibility predicate. Mirrors the same `has_back_iron` rune
  // defined in FluxDiagram.svelte (line 197) so both views agree on when
  // the steel back-iron should be drawn. Top-level (not nested inside
  // `isoGeom` or `geom`) so the Svelte 5 dependency tracker sees both
  // `magnet_arrangement` and `back_iron_thickness_mm` as sources of this
  // derived and the template `{#if has_back_iron}` re-evaluates the
  // instant either one changes.
  let has_back_iron = $derived(
    config.magnet_arrangement.endsWith("BackIron") &&
      config.back_iron_thickness_mm > 0,
  );

  let isoGeom = $derived.by(() => {
    const pcbT = config.pcb_thickness_mm;
    const ag = config.air_gap_mm;
    const mh = config.magnet_height_mm;
    const bi = config.back_iron_thickness_mm;
    return {
      L: config.active_area_length_mm,
      W: config.active_area_width_mm,
      pcbT,
      ag,
      mh,
      bi,
      // Z-stack (stator at z=0, then PCB → air gap → magnet → optional back iron).
      // The magnet must sit ABOVE the PCB with the air gap in between, so the
      // magnet's bottom is at z = pcbT + ag (previously just `ag`, which made the
      // magnet wireframe overlap the PCB wireframe in the 3/4 iso view).
      pcbZTop: pcbT,
      airGapZBottom: pcbT,
      magnetZBottom: pcbT + ag,
      backIronZBottom: pcbT + ag + mh,
      // `moverPosMm` is the CENTER of the magnet array; the magnet
      // extends from `moverPosMm - coilSpan/2` to `moverPosMm + coilSpan/2`.
      magnetStartX: magnetStartMm,
      magnetEndX: magnetEndMm,
    };
  });

  // Render a 3D box as a wireframe path string + its projected corners.
  function isoBoxPath(
    x0: number, y0: number, z0: number,
    dx: number, dy: number, dz: number,
    cx: number, cy: number,
  ): { d: string; corners: [number, number][] } {
    const x1 = x0 + dx, y1 = y0 + dy, z1 = z0 + dz;
    const pts: [number, number, number][] = [
      [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], // bottom
      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1], // top
    ];
    const s = pts.map(([x, y, z]) => isoProject(x, y, z, cx, cy));
    const edges: [number, number][][] = [
      // bottom rectangle
      [s[0], s[1]], [s[1], s[2]], [s[2], s[3]], [s[3], s[0]],
      // top rectangle
      [s[4], s[5]], [s[5], s[6]], [s[6], s[7]], [s[7], s[4]],
      // verticals
      [s[0], s[4]], [s[1], s[5]], [s[2], s[6]], [s[3], s[7]],
    ];
    const d = edges
      .map(([a, b]) => `M ${a[0].toFixed(1)} ${a[1].toFixed(1)} L ${b[0].toFixed(1)} ${b[1].toFixed(1)}`)
      .join(" ");
    return { d, corners: s };
  }

  // Pre-computed wireframe boxes for the iso view. These are derived
  // values (not {@const} tags) because {@const} must be the immediate
  // child of a control-flow block, and the iso view draws them at the
  // top level of its <svg>.
  let isoStatorBox = $derived(
    isoBoxPath(0, 0, 0, isoGeom.L, isoGeom.W, isoGeom.pcbT, isoCenter.cx, isoCenter.cy),
  );
  let isoMagnetBox = $derived(
    isoBoxPath(isoGeom.magnetStartX, 0, isoGeom.magnetZBottom,
      isoGeom.magnetEndX - isoGeom.magnetStartX, isoGeom.W, isoGeom.mh,
      isoCenter.cx, isoCenter.cy),
  );
  let isoBackIronBox = $derived(
    has_back_iron
      ? isoBoxPath(isoGeom.magnetStartX, 0, isoGeom.backIronZBottom,
          isoGeom.magnetEndX - isoGeom.magnetStartX, isoGeom.W, isoGeom.bi,
          isoCenter.cx, isoCenter.cy)
      : null,
  );

  // ====================================================================
  // 2. FRONT-ON ORTHOGRAPHIC VIEW (Y–Z cross-section)
  // ====================================================================
  // View rotated 90° from the side view: the SVG X-axis now spans the
  // board width (Y in the config) and the SVG Y-axis is still Z+ UP.
  // Each layer is rendered as a full-width rectangle. The N/S pole
  // alternation happens along the TRAVEL direction (X in the config),
  // which is invisible in this view — the magnet block is therefore a
  // uniform rectangle (the user sees the height profile, not the pole
  // pattern). A small "N·S" label above the block makes the alternation
  // axis explicit. Real mm thicknesses (modulo the Z exaggeration that
  // fits the stack inside ORTHO_H) are reported in the dim-line labels
  // on the right.
  // ====================================================================

  const ORTHO_W = 180;
  const ORTHO_H = 220;
  const ORTHO_PAD_L = 8;
  const ORTHO_PAD_R = 30; // reserved for the height-dimension labels
  const ORTHO_PAD_T = 12;
  const ORTHO_PAD_B = 16;

  let pcbThicknessMm = $derived(config.pcb_thickness_mm);
  let airGapMm = $derived(config.air_gap_mm);
  let magnetHeightMm = $derived(config.magnet_height_mm);
  let backIronMm = $derived(config.back_iron_thickness_mm);
  let boardWidthMm = $derived(config.active_area_width_mm);
  let totalStackMm = $derived(
    pcbThicknessMm + airGapMm + magnetHeightMm + backIronMm,
  );

  // X-axis now spans the BOARD WIDTH (Y in the config) — was active
  // area length in the X–Z view. Z-axis is still up.
  let orthoXScale = $derived(
    (ORTHO_W - ORTHO_PAD_L - ORTHO_PAD_R) / Math.max(boardWidthMm, 1),
  );
  let orthoZScale = $derived(
    (ORTHO_H - ORTHO_PAD_T - ORTHO_PAD_B) / Math.max(totalStackMm, 0.1),
  );
  // Pixel width of the stackup rect (capped so very wide boards don't
  // overflow; the rect is left-padded to ORTHO_PAD_L regardless).
  let orthoStackPxW = $derived(boardWidthMm * orthoXScale);

  // Layer boundaries — z=0 at the BOTTOM, Z+ UP.
  let orthoBaseY = $derived(ORTHO_H - ORTHO_PAD_B);
  let orthoPcbTopY = $derived(orthoBaseY - pcbThicknessMm * orthoZScale);
  let orthoAirGapTopY = $derived(orthoPcbTopY - airGapMm * orthoZScale);
  let orthoMagnetTopY = $derived(orthoAirGapTopY - magnetHeightMm * orthoZScale);
  let orthoBackIronTopY = $derived(orthoMagnetTopY - backIronMm * orthoZScale);

  // X position of the height-dimension line in the orthographic view.
  let orthoDimX = $derived(ORTHO_W - 4);

  let invalid = $derived(config.travel_mm <= 0);
</script>

<div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4">
  <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
    <h3 class="text-sm font-semibold text-slate-200">Travel Diagram</h3>
    <span class="text-xs text-slate-400">
      L_active = {config.active_area_length_mm.toFixed(1)} mm ·
      coil_span = {config.coil_span_mm.toFixed(1)} mm ·
      <span class={invalid ? 'text-rose-400' : 'text-sky-300'}>L_travel = {config.travel_mm.toFixed(1)} mm</span>
    </span>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-[1fr_180px] gap-3 items-start">
    <!-- ===== 1. 3/4 isometric view ===== -->
    <div class="min-w-0">
      <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">3/4 view</div>
      <svg viewBox="0 0 {ISO_W} {ISO_H}" class="w-full h-auto"
           role="img" aria-label="Three-quarter isometric view of the assembly">
        <!-- Stator (PCB) wireframe box -->
        <path d={isoStatorBox.d} fill="#1e293b" fill-opacity="0.35" stroke="#94a3b8" stroke-width="1" />
        <text x={isoStatorBox.corners[0][0] - 4} y={isoStatorBox.corners[0][1] + 12} text-anchor="end"
              class="fill-slate-400" style="font-size:9px">PCB</text>

        <!-- Magnet array wireframe box (moves with the slider) -->
        <path d={isoMagnetBox.d} fill="#065f46" fill-opacity="0.35" stroke="#10b981" stroke-width="1" />
        <text x={(isoMagnetBox.corners[4][0] + isoMagnetBox.corners[5][0]) / 2}
              y={isoMagnetBox.corners[4][1] - 4} text-anchor="middle"
              class="fill-emerald-300" style="font-size:9px">Magnets</text>

        <!-- Back iron wireframe (if present) -->
        {#if isoBackIronBox}
          <path d={isoBackIronBox.d} fill="#a16207" fill-opacity="0.35" stroke="#ca8a04" stroke-width="1" />
        {/if}

        <!-- Axis legend (bottom-left corner) -->
        <g style="font-size:8px" stroke-linecap="round">
          <!-- X axis: right (red) -->
          <line x1="20" y1={ISO_H - 22} x2="38" y2={ISO_H - 22} stroke="#ef4444" stroke-width="1.4" />
          <text x="40" y={ISO_H - 19} class="fill-red-300">X</text>
          <!-- Y axis: diagonal down-right (green) -->
          <line x1="20" y1={ISO_H - 22} x2="33" y2={ISO_H - 14} stroke="#22c55e" stroke-width="1.4" />
          <text x="34" y={ISO_H - 10} class="fill-green-300">Y</text>
          <!-- Z axis: up (blue) -->
          <line x1="20" y1={ISO_H - 22} x2="20" y2={ISO_H - 40} stroke="#3b82f6" stroke-width="1.4" />
          <text x="23" y={ISO_H - 40} class="fill-blue-300">Z</text>
        </g>
      </svg>
    </div>

    <!-- ===== 2. Front-on orthographic stackup (Y–Z) ===== -->
    <div class="min-w-0">
      <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        Front view (Y–Z)
      </div>
      <svg viewBox="0 0 {ORTHO_W} {ORTHO_H}" class="w-full h-auto"
           role="img" aria-label="Front-on orthographic Y–Z cross-section of the height stack">
        <!-- PCB (bottom layer) — full width -->
        <rect x={ORTHO_PAD_L} y={orthoPcbTopY}
              width={orthoStackPxW}
              height={pcbThicknessMm * orthoZScale}
              fill="#1e293b" stroke="#475569" stroke-width="0.7" />
        <text x={ORTHO_PAD_L + 3} y={orthoBaseY - 2} class="fill-slate-300" style="font-size:7px">PCB</text>

        <!-- Air gap (light tint, only if there's room) — full width -->
        {#if airGapMm > 0 && airGapMm * orthoZScale >= 0.5}
          <rect x={ORTHO_PAD_L} y={orthoAirGapTopY}
                width={orthoStackPxW}
                height={airGapMm * orthoZScale}
                fill="rgba(100,116,139,0.15)" stroke="#475569" stroke-width="0.5" />
        {/if}

        <!-- Magnet block — solid rectangle (N/S alternation is along
             the travel direction, which is hidden in this view) -->
        <rect x={ORTHO_PAD_L} y={orthoMagnetTopY}
              width={orthoStackPxW}
              height={magnetHeightMm * orthoZScale}
              fill="#10b981" fill-opacity="0.45"
              stroke="#10b981" stroke-width="0.5" stroke-opacity="0.8" />
        <text x={ORTHO_PAD_L + orthoStackPxW / 2}
              y={orthoMagnetTopY + magnetHeightMm * orthoZScale / 2 + 2.5}
              text-anchor="middle" class="fill-emerald-200" style="font-size:7px">
          N · S
        </text>

        <!-- Back iron (if present) — full width, gated on the same
             `has_back_iron` predicate as the 3/4 view and FluxDiagram. -->
        {#if has_back_iron && backIronMm * orthoZScale >= 0.5}
          <rect x={ORTHO_PAD_L} y={orthoBackIronTopY}
                width={orthoStackPxW}
                height={backIronMm * orthoZScale}
                fill="#a16207" fill-opacity="0.6" stroke="#ca8a04" stroke-width="0.5" />
        {/if}

        <!-- Stack height dimension line (right side) -->
        <g stroke="#94a3b8" stroke-width="0.5">
          <line x1={orthoDimX} y1={orthoBaseY} x2={orthoDimX} y2={orthoBackIronTopY} />
          <line x1={orthoDimX - 2} y1={orthoBaseY} x2={orthoDimX + 2} y2={orthoBaseY} />
          <line x1={orthoDimX - 2} y1={orthoPcbTopY} x2={orthoDimX + 2} y2={orthoPcbTopY} />
          <line x1={orthoDimX - 2} y1={orthoAirGapTopY} x2={orthoDimX + 2} y2={orthoAirGapTopY} />
          <line x1={orthoDimX - 2} y1={orthoMagnetTopY} x2={orthoDimX + 2} y2={orthoMagnetTopY} />
          {#if has_back_iron}
            <line x1={orthoDimX - 2} y1={orthoBackIronTopY} x2={orthoDimX + 2} y2={orthoBackIronTopY} />
          {/if}
        </g>
        <!-- Layer thickness labels (only if there's room for the text) -->
        <text x={orthoDimX - 4} y={(orthoBaseY + orthoPcbTopY) / 2 + 2.5} text-anchor="end"
              class="fill-slate-300" style="font-size:7px">
          {pcbThicknessMm.toFixed(1)} mm
        </text>
        {#if airGapMm > 0 && airGapMm * orthoZScale > 7}
          <text x={orthoDimX - 4} y={(orthoPcbTopY + orthoAirGapTopY) / 2 + 2.5} text-anchor="end"
                class="fill-slate-300" style="font-size:7px">
            {airGapMm.toFixed(1)} mm
          </text>
        {/if}
        <text x={orthoDimX - 4} y={(orthoAirGapTopY + orthoMagnetTopY) / 2 + 2.5} text-anchor="end"
              class="fill-slate-300" style="font-size:7px">
          {magnetHeightMm.toFixed(1)} mm
        </text>
        {#if has_back_iron && backIronMm * orthoZScale > 7}
          <text x={orthoDimX - 4} y={(orthoMagnetTopY + orthoBackIronTopY) / 2 + 2.5} text-anchor="end"
                class="fill-slate-300" style="font-size:7px">
            {backIronMm.toFixed(1)} mm
          </text>
        {/if}
        <text x={orthoDimX - 4} y={orthoBackIronTopY - 3} text-anchor="end"
              class="fill-slate-200 font-semibold" style="font-size:7px">
          Total: {totalStackMm.toFixed(1)} mm
        </text>
      </svg>

      <!-- Editable layer-thickness inputs (Wish 1). Small inputs so
           they don't visually compete with the main ParameterPanel and
           don't steal focus aggressively — bound straight to the
           config store so any change re-flows the diagram in real time. -->
      <div class="mt-2 space-y-1 text-[10px]" aria-label="Stackup layer thicknesses">
        <div class="flex items-center justify-between gap-1">
          <label for="ortho-pcb-thickness" class="text-slate-400">PCB</label>
          <input
            id="ortho-pcb-thickness"
            type="number"
            step="0.1"
            min="0.1"
            bind:value={config.pcb_thickness_mm}
            aria-label="PCB thickness (mm)"
            class="w-14 rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-right font-mono text-emerald-300 focus:border-emerald-500 focus:outline-none"
          />
        </div>
        <div class="flex items-center justify-between gap-1">
          <label for="ortho-air-gap" class="text-slate-400">Air gap</label>
          <input
            id="ortho-air-gap"
            type="number"
            step="0.05"
            min="0"
            bind:value={config.air_gap_mm}
            aria-label="Air gap (mm)"
            class="w-14 rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-right font-mono text-emerald-300 focus:border-emerald-500 focus:outline-none"
          />
        </div>
        <div class="flex items-center justify-between gap-1">
          <label for="ortho-magnet-height" class="text-slate-400">Magnets</label>
          <input
            id="ortho-magnet-height"
            type="number"
            step="0.1"
            min="0.1"
            bind:value={config.magnet_height_mm}
            aria-label="Magnet height (mm)"
            class="w-14 rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-right font-mono text-emerald-300 focus:border-emerald-500 focus:outline-none"
          />
        </div>
        <div class="flex items-center justify-between gap-1">
          <label for="ortho-back-iron" class="text-slate-400">Back iron</label>
          <input
            id="ortho-back-iron"
            type="number"
            step="0.1"
            min="0"
            bind:value={config.back_iron_thickness_mm}
            aria-label="Back iron thickness (mm)"
            class="w-14 rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-right font-mono text-emerald-300 focus:border-emerald-500 focus:outline-none"
          />
        </div>
      </div>
    </div>
  </div>

  <!-- ===== 3. Mover position slider + number input + extent display ===== -->
  <!-- The slider value is the CENTER of the magnet array (mm). The
       3/4 view's magnet tracks the same value (clamped to keep it on
       the active area). The display row below confirms the actual
       magnet extent in mm. -->
  <div class="mt-3" aria-label="Mover position">
    <div class="flex items-center gap-2">
      <label for="mover-position" class="text-xs text-slate-400 whitespace-nowrap">
        Position:
      </label>
      <input
        id="mover-position"
        type="range"
        min="0"
        max={config.active_area_length_mm}
        step="0.1"
        bind:value={moverPosRaw}
        class="flex-1 accent-emerald-500"
      />
      <input
        type="number"
        min="0"
        max={config.active_area_length_mm}
        step="0.1"
        bind:value={moverPosRaw}
        aria-label="Mover position (mm)"
        class="w-24 rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-right font-mono text-emerald-300 focus:border-emerald-500 focus:outline-none"
      />
      <span class="text-xs text-slate-400">mm</span>
    </div>
    <div class="mt-1 text-[10px] text-slate-500" aria-live="polite">
      Position: {moverPosMm.toFixed(1)} mm · Magnet: {magnetStartMm.toFixed(1)} mm - {magnetEndMm.toFixed(1)} mm
    </div>
  </div>

  {#if invalid}
    <p class="mt-3 text-xs text-rose-400">
      Travel is zero or negative — increase Active Area Length or reduce Magnet Count / Width / Gap.
    </p>
  {:else}
    <p class="mt-3 text-xs text-slate-500">
      3/4 view shows the assembly in axonometric projection (Z exaggerated ×{Z_EXAG}). Front
      view (Y–Z) shows the real stack height with mm-thickness editable inline; the N·S
      marker indicates the alternation axis (along travel, hidden in this view).
    </p>
  {/if}
</div>
