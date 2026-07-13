<script lang="ts">
  import {
    connectKicad,
    writeCoilsToBoard,
    getBoardDiagnostics,
    validateWritePreconditions,
    previewCoils,
  } from "../tauri";
  import { config } from "../stores/config.svelte";
  import type {
    KicadConnection,
    KicadWriteResult,
    BoardDiagnostics,
    PreconditionWarning,
    CoilPreview,
  } from "../types";

  // --- State -------------------------------------------------------------
  let connection = $state<KicadConnection | null>(null);
  let diagnostics = $state<BoardDiagnostics | null>(null);
  let connecting = $state(false);
  let refreshingDiag = $state(false);
  let validating = $state(false);
  let previewing = $state(false);
  let writing = $state(false);
  let dryRun = $state(false);
  let error = $state<string | null>(null);
  let writeResult = $state<KicadWriteResult | null>(null);
  let validationWarnings = $state<PreconditionWarning[] | null>(null);
  let previewResult = $state<CoilPreview | null>(null);
  let toast = $state<string | null>(null);
  let dryRunPreview = $state<string | null>(null);

  // Timeout handle for the auto-dismissing success toast.
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  // --- Derived -----------------------------------------------------------
  let connected = $derived(connection?.connected ?? false);
  let boardName = $derived(connection?.board_name ?? "(not connected)");
  let copperLayers = $derived(connection?.copper_layers ?? 0);

  /**
   * True when the most recent write attempted to create 0 items — i.e.
   * the historical "0 of 0 written" bug. We use this to swap the
   * "Wrote 0 of 0" toast (which looks like success) for a clear error
   * message, since the underlying issue is "the coil generator produced
   * no coils" — the user needs to know that, not see a green checkmark.
   */
  let zeroItemWrite = $derived(
    writeResult !== null &&
      writeResult.items_attempted === 0 &&
      writeResult.items_created === 0,
  );

  /** Flash a transient success/info message that auto-clears after 4s. */
  function showToast(msg: string): void {
    if (toastTimer) clearTimeout(toastTimer);
    toast = msg;
    toastTimer = setTimeout(() => {
      toast = null;
      toastTimer = undefined;
    }, 4000);
  }

  // --- Helpers -----------------------------------------------------------
  /**
   * Map a precondition level to a tailwind border/bg/text triple.
   * Kept as a function (not a derived) so callers can use it in {#each}.
   */
  function warningClasses(level: PreconditionWarning["level"]): string {
    switch (level) {
      case "error":
        return "border-rose-500/60 bg-rose-500/10 text-rose-200";
      case "warning":
        return "border-amber-500/60 bg-amber-500/10 text-amber-200";
      case "info":
        return "border-sky-500/40 bg-sky-500/10 text-sky-200";
    }
  }

  function warningLabel(level: PreconditionWarning["level"]): string {
    return level.toUpperCase();
  }

  // --- Handlers ----------------------------------------------------------
  async function handleConnect(): Promise<void> {
    connecting = true;
    error = null;
    writeResult = null;
    dryRunPreview = null;
    try {
      connection = await connectKicad();
      if (!connection.connected) {
        error = "KiCad IPC socket unavailable — running in mock mode.";
      }
    } catch (e) {
      connection = null;
      error = e instanceof Error ? e.message : String(e);
    } finally {
      connecting = false;
    }
  }

  async function handleRefreshDiagnostics(): Promise<void> {
    refreshingDiag = true;
    error = null;
    try {
      diagnostics = await getBoardDiagnostics();
    } catch (e) {
      diagnostics = null;
      error = e instanceof Error ? e.message : String(e);
    } finally {
      refreshingDiag = false;
    }
  }

  async function handleValidate(): Promise<void> {
    validating = true;
    error = null;
    try {
      // Lazy-fetch diagnostics if the user hasn't called
      // handleRefreshDiagnostics() first. validateWritePreconditions
      // needs the live board snapshot.
      if (!diagnostics) diagnostics = await getBoardDiagnostics();
      const ipc = config.toIpc();
      validationWarnings = await validateWritePreconditions(ipc, diagnostics);
      const n = validationWarnings.length;
      const errs = validationWarnings.filter((w) => w.level === "error").length;
      const tail = n === 0
        ? "no issues — safe to write."
        : `${n} finding(s) (${errs} blocking)`;
      showToast(`Validation complete: ${tail}`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      validating = false;
    }
  }

  async function handlePreview(): Promise<void> {
    previewing = true;
    error = null;
    try {
      const ipc = config.toIpc();
      previewResult = await previewCoils(ipc);
      showToast(
        `Preview: ${previewResult.num_layers} layer(s), ` +
          `${previewResult.total_tracks} track(s), ` +
          `${previewResult.total_vias} via(s).`,
      );
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      previewing = false;
    }
  }

  async function handleWrite(): Promise<void> {
    if (!connected && !dryRun) return;
    writing = true;
    error = null;
    writeResult = null;
    dryRunPreview = null;
    try {
      const ipc = config.toIpc();
      const result = await writeCoilsToBoard(ipc, dryRun);
      writeResult = result;

      // Special-case the "0 of 0" bug: don't show a green toast when
      // nothing was actually written. The Rust side logs the per-layer
      // breakdown to stderr ([pcbstatorgen::write_coils]) — the user
      // can open dev tools to see the diagnostic line.
      if (zeroItemWrite) {
        error =
          `No items were generated by the coil writer (0 attempted, ` +
          `0 created). Check your config — phases, active_area_length, ` +
          `and num_layers must be non-zero. See dev tools for the ` +
          `[pcbstatorgen::write_coils] diagnostic line.`;
        // No toast — the error banner is the right channel.
        return;
      }

      const partial = result.items_created < result.items_attempted;
      const tail = partial
        ? ` of ${result.items_attempted} (${result.items_attempted - result.items_created} failed)`
        : ` of ${result.items_attempted}`;
      if (dryRun) {
        const msg = `Dry run: would write ${result.items_created}${tail} item(s). ${result.commit_id}`;
        dryRunPreview = msg;
        showToast(msg);
      } else {
        const commit = result.commit_id ? ` (commit ${result.commit_id})` : "";
        showToast(
          `Wrote ${result.items_created}${tail} item(s) to board${commit}.`,
        );
      }
    } catch (e) {
      // Real Tauri error — surface to the UI. This is the fix for the
      // "0 of 0" bug: a backend failure no longer gets hidden behind a
      // synthetic zero-result.
      error = e instanceof Error ? e.message : String(e);
    } finally {
      writing = false;
    }
  }
</script>

<div class="rounded-lg bg-slate-800/40 border border-slate-700 p-4 space-y-3">
  <div class="flex items-center justify-between">
    <h3 class="text-sm font-semibold text-slate-200 border-b border-slate-700 pb-1 flex-1">
      KiCad Board Writer
    </h3>
    <!-- Connection status dot -->
    <div class="flex items-center gap-2 text-xs ml-3">
      <span
        class="inline-block h-3 w-3 rounded-full {connected
          ? 'bg-emerald-400'
          : 'bg-rose-500'}"
      ></span>
      <span class={connected ? "text-emerald-300" : "text-rose-300"}>
        {connected ? "connected" : "disconnected"}
      </span>
    </div>
  </div>

  <!-- Board info when connected -->
  {#if connected}
    <div class="text-xs text-slate-400 font-mono">
      Board: <span class="text-slate-200">{boardName}</span>
      · {copperLayers} copper layer{copperLayers === 1 ? "" : "s"}
      {#if diagnostics && diagnostics.board_x_max_mm > 0}
        · {Math.round(diagnostics.board_x_max_mm - diagnostics.board_x_min_mm)} mm
          × {Math.round(diagnostics.board_y_max_mm - diagnostics.board_y_min_mm)} mm
      {/if}
    </div>
  {:else if connection && !connection.connected}
    <div class="text-xs text-slate-500">
      No KiCad board open. Connect to a running KiCad 10 instance to write coils.
    </div>
  {/if}

  <!-- Diagnostics card (from get_board_diagnostics) -->
  {#if diagnostics}
    <div
      class="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-xs text-slate-300"
    >
      <div class="font-semibold text-slate-200 mb-1">Board diagnostics</div>
      <div class="font-mono text-[11px] leading-snug text-slate-400">
        board_name: <span class="text-slate-200">{diagnostics.board_name}</span><br />
        copper_layer_count: <span class="text-slate-200">{diagnostics.copper_layer_count}</span><br />
        {#if diagnostics.board_x_max_mm > 0}
          edge cuts: <span class="text-slate-200">
            {diagnostics.board_x_min_mm.toFixed(1)}…{diagnostics.board_x_max_mm.toFixed(1)} mm
            × {diagnostics.board_y_min_mm.toFixed(1)}…{diagnostics.board_y_max_mm.toFixed(1)} mm
          </span><br />
        {:else}
          edge cuts: <span class="text-slate-500">(not yet queryable in KiCad 10 IPC)</span><br />
        {/if}
        net_classes: <span class="text-slate-200">{diagnostics.available_net_classes.length}</span>
      </div>
    </div>
  {/if}

  <!-- Validation warnings (from validate_write_preconditions) -->
  {#if validationWarnings && validationWarnings.length > 0}
    <div class="space-y-1">
      <div class="text-xs font-semibold text-slate-300">Pre-flight checks</div>
      {#each validationWarnings as w, i (i)}
        <div
          class="rounded-md border px-3 py-2 text-xs {warningClasses(w.level)}"
        >
          <span class="font-mono text-[10px] font-semibold mr-2">
            [{warningLabel(w.level)}{w.field ? ` · ${w.field}` : ""}]
          </span>
          {w.message}
        </div>
      {/each}
    </div>
  {:else if validationWarnings && validationWarnings.length === 0}
    <div
      class="rounded-md border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
    >
      Pre-flight: no issues — config is compatible with the open board.
    </div>
  {/if}

  <!-- Coil preview summary (from preview_coils) -->
  {#if previewResult}
    <div
      class="rounded-md border border-sky-500/40 bg-sky-500/5 px-3 py-2 text-xs text-sky-200"
    >
      <div class="font-semibold mb-1">Coil preview ({previewResult.topology})</div>
      <div class="font-mono text-[11px] leading-snug">
        {previewResult.num_layers} layer(s) ·
        {previewResult.total_tracks} track(s) ·
        {previewResult.total_vias} via(s)
      </div>
      <ul class="mt-1 list-disc pl-5 font-mono text-[11px] leading-snug">
        {#each previewResult.layers as layer (layer.layer_idx)}
          <li>
            layer {layer.layer_idx}: {layer.phase_count} phase(s),
            {layer.segment_count} segment(s),
            {layer.via_count} via(s)
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Action buttons -->
  <div class="flex flex-wrap items-center gap-2">
    <button
      type="button"
      onclick={handleConnect}
      disabled={connecting}
      class="rounded-md border border-slate-600 bg-slate-700/60 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-slate-600/60 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {connecting ? "Connecting…" : connected ? "Reconnect" : "Connect to KiCad"}
    </button>

    <button
      type="button"
      onclick={handleRefreshDiagnostics}
      disabled={refreshingDiag}
      class="rounded-md border border-slate-600 bg-slate-700/60 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-slate-600/60 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {refreshingDiag ? "Refreshing…" : "Refresh Diagnostics"}
    </button>

    <button
      type="button"
      onclick={handleValidate}
      disabled={validating}
      class="rounded-md border border-amber-500/50 bg-amber-600/30 px-3 py-1.5 text-xs font-medium text-amber-100 transition hover:bg-amber-500/40 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {validating ? "Validating…" : "Validate"}
    </button>

    <button
      type="button"
      onclick={handlePreview}
      disabled={previewing}
      class="rounded-md border border-sky-500/50 bg-sky-600/30 px-3 py-1.5 text-xs font-medium text-sky-100 transition hover:bg-sky-500/40 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {previewing ? "Previewing…" : "Preview"}
    </button>

    <button
      type="button"
      onclick={handleWrite}
      disabled={!connected || writing}
      class="rounded-md border border-emerald-500/50 bg-emerald-600/30 px-3 py-1.5 text-xs font-medium text-emerald-100 transition hover:bg-emerald-500/40 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {#if writing}
        {dryRun ? "Generating…" : "Writing…"}
      {:else}
        {dryRun ? "Dry Run: Generate Coils" : "Write to Board"}
      {/if}
    </button>

    <!-- Dry run toggle -->
    <label class="ml-auto flex cursor-pointer select-none items-center gap-2 text-xs text-slate-300">
      <input
        type="checkbox"
        bind:checked={dryRun}
        class="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 accent-sky-500"
      />
      Dry Run
    </label>
  </div>

  <!-- Success toast -->
  {#if toast}
    <div
      class="rounded-md border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
    >
      {toast}
    </div>
  {/if}

  <!-- Dry-run preview (persistent, separate from transient toast) -->
  {#if dryRunPreview}
    <div
      class="rounded-md border border-sky-500/40 bg-sky-500/5 px-3 py-2 text-xs text-sky-200"
    >
      {dryRunPreview}
    </div>
  {/if}

  <!-- Last write result summary -->
  {#if writeResult && !zeroItemWrite}
    <div class="text-xs text-slate-400 font-mono">
      Last write: {writeResult.items_created} of {writeResult.items_attempted} item(s)
      {#if writeResult.commit_id}· commit {writeResult.commit_id}{/if}
    </div>
  {/if}

  <!-- Partial-write warning (KiCad rejected some items) -->
  {#if writeResult && writeResult.items_created > 0 && writeResult.items_created < writeResult.items_attempted}
    <div
      class="rounded-md border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
    >
      <div class="font-semibold">
        Warning: {writeResult.items_attempted - writeResult.items_created} of
        {writeResult.items_attempted} item(s) were rejected by KiCad.
      </div>
      {#if writeResult.failures.length > 0}
        <ul class="mt-1 list-disc pl-5 font-mono text-[11px] leading-snug">
          {#each writeResult.failures as msg, i (i)}
            <li>{msg}</li>
          {/each}
        </ul>
        {#if writeResult.failures.length < (writeResult.items_attempted - writeResult.items_created)}
          <div class="mt-1 italic text-amber-300/80">
            (showing first {writeResult.failures.length} of
            {writeResult.items_attempted - writeResult.items_created} failures — open
            dev tools console for the full response.)
          </div>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Error banner -->
  {#if error}
    <div
      class="rounded-md border border-rose-500/60 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
    >
      <span class="font-semibold">Error:</span> {error}
    </div>
  {/if}
</div>
