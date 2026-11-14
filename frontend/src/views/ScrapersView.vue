<script setup>
import { onMounted, ref } from 'vue'
import { scrapersApi } from '@/api/scrapers'

const scrapers = ref([])
const loading = ref(true)
const error = ref('')

const url = ref('')
const previewing = ref(false)
const analyzing = ref(false)
const preview = ref(null)
const analysis = ref(null)
const testError = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    scrapers.value = await scrapersApi.list()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function runPreview() {
  if (!url.value.trim()) return
  previewing.value = true
  testError.value = ''
  preview.value = null
  try {
    preview.value = await scrapersApi.preview(url.value.trim())
  } catch (err) {
    testError.value = err.message
  } finally {
    previewing.value = false
  }
}

async function runAnalyze() {
  if (!url.value.trim()) return
  analyzing.value = true
  testError.value = ''
  analysis.value = null
  try {
    analysis.value = await scrapersApi.analyze(url.value.trim())
  } catch (err) {
    testError.value = err.message
  } finally {
    analyzing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold tracking-tight text-white">Scrapers</h1>
      <p class="mt-1 text-sm text-slate-400">
        Satu modul per situs. Tambah file di
        <code class="rounded bg-ink-800 px-1 py-0.5 text-xs">backend/scrapers/sites/</code>
        dan modul otomatis terdaftar.
      </p>
    </header>

    <div
      v-if="error"
      class="mb-5 rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300"
    >
      Gagal memuat daftar scraper: {{ error }}
    </div>

    <p v-if="loading" class="text-sm text-slate-500">Memuat…</p>

    <div v-else class="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <article v-for="scraper in scrapers" :key="scraper.name" class="card space-y-2">
        <div class="flex items-start justify-between gap-2">
          <h2 class="text-sm font-semibold text-slate-100">{{ scraper.display_name }}</h2>
          <span class="badge shrink-0 bg-ink-800 font-mono text-slate-400">
            {{ scraper.name }}
          </span>
        </div>
        <p class="font-mono text-[11px] text-slate-500">
          {{ scraper.domains.join(', ') || 'semua domain (fallback)' }}
        </p>
        <div class="flex flex-wrap gap-1.5 text-[11px]">
          <span class="badge bg-ink-800 text-slate-300">{{ scraper.source_lang }}</span>
          <span
            v-if="scraper.needs_playwright"
            class="badge bg-amber-950/60 text-amber-400"
          >
            butuh playwright
          </span>
          <span v-else class="badge bg-emerald-950/50 text-emerald-400">httpx</span>
        </div>
      </article>
    </div>

    <!-- test panel -->
    <section class="card space-y-4">
      <div>
        <h2 class="text-sm font-semibold text-white">Test Scraper &amp; AI Analyze</h2>
        <p class="mt-1 text-xs text-slate-500">
          Preview memakai modul scraper yang cocok dengan domain. AI Analyze memakai model
          <span class="font-mono text-slate-400">scrape_analysis</span> dari Settings.
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <input
          v-model="url"
          class="input min-w-0 flex-1 font-mono text-xs"
          type="url"
          placeholder="https://www.69shuba.com/book/12345.htm"
        />
        <button class="btn-ghost" :disabled="previewing || !url.trim()" @click="runPreview">
          {{ previewing ? 'Mengambil…' : 'Test Preview' }}
        </button>
        <button class="btn-primary" :disabled="analyzing || !url.trim()" @click="runAnalyze">
          {{ analyzing ? 'Menganalisis…' : 'AI Analyze' }}
        </button>
      </div>

      <div
        v-if="testError"
        class="rounded-lg border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300"
      >
        {{ testError }}
      </div>

      <div v-if="preview" class="rounded-lg border border-ink-700 bg-ink-850 p-4 text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge bg-indigo-950/70 text-indigo-300">{{ preview.scraper }}</span>
          <span v-if="!preview.dedicated" class="badge bg-amber-950/60 text-amber-400">
            generik
          </span>
          <span class="badge bg-ink-800 text-slate-400">{{ preview.kind }}</span>
        </div>
        <p class="mt-2 font-medium text-slate-100">{{ preview.title }}</p>
        <p v-if="preview.author" class="text-xs text-slate-400">{{ preview.author }}</p>
        <p v-if="preview.kind === 'novel'" class="mt-1 text-xs text-slate-400">
          {{ preview.chapter_count }} bab terdeteksi
        </p>
        <p v-else class="mt-1 text-xs text-slate-400">
          {{ preview.content_length }} karakter konten
        </p>
        <pre
          v-if="preview.content_preview"
          class="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded bg-ink-900 p-3 font-mono text-[11px] text-slate-400"
          >{{ preview.content_preview }}</pre
        >
        <ul
          v-if="preview.chapters?.length"
          class="mt-2 max-h-40 space-y-0.5 overflow-y-auto text-[11px] text-slate-500"
        >
          <li v-for="chapter in preview.chapters" :key="chapter.url">
            {{ chapter.chapter_number }}. {{ chapter.title }}
          </li>
        </ul>
      </div>

      <div v-if="analysis" class="rounded-lg border border-ink-700 bg-ink-850 p-4 text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge bg-indigo-950/70 text-indigo-300">{{ analysis.provider_type }}</span>
          <span class="badge bg-ink-800 font-mono text-slate-400">{{ analysis.model }}</span>
        </div>
        <template v-if="analysis.analysis">
          <dl class="mt-3 grid gap-1.5 text-xs">
            <div
              v-for="(value, key) in analysis.analysis"
              :key="key"
              class="grid grid-cols-[180px_1fr] gap-2"
            >
              <dt class="font-mono text-slate-500">{{ key }}</dt>
              <dd class="break-words text-slate-300">
                {{ Array.isArray(value) ? value.join(', ') || '—' : value || '—' }}
              </dd>
            </div>
          </dl>
        </template>
        <pre
          v-else
          class="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded bg-ink-900 p-3 font-mono text-[11px] text-slate-400"
          >{{ analysis.raw }}</pre
        >
      </div>
    </section>
  </div>
</template>
