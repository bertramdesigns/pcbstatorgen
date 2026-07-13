<script lang="ts">
  import { connectKicad, writeCoilsToBoard, generateCoils } from "../tauri";
  import { config } from "../stores/config.svelte";
  import type { KicadConnection, KicadWriteResult } from "../types";

  // --- State -------------------------------------------------------------
  let connection = $state<KicadConnection | null>(null);
  let connecting = $state(false);
  let writing = $state(false);
  let dryRun = $state(false);
  let error = $state<string | null>(null);
  let writeResult = $state<KicadWriteResult | null>(null);
  let toast = $state<string | null>(null);
  let dryRunPreview = $state<string | null>(null);

  // Timeout handle for the auto-dismissing success toast.
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  // --- Derived -----------------------------------------------------------
  let connected = $derived(connection?.connected ?? false);
  let boardName = $derived(connection?.board_name ?? "(not connected)");
  let copperLayers = $derived(connection?.copper_layers ?? 0);

  /** Flash a transient success message that auto-clears after 4s. */
  function showToast(msg: string): void {
    if (toastTimer) clearTimeout(toastTimer);
    toast = msg;
    toastTimer = setTimeout(() => {
      toast = null;
      toastTimer = undefined;
    }, 4000);
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

  async function handleWrite(): Promise<void> {
    if (!connected && !dryRun) return;
    writing = true;
    error = null;
    writeResult = null;
    dryRunPreview = null;
    try {
      const ipc = config.toIpc();
      if (dryRun) {
        // Dry run: generate coils only, do not touch the board socket.
        const coils = await generateCoils(ipc);
        const segCount = coils.phases.reduce(
          (n, p) => n + p.segments.length,
          0,
        );
        const msg =
          `Dry run: generated ${coils.phases.length} phase(s) across ` +
          `${coils.layer_count} layer(s), ${segCount} segments total. ` +
          `No board write performed.`;
        dryRunPreview = msg;
        showToast(msg);
      } else {
        const result = await writeCoilsToBoard(ipc);
        writeResult = result;
        showToast(
          `Wrote ${result.items_created} item(s) to board` +
            (result.commit_id ? ` (commit ${result.commit_id})` : "") + ".",
        );
      }
    } catch (e) {
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
    </div>
  {:else if connection && !connection.connected}
    <div class="text-xs text-slate-500">
      No KiCad board open. Connect to a running KiCad 10 instance to write coils.
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
      onclick={handleWrite}
      disabled={!connected || writing}
      class="rounded-md border border-sky-500/50 bg-sky-600/40 px-3 py-1.5 text-xs font-medium text-sky-100 transition hover:bg-sky-500/50 disabled:cursor-not-allowed disabled:opacity-40"
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
  {#if writeResult}
    <div class="text-xs text-slate-400 font-mono">
      Last write: {writeResult.items_created} item(s)
      {#if writeResult.commit_id}· commit {writeResult.commit_id}{/if}
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
