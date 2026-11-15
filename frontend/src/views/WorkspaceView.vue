<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'
import { readerApi } from '@/api/reader'
import { settingsApi } from '@/api/settings'
import { translationApi } from '@/api/translation'

const route = useRoute()
const router = useRouter()

const novelId = computed(() => Number(route.params.id))

const novel = ref(null)
const chapters = ref([])
const loading = ref(true)
const error = ref('')
const notice = ref(null)

const tab = ref('chapters')
const filter = ref('all')
const selected = ref([])
const fetching = ref(false)
const fetchBatchSize = ref(50)
const showUrlModal = ref(false)
const urlsText = ref('')
const savingUrls = ref(false)
const syncingUrl = ref(false)

// -- job / live progress ------------------------------------------------
const job = ref(null)
const jobEvents = ref([])
const jobMessage = ref('')
const jobChunk = ref(null)
let closeStream = null

const jobActive = computed(
  () => job.value && ['queued', 'running'].includes(job.value.status),
)
const jobPercent = computed(() => {
  if (!job.value?.total_items) return 0
  return Math.min(100, Math.round((job.value.completed_items / job.value.total_items) * 100))
})

// -- reference ----------------------------------------------------------
const reference = ref(null)
const referenceLoading = ref(false)
const savingReference = ref(false)
const referenceDirty = ref(false)

// -- modals -------------------------------------------------------------
const showManual = ref(false)
const manualForm = reactive({ chapter_number: null, title: '', raw_content: '' })
const savingManual = ref(false)

const editing = ref(null)
const editForm = reactive({ title: '', raw_content: '', translated_content: '' })
const savingEdit = ref(false)
const editPane = ref('both')

// -- translate options --------------------------------------------------
const AUTO_REF_KEY = 'translatale:auto-reference'
const autoUpdateReference = ref(localStorage.getItem(AUTO_REF_KEY) !== '0')
const contextWarning = ref(null)
watch(autoUpdateReference, (value) => {
  localStorage.setItem(AUTO_REF_KEY, value ? '1' : '0')
})

// -- synopsis panel -----------------------------------------------------
const synopsisExpanded = ref(false)
const showRawSynopsis = ref(false)
const editingSynopsis = ref(false)
const synopsisDraft = ref('')
const savingSynopsis = ref(false)
const refiningSynopsis = ref(false)

const uploading = ref(false)
const fileInput = ref(null)

const filters = [
  { value: 'all', label: 'Semua' },
  { value: 'pending_fetch', label: 'Pending Fetch' },
  { value: 'raw', label: 'Raw' },
  { value: 'translating', label: 'Translating' },
  { value: 'translated', label: 'Translated' },
  { value: 'error', label: 'Error' },
]

const statusStyles = {
  pending_fetch: 'bg-amber-950/60 text-amber-400',
  raw: 'bg-emerald-950/60 text-emerald-400',
  translating: 'bg-sky-950/60 text-sky-400',
  translated: 'bg-indigo-950/60 text-indigo-300',
  error: 'bg-rose-950/60 text-rose-400',
}

const gradeStyles = {
  A: 'bg-emerald-950/60 text-emerald-400',
  B: 'bg-sky-950/60 text-sky-400',
  C: 'bg-amber-950/60 text-amber-400',
  D: 'bg-rose-950/60 text-rose-400',
}

function gradeFor(score) {
  if (score === null || score === undefined) return null
  if (score >= 90) return 'A'
  if (score >= 75) return 'B'
  if (score >= 60) return 'C'
  return 'D'
}

const visibleChapters = computed(() =>
  filter.value === 'all'
    ? chapters.value
    : chapters.value.filter((chapter) => chapter.status === filter.value),
)

const selectedChapters = computed(() =>
  chapters.value.filter((chapter) => selected.value.includes(chapter.id)),
)

const translatableSelected = computed(() =>
  selectedChapters.value.filter((chapter) => (chapter.raw_content || '').trim()),
)

const pendingSelected = computed(() =>
  selectedChapters.value.filter((chapter) => chapter.status === 'pending_fetch'),
)

const clearableSelected = computed(() =>
  selectedChapters.value.filter(
    (chapter) =>
      chapter.status === 'translated' ||
      chapter.status === 'error' ||
      (chapter.translated_content || '').trim(),
  ),
)
const clearing = ref(false)

const allVisibleSelected = computed(
  () =>
    visibleChapters.value.length > 0 &&
    visibleChapters.value.every((chapter) => selected.value.includes(chapter.id)),
)

const displaySynopsis = computed(() => {
  const translated = (novel.value?.synopsis_translated || '').trim()
  const original = (novel.value?.synopsis || '').trim()
  return translated || original
})

const JOB_LABELS = {
  translate: 'Translate',
  story_analysis: 'Analisa Cerita',
  fetch: 'Fetch Bab',
}

function jobLabel(type) {
  return JOB_LABELS[type] ?? type ?? 'Job'
}

function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => {
    if (notice.value?.text === text) notice.value = null
  }, 7000)
}

// ----------------------------------------------------------------------
// Loading
// ----------------------------------------------------------------------
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [novelData, chapterData] = await Promise.all([
      novelsApi.get(novelId.value),
      novelsApi.listChapters(novelId.value),
    ])
    novel.value = novelData
    chapters.value = chapterData
    selected.value = selected.value.filter((id) => chapterData.some((c) => c.id === id))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadReference() {
  referenceLoading.value = true
  try {
    const data = await translationApi.getReference(novelId.value)
    reference.value = {
      characters: data.characters ?? [],
      locations: data.locations ?? [],
      terms: data.terms ?? [],
      translation_guide: data.translation_guide ?? '',
      chapter_context: data.chapter_context ?? [],
    }
    referenceDirty.value = false
  } catch (err) {
    flash('error', `Gagal memuat reference: ${err.message}`)
  } finally {
    referenceLoading.value = false
  }
}

// ----------------------------------------------------------------------
// Selection
// ----------------------------------------------------------------------
function toggle(id) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
}

function toggleAll() {
  if (allVisibleSelected.value) {
    const visibleIds = visibleChapters.value.map((chapter) => chapter.id)
    selected.value = selected.value.filter((id) => !visibleIds.includes(id))
  } else {
    selected.value = [...new Set([...selected.value, ...visibleChapters.value.map((c) => c.id)])]
  }
}

// ----------------------------------------------------------------------
// Jobs
// ----------------------------------------------------------------------
function stopStream() {
  if (closeStream) {
    closeStream()
    closeStream = null
  }
}

function watchJob(jobId) {
  stopStream()
  jobEvents.value = []
  closeStream = translationApi.subscribeJob(jobId, {
    onEvent(event) {
      jobEvents.value = [...jobEvents.value.slice(-40), event]
      if (event.message) jobMessage.value = event.message
      if (event.type === 'chunk') {
        jobChunk.value = { index: event.chunk_index, total: event.chunk_total }
      }
      if (event.type === 'chapter' || event.type === 'chapter_done') {
        jobChunk.value = null
      }
      if (event.type === 'reference_update' && !referenceDirty.value) {
        // New characters/terms landed: show them in the reference tab right away.
        loadReference()
      }
      if (job.value) {
        job.value = {
          ...job.value,
          status: event.status ?? job.value.status,
          completed_items: event.completed_items ?? job.value.completed_items,
          total_items: event.total_items ?? job.value.total_items,
          message: event.message ?? job.value.message,
        }
      }
    },
    async onDone(event) {
      closeStream = null
      jobChunk.value = null
      if (job.value) {
        job.value = { ...job.value, status: event.status ?? job.value.status }
      }
      await Promise.all([load(), loadReference()])
      if (event.type === 'error') {
        flash('error', `Job gagal: ${event.message}`)
      } else if (event.type === 'cancelled') {
        flash('error', 'Job dibatalkan.')
      } else {
        flash('success', 'Job selesai.')
      }
    },
    onError() {
      closeStream = null
      flash('error', 'Koneksi progres terputus. Muat ulang halaman untuk melihat status.')
    },
  })
}

async function runTranslateWithIds(ids) {
  if (!ids.length) return
  try {
    const started = await translationApi.startTranslate(
      novelId.value,
      ids,
      autoUpdateReference.value,
    )
    job.value = started
    jobMessage.value = started.message
    watchJob(started.id)
    await load()
  } catch (err) {
    flash('error', `Gagal memulai translate: ${err.message}`)
  }
}

async function startTranslate() {
  const selectedList = translatableSelected.value
  const ids = selectedList.map((chapter) => chapter.id)
  if (!ids.length) return

  const minSelectedNo = Math.min(...selectedList.map((chapter) => chapter.chapter_number))
  const earlierUntranslated = chapters.value.filter(
    (chapter) => chapter.chapter_number < minSelectedNo && chapter.status !== 'translated',
  )
  if (!earlierUntranslated.length) {
    await runTranslateWithIds(ids)
    return
  }

  const earlierReady = earlierUntranslated.filter(
    (chapter) => chapter.status === 'raw' || chapter.status === 'error',
  )
  const earlierPending = earlierUntranslated.filter(
    (chapter) => chapter.status === 'pending_fetch',
  )
  const sample = earlierUntranslated
    .slice(0, 5)
    .map((chapter) => `Bab ${chapter.chapter_number}`)
    .join(', ')
  contextWarning.value = {
    minSelectedNo,
    earlierCount: earlierUntranslated.length,
    earlierSample: earlierUntranslated.length > 5 ? `${sample}, …` : sample,
    earlierReadyIds: earlierReady.map((chapter) => chapter.id),
    pendingCount: earlierPending.length,
    selectedIds: ids,
  }
}

async function confirmTranslateEarlier() {
  const warn = contextWarning.value
  contextWarning.value = null
  if (!warn) return
  if (!warn.earlierReadyIds.length) {
    flash('error', 'Bab sebelumnya masih berstatus pending fetch. Jalankan Fetch Raw terlebih dahulu.')
    return
  }
  const combined = Array.from(new Set([...warn.earlierReadyIds, ...warn.selectedIds]))
  await runTranslateWithIds(combined)
}

async function confirmTranslateAnyway() {
  const warn = contextWarning.value
  contextWarning.value = null
  if (!warn) return
  await runTranslateWithIds(warn.selectedIds)
}

async function startAnalyze() {
  try {
    const ids = selected.value.length ? selected.value : null
    const started = await translationApi.startAnalyze(novelId.value, ids)
    job.value = started
    jobMessage.value = started.message
    watchJob(started.id)
  } catch (err) {
    flash('error', `Gagal memulai analisa: ${err.message}`)
  }
}

async function cancelJob() {
  if (!job.value) return
  try {
    const updated = await translationApi.cancelJob(job.value.id)
    job.value = updated
  } catch (err) {
    flash('error', `Gagal membatalkan: ${err.message}`)
  }
}

function dismissJob() {
  stopStream()
  job.value = null
  jobEvents.value = []
  jobChunk.value = null
}

// ----------------------------------------------------------------------
// Chapters
// ----------------------------------------------------------------------
async function startFetch(payload) {
  try {
    const started = await novelsApi.startFetchJob(novelId.value, payload)
    job.value = started
    jobMessage.value = started.message
    watchJob(started.id)
    selected.value = []
  } catch (err) {
    flash('error', `Gagal memulai fetch: ${err.message}`)
  }
}

async function fetchSelected() {
  const ids = pendingSelected.value.map((chapter) => chapter.id)
  if (!ids.length) return
  fetching.value = true
  try {
    await startFetch({ chapterIds: ids })
  } finally {
    fetching.value = false
  }
}

async function clearSelectedTranslations() {
  const ids = clearableSelected.value.map((chapter) => chapter.id)
  if (!ids.length) return
  if (
    !window.confirm(
      `Hapus hasil terjemahan untuk ${ids.length} bab terpilih? Teks sumber (raw) akan tetap disimpan dan status di-reset ke raw.`,
    )
  ) {
    return
  }
  clearing.value = true
  try {
    const res = await novelsApi.clearTranslations(novelId.value, ids)
    selected.value = []
    await load()
    flash('success', `Terjemahan ${res.cleared} bab dihapus (teks raw tetap aman).`)
  } catch (err) {
    flash('error', `Gagal menghapus terjemahan: ${err.message}`)
  } finally {
    clearing.value = false
  }
}

async function clearSingleTranslation(chapter) {
  if (
    !window.confirm(
      `Hapus hasil terjemahan Bab ${chapter.chapter_number}? Teks sumber (raw) akan tetap disimpan.`,
    )
  ) {
    return
  }
  clearing.value = true
  try {
    await novelsApi.clearTranslations(novelId.value, [chapter.id])
    await load()
    flash('success', `Terjemahan Bab ${chapter.chapter_number} dihapus.`)
  } catch (err) {
    flash('error', `Gagal menghapus terjemahan: ${err.message}`)
  } finally {
    clearing.value = false
  }
}

async function fetchBatch() {
  fetching.value = true
  try {
    await startFetch({})
  } finally {
    fetching.value = false
  }
}

function openUrlModal() {
  urlsText.value = ''
  showUrlModal.value = true
}

function startEditSynopsis() {
  synopsisDraft.value = novel.value?.synopsis_translated || ''
  editingSynopsis.value = true
  synopsisExpanded.value = true
}

async function saveSynopsisEdit() {
  savingSynopsis.value = true
  try {
    novel.value = await novelsApi.update(novelId.value, {
      synopsis_translated: synopsisDraft.value,
    })
    editingSynopsis.value = false
    flash('success', 'Sinopsis disimpan.')
  } catch (err) {
    flash('error', `Gagal menyimpan sinopsis: ${err.message}`)
  } finally {
    savingSynopsis.value = false
  }
}

async function runRefineSynopsis() {
  refiningSynopsis.value = true
  try {
    novel.value = await novelsApi.refineSynopsis(novelId.value)
    synopsisExpanded.value = true
    flash('success', 'Sinopsis diperbaiki memakai konteks cerita.')
  } catch (err) {
    flash('error', `Gagal memperbaiki sinopsis: ${err.message}`)
  } finally {
    refiningSynopsis.value = false
  }
}

async function addFromUrls() {
  const urls = urlsText.value
    .split(/\s*\n\s*/)
    .map((url) => url.trim())
    .filter(Boolean)
  if (!urls.length) return

  savingUrls.value = true
  try {
    const result = await novelsApi.addChaptersFromUrl(novelId.value, urls)
    showUrlModal.value = false
    await load()
    const parts = [`${result.added} bab ditambahkan`]
    if (result.skipped) parts.push(`${result.skipped} duplikat dilewati`)
    if (result.failed) parts.push(`${result.failed} gagal`)
    const detail = result.errors?.[0]?.error ? ` — ${result.errors[0].error}` : ''
    flash(result.failed ? 'error' : 'success', parts.join(', ') + detail)
  } catch (err) {
    flash('error', `Gagal menambah bab dari URL: ${err.message}`)
  } finally {
    savingUrls.value = false
  }
}

async function syncFromSource() {
  syncingUrl.value = true
  try {
    const result = await novelsApi.syncNovelChapters(novelId.value)
    await load()
    flash(
      'success',
      result.added
        ? `${result.added} bab baru ditambahkan (${result.skipped} sudah ada).`
        : `Tidak ada bab baru — ${result.found ?? 0} bab di sumber sudah ada semua.`,
    )
  } catch (err) {
    flash('error', `Gagal cek bab baru: ${err.message}`)
  } finally {
    syncingUrl.value = false
  }
}

function openManual() {
  manualForm.chapter_number = null
  manualForm.title = ''
  manualForm.raw_content = ''
  showManual.value = true
}

async function saveManual() {
  if (!manualForm.raw_content.trim()) return
  savingManual.value = true
  try {
    await novelsApi.addManualChapter(novelId.value, {
      title: manualForm.title,
      raw_content: manualForm.raw_content,
      chapter_number: manualForm.chapter_number ? Number(manualForm.chapter_number) : null,
    })
    showManual.value = false
    await load()
    flash('success', 'Bab manual ditambahkan.')
  } catch (err) {
    flash('error', `Gagal menambah bab: ${err.message}`)
  } finally {
    savingManual.value = false
  }
}

function pickFiles() {
  fileInput.value?.click()
}

async function onFilesChosen(event) {
  const files = [...(event.target.files ?? [])]
  event.target.value = ''
  if (!files.length) return
  uploading.value = true
  try {
    const created = await novelsApi.uploadChapters(novelId.value, files)
    await load()
    flash('success', `${created.length} bab diunggah.`)
  } catch (err) {
    flash('error', `Gagal upload: ${err.message}`)
  } finally {
    uploading.value = false
  }
}

function openChapter(chapter) {
  editing.value = chapter
  editForm.title = chapter.title
  editForm.raw_content = chapter.raw_content
  editForm.translated_content = chapter.translated_content
  editPane.value = 'both'
}

function openReader(chapterId) {
  const suffix = chapterId ? `/${chapterId}` : ''
  router.push(`/novels/${novelId.value}/read${suffix}`)
}

async function downloadExport(format) {
  try {
    const response = await fetch(readerApi.exportUrl(novelId.value, format))
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`
      try {
        const body = await response.json()
        if (body?.detail) detail = String(body.detail)
      } catch {
        /* keep the status line */
      }
      throw new Error(detail)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${novel.value?.title || 'novel'}.${format}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    flash('success', `Export .${format} diunduh.`)
  } catch (err) {
    flash('error', `Gagal export .${format}: ${err.message}`)
  }
}

async function saveChapter() {
  if (!editing.value) return
  savingEdit.value = true
  try {
    await novelsApi.updateChapter(editing.value.id, {
      title: editForm.title,
      raw_content: editForm.raw_content,
      translated_content: editForm.translated_content,
    })
    editing.value = null
    await load()
    flash('success', 'Bab disimpan.')
  } catch (err) {
    flash('error', `Gagal menyimpan bab: ${err.message}`)
  } finally {
    savingEdit.value = false
  }
}

async function removeChapter(chapter) {
  if (!window.confirm(`Hapus bab "${chapter.title}"?`)) return
  try {
    await novelsApi.removeChapter(chapter.id)
    await load()
    flash('success', 'Bab dihapus.')
  } catch (err) {
    flash('error', `Gagal menghapus bab: ${err.message}`)
  }
}

// ----------------------------------------------------------------------
// Reference editing
// ----------------------------------------------------------------------
function markDirty() {
  referenceDirty.value = true
}

function addCharacter() {
  reference.value.characters.push({
    name: '',
    romanized_name: '',
    age: '',
    gender: '',
    aliases: [],
    relationships: '',
    notes: '',
  })
  markDirty()
}

function addTerm() {
  reference.value.terms.push({ source: '', target: '', note: '' })
  markDirty()
}

function addLocation() {
  reference.value.locations.push({ source: '', target: '', note: '' })
  markDirty()
}

function removeAt(list, index) {
  list.splice(index, 1)
  markDirty()
}

function aliasesToText(character) {
  return (character.aliases ?? []).join(', ')
}

function setAliases(character, value) {
  character.aliases = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  markDirty()
}

async function saveReference() {
  savingReference.value = true
  try {
    const payload = {
      characters: reference.value.characters.filter((item) => item.name?.trim()),
      locations: reference.value.locations.filter((item) => item.source?.trim()),
      terms: reference.value.terms.filter((item) => item.source?.trim()),
      translation_guide: reference.value.translation_guide,
    }
    const saved = await translationApi.saveReference(novelId.value, payload)
    reference.value = {
      characters: saved.characters ?? [],
      locations: saved.locations ?? [],
      terms: saved.terms ?? [],
      translation_guide: saved.translation_guide ?? '',
      chapter_context: saved.chapter_context ?? [],
    }
    referenceDirty.value = false
    flash('success', 'Reference disimpan.')
  } catch (err) {
    flash('error', `Gagal menyimpan reference: ${err.message}`)
  } finally {
    savingReference.value = false
  }
}

watch(novelId, async () => {
  stopStream()
  job.value = null
  await Promise.all([load(), loadReference()])
})

onMounted(async () => {
  await Promise.all([load(), loadReference()])
  try {
    const scraper = await settingsApi.getScraperSettings()
    fetchBatchSize.value = scraper.fetch_batch_size ?? 50
  } catch {
    // The button just falls back to the default batch size.
  }
})

onBeforeUnmount(stopStream)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <button class="mb-4 text-xs text-slate-400 hover:text-slate-200" @click="router.push('/library')">
      ← Library
    </button>

    <p v-if="loading" class="text-sm text-slate-500">Memuat…</p>

    <div
      v-else-if="error"
      class="rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300"
    >
      {{ error }}
    </div>

    <template v-else-if="novel">
      <header class="mb-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <h1 class="text-2xl font-semibold tracking-tight text-white">
              {{ novel.title_translated || novel.title }}
            </h1>
            <p class="mt-1 text-sm text-slate-400">
              {{ novel.author || 'Penulis tidak diketahui' }} ·
              <span class="font-mono text-xs">{{ novel.source_lang }} → {{ novel.target_lang }}</span>
            </p>
            <div
              class="mt-2 rounded-lg border border-ink-800/80 bg-ink-900/50 px-3 py-2 text-[11px] text-slate-400"
            >
              <span class="font-semibold uppercase tracking-wider text-slate-500">Sumber:</span>
              <span class="ml-1.5 text-slate-300">{{ novel.title }}</span>
              <span v-if="novel.scraper_name" class="ml-2 font-mono text-slate-500">
                ({{ novel.scraper_name }})
              </span>
              <p v-if="novel.source_url" class="mt-0.5 truncate font-mono text-slate-500">
                {{ novel.source_url }}
              </p>
            </div>
          </div>
          <div class="flex flex-wrap gap-1.5 text-[11px]">
            <span
              class="badge"
              :class="
                novel.source_type === 'scraper'
                  ? 'bg-indigo-950/70 text-indigo-300'
                  : 'bg-ink-800 text-slate-400'
              "
            >
              {{ novel.source_type === 'scraper' ? 'Scraper' : 'Manual' }}
            </span>
            <span class="badge bg-ink-800 text-slate-300">{{ novel.chapter_count }} bab</span>
            <span class="badge bg-emerald-950/50 text-emerald-400">{{ novel.raw_count }} raw</span>
            <span class="badge bg-sky-950/50 text-sky-400">
              {{ novel.translated_count }} translated
            </span>
            <span v-if="novel.pending_count" class="badge bg-amber-950/50 text-amber-400">
              {{ novel.pending_count }} pending
            </span>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button
            class="btn-primary !px-3 !py-1.5 text-xs"
            :disabled="!novel.translated_count"
            :title="novel.translated_count ? 'Buka reader' : 'Belum ada bab terjemahan'"
            @click="openReader()"
          >
            Baca
          </button>
          <button class="btn-ghost !px-3 !py-1.5 text-xs" @click="downloadExport('txt')">
            Export (.txt)
          </button>
          <button class="btn-ghost !px-3 !py-1.5 text-xs" @click="downloadExport('json')">
            Backup (.json)
          </button>
        </div>
      </header>

      <!-- ============================ SYNOPIS ============================ -->
      <section class="card mb-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <h2 class="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
              Sinopsis
              <span
                v-if="novel.synopsis_translated"
                class="badge bg-emerald-950/50 text-emerald-400"
              >
                terjemahan
              </span>
              <span
                v-else-if="novel.synopsis"
                class="badge bg-amber-950/50 text-amber-400"
              >
                belum diterjemahkan
              </span>
            </h2>
            <p
              v-if="displaySynopsis"
              class="mt-1 whitespace-pre-line text-xs leading-relaxed text-slate-400"
              :class="{ 'line-clamp-3': !synopsisExpanded }"
            >
              {{ displaySynopsis }}
            </p>
            <p v-else class="mt-1 text-xs text-slate-500">Novel ini belum punya sinopsis.</p>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="displaySynopsis"
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="synopsisExpanded = !synopsisExpanded"
            >
              {{ synopsisExpanded ? 'Ringkas' : 'Baca semua' }}
            </button>
            <button
              v-if="novel.synopsis"
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="showRawSynopsis = !showRawSynopsis"
            >
              {{ showRawSynopsis ? 'Sembunyikan asli' : 'Lihat asli' }}
            </button>
            <button class="btn-ghost !px-2.5 !py-1 text-[11px]" @click="startEditSynopsis">
              Edit
            </button>
            <button
              class="btn-primary !px-2.5 !py-1 text-[11px]"
              :disabled="!novel.has_story_analysis || refiningSynopsis"
              :title="
                novel.has_story_analysis
                  ? 'Perbaiki tata bahasa sinopsis memakai istilah dari Analisa Cerita'
                  : 'Jalankan Analisa Cerita terlebih dahulu'
              "
              @click="runRefineSynopsis"
            >
              {{ refiningSynopsis ? 'Memperbaiki…' : 'Perbaiki Sinopsis' }}
            </button>
          </div>
        </div>

        <p v-if="!novel.has_story_analysis" class="mt-2 text-[11px] text-amber-500/80">
          <span class="font-medium text-amber-400">Perbaiki Sinopsis</span> aktif setelah
          <span class="text-amber-400">Analisa Cerita (AI)</span> dijalankan.
        </p>

        <div v-if="showRawSynopsis" class="mt-3 rounded-lg border border-ink-800 bg-ink-850 p-3">
          <p class="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
            Sinopsis asli ({{ novel.source_lang }})
          </p>
          <p class="whitespace-pre-line text-xs leading-relaxed text-slate-400">
            {{ novel.synopsis || '—' }}
          </p>
        </div>

        <div v-if="editingSynopsis" class="mt-3 space-y-2">
          <label class="label" for="synopsis-edit">Edit sinopsis terjemahan</label>
          <textarea
            id="synopsis-edit"
            v-model="synopsisDraft"
            class="input h-32 resize-y text-xs"
            placeholder="Tulis sinopsis terjemahan…"
          />
          <div class="flex justify-end gap-2">
            <button
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="editingSynopsis = false"
            >
              Batal
            </button>
            <button
              class="btn-primary !px-2.5 !py-1 text-[11px]"
              :disabled="savingSynopsis"
              @click="saveSynopsisEdit"
            >
              {{ savingSynopsis ? 'Menyimpan…' : 'Simpan Sinopsis' }}
            </button>
          </div>
        </div>
      </section>

      <!-- tabs -->
      <div class="mb-5 flex gap-1 border-b border-ink-800">
        <button
          class="px-4 py-2 text-sm font-medium"
          :class="
            tab === 'chapters'
              ? 'border-b-2 border-indigo-500 text-white'
              : 'text-slate-400 hover:text-slate-200'
          "
          @click="tab = 'chapters'"
        >
          Chapters
        </button>
        <button
          class="px-4 py-2 text-sm font-medium"
          :class="
            tab === 'reference'
              ? 'border-b-2 border-indigo-500 text-white'
              : 'text-slate-400 hover:text-slate-200'
          "
          @click="tab = 'reference'"
        >
          Story &amp; Reference
          <span
            v-if="reference?.characters?.length || reference?.terms?.length"
            class="ml-1 text-[11px] text-slate-500"
          >
            ({{ reference.characters.length }} karakter, {{ reference.terms.length }} istilah)
          </span>
        </button>
      </div>

      <div
        v-if="notice"
        class="mb-5 rounded-lg border px-4 py-3 text-sm"
        :class="
          notice.type === 'success'
            ? 'border-emerald-900/60 bg-emerald-950/40 text-emerald-300'
            : 'border-rose-900/60 bg-rose-950/40 text-rose-300'
        "
      >
        {{ notice.text }}
      </div>

      <!-- ===================== live progress ===================== -->
      <div
        v-if="job"
        class="mb-5 rounded-xl border px-4 py-3"
        :class="
          jobActive
            ? 'border-indigo-900/60 bg-indigo-950/20'
            : job.status === 'completed'
              ? 'border-emerald-900/60 bg-emerald-950/20'
              : 'border-rose-900/60 bg-rose-950/20'
        "
      >
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-medium text-slate-100">
            {{ jobLabel(job.job_type) }}
          </span>
          <span class="badge bg-ink-800 text-slate-300">{{ job.status }}</span>
          <span class="text-xs text-slate-400">
            {{ job.completed_items }}/{{ job.total_items }}
          </span>
          <span v-if="jobChunk" class="text-xs text-slate-500">
            chunk {{ jobChunk.index }}/{{ jobChunk.total }}
          </span>
          <div class="ml-auto flex gap-2">
            <button
              v-if="jobActive"
              class="btn-danger !px-2.5 !py-1 text-xs"
              @click="cancelJob"
            >
              Cancel
            </button>
            <button v-else class="btn-ghost !px-2.5 !py-1 text-xs" @click="dismissJob">
              Tutup
            </button>
          </div>
        </div>

        <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full transition-all"
            :class="job.status === 'failed' ? 'bg-rose-500' : 'bg-indigo-500'"
            :style="{ width: `${jobPercent}%` }"
          />
        </div>

        <p class="mt-2 text-xs text-slate-400">{{ jobMessage || job.message }}</p>
        <p v-if="job.error" class="mt-1 text-xs text-rose-400">{{ job.error }}</p>

        <div
          v-if="jobEvents.length"
          class="mt-2 max-h-28 overflow-y-auto rounded bg-ink-950/60 p-2 font-mono text-[11px] text-slate-500"
        >
          <div v-for="(event, index) in jobEvents.slice(-12)" :key="index">
            <span class="text-slate-600">{{ event.type }}</span>
            <span v-if="event.chapter_number"> · bab {{ event.chapter_number }}</span>
            <span v-if="event.chunk_index"> · chunk {{ event.chunk_index }}/{{ event.chunk_total }}</span>
            <span v-if="event.grade"> · {{ event.quality_score }} ({{ event.grade }})</span>
            <span v-if="event.message"> — {{ event.message }}</span>
          </div>
        </div>
      </div>

      <!-- ===================== TAB: chapters ===================== -->
      <template v-if="tab === 'chapters'">
        <div class="mb-5 flex flex-wrap items-center gap-2">
          <button
            class="btn-primary"
            :disabled="!translatableSelected.length || jobActive"
            @click="startTranslate"
          >
            Translate Terpilih ({{ translatableSelected.length }})
          </button>
          <button
            class="btn-danger"
            :disabled="!clearableSelected.length || jobActive || clearing"
            title="Hapus hasil terjemahan bab terpilih tanpa menghapus teks raw"
            @click="clearSelectedTranslations"
          >
            Hapus Terjemahan ({{ clearableSelected.length }})
          </button>
          <button class="btn-ghost" :disabled="jobActive" @click="startAnalyze">
            Analisa Cerita (AI)
          </button>

          <label
            class="flex cursor-pointer select-none items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-850 px-2.5 py-1.5 text-[11px] text-slate-300"
            for="auto-update-reference"
            title="Deteksi karakter, lokasi & istilah baru otomatis sebelum menerjemahkan tiap bab memakai model Analisa Cerita"
          >
            <input
              id="auto-update-reference"
              v-model="autoUpdateReference"
              type="checkbox"
              class="h-3.5 w-3.5 accent-indigo-500"
            />
            Auto-update referensi
          </label>

          <span class="mx-1 h-5 w-px self-center bg-ink-700" />

          <button
            class="btn-ghost"
            :disabled="jobActive || fetching || !novel.pending_count"
            :title="
              novel.pending_count
                ? `Fetch ${Math.min(fetchBatchSize, novel.pending_count)} bab pending berikutnya`
                : 'Tidak ada bab pending_fetch'
            "
            @click="fetchBatch"
          >
            Fetch Batch ({{ Math.min(fetchBatchSize, novel.pending_count || 0) }} bab)
          </button>
          <button
            class="btn-ghost"
            :disabled="jobActive || fetching || !pendingSelected.length"
            @click="fetchSelected"
          >
            Fetch Terpilih ({{ pendingSelected.length }})
          </button>
          <button class="btn-ghost" @click="openUrlModal">+ Bab dari URL</button>
          <button
            v-if="novel.source_url"
            class="btn-ghost"
            :disabled="jobActive || syncingUrl"
            title="Bandingkan daftar bab di situs sumber dengan yang ada di sini"
            @click="syncFromSource"
          >
            {{ syncingUrl ? 'Mengecek…' : 'Cek Bab Baru (Sync URL)' }}
          </button>

          <span class="mx-1 h-5 w-px self-center bg-ink-700" />

          <button class="btn-ghost" @click="openManual">+ Bab Manual</button>
          <button class="btn-ghost" :disabled="uploading" @click="pickFiles">
            {{ uploading ? 'Mengunggah…' : 'Upload .txt' }}
          </button>
          <input
            ref="fileInput"
            type="file"
            accept=".txt,text/plain"
            multiple
            class="hidden"
            @change="onFilesChosen"
          />
        </div>

        <div class="mb-3 flex flex-wrap gap-1">
          <button
            v-for="item in filters"
            :key="item.value"
            class="rounded-lg px-3 py-1.5 text-xs font-medium"
            :class="
              filter === item.value
                ? 'bg-ink-800 text-white'
                : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
            "
            @click="filter = item.value"
          >
            {{ item.label }}
            <span class="text-slate-500">
              {{
                item.value === 'all'
                  ? chapters.length
                  : chapters.filter((c) => c.status === item.value).length
              }}
            </span>
          </button>
        </div>

        <div class="overflow-hidden rounded-xl border border-ink-700">
          <table class="w-full text-left text-sm">
            <thead class="bg-ink-850 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th class="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 rounded border-ink-600 bg-ink-850 text-indigo-600"
                    :checked="allVisibleSelected"
                    @change="toggleAll"
                  />
                </th>
                <th class="w-12 px-3 py-2">#</th>
                <th class="px-3 py-2">Judul</th>
                <th class="w-28 px-3 py-2">Status</th>
                <th class="w-24 px-3 py-2">Quality</th>
                <th class="w-16 px-3 py-2 text-right">Chars</th>
                <th class="w-36 px-3 py-2 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-800">
              <tr v-if="!visibleChapters.length">
                <td colspan="7" class="px-3 py-10 text-center text-sm text-slate-500">
                  Tidak ada bab pada filter ini.
                </td>
              </tr>
              <tr v-for="chapter in visibleChapters" :key="chapter.id" class="hover:bg-ink-850/60">
                <td class="px-3 py-2">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 rounded border-ink-600 bg-ink-850 text-indigo-600"
                    :checked="selected.includes(chapter.id)"
                    @change="toggle(chapter.id)"
                  />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-slate-500">
                  {{ chapter.chapter_number }}
                </td>
                <td class="px-3 py-2">
                  <button
                    class="text-left text-slate-200 hover:text-white hover:underline"
                    @click="openChapter(chapter)"
                  >
                    {{ chapter.title || '(tanpa judul)' }}
                  </button>
                  <p v-if="chapter.title_translated" class="text-[11px] text-slate-500">
                    {{ chapter.title_translated }}
                  </p>
                </td>
                <td class="px-3 py-2">
                  <span
                    class="badge"
                    :class="statusStyles[chapter.status] ?? 'bg-ink-800 text-slate-400'"
                  >
                    {{ chapter.status }}
                  </span>
                </td>
                <td class="px-3 py-2">
                  <span
                    v-if="chapter.quality_score !== null && chapter.quality_score !== undefined"
                    class="badge"
                    :class="gradeStyles[gradeFor(chapter.quality_score)]"
                  >
                    {{ Math.round(chapter.quality_score) }} · {{ gradeFor(chapter.quality_score) }}
                  </span>
                  <span v-else class="text-xs text-slate-600">—</span>
                </td>
                <td class="px-3 py-2 text-right font-mono text-xs text-slate-500">
                  {{ chapter.raw_content.length }}
                </td>
                <td class="px-3 py-2 text-right">
                  <button
                    v-if="chapter.status === 'translated'"
                    class="btn-primary !px-2 !py-0.5 text-[11px]"
                    @click="openReader(chapter.id)"
                  >
                    Baca
                  </button>
                  <button class="btn-ghost !px-2 !py-0.5 text-[11px]" @click="openChapter(chapter)">
                    Lihat/Edit
                  </button>
                  <button
                    v-if="
                      chapter.status === 'translated' ||
                      chapter.status === 'error' ||
                      (chapter.translated_content || '').trim()
                    "
                    class="btn-ghost ml-1 !px-2 !py-0.5 text-[11px] text-amber-300 hover:text-amber-200"
                    :disabled="jobActive || clearing"
                    title="Hapus hasil terjemahan bab ini tanpa menghapus teks raw"
                    @click="clearSingleTranslation(chapter)"
                  >
                    Reset TL
                  </button>
                  <button
                    class="btn-danger ml-1 !px-2 !py-0.5 text-[11px]"
                    @click="removeChapter(chapter)"
                  >
                    Hapus
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- ===================== TAB: reference ===================== -->
      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <button class="btn-ghost" :disabled="jobActive" @click="startAnalyze">
            Run AI Analysis
          </button>
          <button class="btn-primary" :disabled="savingReference" @click="saveReference">
            {{ savingReference ? 'Menyimpan…' : 'Simpan Perubahan' }}
          </button>
          <span v-if="referenceDirty" class="text-xs text-amber-400">ada perubahan belum disimpan</span>
          <span v-else class="text-xs text-slate-500">tersimpan</span>
        </div>

        <p v-if="referenceLoading" class="text-sm text-slate-500">Memuat reference…</p>

        <div v-else-if="reference" class="space-y-5">
          <!-- guide -->
          <section class="card">
            <h2 class="mb-2 text-sm font-semibold text-white">Translation Guide</h2>
            <p class="mb-2 text-xs text-slate-500">
              Gaya bahasa, nada, aturan penamaan. Disuntikkan ke setiap prompt translasi.
            </p>
            <textarea
              v-model="reference.translation_guide"
              class="input h-28 resize-y text-xs"
              placeholder="mis. Gunakan nada formal, pertahankan istilah militer, nama karakter memakai romanisasi…"
              @input="markDirty"
            />
          </section>

          <!-- characters -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-white">
                Characters
                <span class="ml-1 text-xs font-normal text-slate-500">
                  ({{ reference.characters.length }})
                </span>
              </h2>
              <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="addCharacter">
                + Karakter
              </button>
            </div>

            <p v-if="!reference.characters.length" class="text-xs text-slate-500">
              Belum ada karakter. Jalankan Run AI Analysis atau tambah manual.
            </p>

            <div v-for="(character, index) in reference.characters" :key="index" class="mb-3 rounded-lg border border-ink-800 p-3">
              <div class="grid gap-2 sm:grid-cols-4">
                <div>
                  <label class="label">Nama (sumber)</label>
                  <input v-model="character.name" class="input text-xs" @input="markDirty" />
                </div>
                <div>
                  <label class="label">Romanized</label>
                  <input
                    v-model="character.romanized_name"
                    class="input text-xs"
                    @input="markDirty"
                  />
                </div>
                <div>
                  <label class="label">Gender</label>
                  <input v-model="character.gender" class="input text-xs" @input="markDirty" />
                </div>
                <div>
                  <label class="label">Usia</label>
                  <input v-model="character.age" class="input text-xs" @input="markDirty" />
                </div>
              </div>
              <div class="mt-2 grid gap-2 sm:grid-cols-3">
                <div>
                  <label class="label">Alias (pisahkan koma)</label>
                  <input
                    :value="aliasesToText(character)"
                    class="input text-xs"
                    @input="setAliases(character, $event.target.value)"
                  />
                </div>
                <div>
                  <label class="label">Relasi</label>
                  <input
                    v-model="character.relationships"
                    class="input text-xs"
                    @input="markDirty"
                  />
                </div>
                <div>
                  <label class="label">Catatan</label>
                  <input v-model="character.notes" class="input text-xs" @input="markDirty" />
                </div>
              </div>
              <div class="mt-2 text-right">
                <button
                  class="btn-danger !px-2 !py-0.5 text-[11px]"
                  @click="removeAt(reference.characters, index)"
                >
                  Hapus karakter
                </button>
              </div>
            </div>
          </section>

          <!-- terms -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-white">
                Terms / Glossary
                <span class="ml-1 text-xs font-normal text-slate-500">
                  ({{ reference.terms.length }})
                </span>
              </h2>
              <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="addTerm">+ Istilah</button>
            </div>
            <p v-if="!reference.terms.length" class="text-xs text-slate-500">
              Istilah wajib (tingkatan, teknik, organisasi). Dipakai juga untuk skor kepatuhan.
            </p>
            <div
              v-for="(term, index) in reference.terms"
              :key="index"
              class="mb-2 grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]"
            >
              <input v-model="term.source" class="input text-xs" placeholder="sumber" @input="markDirty" />
              <input v-model="term.target" class="input text-xs" placeholder="terjemahan" @input="markDirty" />
              <input v-model="term.note" class="input text-xs" placeholder="catatan" @input="markDirty" />
              <button class="btn-danger !px-2 !py-1 text-[11px]" @click="removeAt(reference.terms, index)">
                ✕
              </button>
            </div>
          </section>

          <!-- locations -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-white">
                Locations
                <span class="ml-1 text-xs font-normal text-slate-500">
                  ({{ reference.locations.length }})
                </span>
              </h2>
              <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="addLocation">+ Lokasi</button>
            </div>
            <p v-if="!reference.locations.length" class="text-xs text-slate-500">Belum ada lokasi.</p>
            <div
              v-for="(location, index) in reference.locations"
              :key="index"
              class="mb-2 grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]"
            >
              <input v-model="location.source" class="input text-xs" placeholder="sumber" @input="markDirty" />
              <input v-model="location.target" class="input text-xs" placeholder="terjemahan" @input="markDirty" />
              <input v-model="location.note" class="input text-xs" placeholder="catatan" @input="markDirty" />
              <button
                class="btn-danger !px-2 !py-1 text-[11px]"
                @click="removeAt(reference.locations, index)"
              >
                ✕
              </button>
            </div>
          </section>

          <!-- rolling context -->
          <section class="card">
            <h2 class="mb-2 text-sm font-semibold text-white">
              Rolling Chapter Context
              <span class="ml-1 text-xs font-normal text-slate-500">
                ({{ reference.chapter_context.length }}/5 terakhir)
              </span>
            </h2>
            <p v-if="!reference.chapter_context.length" class="text-xs text-slate-500">
              Belum ada ringkasan. Jalankan Run AI Analysis untuk mengisinya.
            </p>
            <ol v-else class="space-y-2">
              <li
                v-for="entry in reference.chapter_context"
                :key="entry.chapter_id"
                class="rounded-lg border border-ink-800 px-3 py-2 text-xs"
              >
                <span class="font-mono text-slate-500">Bab {{ entry.chapter_number }}</span>
                <span class="ml-2 text-slate-300">{{ entry.title }}</span>
                <p class="mt-1 text-slate-400">{{ entry.summary }}</p>
              </li>
            </ol>
          </section>
        </div>
      </template>
    </template>

    <!-- ===================== chapters from URL modal ===================== -->
    <div
      v-if="showUrlModal"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="showUrlModal = false"
    >
      <form
        class="w-full max-w-2xl space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl"
        @submit.prevent="addFromUrls"
      >
        <div>
          <h2 class="text-sm font-semibold text-white">Tambah Bab dari URL</h2>
          <p class="mt-1 text-xs text-slate-500">
            Satu URL bab per baris. Modul scraper dipilih otomatis dari domain; URL yang sudah ada
            di novel ini akan dilewati.
          </p>
        </div>
        <div>
          <label class="label" for="urls-input">URL bab</label>
          <textarea
            id="urls-input"
            v-model="urlsText"
            class="input h-40 resize-y font-mono text-xs"
            placeholder="https://contoh.com/book/123/chapter-1.htm&#10;https://contoh.com/book/123/chapter-2.htm"
          />
          <p class="mt-1 text-[11px] text-slate-500">
            {{ urlsText.split(/\n/).filter((item) => item.trim()).length }} URL terdeteksi
          </p>
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="showUrlModal = false">Batal</button>
          <button type="submit" class="btn-primary" :disabled="savingUrls || !urlsText.trim()">
            {{ savingUrls ? 'Mengambil…' : 'Tambah Bab' }}
          </button>
        </div>
      </form>
    </div>

    <!-- ===================== manual chapter modal ===================== -->
    <div
      v-if="showManual"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="showManual = false"
    >
      <form
        class="w-full max-w-2xl space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl"
        @submit.prevent="saveManual"
      >
        <h2 class="text-sm font-semibold text-white">Tambah Bab Manual</h2>
        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="label" for="manual-no">Nomor bab</label>
            <input
              id="manual-no"
              v-model.number="manualForm.chapter_number"
              class="input"
              type="number"
              step="1"
              placeholder="otomatis"
            />
          </div>
          <div class="col-span-2">
            <label class="label" for="manual-chapter-title">Judul bab</label>
            <input
              id="manual-chapter-title"
              v-model="manualForm.title"
              class="input"
              type="text"
              placeholder="opsional"
            />
          </div>
        </div>
        <div>
          <label class="label" for="manual-content">Isi bab (paste teks)</label>
          <textarea
            id="manual-content"
            v-model="manualForm.raw_content"
            class="input h-64 resize-y font-mono text-xs"
            placeholder="Tempel isi bab di sini…"
          />
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="showManual = false">Batal</button>
          <button
            type="submit"
            class="btn-primary"
            :disabled="savingManual || !manualForm.raw_content.trim()"
          >
            {{ savingManual ? 'Menyimpan…' : 'Simpan Bab' }}
          </button>
        </div>
      </form>
    </div>

    <!-- ===================== chapter raw/translated modal ===================== -->
    <div
      v-if="editing"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-8"
      @click.self="editing = null"
    >
      <form
        class="w-full max-w-6xl space-y-3 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl"
        @submit.prevent="saveChapter"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold text-white">
            Bab {{ editing.chapter_number }}
            <span class="badge ml-2" :class="statusStyles[editing.status]">{{ editing.status }}</span>
            <span
              v-if="editing.quality_score !== null && editing.quality_score !== undefined"
              class="badge ml-1"
              :class="gradeStyles[gradeFor(editing.quality_score)]"
            >
              {{ Math.round(editing.quality_score) }} · {{ gradeFor(editing.quality_score) }}
            </span>
          </h2>
          <div class="flex items-center gap-1">
            <button
              v-for="pane in ['both', 'raw', 'translated']"
              :key="pane"
              type="button"
              class="rounded px-2 py-1 text-[11px]"
              :class="editPane === pane ? 'bg-ink-800 text-white' : 'text-slate-400 hover:text-slate-200'"
              @click="editPane = pane"
            >
              {{ pane === 'both' ? 'Side by side' : pane === 'raw' ? 'Raw' : 'Translated' }}
            </button>
            <button type="button" class="ml-2 text-slate-500 hover:text-slate-200" @click="editing = null">
              ✕
            </button>
          </div>
        </div>

        <div>
          <label class="label" for="edit-title">Judul</label>
          <input id="edit-title" v-model="editForm.title" class="input" type="text" />
        </div>

        <div class="grid gap-3" :class="editPane === 'both' ? 'lg:grid-cols-2' : 'grid-cols-1'">
          <div v-if="editPane !== 'translated'">
            <label class="label" for="edit-raw">
              Raw ({{ editForm.raw_content.length }} karakter)
            </label>
            <textarea
              id="edit-raw"
              v-model="editForm.raw_content"
              class="input h-80 resize-y font-mono text-xs"
              placeholder="Belum ada isi — jalankan Fetch Raw untuk bab ini."
            />
          </div>
          <div v-if="editPane !== 'raw'">
            <label class="label" for="edit-translated">
              Translated ({{ editForm.translated_content.length }} karakter)
            </label>
            <textarea
              id="edit-translated"
              v-model="editForm.translated_content"
              class="input h-80 resize-y font-mono text-xs"
              placeholder="Belum diterjemahkan — pilih bab ini lalu klik Translate Terpilih."
            />
          </div>
        </div>

        <div class="flex items-center justify-end gap-2">
          <button type="button" class="btn-ghost" @click="editing = null">Batal</button>
          <button type="submit" class="btn-primary" :disabled="savingEdit">
            {{ savingEdit ? 'Menyimpan…' : 'Simpan' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Modal: Peringatan bab sebelumnya belum diterjemahkan -->
    <div
      v-if="contextWarning"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      @click.self="contextWarning = null"
    >
      <div class="card w-full max-w-lg space-y-4 border-amber-800/70">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-semibold text-amber-300">
              Bab Sebelumnya Belum Diterjemahkan
            </h2>
            <p class="mt-1 text-xs text-slate-400">
              Anda memilih mulai dari <strong>Bab {{ contextWarning.minSelectedNo }}</strong>, namun
              masih ada <strong>{{ contextWarning.earlierCount }} bab sebelumnya</strong> yang
              belum berstatus <code class="text-slate-300">translated</code> ({{
                contextWarning.earlierSample
              }}).
            </p>
          </div>
          <button
            type="button"
            class="text-slate-500 hover:text-slate-200"
            @click="contextWarning = null"
          >
            ✕
          </button>
        </div>

        <div class="rounded-lg border border-amber-900/60 bg-amber-950/30 p-3 text-xs leading-relaxed text-amber-200">
          Jika langsung menerjemahkan bab ini tanpa bab sebelumnya, terjemahan
          <strong>berisiko tidak memiliki konteks cerita sebelumnya</strong> sehingga konsistensi
          alur, gaya bahasa, dan nama karakter bisa kurang memuaskan.
          <span v-if="contextWarning.pendingCount" class="mt-1 block text-amber-300/90">
            Catatan: {{ contextWarning.pendingCount }} bab sebelumnya masih berstatus
            <code>pending_fetch</code> (belum di-fetch raw).
          </span>
        </div>

        <div class="flex flex-wrap justify-end gap-2">
          <button type="button" class="btn-ghost text-xs" @click="contextWarning = null">
            Batal
          </button>
          <button
            v-if="contextWarning.earlierReadyIds.length"
            type="button"
            class="btn-primary text-xs"
            @click="confirmTranslateEarlier"
          >
            Translate Bab Sebelumnya Dulu ({{ contextWarning.earlierReadyIds.length + contextWarning.selectedIds.length }} bab)
          </button>
          <button
            type="button"
            class="rounded-lg border border-amber-700/70 bg-amber-950/50 px-3 py-1.5 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-900/60"
            @click="confirmTranslateAnyway"
          >
            Tetap Translate (Tanpa Konteks)
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
