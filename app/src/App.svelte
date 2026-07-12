<script lang="ts">
  // pcbstatorgen single-dashboard — placeholder scaffold.
  // TODO(svelte-file-editor): build full dashboard per PRODUCT_GOALS.md §3.A.
  let topology: "linear" | "radial" = "linear";
</script>

<main class="min-h-screen bg-slate-900 text-slate-100 p-8">
  <h1 class="text-2xl font-bold mb-4">pcbstatorgen</h1>
  <div class="mb-4">
    <button class="px-3 py-1 rounded bg-emerald-600">Linear</button>
    <button class="px-3 py-1 rounded bg-slate-700 opacity-50 cursor-not-allowed" disabled>
      Radial — TODO
    </button>
  </div>
  <p class="text-slate-400">Phase 5+6 scaffold. Physics + UI wiring pending.</p>
</main>
