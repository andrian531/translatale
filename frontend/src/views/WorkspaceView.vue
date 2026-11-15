<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'
import { readerApi } from '@/api/reader'
import { settingsApi } from '@/api/settings'
import { translationApi } from '@/api/translation'
import { useI18n } from '@/i18n'

const { t } = useI18n()

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
  { value: 'all', labelKey: 'workspace.filters.all' },
  { value: 'pending_fetch', labelKey: 'common.status.pending_fetch' },
  { value: 'raw', labelKey: 'common.status.raw' },
  { value: 'translating', labelKey: 'common.status.translating' },
  { value: 'translated', labelKey: 'common.status.translated' },
  { value: 'error', labelKey: 'common.status.error' },
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

const searchQuery = ref('')
const sortKey = ref('chapter_number')
const sortDir = ref('asc')

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

function sortIndicator(key) {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? ' ↑' : ' ↓'
}

const visibleChapters = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const filtered = chapters.value.filter((chapter) => {
    if (filter.value !== 'all' && chapter.status !== filter.value) return false
    if (!q) return true
    const num = String(chapter.chapter_number ?? '')
    const title = (chapter.title || '').toLowerCase()
    const translated = (chapter.title_translated || '').toLowerCase()
    return num.includes(q) || title.includes(q) || translated.includes(q)
  })

  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...filtered].sort((a, b) => {
    if (key === 'chapter_number') return ((a.chapter_number ?? 0) - (b.chapter_number ?? 0)) * dir
    if (key === 'title') {
      const ta = (a.title_translated || a.title || '').toLowerCase()
      const tb = (b.title_translated || b.title || '').toLowerCase()
      return ta.localeCompare(tb) * dir
    }
    if (key === 'status') return String(a.status || '').localeCompare(String(b.status || '')) * dir
    if (key === 'quality') {
      const qa = a.quality_score ?? -1
      const qb = b.quality_score ?? -1
      return (qa - qb) * dir
    }
    if (key === 'chars') {
      return ((a.raw_content?.length ?? 0) - (b.raw_content?.length ?? 0)) * dir
    }
    return 0
  })
})

const pageSize = ref(50)
const currentPage = ref(1)
const totalPages = computed(() => Math.max(1, Math.ceil(visibleChapters.value.length / pageSize.value)))
const paginatedChapters = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return visibleChapters.value.slice(start, start + pageSize.value)
})
const pageRange = computed(() => {
  const total = visibleChapters.value.length
  if (!total) return { start: 0, end: 0, total: 0 }
  const start = (currentPage.value - 1) * pageSize.value + 1
  const end = Math.min(total, currentPage.value * pageSize.value)
  return { start, end, total }
})

watch([filter, searchQuery, pageSize, sortKey, sortDir], () => {
  currentPage.value = 1
})
watch(totalPages, (max) => {
  if (currentPage.value > max) currentPage.value = max
})

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
    paginatedChapters.value.length > 0 &&
    paginatedChapters.value.every((chapter) => selected.value.includes(chapter.id)),
)

const displaySynopsis = computed(() => {
  const translated = (novel.value?.synopsis_translated || '').trim()
  const original = (novel.value?.synopsis || '').trim()
  return translated || original
})

const JOB_LABELS = {
  translate: 'common.job.translate',
  story_analysis: 'common.job.story_analysis',
  fetch: 'common.job.fetch',
  apply_reference: 'workspace.job.apply_reference',
}

const JOB_STATUS_KEYS = {
  queued: 'common.job.queued',
  running: 'common.job.running',
  completed: 'common.job.completed',
  failed: 'common.job.failed',
  cancelled: 'common.job.cancelled',
}

const CHAPTER_STATUS_KEYS = {
  pending_fetch: 'common.status.pending_fetch',
  raw: 'common.status.raw',
  translating: 'common.status.translating',
  translated: 'common.status.translated',
  error: 'common.status.error',
}

const translatedChaptersCount = computed(
  () => chapters.value.filter((c) => (c.translated_content || '').trim() || c.status === 'translated').length,
)
const applyingReference = ref(false)

function jobLabel(type) {
  const key = JOB_LABELS[type]
  if (key) return t(key)
  return type || t('workspace.job.unknown')
}

function jobStatusLabel(status) {
  const key = JOB_STATUS_KEYS[status]
  return key ? t(key) : status
}

function chapterStatusLabel(status) {
  const key = CHAPTER_STATUS_KEYS[status]
  return key ? t(key) : status
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
    flash('error', t('workspace.errors.loadReference', { message: err.message }))
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
    const visibleIds = paginatedChapters.value.map((chapter) => chapter.id)
    selected.value = selected.value.filter((id) => !visibleIds.includes(id))
  } else {
    selected.value = [...new Set([...selected.value, ...paginatedChapters.value.map((c) => c.id)])]
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
        flash('error', t('common.job.failedMessage', { message: event.message }))
      } else if (event.type === 'cancelled') {
        flash('error', t('common.job.cancelledMessage'))
      } else {
        flash('success', t('common.job.finished'))
      }
    },
    onError() {
      closeStream = null
      flash('error', t('common.job.streamLost'))
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
    flash('error', t('workspace.errors.startTranslate', { message: err.message }))
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
    .map((chapter) => t('common.job.chapter', { number: chapter.chapter_number }))
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
    flash('error', t('workspace.errors.earlierPending'))
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
    flash('error', t('workspace.errors.startAnalyze', { message: err.message }))
  }
}

async function cancelJob() {
  if (!job.value) return
  try {
    const updated = await translationApi.cancelJob(job.value.id)
    job.value = updated
  } catch (err) {
    flash('error', t('workspace.errors.cancelJob', { message: err.message }))
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
    flash('error', t('workspace.errors.startFetch', { message: err.message }))
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
    !window.confirm(t('workspace.confirm.clearSelected', { count: ids.length }))
  ) {
    return
  }
  clearing.value = true
  try {
    const res = await novelsApi.clearTranslations(novelId.value, ids)
    selected.value = []
    await load()
    flash('success', t('workspace.notices.clearedSelected', { count: res.cleared }))
  } catch (err) {
    flash('error', t('workspace.errors.clearTranslations', { message: err.message }))
  } finally {
    clearing.value = false
  }
}

async function clearSingleTranslation(chapter) {
  if (
    !window.confirm(t('workspace.confirm.clearSingle', { number: chapter.chapter_number }))
  ) {
    return
  }
  clearing.value = true
  try {
    await novelsApi.clearTranslations(novelId.value, [chapter.id])
    await load()
    flash('success', t('workspace.notices.clearedSingle', { number: chapter.chapter_number }))
  } catch (err) {
    flash('error', t('workspace.errors.clearTranslations', { message: err.message }))
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
    flash('success', t('workspace.notices.synopsisSaved'))
  } catch (err) {
    flash('error', t('workspace.errors.saveSynopsis', { message: err.message }))
  } finally {
    savingSynopsis.value = false
  }
}

async function runRefineSynopsis() {
  refiningSynopsis.value = true
  try {
    novel.value = await novelsApi.refineSynopsis(novelId.value)
    synopsisExpanded.value = true
    flash('success', t('workspace.notices.synopsisRefined'))
  } catch (err) {
    flash('error', t('workspace.errors.refineSynopsis', { message: err.message }))
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
    const parts = [t('workspace.notices.urlsAdded', { count: result.added })]
    if (result.skipped) parts.push(t('workspace.notices.urlsSkipped', { count: result.skipped }))
    if (result.failed) parts.push(t('workspace.notices.urlsFailed', { count: result.failed }))
    const detail = result.errors?.[0]?.error ? ` — ${result.errors[0].error}` : ''
    flash(result.failed ? 'error' : 'success', parts.join(', ') + detail)
  } catch (err) {
    flash('error', t('workspace.errors.addFromUrls', { message: err.message }))
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
        ? t('workspace.notices.syncAdded', { added: result.added, skipped: result.skipped })
        : t('workspace.notices.syncNone', { found: result.found ?? 0 }),
    )
  } catch (err) {
    flash('error', t('workspace.errors.sync', { message: err.message }))
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
    flash('success', t('workspace.notices.manualAdded'))
  } catch (err) {
    flash('error', t('workspace.errors.addManual', { message: err.message }))
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
    flash('success', t('workspace.notices.uploaded', { count: created.length }))
  } catch (err) {
    flash('error', t('workspace.errors.upload', { message: err.message }))
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
    flash('success', t('workspace.notices.exported', { format }))
  } catch (err) {
    flash('error', t('workspace.errors.export', { format, message: err.message }))
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
    flash('success', t('workspace.notices.chapterSaved'))
  } catch (err) {
    flash('error', t('workspace.errors.saveChapter', { message: err.message }))
  } finally {
    savingEdit.value = false
  }
}

async function removeChapter(chapter) {
  if (!window.confirm(t('workspace.confirm.removeChapter', { title: chapter.title }))) return
  try {
    await novelsApi.removeChapter(chapter.id)
    await load()
    flash('success', t('workspace.notices.chapterRemoved'))
  } catch (err) {
    flash('error', t('workspace.errors.removeChapter', { message: err.message }))
  }
}

// ----------------------------------------------------------------------
// Reference editing
// ----------------------------------------------------------------------
function markDirty() {
  referenceDirty.value = true
}

const characterModal = ref(null)

function openCharacterModal(index = -1) {
  const existing = index >= 0 ? reference.value.characters[index] : null
  characterModal.value = {
    index,
    name: existing?.name || '',
    romanized_name: existing?.romanized_name || '',
    gender: existing?.gender || '',
    age: existing?.age || '',
    aliasesText: (existing?.aliases ?? []).join(', '),
    relationships: existing?.relationships || '',
    notes: existing?.notes || '',
  }
}

function saveCharacterModal() {
  const modal = characterModal.value
  if (!modal) return
  if (!modal.name.trim() && !modal.romanized_name.trim()) {
    flash('error', t('workspace.errors.characterNameRequired'))
    return
  }
  const entry = {
    name: modal.name.trim(),
    romanized_name: modal.romanized_name.trim(),
    gender: modal.gender.trim(),
    age: modal.age.trim(),
    aliases: modal.aliasesText
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    relationships: modal.relationships.trim(),
    notes: modal.notes.trim(),
  }
  if (modal.index >= 0) {
    reference.value.characters[modal.index] = entry
  } else {
    reference.value.characters.push(entry)
  }
  markDirty()
  characterModal.value = null
}

function addCharacter() {
  openCharacterModal(-1)
}

function addTerm() {
  reference.value.terms.push({
    source: '',
    romanized: '',
    target: '',
    note: '',
    keep_romanized: false,
  })
  markDirty()
}

function addLocation() {
  reference.value.locations.push({
    source: '',
    romanized: '',
    target: '',
    note: '',
    keep_romanized: false,
  })
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
    flash('success', t('workspace.notices.referenceSaved'))
  } catch (err) {
    flash('error', t('workspace.errors.saveReference', { message: err.message }))
  } finally {
    savingReference.value = false
  }
}

async function applyReferenceToTranslated() {
  if (!translatedChaptersCount.value) {
    flash('error', t('workspace.errors.noTranslatedChapters'))
    return
  }
  if (
    !window.confirm(
      t('workspace.confirm.applyReference', { count: translatedChaptersCount.value }),
    )
  ) {
    return
  }
  applyingReference.value = true
  try {
    if (referenceDirty.value) {
      await saveReference()
    }
    const started = await translationApi.applyReference(novelId.value)
    job.value = started
    jobMessage.value = started.message
    watchJob(started.id)
  } catch (err) {
    flash('error', t('workspace.errors.applyReference', { message: err.message }))
  } finally {
    applyingReference.value = false
  }
}

// -- cover & cover prompt -----------------------------------------------
const coverInput = ref(null)
const uploadingCover = ref(false)
const showCoverPromptModal = ref(false)
const generatingCoverPrompt = ref(false)
const coverPromptResult = ref(null)
const copiedPromptKey = ref('')
const coverPromptForm = reactive({
  style: 'webnovel_cover',
  mood: '',
  extra_notes: '',
})

function pickCover() {
  coverInput.value?.click()
}

async function onCoverChosen(event) {
  const file = event.target.files?.[0]
  if (!file) return
  uploadingCover.value = true
  try {
    novel.value = await novelsApi.uploadCover(novelId.value, file)
    flash('success', t('workspace.cover.uploaded'))
  } catch (err) {
    flash('error', t('workspace.cover.uploadFailed', { message: err.message }))
  } finally {
    uploadingCover.value = false
    event.target.value = ''
  }
}

async function removeCover() {
  if (!window.confirm(t('workspace.confirm.removeCover'))) return
  uploadingCover.value = true
  try {
    novel.value = await novelsApi.deleteCover(novelId.value)
    flash('success', t('workspace.cover.removed'))
  } catch (err) {
    flash('error', t('workspace.cover.uploadFailed', { message: err.message }))
  } finally {
    uploadingCover.value = false
  }
}

function openCoverPromptModal() {
  showCoverPromptModal.value = true
}

async function runGenerateCoverPrompt() {
  generatingCoverPrompt.value = true
  try {
    coverPromptResult.value = await translationApi.generateCoverPrompt(novelId.value, {
      style: coverPromptForm.style,
      mood: coverPromptForm.mood,
      extra_notes: coverPromptForm.extra_notes,
    })
  } catch (err) {
    flash('error', t('workspace.coverPrompt.generateFailed', { message: err.message }))
  } finally {
    generatingCoverPrompt.value = false
  }
}

async function copyPromptText(key, text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copiedPromptKey.value = key
    window.setTimeout(() => {
      if (copiedPromptKey.value === key) copiedPromptKey.value = ''
    }, 2000)
  } catch {
    // Clipboard unavailable
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
      ← {{ t('workspace.backToLibrary') }}
    </button>

    <p v-if="loading" class="text-sm text-slate-500">{{ t('common.actions.loading') }}</p>

    <div
      v-else-if="error"
      class="rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300"
    >
      {{ error }}
    </div>

    <template v-else-if="novel">
      <header class="mb-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex min-w-0 flex-1 items-start gap-4">
            <div class="shrink-0">
              <img
                v-if="novel.cover_url"
                :src="novel.cover_url"
                :alt="novel.title_translated || novel.title"
                class="aspect-[2/3] w-20 rounded-lg border border-ink-700 object-cover shadow"
              />
              <div
                v-else
                class="grid aspect-[2/3] w-20 place-items-center rounded-lg border border-dashed border-ink-700 bg-ink-900/40 px-1 text-center text-[10px] text-slate-500"
              >
                {{ t('workspace.cover.noCover') }}
              </div>
              <input
                ref="coverInput"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                class="hidden"
                @change="onCoverChosen"
              />
              <div class="mt-1.5 flex flex-col gap-1">
                <button
                  type="button"
                  class="btn-ghost !px-2 !py-0.5 text-[10px]"
                  :disabled="uploadingCover"
                  @click="pickCover"
                >
                  {{
                    uploadingCover
                      ? t('workspace.cover.uploading')
                      : novel.cover_url
                        ? t('workspace.cover.changeCover')
                        : t('workspace.cover.setCover')
                  }}
                </button>
                <button
                  v-if="novel.cover_url"
                  type="button"
                  class="btn-danger !px-2 !py-0.5 text-[10px]"
                  :disabled="uploadingCover"
                  @click="removeCover"
                >
                  {{ t('workspace.cover.removeCover') }}
                </button>
                <button
                  type="button"
                  class="btn-ghost !px-2 !py-0.5 text-[10px] text-indigo-300"
                  @click="openCoverPromptModal"
                >
                  {{ t('workspace.coverPrompt.button') }}
                </button>
              </div>
            </div>

            <div class="min-w-0 flex-1">
              <h1 class="text-2xl font-semibold tracking-tight text-strong">
                {{ novel.title_translated || novel.title }}
              </h1>
              <p class="mt-1 text-sm text-slate-400">
                {{ novel.author || t('workspace.unknownAuthor') }} ·
                <span class="font-mono text-xs">{{ novel.source_lang }} → {{ novel.target_lang }}</span>
              </p>
              <div
                class="mt-2 rounded-lg border border-ink-800/80 bg-ink-900/50 px-3 py-2 text-[11px] text-slate-400"
              >
                <span class="font-semibold uppercase tracking-wider text-slate-500">
                  {{ t('workspace.source') }}
                </span>
                <span class="ml-1.5 text-slate-300">{{ novel.title }}</span>
                <span v-if="novel.scraper_name" class="ml-2 font-mono text-slate-500">
                  ({{ novel.scraper_name }})
                </span>
                <p v-if="novel.source_url" class="mt-0.5 truncate font-mono text-slate-500">
                  {{ novel.source_url }}
                </p>
              </div>
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
              {{
                novel.source_type === 'scraper'
                  ? t('workspace.sourceType.scraper')
                  : t('workspace.sourceType.manual')
              }}
            </span>
            <span class="badge bg-ink-800 text-slate-300">
              {{ t('common.units.chapters', { count: novel.chapter_count }) }}
            </span>
            <span class="badge bg-emerald-950/50 text-emerald-400">
              {{ t('workspace.counts.raw', { count: novel.raw_count }) }}
            </span>
            <span class="badge bg-sky-950/50 text-sky-400">
              {{ t('workspace.counts.translated', { count: novel.translated_count }) }}
            </span>
            <span v-if="novel.pending_count" class="badge bg-amber-950/50 text-amber-400">
              {{ t('workspace.counts.pending', { count: novel.pending_count }) }}
            </span>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button
            class="btn-primary !px-3 !py-1.5 text-xs"
            :disabled="!novel.translated_count"
            :title="
              novel.translated_count
                ? t('workspace.tooltips.openReader')
                : t('workspace.tooltips.noTranslatedChapters')
            "
            @click="openReader()"
          >
            {{ t('workspace.actions.read') }}
          </button>
          <button class="btn-ghost !px-3 !py-1.5 text-xs" @click="downloadExport('txt')">
            {{ t('workspace.actions.exportTxt') }}
          </button>
          <button class="btn-ghost !px-3 !py-1.5 text-xs" @click="downloadExport('json')">
            {{ t('workspace.actions.backupJson') }}
          </button>
        </div>
      </header>

      <!-- ============================ SYNOPIS ============================ -->
      <section class="card mb-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <h2 class="flex flex-wrap items-center gap-2 text-sm font-semibold text-strong">
              {{ t('workspace.synopsis.title') }}
              <span
                v-if="novel.synopsis_translated"
                class="badge bg-emerald-950/50 text-emerald-400"
              >
                {{ t('workspace.synopsis.translatedBadge') }}
              </span>
              <span
                v-else-if="novel.synopsis"
                class="badge bg-amber-950/50 text-amber-400"
              >
                {{ t('workspace.synopsis.untranslatedBadge') }}
              </span>
            </h2>
            <p
              v-if="displaySynopsis"
              class="mt-1 whitespace-pre-line text-xs leading-relaxed text-slate-400"
              :class="{ 'line-clamp-3': !synopsisExpanded }"
            >
              {{ displaySynopsis }}
            </p>
            <p v-else class="mt-1 text-xs text-slate-500">{{ t('workspace.synopsis.empty') }}</p>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="displaySynopsis"
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="synopsisExpanded = !synopsisExpanded"
            >
              {{ synopsisExpanded ? t('workspace.synopsis.collapse') : t('workspace.synopsis.expand') }}
            </button>
            <button
              v-if="novel.synopsis"
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="showRawSynopsis = !showRawSynopsis"
            >
              {{ showRawSynopsis ? t('workspace.synopsis.hideOriginal') : t('workspace.synopsis.showOriginal') }}
            </button>
            <button class="btn-ghost !px-2.5 !py-1 text-[11px]" @click="startEditSynopsis">
              {{ t('common.actions.edit') }}
            </button>
            <button
              class="btn-primary !px-2.5 !py-1 text-[11px]"
              :disabled="!novel.has_story_analysis || refiningSynopsis"
              :title="
                novel.has_story_analysis
                  ? t('workspace.tooltips.refineSynopsis')
                  : t('workspace.tooltips.runAnalysisFirst')
              "
              @click="runRefineSynopsis"
            >
              {{ refiningSynopsis ? t('workspace.synopsis.refining') : t('workspace.synopsis.refine') }}
            </button>
          </div>
        </div>

        <p v-if="!novel.has_story_analysis" class="mt-2 text-[11px] text-amber-500/80">
          <span class="font-medium text-amber-400">{{ t('workspace.synopsis.refine') }}</span>
          {{ t('workspace.synopsis.refineHintA') }}
          <span class="text-amber-400">{{ t('workspace.actions.analyze') }}</span>
          {{ t('workspace.synopsis.refineHintB') }}
        </p>

        <div v-if="showRawSynopsis" class="mt-3 rounded-lg border border-ink-800 bg-ink-850 p-3">
          <p class="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
            {{ t('workspace.synopsis.originalTitle', { lang: novel.source_lang }) }}
          </p>
          <p class="whitespace-pre-line text-xs leading-relaxed text-slate-400">
            {{ novel.synopsis || '—' }}
          </p>
        </div>

        <div v-if="editingSynopsis" class="mt-3 space-y-2">
          <label class="label" for="synopsis-edit">{{ t('workspace.synopsis.editLabel') }}</label>
          <textarea
            id="synopsis-edit"
            v-model="synopsisDraft"
            class="input h-32 resize-y text-xs"
            :placeholder="t('workspace.synopsis.editPlaceholder')"
          />
          <div class="flex justify-end gap-2">
            <button
              class="btn-ghost !px-2.5 !py-1 text-[11px]"
              @click="editingSynopsis = false"
            >
              {{ t('common.actions.cancel') }}
            </button>
            <button
              class="btn-primary !px-2.5 !py-1 text-[11px]"
              :disabled="savingSynopsis"
              @click="saveSynopsisEdit"
            >
              {{ savingSynopsis ? t('common.actions.saving') : t('workspace.synopsis.save') }}
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
              ? 'border-b-2 border-indigo-500 text-strong'
              : 'text-slate-400 hover:text-slate-200'
          "
          @click="tab = 'chapters'"
        >
          {{ t('workspace.tabs.chapters') }}
        </button>
        <button
          class="px-4 py-2 text-sm font-medium"
          :class="
            tab === 'reference'
              ? 'border-b-2 border-indigo-500 text-strong'
              : 'text-slate-400 hover:text-slate-200'
          "
          @click="tab = 'reference'"
        >
          {{ t('workspace.tabs.reference') }}
          <span
            v-if="reference?.characters?.length || reference?.terms?.length"
            class="ml-1 text-[11px] text-slate-500"
          >
            {{
              t('workspace.tabs.referenceCounts', {
                characters: reference.characters.length,
                terms: reference.terms.length,
              })
            }}
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
          <span class="badge bg-ink-800 text-slate-300">{{ jobStatusLabel(job.status) }}</span>
          <span class="text-xs text-slate-400">
            {{
              t('common.job.progress', { done: job.completed_items, total: job.total_items })
            }}
          </span>
          <span v-if="jobChunk" class="text-xs text-slate-500">
            {{ t('common.job.chunk', { index: jobChunk.index, total: jobChunk.total }) }}
          </span>
          <div class="ml-auto flex gap-2">
            <button
              v-if="jobActive"
              class="btn-danger !px-2.5 !py-1 text-xs"
              @click="cancelJob"
            >
              {{ t('common.job.cancel') }}
            </button>
            <button v-else class="btn-ghost !px-2.5 !py-1 text-xs" @click="dismissJob">
              {{ t('common.job.close') }}
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
            <span v-if="event.chapter_number">
              · {{ t('common.job.chapter', { number: event.chapter_number }) }}
            </span>
            <span v-if="event.chunk_index">
              · {{ t('common.job.chunk', { index: event.chunk_index, total: event.chunk_total }) }}
            </span>
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
            {{ t('workspace.actions.translateSelected', { count: translatableSelected.length }) }}
          </button>
          <button
            class="btn-danger"
            :disabled="!clearableSelected.length || jobActive || clearing"
            :title="t('workspace.tooltips.clearSelected')"
            @click="clearSelectedTranslations"
          >
            {{ t('workspace.actions.clearTranslations', { count: clearableSelected.length }) }}
          </button>
          <button class="btn-ghost" :disabled="jobActive" @click="startAnalyze">
            {{ t('workspace.actions.analyze') }}
          </button>

          <label
            class="flex cursor-pointer select-none items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-850 px-2.5 py-1.5 text-[11px] text-slate-300"
            for="auto-update-reference"
            :title="t('workspace.tooltips.autoReference')"
          >
            <input
              id="auto-update-reference"
              v-model="autoUpdateReference"
              type="checkbox"
              class="h-3.5 w-3.5 accent-indigo-500"
            />
            {{ t('workspace.actions.autoReference') }}
          </label>

          <span class="mx-1 h-5 w-px self-center bg-ink-700" />

          <button
            class="btn-ghost"
            :disabled="jobActive || fetching || !novel.pending_count"
            :title="
              novel.pending_count
                ? t('workspace.tooltips.fetchBatch', {
                    count: Math.min(fetchBatchSize, novel.pending_count),
                  })
                : t('workspace.tooltips.noPending')
            "
            @click="fetchBatch"
          >
            {{
              t('workspace.actions.fetchBatch', {
                count: Math.min(fetchBatchSize, novel.pending_count || 0),
              })
            }}
          </button>
          <button
            class="btn-ghost"
            :disabled="jobActive || fetching || !pendingSelected.length"
            @click="fetchSelected"
          >
            {{ t('workspace.actions.fetchSelected', { count: pendingSelected.length }) }}
          </button>
          <button class="btn-ghost" @click="openUrlModal">
            {{ t('workspace.actions.addFromUrl') }}
          </button>
          <button
            v-if="novel.source_url"
            class="btn-ghost"
            :disabled="jobActive || syncingUrl"
            :title="t('workspace.tooltips.sync')"
            @click="syncFromSource"
          >
            {{ syncingUrl ? t('workspace.actions.checking') : t('workspace.actions.checkNewChapters') }}
          </button>

          <span class="mx-1 h-5 w-px self-center bg-ink-700" />

          <button class="btn-ghost" @click="openManual">{{ t('workspace.actions.addManual') }}</button>
          <button class="btn-ghost" :disabled="uploading" @click="pickFiles">
            {{ uploading ? t('workspace.actions.uploading') : t('workspace.actions.uploadTxt') }}
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

        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap gap-1">
            <button
              v-for="item in filters"
              :key="item.value"
              class="rounded-lg px-3 py-1.5 text-xs font-medium"
              :class="
                filter === item.value
                  ? 'bg-ink-800 text-strong'
                  : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
              "
              @click="filter = item.value"
            >
              {{ t(item.labelKey) }}
              <span class="text-slate-400">
                {{
                  item.value === 'all'
                    ? chapters.length
                    : chapters.filter((c) => c.status === item.value).length
                }}
              </span>
            </button>
          </div>

          <div class="relative w-full sm:w-64">
            <input
              v-model="searchQuery"
              type="text"
              class="input !py-1.5 pr-7 text-xs"
              :placeholder="t('workspace.table.searchPlaceholder')"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-strong"
              :title="t('workspace.table.clearSearch')"
              :aria-label="t('workspace.table.clearSearch')"
              @click="searchQuery = ''"
            >
              ✕
            </button>
          </div>
        </div>

        <div class="overflow-hidden rounded-xl border border-ink-700">
          <table class="w-full text-left text-sm">
            <thead class="bg-ink-850 text-[11px] uppercase tracking-wide text-slate-400">
              <tr>
                <th class="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 rounded border-ink-600 bg-ink-850 text-indigo-600"
                    :checked="allVisibleSelected"
                    @change="toggleAll"
                  />
                </th>
                <th
                  class="w-14 cursor-pointer select-none px-3 py-2 hover:text-strong"
                  @click="toggleSort('chapter_number')"
                >
                  #{{ sortIndicator('chapter_number') }}
                </th>
                <th
                  class="cursor-pointer select-none px-3 py-2 hover:text-strong"
                  @click="toggleSort('title')"
                >
                  {{ t('workspace.table.title') }}{{ sortIndicator('title') }}
                </th>
                <th
                  class="w-28 cursor-pointer select-none px-3 py-2 hover:text-strong"
                  @click="toggleSort('status')"
                >
                  {{ t('workspace.table.status') }}{{ sortIndicator('status') }}
                </th>
                <th
                  class="w-24 cursor-pointer select-none px-3 py-2 hover:text-strong"
                  @click="toggleSort('quality')"
                >
                  {{ t('workspace.table.quality') }}{{ sortIndicator('quality') }}
                </th>
                <th
                  class="w-20 cursor-pointer select-none px-3 py-2 text-right hover:text-strong"
                  @click="toggleSort('chars')"
                >
                  {{ t('workspace.table.chars') }}{{ sortIndicator('chars') }}
                </th>
                <th class="w-px whitespace-nowrap px-3 py-2 text-right">
                  {{ t('workspace.table.actions') }}
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-800">
              <tr v-if="!paginatedChapters.length">
                <td colspan="7" class="px-3 py-10 text-center text-sm text-slate-500">
                  {{ t('workspace.table.empty') }}
                </td>
              </tr>
              <tr
                v-for="chapter in paginatedChapters"
                :key="chapter.id"
                class="hover:bg-ink-850/60"
              >
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
                    class="text-left text-slate-200 hover:text-strong hover:underline"
                    @click="openChapter(chapter)"
                  >
                    {{ chapter.title || t('workspace.table.untitled') }}
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
                    {{ chapterStatusLabel(chapter.status) }}
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
                  <span v-else class="text-xs text-slate-500">—</span>
                </td>
                <td class="px-3 py-2 text-right font-mono text-xs text-slate-500">
                  {{ chapter.raw_content.length }}
                </td>
                <td class="whitespace-nowrap px-3 py-2 text-right">
                  <div class="inline-flex items-center justify-end gap-1">
                    <button
                      v-if="chapter.status === 'translated'"
                      class="btn-primary inline-flex items-center gap-1 !px-2 !py-1 text-[11px]"
                      :title="t('workspace.actions.read')"
                      :aria-label="t('workspace.actions.read')"
                      @click="openReader(chapter.id)"
                    >
                      <svg
                        class="h-3.5 w-3.5 shrink-0"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                      </svg>
                      <span class="hidden lg:inline">{{ t('workspace.actions.read') }}</span>
                    </button>
                    <button
                      class="btn-ghost inline-flex items-center gap-1 !px-2 !py-1 text-[11px]"
                      :title="t('workspace.actions.viewEdit')"
                      :aria-label="t('workspace.actions.viewEdit')"
                      @click="openChapter(chapter)"
                    >
                      <svg
                        class="h-3.5 w-3.5 shrink-0"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M12 20h9" />
                        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
                      </svg>
                      <span class="hidden lg:inline">{{ t('workspace.actions.viewEdit') }}</span>
                    </button>
                    <button
                      v-if="
                        chapter.status === 'translated' ||
                        chapter.status === 'error' ||
                        (chapter.translated_content || '').trim()
                      "
                      class="btn-ghost inline-flex items-center gap-1 !px-2 !py-1 text-[11px] text-amber-300 hover:text-amber-200"
                      :disabled="jobActive || clearing"
                      :title="t('workspace.tooltips.clearSingle')"
                      :aria-label="t('workspace.actions.resetTranslation')"
                      @click="clearSingleTranslation(chapter)"
                    >
                      <svg
                        class="h-3.5 w-3.5 shrink-0"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                        <path d="M3 3v5h5" />
                      </svg>
                      <span class="hidden lg:inline">{{
                        t('workspace.actions.resetTranslation')
                      }}</span>
                    </button>
                    <button
                      class="btn-danger inline-flex items-center gap-1 !px-2 !py-1 text-[11px]"
                      :title="t('common.actions.delete')"
                      :aria-label="t('common.actions.delete')"
                      @click="removeChapter(chapter)"
                    >
                      <svg
                        class="h-3.5 w-3.5 shrink-0"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M3 6h18" />
                        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                      </svg>
                      <span class="hidden lg:inline">{{ t('common.actions.delete') }}</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div
          v-if="visibleChapters.length"
          class="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400"
        >
          <div class="flex flex-wrap items-center gap-3">
            <span>
              {{ t('workspace.table.showingRange', pageRange) }}
            </span>
            <label class="flex items-center gap-1.5">
              <span class="text-slate-500">{{ t('workspace.table.perPage') }}</span>
              <select
                v-model.number="pageSize"
                class="rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
              >
                <option :value="25">25</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
                <option :value="200">200</option>
              </select>
            </label>
          </div>

          <div class="flex items-center gap-1.5">
            <button
              type="button"
              class="btn-ghost !px-2.5 !py-1 text-xs"
              :disabled="currentPage <= 1"
              @click="currentPage--"
            >
              {{ t('workspace.table.prev') }}
            </button>
            <span class="px-2 font-mono text-xs text-slate-300">
              {{ t('workspace.table.pageOf', { page: currentPage, total: totalPages }) }}
            </span>
            <button
              type="button"
              class="btn-ghost !px-2.5 !py-1 text-xs"
              :disabled="currentPage >= totalPages"
              @click="currentPage++"
            >
              {{ t('workspace.table.next') }}
            </button>
          </div>
        </div>
      </template>

      <!-- ===================== TAB: reference ===================== -->
      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <button class="btn-ghost" :disabled="jobActive" @click="startAnalyze">
            {{ t('workspace.actions.runAnalysis') }}
          </button>
          <button class="btn-primary" :disabled="savingReference" @click="saveReference">
            {{ savingReference ? t('common.actions.saving') : t('workspace.actions.saveChanges') }}
          </button>
          <button
            class="btn-ghost"
            :disabled="jobActive || applyingReference || !translatedChaptersCount"
            :title="t('workspace.tooltips.applyReference')"
            @click="applyReferenceToTranslated"
          >
            {{
              applyingReference
                ? t('workspace.actions.starting')
                : t('workspace.actions.applyToTranslated', { count: translatedChaptersCount })
            }}
          </button>
          <span v-if="referenceDirty" class="text-xs text-amber-400">
            {{ t('common.state.unsaved') }}
          </span>
          <span v-else class="text-xs text-slate-500">{{ t('workspace.state.saved') }}</span>
        </div>

        <p v-if="referenceLoading" class="text-sm text-slate-500">
          {{ t('workspace.reference.loading') }}
        </p>

        <div v-else-if="reference" class="space-y-5">
          <!-- guide -->
          <section class="card">
            <h2 class="mb-2 text-sm font-semibold text-strong">
              {{ t('workspace.reference.guideTitle') }}
            </h2>
            <p class="mb-2 text-xs text-slate-500">{{ t('workspace.reference.guideHint') }}</p>
            <textarea
              v-model="reference.translation_guide"
              class="input h-28 resize-y text-xs"
              :placeholder="t('workspace.reference.guidePlaceholder')"
              @input="markDirty"
            />
          </section>

          <!-- characters -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between gap-2">
              <h2 class="text-sm font-semibold text-strong">
                {{ t('workspace.reference.charactersTitle') }}
                <span class="ml-1 text-xs font-normal tabular-nums text-slate-500">
                  ({{ reference.characters.length }})
                </span>
              </h2>
              <button
                type="button"
                class="btn-ghost !px-2.5 !py-1 text-xs"
                @click="addCharacter"
              >
                {{ t('workspace.reference.addCharacter') }}
              </button>
            </div>

            <p v-if="!reference.characters.length" class="text-xs text-slate-500">
              {{ t('workspace.reference.charactersEmpty') }}
            </p>

            <div v-else>
              <div class="hidden gap-3 border-b border-ink-800/80 pb-1.5 text-[11px] font-medium text-slate-400 sm:grid sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1.8fr)_minmax(0,1.4fr)_auto]">
                <span>{{ t('workspace.reference.colCharacter') }}</span>
                <span>{{ t('workspace.reference.colAliases') }}</span>
                <span>{{ t('workspace.reference.colNotes') }}</span>
                <span class="text-right">{{ t('workspace.reference.colActions') }}</span>
              </div>
              <div class="divide-y divide-ink-800/80">
                <div
                  v-for="(character, index) in reference.characters"
                  :key="index"
                  class="grid items-start gap-2.5 py-2.5 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1.8fr)_minmax(0,1.4fr)_auto]"
                >
                  <div class="min-w-0">
                    <p class="truncate text-xs font-semibold text-strong">
                      {{ character.romanized_name || character.name || t('workspace.reference.unnamed') }}
                    </p>
                    <p
                      v-if="character.name && character.romanized_name"
                      class="truncate text-[11px] text-slate-400"
                    >
                      {{ t('workspace.reference.originalName', { name: character.name }) }}
                    </p>
                    <div
                      v-if="character.gender || character.age"
                      class="mt-1 flex flex-wrap gap-1 text-[10px]"
                    >
                      <span
                        v-if="character.gender"
                        class="badge bg-sky-950/60 text-sky-300"
                        :title="t('workspace.reference.gender')"
                      >
                        {{ character.gender }}
                      </span>
                      <span
                        v-if="character.age"
                        class="badge bg-amber-950/60 text-amber-300"
                        :title="t('workspace.reference.age')"
                      >
                        {{ character.age }}
                      </span>
                    </div>
                  </div>

                  <div class="min-w-0 space-y-1 text-xs">
                    <p v-if="(character.aliases ?? []).length" class="text-indigo-300">
                      <span class="text-[11px] text-slate-500">
                        {{ t('workspace.reference.aliasesLabel') }}
                      </span>
                      {{ aliasesToText(character) }}
                    </p>
                    <p v-if="character.relationships" class="text-slate-300">
                      <span class="text-[11px] text-slate-500">
                        {{ t('workspace.reference.relationsLabel') }}
                      </span>
                      {{ character.relationships }}
                    </p>
                    <p
                      v-if="!(character.aliases ?? []).length && !character.relationships"
                      class="text-slate-500"
                    >
                      —
                    </p>
                  </div>

                  <div class="min-w-0 text-xs text-slate-400">
                    {{ character.notes || '—' }}
                  </div>

                  <div class="flex shrink-0 items-center justify-end gap-1">
                    <button
                      type="button"
                      class="btn-ghost !px-2 !py-1 text-[11px]"
                      @click="openCharacterModal(index)"
                    >
                      {{ t('common.actions.edit') }}
                    </button>
                    <button
                      type="button"
                      class="btn-danger !px-2 !py-1 text-[11px]"
                      :title="t('workspace.reference.removeCharacter')"
                      :aria-label="t('workspace.reference.removeCharacter')"
                      @click="removeAt(reference.characters, index)"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- terms -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between gap-2">
              <h2 class="text-sm font-semibold text-strong">
                {{ t('workspace.reference.termsTitle') }}
                <span class="ml-1 text-xs font-normal tabular-nums text-slate-500">
                  ({{ reference.terms.length }})
                </span>
              </h2>
              <button
                type="button"
                class="btn-ghost !px-2.5 !py-1 text-xs"
                @click="addTerm"
              >
                {{ t('workspace.reference.addTerm') }}
              </button>
            </div>
            <p v-if="!reference.terms.length" class="text-xs text-slate-500">
              {{ t('workspace.reference.termsEmpty') }}
            </p>
            <div v-else>
              <div class="hidden gap-1.5 border-b border-ink-800/80 pb-1.5 text-[11px] font-medium text-slate-400 sm:grid sm:grid-cols-[minmax(0,0.85fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1fr)_76px_28px]">
                <span>{{ t('workspace.reference.colSource') }}</span>
                <span>{{ t('workspace.reference.colRomanized') }}</span>
                <span>{{ t('workspace.reference.colTarget') }}</span>
                <span>{{ t('workspace.reference.colNotes') }}</span>
                <span
                  class="whitespace-nowrap text-center"
                  :title="t('workspace.reference.latinHint')"
                >
                  {{ t('workspace.reference.colLatin') }}
                </span>
                <span />
              </div>
              <div class="divide-y divide-ink-800/70">
                <div
                  v-for="(term, index) in reference.terms"
                  :key="index"
                  class="grid grid-cols-2 items-center gap-1.5 py-1.5 sm:grid-cols-[minmax(0,0.85fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1fr)_76px_28px]"
                >
                  <input
                    v-model="term.source"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phSource')"
                    :title="t('workspace.reference.titleSourceTerm')"
                    :aria-label="t('workspace.reference.ariaSourceTerm')"
                    @input="markDirty"
                  />
                  <input
                    v-model="term.romanized"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phRomanized')"
                    :title="t('workspace.reference.titleRomanized')"
                    :aria-label="t('workspace.reference.ariaRomanized')"
                    @input="markDirty"
                  />
                  <input
                    v-model="term.target"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phTarget')"
                    :title="t('workspace.reference.titleTargetTerm')"
                    :aria-label="t('workspace.reference.ariaTarget')"
                    @input="markDirty"
                  />
                  <input
                    v-model="term.note"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phNote')"
                    :title="t('workspace.reference.titleNoteTerm')"
                    :aria-label="t('workspace.reference.ariaNote')"
                    @input="markDirty"
                  />
                  <label
                    class="flex h-[26px] w-fit cursor-pointer select-none items-center justify-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 sm:w-full sm:px-1.5"
                    :class="
                      term.keep_romanized
                        ? 'border-indigo-500/60 bg-indigo-950/50 text-indigo-200'
                        : 'border-ink-700 bg-ink-850 text-slate-400 hover:text-slate-200'
                    "
                    :title="
                      term.keep_romanized && (term.romanized || '').trim()
                        ? (term.target || '').trim()
                          ? t('workspace.reference.formatWithTarget', {
                              romanized: term.romanized.trim(),
                              target: term.target.trim(),
                            })
                          : t('workspace.reference.formatPlain', {
                              romanized: term.romanized.trim(),
                            })
                        : t('workspace.reference.latinFormatHint')
                    "
                  >
                    <input
                      v-model="term.keep_romanized"
                      type="checkbox"
                      class="h-3 w-3 accent-indigo-500 focus:outline-none"
                      :aria-label="t('workspace.reference.keepLatinAria')"
                      @change="markDirty"
                    />
                    <span>{{ t('workspace.reference.latin') }}</span>
                  </label>
                  <button
                    type="button"
                    class="btn-danger h-[26px] w-7 justify-self-end !p-0 text-[11px] sm:w-full sm:justify-self-auto"
                    :title="t('workspace.reference.removeTerm')"
                    :aria-label="t('workspace.reference.removeTerm')"
                    @click="removeAt(reference.terms, index)"
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          </section>

          <!-- locations -->
          <section class="card">
            <div class="mb-3 flex items-center justify-between gap-2">
              <h2 class="text-sm font-semibold text-strong">
                {{ t('workspace.reference.locationsTitle') }}
                <span class="ml-1 text-xs font-normal tabular-nums text-slate-500">
                  ({{ reference.locations.length }})
                </span>
              </h2>
              <button
                type="button"
                class="btn-ghost !px-2.5 !py-1 text-xs"
                @click="addLocation"
              >
                {{ t('workspace.reference.addLocation') }}
              </button>
            </div>
            <p v-if="!reference.locations.length" class="text-xs text-slate-500">
              {{ t('workspace.reference.locationsEmpty') }}
            </p>
            <div v-else>
              <div class="hidden gap-1.5 border-b border-ink-800/80 pb-1.5 text-[11px] font-medium text-slate-400 sm:grid sm:grid-cols-[minmax(0,0.85fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1fr)_76px_28px]">
                <span>{{ t('workspace.reference.colSource') }}</span>
                <span>{{ t('workspace.reference.colRomanized') }}</span>
                <span>{{ t('workspace.reference.colTarget') }}</span>
                <span>{{ t('workspace.reference.colNotes') }}</span>
                <span
                  class="whitespace-nowrap text-center"
                  :title="t('workspace.reference.latinHint')"
                >
                  {{ t('workspace.reference.colLatin') }}
                </span>
                <span />
              </div>
              <div class="divide-y divide-ink-800/70">
                <div
                  v-for="(location, index) in reference.locations"
                  :key="index"
                  class="grid grid-cols-2 items-center gap-1.5 py-1.5 sm:grid-cols-[minmax(0,0.85fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1fr)_76px_28px]"
                >
                  <input
                    v-model="location.source"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phSource')"
                    :title="t('workspace.reference.titleSourceLocation')"
                    :aria-label="t('workspace.reference.ariaSourceLocation')"
                    @input="markDirty"
                  />
                  <input
                    v-model="location.romanized"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phRomanized')"
                    :title="t('workspace.reference.titleRomanized')"
                    :aria-label="t('workspace.reference.ariaRomanized')"
                    @input="markDirty"
                  />
                  <input
                    v-model="location.target"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phTarget')"
                    :title="t('workspace.reference.titleTargetLocation')"
                    :aria-label="t('workspace.reference.ariaTarget')"
                    @input="markDirty"
                  />
                  <input
                    v-model="location.note"
                    class="input !px-2 !py-1 text-xs"
                    :placeholder="t('workspace.reference.phNote')"
                    :title="t('workspace.reference.titleNoteLocation')"
                    :aria-label="t('workspace.reference.ariaNote')"
                    @input="markDirty"
                  />
                  <label
                    class="flex h-[26px] w-fit cursor-pointer select-none items-center justify-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 sm:w-full sm:px-1.5"
                    :class="
                      location.keep_romanized
                        ? 'border-indigo-500/60 bg-indigo-950/50 text-indigo-200'
                        : 'border-ink-700 bg-ink-850 text-slate-400 hover:text-slate-200'
                    "
                    :title="
                      location.keep_romanized && (location.romanized || '').trim()
                        ? (location.target || '').trim()
                          ? t('workspace.reference.formatWithTarget', {
                              romanized: location.romanized.trim(),
                              target: location.target.trim(),
                            })
                          : t('workspace.reference.formatPlain', {
                              romanized: location.romanized.trim(),
                            })
                        : t('workspace.reference.latinFormatHint')
                    "
                  >
                    <input
                      v-model="location.keep_romanized"
                      type="checkbox"
                      class="h-3 w-3 accent-indigo-500 focus:outline-none"
                      :aria-label="t('workspace.reference.keepLatinAria')"
                      @change="markDirty"
                    />
                    <span>{{ t('workspace.reference.latin') }}</span>
                  </label>
                  <button
                    type="button"
                    class="btn-danger h-[26px] w-7 justify-self-end !p-0 text-[11px] sm:w-full sm:justify-self-auto"
                    :title="t('workspace.reference.removeLocation')"
                    :aria-label="t('workspace.reference.removeLocation')"
                    @click="removeAt(reference.locations, index)"
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          </section>

          <!-- rolling context -->
          <section class="card">
            <h2 class="mb-2 text-sm font-semibold text-strong">
              {{ t('workspace.reference.contextTitle') }}
              <span class="ml-1 text-xs font-normal text-slate-500">
                {{ t('workspace.reference.contextCount', { count: reference.chapter_context.length }) }}
              </span>
            </h2>
            <p v-if="!reference.chapter_context.length" class="text-xs text-slate-500">
              {{ t('workspace.reference.contextEmpty') }}
            </p>
            <ol v-else class="space-y-2">
              <li
                v-for="entry in reference.chapter_context"
                :key="entry.chapter_id"
                class="rounded-lg border border-ink-800 px-3 py-2 text-xs"
              >
                <span class="font-mono text-slate-500">
                  {{ t('common.job.chapter', { number: entry.chapter_number }) }}
                </span>
                <span class="ml-2 text-slate-300">{{ entry.title }}</span>
                <p class="mt-1 text-slate-400">{{ entry.summary }}</p>
              </li>
            </ol>
          </section>
        </div>
      </template>
    </template>

    <!-- ===================== character edit modal ===================== -->
    <div
      v-if="characterModal"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="characterModal = null"
    >
      <form
        class="w-full max-w-xl space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl"
        @submit.prevent="saveCharacterModal"
      >
        <div>
          <h2 class="text-sm font-semibold text-strong">
            {{
              characterModal.index >= 0
                ? t('workspace.characterModal.editTitle')
                : t('workspace.characterModal.addTitle')
            }}
          </h2>
          <p class="mt-1 text-xs text-slate-500">{{ t('workspace.characterModal.hint') }}</p>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="label" for="char-name">{{ t('workspace.characterModal.name') }}</label>
            <input
              id="char-name"
              v-model="characterModal.name"
              class="input text-xs"
              :placeholder="t('workspace.characterModal.namePlaceholder')"
            />
          </div>
          <div>
            <label class="label" for="char-romanized">
              {{ t('workspace.characterModal.romanized') }}
            </label>
            <input
              id="char-romanized"
              v-model="characterModal.romanized_name"
              class="input text-xs"
              :placeholder="t('workspace.characterModal.romanizedPlaceholder')"
            />
          </div>
          <div>
            <label class="label" for="char-gender">{{ t('workspace.characterModal.gender') }}</label>
            <input
              id="char-gender"
              v-model="characterModal.gender"
              class="input text-xs"
              :placeholder="t('workspace.characterModal.genderPlaceholder')"
            />
          </div>
          <div>
            <label class="label" for="char-age">{{ t('workspace.characterModal.age') }}</label>
            <input
              id="char-age"
              v-model="characterModal.age"
              class="input text-xs"
              :placeholder="t('workspace.characterModal.agePlaceholder')"
            />
          </div>
        </div>

        <div>
          <label class="label" for="char-aliases">{{ t('workspace.characterModal.aliases') }}</label>
          <input
            id="char-aliases"
            v-model="characterModal.aliasesText"
            class="input text-xs"
            :placeholder="t('workspace.characterModal.aliasesPlaceholder')"
          />
        </div>

        <div>
          <label class="label" for="char-relationships">
            {{ t('workspace.characterModal.relationships') }}
          </label>
          <input
            id="char-relationships"
            v-model="characterModal.relationships"
            class="input text-xs"
            :placeholder="t('workspace.characterModal.relationshipsPlaceholder')"
          />
        </div>

        <div>
          <label class="label" for="char-notes">{{ t('workspace.characterModal.notes') }}</label>
          <textarea
            id="char-notes"
            v-model="characterModal.notes"
            class="input h-20 resize-y text-xs"
            :placeholder="t('workspace.characterModal.notesPlaceholder')"
          />
        </div>

        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="characterModal = null">
            {{ t('common.actions.cancel') }}
          </button>
          <button type="submit" class="btn-primary">{{ t('workspace.characterModal.save') }}</button>
        </div>
      </form>
    </div>

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
          <h2 class="text-sm font-semibold text-strong">{{ t('workspace.urlModal.title') }}</h2>
          <p class="mt-1 text-xs text-slate-500">{{ t('workspace.urlModal.hint') }}</p>
        </div>
        <div>
          <label class="label" for="urls-input">{{ t('workspace.urlModal.label') }}</label>
          <textarea
            id="urls-input"
            v-model="urlsText"
            class="input h-40 resize-y font-mono text-xs"
            placeholder="https://contoh.com/book/123/chapter-1.htm&#10;https://contoh.com/book/123/chapter-2.htm"
          />
          <p class="mt-1 text-[11px] text-slate-500">
            {{ t('workspace.urlModal.detected', { count: urlsText.split(/\n/).filter((item) => item.trim()).length }) }}
          </p>
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="showUrlModal = false">
            {{ t('common.actions.cancel') }}
          </button>
          <button type="submit" class="btn-primary" :disabled="savingUrls || !urlsText.trim()">
            {{ savingUrls ? t('workspace.urlModal.fetching') : t('workspace.urlModal.submit') }}
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
        <h2 class="text-sm font-semibold text-strong">{{ t('workspace.manualModal.title') }}</h2>
        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="label" for="manual-no">{{ t('workspace.manualModal.number') }}</label>
            <input
              id="manual-no"
              v-model.number="manualForm.chapter_number"
              class="input"
              type="number"
              step="1"
              :placeholder="t('workspace.manualModal.numberPlaceholder')"
            />
          </div>
          <div class="col-span-2">
            <label class="label" for="manual-chapter-title">
              {{ t('workspace.manualModal.chapterTitle') }}
            </label>
            <input
              id="manual-chapter-title"
              v-model="manualForm.title"
              class="input"
              type="text"
              :placeholder="t('common.state.optional')"
            />
          </div>
        </div>
        <div>
          <label class="label" for="manual-content">{{ t('workspace.manualModal.content') }}</label>
          <textarea
            id="manual-content"
            v-model="manualForm.raw_content"
            class="input h-64 resize-y font-mono text-xs"
            :placeholder="t('workspace.manualModal.contentPlaceholder')"
          />
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="showManual = false">
            {{ t('common.actions.cancel') }}
          </button>
          <button
            type="submit"
            class="btn-primary"
            :disabled="savingManual || !manualForm.raw_content.trim()"
          >
            {{ savingManual ? t('common.actions.saving') : t('workspace.manualModal.save') }}
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
          <h2 class="text-sm font-semibold text-strong">
            {{ t('common.job.chapter', { number: editing.chapter_number }) }}
            <span class="badge ml-2" :class="statusStyles[editing.status]">
              {{ chapterStatusLabel(editing.status) }}
            </span>
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
              :class="editPane === pane
                ? 'bg-ink-800 text-strong'
                : 'text-slate-400 hover:text-slate-200'"
              @click="editPane = pane"
            >
              {{
                pane === 'both'
                  ? t('workspace.chapterModal.sideBySide')
                  : pane === 'raw'
                    ? t('common.status.raw')
                    : t('common.status.translated')
              }}
            </button>
            <button type="button" class="ml-2 text-slate-500 hover:text-slate-200" @click="editing = null">
              ✕
            </button>
          </div>
        </div>

        <div>
          <label class="label" for="edit-title">{{ t('workspace.chapterModal.title') }}</label>
          <input id="edit-title" v-model="editForm.title" class="input" type="text" />
        </div>

        <div class="grid gap-3" :class="editPane === 'both' ? 'lg:grid-cols-2' : 'grid-cols-1'">
          <div v-if="editPane !== 'translated'">
            <label class="label" for="edit-raw">
              {{ t('workspace.chapterModal.rawLabel', { count: editForm.raw_content.length }) }}
            </label>
            <textarea
              id="edit-raw"
              v-model="editForm.raw_content"
              class="input h-80 resize-y font-mono text-xs"
              :placeholder="t('workspace.chapterModal.rawPlaceholder')"
            />
          </div>
          <div v-if="editPane !== 'raw'">
            <label class="label" for="edit-translated">
              {{
                t('workspace.chapterModal.translatedLabel', {
                  count: editForm.translated_content.length,
                })
              }}
            </label>
            <textarea
              id="edit-translated"
              v-model="editForm.translated_content"
              class="input h-80 resize-y font-mono text-xs"
              :placeholder="t('workspace.chapterModal.translatedPlaceholder')"
            />
          </div>
        </div>

        <div class="flex items-center justify-end gap-2">
          <button type="button" class="btn-ghost" @click="editing = null">
            {{ t('common.actions.cancel') }}
          </button>
          <button type="submit" class="btn-primary" :disabled="savingEdit">
            {{ savingEdit ? t('common.actions.saving') : t('common.actions.save') }}
          </button>
        </div>
      </form>
    </div>

    <!-- Modal: warning that earlier chapters are not translated yet -->
    <div
      v-if="contextWarning"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      @click.self="contextWarning = null"
    >
      <div class="card w-full max-w-lg space-y-4 border-amber-800/70">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-semibold text-amber-300">
              {{ t('workspace.contextWarning.title') }}
            </h2>
            <p class="mt-1 text-xs text-slate-400">
              {{ t('workspace.contextWarning.bodyStart') }}
              <strong>{{ t('common.job.chapter', { number: contextWarning.minSelectedNo }) }}</strong>{{ t('workspace.contextWarning.bodyMiddle') }}
              <strong>{{ t('workspace.contextWarning.earlierCount', { count: contextWarning.earlierCount }) }}</strong>
              {{ t('workspace.contextWarning.bodyAfterCount') }}
              <code class="text-slate-300">translated</code>
              {{ t('workspace.contextWarning.bodyEnd', { sample: contextWarning.earlierSample }) }}
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
          {{ t('workspace.contextWarning.warnStart') }}
          <strong>{{ t('workspace.contextWarning.warnStrong') }}</strong>{{ t('workspace.contextWarning.warnEnd') }}
          <span v-if="contextWarning.pendingCount" class="mt-1 block text-amber-300/90">
            {{ t('workspace.contextWarning.noteStart', { count: contextWarning.pendingCount }) }}
            <code>pending_fetch</code>
            {{ t('workspace.contextWarning.noteEnd') }}
          </span>
        </div>

        <div class="flex flex-wrap justify-end gap-2">
          <button type="button" class="btn-ghost text-xs" @click="contextWarning = null">
            {{ t('common.actions.cancel') }}
          </button>
          <button
            v-if="contextWarning.earlierReadyIds.length"
            type="button"
            class="btn-primary text-xs"
            @click="confirmTranslateEarlier"
          >
            {{
              t('workspace.contextWarning.translateEarlier', {
                count: contextWarning.earlierReadyIds.length + contextWarning.selectedIds.length,
              })
            }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-amber-700/70 bg-amber-950/50 px-3 py-1.5 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-900/60"
            @click="confirmTranslateAnyway"
          >
            {{ t('workspace.contextWarning.translateAnyway') }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===================== cover prompt generator modal ===================== -->
    <div
      v-if="showCoverPromptModal"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="showCoverPromptModal = false"
    >
      <div class="w-full max-w-3xl space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold text-strong">
              {{ t('workspace.coverPrompt.title') }}
            </h2>
            <p class="mt-1 text-xs text-slate-500">
              {{ t('workspace.coverPrompt.subtitle') }}
            </p>
          </div>
          <button type="button" class="btn-ghost !px-2.5 !py-1 text-xs" @click="showCoverPromptModal = false">
            ✕
          </button>
        </div>

        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="runGenerateCoverPrompt">
          <div>
            <label class="label" for="cover-style">{{ t('workspace.coverPrompt.style') }}</label>
            <select id="cover-style" v-model="coverPromptForm.style" class="input text-xs">
              <option value="webnovel_cover">{{ t('workspace.coverPrompt.styles.webnovel_cover') }}</option>
              <option value="anime_illustration">{{ t('workspace.coverPrompt.styles.anime_illustration') }}</option>
              <option value="xianxia_ink">{{ t('workspace.coverPrompt.styles.xianxia_ink') }}</option>
              <option value="dark_fantasy">{{ t('workspace.coverPrompt.styles.dark_fantasy') }}</option>
              <option value="semi_realistic">{{ t('workspace.coverPrompt.styles.semi_realistic') }}</option>
            </select>
          </div>
          <div>
            <label class="label" for="cover-mood">{{ t('workspace.coverPrompt.mood') }}</label>
            <input
              id="cover-mood"
              v-model="coverPromptForm.mood"
              class="input text-xs"
              :placeholder="t('workspace.coverPrompt.moodPlaceholder')"
            />
          </div>
          <div class="sm:col-span-2">
            <label class="label" for="cover-extra">{{ t('workspace.coverPrompt.extraNotes') }}</label>
            <input
              id="cover-extra"
              v-model="coverPromptForm.extra_notes"
              class="input text-xs"
              :placeholder="t('workspace.coverPrompt.extraPlaceholder')"
            />
          </div>
          <div class="flex justify-end sm:col-span-2">
            <button type="submit" class="btn-primary text-xs" :disabled="generatingCoverPrompt">
              {{
                generatingCoverPrompt
                  ? t('workspace.coverPrompt.generating')
                  : t('workspace.coverPrompt.generate')
              }}
            </button>
          </div>
        </form>

        <div v-if="coverPromptResult" class="space-y-4 border-t border-ink-800 pt-4">
          <!-- Format 1: Text + Negative Prompt -->
          <div class="space-y-2 rounded-lg border border-ink-800 bg-ink-950/50 p-3">
            <h3 class="text-xs font-semibold text-strong">
              {{ t('workspace.coverPrompt.textFormatTitle') }}
            </h3>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="text-[11px] font-medium text-slate-400">
                  {{ t('workspace.coverPrompt.positiveLabel') }}
                </span>
                <button
                  type="button"
                  class="btn-ghost !px-2 !py-0.5 text-[11px]"
                  @click="copyPromptText('positive', coverPromptResult.positive_prompt)"
                >
                  {{
                    copiedPromptKey === 'positive'
                      ? t('workspace.coverPrompt.copied')
                      : t('workspace.coverPrompt.copy')
                  }}
                </button>
              </div>
              <textarea
                :value="coverPromptResult.positive_prompt"
                readonly
                class="input h-28 resize-y text-xs leading-relaxed"
              />
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="text-[11px] font-medium text-slate-400">
                  {{ t('workspace.coverPrompt.negativeLabel') }}
                </span>
                <button
                  type="button"
                  class="btn-ghost !px-2 !py-0.5 text-[11px]"
                  @click="copyPromptText('negative', coverPromptResult.negative_prompt)"
                >
                  {{
                    copiedPromptKey === 'negative'
                      ? t('workspace.coverPrompt.copied')
                      : t('workspace.coverPrompt.copy')
                  }}
                </button>
              </div>
              <textarea
                :value="coverPromptResult.negative_prompt"
                readonly
                class="input h-16 resize-y text-xs leading-relaxed"
              />
            </div>
          </div>

          <!-- Format 2: Structured JSON Prompt -->
          <div class="space-y-2 rounded-lg border border-ink-800 bg-ink-950/50 p-3">
            <div class="flex items-center justify-between">
              <h3 class="text-xs font-semibold text-strong">
                {{ t('workspace.coverPrompt.jsonFormatTitle') }}
              </h3>
              <button
                type="button"
                class="btn-ghost !px-2 !py-0.5 text-[11px]"
                @click="
                  copyPromptText('json', JSON.stringify(coverPromptResult.json_prompt, null, 2))
                "
              >
                {{
                  copiedPromptKey === 'json'
                    ? t('workspace.coverPrompt.copied')
                    : t('workspace.coverPrompt.copy')
                }}
              </button>
            </div>
            <pre class="max-h-64 overflow-auto rounded-lg border border-ink-800 bg-ink-900 p-3 font-mono text-[11px] text-slate-300">{{ JSON.stringify(coverPromptResult.json_prompt, null, 2) }}</pre>
          </div>
        </div>

        <div class="flex justify-end">
          <button type="button" class="btn-ghost text-xs" @click="showCoverPromptModal = false">
            {{ t('workspace.coverPrompt.close') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
