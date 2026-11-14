<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'
import { scrapersApi } from '@/api/scrapers'

const router = useRouter()

const novels = ref([])
const loading = ref(true)
const error = ref('')
const notice = ref(null)

const showModal = ref(false)
const tab = ref('url')

const urlForm = reactive({ url: '', target_lang: 'id' })
const preview = ref(null)
const previewing = ref(false)
const savingUrl = ref(false)

const manualForm = reactive({
  title: '',
  author: '',
  source_lang: 'zh',
  target_lang: 'id',
  synopsis: '',
})
const savingManual = ref(false)

const deletingId = ref(null)

const sourceLangs = [
  { value: 'zh', label: 'Chinese (zh)' },
  { value: 'ja', label: 'Japanese (ja)' },
  { value: 'ko', label: 'Korean (ko)' },
  { value: 'en', label: 'English (en)' },
]
const targetLangs = [
  { value: 'id', label: 'Indonesian (id)' },
  { value: 'en', label: 'English (en)' },
]

const canSaveUrl = computed(() => preview.value?.kind === 'novel' && !savingUrl.value)

function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => {
    if (notice.value?.text === text) notice.value = null
  }, 6000)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    novels.value = await novelsApi.list()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function openModal() {
  showModal.value = true
  tab.value = 'url'
  preview.value = null
  urlForm.url = ''
  Object.assign(manualForm, {
    title: '',
    author: '',
    source_lang: 'zh',
    target_lang: 'id',
    synopsis: '',
  })
}

function closeModal() {
  showModal.value = false
  preview.value = null
}

async function doPreview() {
  if (!urlForm.url.trim()) return
  previewing.value = true
  preview.value = null
  try {
    preview.value = await scrapersApi.preview(urlForm.url.trim())
  } catch (err) {
    preview.value = { ok: false, error: err.message }
  } finally {
    previewing.value = false
  }
}

async function saveFromUrl() {
  savingUrl.value = true
  try {
    const novel = await novelsApi.createFromUrl({
      url: urlForm.url.trim(),
      target_lang: urlForm.target_lang,
    })
    closeModal()
    await load()
    flash(
      'success',
      `"${novel.title}" ditambahkan dengan ${novel.chapter_count} bab (status pending fetch).`,
    )
  } catch (err) {
    flash('error', `Gagal menambah novel: ${err.message}`)
  } finally {
    savingUrl.value = false
  }
}

async function saveManual() {
  if (!manualForm.title.trim()) return
  savingManual.value = true
  try {
    const novel = await novelsApi.create({ ...manualForm, title: manualForm.title.trim() })
    closeModal()
    await load()
    flash('success', `"${novel.title}" ditambahkan.`)
  } catch (err) {
    flash('error', `Gagal menambah novel: ${err.message}`)
  } finally {
    savingManual.value = false
  }
}

async function remove(novel) {
  if (!window.confirm(`Hapus "${novel.title}" beserta ${novel.chapter_count} bab?`)) return
  deletingId.value = novel.id
  try {
    await novelsApi.remove(novel.id)
    await load()
    flash('success', `"${novel.title}" dihapus.`)
  } catch (err) {
    flash('error', `Gagal menghapus: ${err.message}`)
  } finally {
    deletingId.value = null
  }
}

function openWorkspace(novel) {
  router.push(`/novels/${novel.id}`)
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <header class="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-white">Library</h1>
        <p class="mt-1 text-sm text-slate-400">
          Novel dari scraper maupun input manual.
          <span class="text-slate-500">({{ novels.length }} novel)</span>
        </p>
      </div>
      <button class="btn-primary" @click="openModal">+ Tambah Novel</button>
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

    <div
      v-if="error"
      class="mb-5 rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300"
    >
      Gagal memuat library: {{ error }}
      <button class="ml-2 underline" @click="load">coba lagi</button>
    </div>

    <p v-if="loading" class="text-sm text-slate-500">Memuat…</p>

    <div
      v-else-if="!novels.length"
      class="rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-6 py-16 text-center"
    >
      <p class="text-sm font-medium text-slate-300">Belum ada novel.</p>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-500">
        Tambah dari URL situs yang didukung (69shuba, syosetu, bq730, 52shuku) atau input manual
        dengan paste teks / upload <code class="rounded bg-ink-800 px-1 py-0.5 text-xs">.txt</code>.
      </p>
      <button class="btn-primary mt-6" @click="openModal">+ Tambah Novel</button>
    </div>

    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="novel in novels"
        :key="novel.id"
        class="card flex flex-col gap-3 transition-colors hover:border-ink-600"
      >
        <div class="flex items-start justify-between gap-2">
          <h2 class="text-sm font-semibold leading-snug text-slate-100">{{ novel.title }}</h2>
          <span
            class="badge shrink-0"
            :class="
              novel.source_type === 'scraper'
                ? 'bg-indigo-950/70 text-indigo-300'
                : 'bg-ink-800 text-slate-400'
            "
          >
            {{ novel.source_type === 'scraper' ? 'Scraper' : 'Manual' }}
          </span>
        </div>

        <p class="text-xs text-slate-400">
          {{ novel.author || 'Penulis tidak diketahui' }}
        </p>

        <p class="font-mono text-[11px] text-slate-500">
          {{ novel.source_lang }} → {{ novel.target_lang }}
          <span v-if="novel.scraper_name"> · {{ novel.scraper_name }}</span>
        </p>

        <div class="flex flex-wrap gap-1.5 text-[11px]">
          <span class="badge bg-ink-800 text-slate-300">{{ novel.chapter_count }} bab</span>
          <span class="badge bg-emerald-950/50 text-emerald-400">{{ novel.raw_count }} raw</span>
          <span class="badge bg-sky-950/50 text-sky-400">
            {{ novel.translated_count }} translated
          </span>
          <span v-if="novel.pending_count" class="badge bg-amber-950/50 text-amber-400">
            {{ novel.pending_count }} pending
          </span>
        </div>

        <div class="mt-auto flex items-center gap-2 pt-1">
          <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="openWorkspace(novel)">
            Buka workspace →
          </button>
          <button
            class="btn-danger ml-auto !px-2.5 !py-1 text-xs"
            :disabled="deletingId === novel.id"
            @click="remove(novel)"
          >
            Hapus
          </button>
        </div>
      </article>
    </div>

    <!-- ============================ MODAL ============================ -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10"
      @click.self="closeModal"
    >
      <div class="w-full max-w-2xl rounded-xl border border-ink-700 bg-ink-900 shadow-2xl">
        <div class="flex items-center justify-between border-b border-ink-800 px-5 py-3">
          <h2 class="text-sm font-semibold text-white">Tambah Novel</h2>
          <button class="text-slate-500 hover:text-slate-200" @click="closeModal">✕</button>
        </div>

        <div class="flex gap-1 border-b border-ink-800 px-5 pt-3">
          <button
            class="rounded-t-lg px-3 py-2 text-sm font-medium"
            :class="
              tab === 'url'
                ? 'border-b-2 border-indigo-500 text-white'
                : 'text-slate-400 hover:text-slate-200'
            "
            @click="tab = 'url'"
          >
            Dari URL (Scraper)
          </button>
          <button
            class="rounded-t-lg px-3 py-2 text-sm font-medium"
            :class="
              tab === 'manual'
                ? 'border-b-2 border-indigo-500 text-white'
                : 'text-slate-400 hover:text-slate-200'
            "
            @click="tab = 'manual'"
          >
            Input Manual
          </button>
        </div>

        <!-- tab: URL -->
        <form v-if="tab === 'url'" class="space-y-4 p-5" @submit.prevent="saveFromUrl">
          <div>
            <label class="label" for="novel-url">URL halaman novel</label>
            <div class="flex gap-2">
              <input
                id="novel-url"
                v-model="urlForm.url"
                class="input font-mono text-xs"
                type="url"
                placeholder="https://www.69shuba.com/book/12345.htm"
              />
              <button
                type="button"
                class="btn-ghost shrink-0"
                :disabled="previewing || !urlForm.url.trim()"
                @click="doPreview"
              >
                {{ previewing ? 'Mengambil…' : 'Preview' }}
              </button>
            </div>
            <p class="mt-1 text-[11px] text-slate-500">
              Modul scraper dipilih otomatis dari domain. Domain tak dikenal memakai scraper
              generik.
            </p>
          </div>

          <div>
            <label class="label" for="url-target">Bahasa target</label>
            <select id="url-target" v-model="urlForm.target_lang" class="input">
              <option v-for="lang in targetLangs" :key="lang.value" :value="lang.value">
                {{ lang.label }}
              </option>
            </select>
          </div>

          <div
            v-if="preview"
            class="rounded-lg border px-4 py-3 text-sm"
            :class="
              preview.ok
                ? 'border-ink-700 bg-ink-850'
                : 'border-rose-900/60 bg-rose-950/30 text-rose-300'
            "
          >
            <template v-if="preview.ok">
              <div class="flex flex-wrap items-center gap-2">
                <span class="badge bg-indigo-950/70 text-indigo-300">{{ preview.scraper }}</span>
                <span v-if="!preview.dedicated" class="badge bg-amber-950/60 text-amber-400">
                  generik
                </span>
                <span class="badge bg-ink-800 text-slate-400">{{ preview.kind }}</span>
              </div>
              <p class="mt-2 font-medium text-slate-100">{{ preview.title }}</p>
              <p v-if="preview.author" class="text-xs text-slate-400">{{ preview.author }}</p>
              <p class="mt-1 text-xs text-slate-400">
                <template v-if="preview.kind === 'novel'">
                  {{ preview.chapter_count }} bab terdeteksi
                </template>
                <template v-else>
                  Halaman ini terdeteksi sebagai satu bab ({{ preview.content_length }} karakter),
                  bukan daftar isi.
                </template>
              </p>
              <ul
                v-if="preview.chapters?.length"
                class="mt-2 max-h-32 space-y-0.5 overflow-y-auto text-[11px] text-slate-500"
              >
                <li v-for="chapter in preview.chapters" :key="chapter.url">
                  {{ chapter.chapter_number }}. {{ chapter.title }}
                </li>
              </ul>
            </template>
            <template v-else>{{ preview.error }}</template>
          </div>

          <div class="flex justify-end gap-2 pt-1">
            <button type="button" class="btn-ghost" @click="closeModal">Batal</button>
            <button type="submit" class="btn-primary" :disabled="!canSaveUrl">
              {{ savingUrl ? 'Menyimpan…' : 'Simpan Novel' }}
            </button>
          </div>
        </form>

        <!-- tab: manual -->
        <form v-else class="space-y-4 p-5" @submit.prevent="saveManual">
          <div>
            <label class="label" for="manual-title">Judul</label>
            <input
              id="manual-title"
              v-model="manualForm.title"
              class="input"
              type="text"
              placeholder="Judul novel"
            />
          </div>
          <div>
            <label class="label" for="manual-author">Penulis</label>
            <input
              id="manual-author"
              v-model="manualForm.author"
              class="input"
              type="text"
              placeholder="opsional"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="label" for="manual-source">Bahasa sumber</label>
              <select id="manual-source" v-model="manualForm.source_lang" class="input">
                <option v-for="lang in sourceLangs" :key="lang.value" :value="lang.value">
                  {{ lang.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="label" for="manual-target">Bahasa target</label>
              <select id="manual-target" v-model="manualForm.target_lang" class="input">
                <option v-for="lang in targetLangs" :key="lang.value" :value="lang.value">
                  {{ lang.label }}
                </option>
              </select>
            </div>
          </div>
          <div>
            <label class="label" for="manual-synopsis">Sinopsis</label>
            <textarea
              id="manual-synopsis"
              v-model="manualForm.synopsis"
              class="input h-24 resize-y"
              placeholder="opsional"
            />
          </div>
          <div class="flex justify-end gap-2 pt-1">
            <button type="button" class="btn-ghost" @click="closeModal">Batal</button>
            <button
              type="submit"
              class="btn-primary"
              :disabled="savingManual || !manualForm.title.trim()"
            >
              {{ savingManual ? 'Menyimpan…' : 'Simpan Novel' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
