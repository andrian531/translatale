<script setup>
// Placeholder for Phase 2 (novel input: scraper + manual paste/upload).
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-10">
    <h1 class="text-2xl font-semibold tracking-tight text-white">Library</h1>
    <p class="mt-1 text-sm text-slate-400">
      Daftar novel dan input bab akan tersedia di Phase 2.
    </p>

    <div
      class="mt-8 rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-6 py-16 text-center"
    >
      <p class="text-sm font-medium text-slate-300">Belum ada novel.</p>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-500">
        Phase 2 akan menambahkan tab <span class="text-slate-300">Dari URL (Scraper)</span> dan
        <span class="text-slate-300">Input Manual</span> (paste teks / upload
        <code class="rounded bg-ink-800 px-1 py-0.5 text-xs">.txt</code>).
      </p>
      <RouterLink
        to="/settings"
        class="mt-6 inline-flex items-center rounded-lg border border-ink-700 bg-ink-850 px-3.5 py-2 text-sm font-medium text-slate-300 hover:bg-ink-800"
      >
        Atur provider LLM dulu →
      </RouterLink>
    </div>
  </div>
</template>
