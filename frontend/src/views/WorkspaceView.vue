<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'

const route = useRoute()
const router = useRouter()

const novelId = computed(() => Number(route.params.id))

const novel = ref(null)
const chapters = ref([])
const loading = ref(true)
const error = ref('')
const notice = ref(null)

const filter = ref('all')
const selected = ref([])
const fetching = ref(false)

const showManual = ref(false)
const manualForm = reactive({ chapter_number: null, title: '', raw_content: '' })
const savingManual = ref(false)

const editing = ref(null)
const editForm = reactive({ title: '', raw_content: '' })
const savingEdit = ref(false)

const uploading = ref(false)
const fileInput = ref(null)

const filters = [
  { value: 'all', label: 'Semua' },
  { value: 'pending_fetch', label: 'Pending Fetch' },
  { value: 'raw', label: 'Raw' },
  { value: 'translated', label: 'Translated' },
]

const statusStyles = {
  pending_fetch: 'bg-amber-950/60 text-amber-400',
  raw: 'bg-emerald-950/60 text-emerald-400',
  translating: 'bg-sky-950/60 text-sky-400',
  translated: 'bg-indigo-950/60 text-indigo-300',
  error: 'bg-rose-950/60 text-rose-400',
}

const visibleChapters = computed(() =>
  filter.value === 'all'
    ? chapters.value
    : chapters.value.filter((chapter) => chapter.status === filter.value),
)

const pendingSelected = computed(() =>
  chapters.value.filter(
    (chapter) => selected.value.includes(chapter.id) && chapter.status === 'pending_fetch',
  ),
)

const allVisibleSelected = computed(
  () =>
    visibleChapters.value.length > 0 &&
    visibleChapters.value.every((chapter) => selected.value.includes(chapter.id)),
)

function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => {
    if (notice.value?.text === text) notice.value = null
  }, 7000)
}

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
    const merged = new Set([...selected.value, ...visibleChapters.value.map((c) => c.id)])
    selected.value = [...merged]
  }
}

async function fetchSelected() {
  const ids = pendingSelected.value.map((chapter) => chapter.id)
  if (!ids.length) return
  fetching.value = true
  try {
    const result = await novelsApi.fetchChapters(novelId.value, ids)
    await load()
    if (result.failed) {
      flash(
        'error',
        `${result.fetched} bab berhasil, ${result.failed} gagal. ${result.errors[0]?.error ?? ''}`,
      )
    } else {
      flash('success', `${result.fetched} bab berhasil di-fetch.`)
    }
    selected.value = []
  } catch (err) {
    flash('error', `Gagal fetch: ${err.message}`)
  } finally {
    fetching.value = false
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
}

async function saveChapter() {
  if (!editing.value) return
  savingEdit.value = true
  try {
    await novelsApi.updateChapter(editing.value.id, {
      title: editForm.title,
      raw_content: editForm.raw_content,
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

watch(novelId, load)
onMounted(load)
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
      <header class="mb-6">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 class="text-2xl font-semibold tracking-tight text-white">{{ novel.title }}</h1>
            <p class="mt-1 text-sm text-slate-400">
              {{ novel.author || 'Penulis tidak diketahui' }} ·
              <span class="font-mono text-xs">{{ novel.source_lang }} → {{ novel.target_lang }}</span>
            </p>
            <p v-if="novel.source_url" class="mt-1 truncate font-mono text-[11px] text-slate-500">
              {{ novel.source_url }}
            </p>
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

        <p v-if="novel.synopsis" class="mt-3 max-w-3xl text-sm text-slate-400">
          {{ novel.synopsis }}
        </p>
      </header>

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

      <!-- actions -->
      <div class="mb-5 flex flex-wrap items-center gap-2">
        <button
          class="btn-primary"
          :disabled="fetching || !pendingSelected.length"
          @click="fetchSelected"
        >
          {{ fetching ? 'Mengambil…' : `Fetch Raw Terpilih (${pendingSelected.length})` }}
        </button>
        <button class="btn-ghost" @click="openManual">+ Tambah Bab Manual</button>
        <button class="btn-ghost" :disabled="uploading" @click="pickFiles">
          {{ uploading ? 'Mengunggah…' : 'Upload .txt (Batch)' }}
        </button>
        <input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          multiple
          class="hidden"
          @change="onFilesChosen"
        />
        <span class="ml-auto text-xs text-slate-500">
          Translate tersedia di Phase 3
        </span>
        <button class="btn-ghost !px-2.5 !py-1 text-xs" disabled title="Phase 3">
          Translate Selected
        </button>
      </div>

      <!-- filters -->
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

      <!-- chapter table -->
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
              <th class="w-14 px-3 py-2">#</th>
              <th class="px-3 py-2">Judul</th>
              <th class="w-32 px-3 py-2">Status</th>
              <th class="w-20 px-3 py-2 text-right">Chars</th>
              <th class="w-40 px-3 py-2 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-800">
            <tr v-if="!visibleChapters.length">
              <td colspan="6" class="px-3 py-10 text-center text-sm text-slate-500">
                Tidak ada bab pada filter ini.
              </td>
            </tr>
            <tr
              v-for="chapter in visibleChapters"
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
                  class="text-left text-slate-200 hover:text-white hover:underline"
                  @click="openChapter(chapter)"
                >
                  {{ chapter.title || '(tanpa judul)' }}
                </button>
              </td>
              <td class="px-3 py-2">
                <span class="badge" :class="statusStyles[chapter.status] ?? 'bg-ink-800 text-slate-400'">
                  {{ chapter.status }}
                </span>
              </td>
              <td class="px-3 py-2 text-right font-mono text-xs text-slate-500">
                {{ chapter.raw_content.length }}
              </td>
              <td class="px-3 py-2 text-right">
                <button class="btn-ghost !px-2 !py-0.5 text-[11px]" @click="openChapter(chapter)">
                  Lihat/Edit
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

    <!-- ===================== chapter edit modal ===================== -->
    <div
      v-if="editing"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="editing = null"
    >
      <form
        class="w-full max-w-3xl space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-5 shadow-2xl"
        @submit.prevent="saveChapter"
      >
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-white">
            Bab {{ editing.chapter_number }}
            <span class="ml-2 badge" :class="statusStyles[editing.status]">
              {{ editing.status }}
            </span>
          </h2>
          <button type="button" class="text-slate-500 hover:text-slate-200" @click="editing = null">
            ✕
          </button>
        </div>
        <div>
          <label class="label" for="edit-title">Judul</label>
          <input id="edit-title" v-model="editForm.title" class="input" type="text" />
        </div>
        <div>
          <label class="label" for="edit-content">Isi raw</label>
          <textarea
            id="edit-content"
            v-model="editForm.raw_content"
            class="input h-80 resize-y font-mono text-xs"
            placeholder="Belum ada isi — jalankan Fetch Raw untuk bab ini."
          />
        </div>
        <div class="flex items-center justify-between">
          <span class="text-[11px] text-slate-500">
            {{ editForm.raw_content.length }} karakter
          </span>
          <div class="flex gap-2">
            <button type="button" class="btn-ghost" @click="editing = null">Batal</button>
            <button type="submit" class="btn-primary" :disabled="savingEdit">
              {{ savingEdit ? 'Menyimpan…' : 'Simpan' }}
            </button>
          </div>
        </div>
      </form>
    </div>
  </div>
</template>
