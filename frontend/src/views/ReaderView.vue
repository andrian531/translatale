<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'
import { readerApi } from '@/api/reader'

const route = useRoute()
const router = useRouter()

const novelId = computed(() => Number(route.params.id))

const novel = ref(null)
const chapters = ref([])
const chapter = ref(null)
const loading = ref(true)
const chapterLoading = ref(false)
const error = ref('')

const scrollEl = ref(null)
const scrollPercent = ref(0)
const savedAt = ref('')

// -- preferences (persisted in localStorage) ----------------------------
const THEME_KEY = 'translatale:reader:theme'
const FONT_KEY = 'translatale:reader:font'
const WIDTH_KEY = 'translatale:reader:width'
const SIDEBAR_KEY = 'translatale:reader:sidebar'

const theme = ref(localStorage.getItem(THEME_KEY) || 'dark')
const fontSize = ref(Number(localStorage.getItem(FONT_KEY)) || 18)
const width = ref(localStorage.getItem(WIDTH_KEY) || 'normal')
const sidebarOpen = ref(localStorage.getItem(SIDEBAR_KEY) !== 'closed')
const showRaw = ref(false)

const themes = {
  light: {
    shell: 'bg-[#faf9f7] text-[#1f2328]',
    panel: 'bg-[#faf9f7]/95 border-[#e3ddd2]',
    muted: 'text-[#6b6459]',
    soft: 'bg-[#f0ece4]',
    accent: 'text-[#8a5a2b]',
  },
  sepia: {
    shell: 'bg-[#f4ecd8] text-[#3b2f1e]',
    panel: 'bg-[#f4ecd8]/95 border-[#ddcda8]',
    muted: 'text-[#7a6a4f]',
    soft: 'bg-[#ece0c4]',
    accent: 'text-[#8a5a2b]',
  },
  dark: {
    shell: 'bg-ink-950 text-slate-200',
    panel: 'bg-ink-900/95 border-ink-700',
    muted: 'text-slate-500',
    soft: 'bg-ink-850',
    accent: 'text-indigo-300',
  },
}

const themeClass = computed(() => themes[theme.value] ?? themes.dark)

const widthClass = computed(
  () =>
    ({
      narrow: 'max-w-2xl',
      normal: 'max-w-3xl',
      wide: 'max-w-5xl',
    })[width.value] ?? 'max-w-3xl',
)

const currentIndex = computed(() =>
  chapters.value.findIndex((item) => item.id === chapter.value?.id),
)
const prevChapter = computed(() =>
  currentIndex.value > 0 ? chapters.value[currentIndex.value - 1] : null,
)
const nextChapter = computed(() =>
  currentIndex.value >= 0 && currentIndex.value < chapters.value.length - 1
    ? chapters.value[currentIndex.value + 1]
    : null,
)

const paragraphs = computed(() => {
  const text = chapter.value?.translated_content || ''
  return text
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
})

const rawParagraphs = computed(() => {
  const text = chapter.value?.raw_content || ''
  return text
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
})

const hasTranslation = computed(() => Boolean((chapter.value?.translated_content || '').trim()))

// ----------------------------------------------------------------------
// Preferences
// ----------------------------------------------------------------------
function setTheme(value) {
  theme.value = value
  localStorage.setItem(THEME_KEY, value)
}

function changeFont(delta) {
  const next = Math.min(30, Math.max(14, fontSize.value + delta))
  fontSize.value = next
  localStorage.setItem(FONT_KEY, String(next))
}

function setWidth(value) {
  width.value = value
  localStorage.setItem(WIDTH_KEY, value)
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
  localStorage.setItem(SIDEBAR_KEY, sidebarOpen.value ? 'open' : 'closed')
}

// ----------------------------------------------------------------------
// Data
// ----------------------------------------------------------------------
async function loadNovel() {
  loading.value = true
  error.value = ''
  try {
    const [novelData, chapterData] = await Promise.all([
      novelsApi.get(novelId.value),
      novelsApi.listChapters(novelId.value),
    ])
    novel.value = novelData
    chapters.value = chapterData
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function resolveChapterId() {
  const fromRoute = Number(route.params.chapterId)
  if (fromRoute && chapters.value.some((item) => item.id === fromRoute)) return fromRoute

  const lastRead = novel.value?.last_read_chapter_id
  if (lastRead && chapters.value.some((item) => item.id === lastRead)) return lastRead

  const firstTranslated = chapters.value.find((item) => item.status === 'translated')
  if (firstTranslated) return firstTranslated.id

  return chapters.value[0]?.id ?? null
}

async function openChapter(chapterId, { replace = false } = {}) {
  if (!chapterId) return
  chapterLoading.value = true
  try {
    const data = await novelsApi.getChapter(chapterId)
    chapter.value = data
    showRaw.value = false
    scrollPercent.value = 0
    await nextTick()
    if (scrollEl.value) scrollEl.value.scrollTop = 0
    await saveProgress(0)
    if (replace) {
      router.replace(`/novels/${novelId.value}/read/${chapterId}`)
    }
  } catch (err) {
    error.value = err.message
  } finally {
    chapterLoading.value = false
  }
}

async function saveProgress(percent) {
  if (!chapter.value) return
  const value = Math.max(0, Math.min(100, Number(percent) || 0))
  localStorage.setItem(
    `translatale:progress:${novelId.value}`,
    JSON.stringify({ chapterId: chapter.value.id, percent: value }),
  )
  try {
    await readerApi.saveProgress(novelId.value, {
      chapter_id: chapter.value.id,
      scroll_percent: value,
    })
    savedAt.value = new Date().toLocaleTimeString('id-ID')
  } catch {
    /* progress is best-effort; never block reading */
  }
}

let saveTimer = null
function onScroll() {
  const el = scrollEl.value
  if (!el) return
  const max = el.scrollHeight - el.clientHeight
  scrollPercent.value = max > 0 ? Math.min(100, Math.round((el.scrollTop / max) * 100)) : 100
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => saveProgress(scrollPercent.value), 1200)
}

// ----------------------------------------------------------------------
// Navigation
// ----------------------------------------------------------------------
function goTo(target) {
  if (!target) return
  router.push(`/novels/${novelId.value}/read/${target.id}`)
}

function onKeydown(event) {
  const tag = (event.target?.tagName || '').toLowerCase()
  if (['input', 'textarea', 'select'].includes(tag) || event.target?.isContentEditable) return
  if (event.key === 'ArrowLeft' && prevChapter.value) {
    event.preventDefault()
    goTo(prevChapter.value)
  } else if (event.key === 'ArrowRight' && nextChapter.value) {
    event.preventDefault()
    goTo(nextChapter.value)
  }
}

// ----------------------------------------------------------------------
// Lifecycle
// ----------------------------------------------------------------------
watch(
  () => route.params.chapterId,
  async (value) => {
    if (!chapters.value.length) return
    const id = Number(value)
    if (id && id !== chapter.value?.id) {
      await openChapter(id)
    }
  },
)

onMounted(async () => {
  await loadNovel()
  if (chapters.value.length) {
    const id = resolveChapterId()
    await openChapter(id, { replace: !route.params.chapterId })
  }
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (saveTimer) clearTimeout(saveTimer)
})
</script>

<template>
  <div class="flex h-screen flex-col" :class="themeClass.shell">
    <!-- ============================ header ============================ -->
    <header class="shrink-0 border-b px-4 py-2" :class="themeClass.panel">
      <div class="flex flex-wrap items-center gap-2">
        <button
          class="rounded px-2 py-1 text-xs hover:opacity-70"
          :class="themeClass.muted"
          title="Tampilkan/sembunyikan daftar bab"
          @click="toggleSidebar"
        >
          ☰
        </button>
        <button
          class="rounded px-2 py-1 text-xs hover:opacity-70"
          :class="themeClass.muted"
          @click="router.push(`/novels/${novelId}`)"
        >
          ← Workspace
        </button>

        <span class="truncate text-sm font-medium">
          {{ novel?.title_translated || novel?.title || 'Reader' }}
        </span>

        <div class="ml-auto flex flex-wrap items-center gap-1">
          <!-- theme -->
          <div class="flex overflow-hidden rounded border" :class="themeClass.panel">
            <button
              v-for="option in ['light', 'sepia', 'dark']"
              :key="option"
              class="px-2 py-1 text-[11px] capitalize"
              :class="theme === option ? 'bg-indigo-600 text-white' : themeClass.muted"
              @click="setTheme(option)"
            >
              {{ option }}
            </button>
          </div>

          <!-- font size -->
          <div class="flex items-center gap-1">
            <button
              class="rounded border px-2 py-1 text-[11px]"
              :class="themeClass.panel"
              title="Perkecil font"
              @click="changeFont(-1)"
            >
              A-
            </button>
            <span class="w-6 text-center text-[11px]" :class="themeClass.muted">
              {{ fontSize }}
            </span>
            <button
              class="rounded border px-2 py-1 text-[11px]"
              :class="themeClass.panel"
              title="Perbesar font"
              @click="changeFont(1)"
            >
              A+
            </button>
          </div>

          <!-- width -->
          <div class="flex overflow-hidden rounded border" :class="themeClass.panel">
            <button
              v-for="option in ['narrow', 'normal', 'wide']"
              :key="option"
              class="px-2 py-1 text-[11px]"
              :class="width === option ? 'bg-indigo-600 text-white' : themeClass.muted"
              @click="setWidth(option)"
            >
              {{ option === 'narrow' ? 'Sempit' : option === 'normal' ? 'Normal' : 'Lebar' }}
            </button>
          </div>

          <button
            class="rounded border px-2 py-1 text-[11px]"
            :class="showRaw ? 'bg-indigo-600 text-white' : themeClass.panel"
            @click="showRaw = !showRaw"
          >
            Raw
          </button>
        </div>
      </div>

      <div class="mt-1 flex items-center gap-2 text-[11px]" :class="themeClass.muted">
        <button :disabled="!prevChapter" class="disabled:opacity-30" @click="goTo(prevChapter)">
          ← Prev
        </button>
        <span class="truncate">
          <template v-if="chapter">
            Bab {{ chapter.chapter_number }} / {{ chapters.length }}
            <span v-if="chapter.title_translated"> · {{ chapter.title_translated }}</span>
          </template>
        </span>
        <button :disabled="!nextChapter" class="disabled:opacity-30" @click="goTo(nextChapter)">
          Next →
        </button>
        <span class="ml-auto">{{ scrollPercent }}%</span>
      </div>

      <div class="mt-1 h-0.5 w-full overflow-hidden rounded" :class="themeClass.soft">
        <div class="h-full bg-indigo-500 transition-all" :style="{ width: `${scrollPercent}%` }" />
      </div>
    </header>

    <!-- ============================= body ============================= -->
    <div class="flex min-h-0 flex-1">
      <!-- TOC -->
      <aside
        v-if="sidebarOpen"
        class="w-72 shrink-0 overflow-y-auto border-r"
        :class="themeClass.panel"
      >
        <p class="px-3 py-2 text-[11px] uppercase tracking-wide" :class="themeClass.muted">
          Daftar Bab ({{ chapters.length }})
        </p>
        <ul>
          <li v-for="item in chapters" :key="item.id">
            <button
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:opacity-80"
              :class="
                item.id === chapter?.id
                  ? 'bg-indigo-600/20 font-medium text-indigo-400'
                  : themeClass.muted
              "
              @click="goTo(item)"
            >
              <span class="w-6 shrink-0 text-right font-mono opacity-60">
                {{ item.chapter_number }}
              </span>
              <span class="min-w-0 flex-1 truncate">
                {{ item.title_translated || item.title || '(tanpa judul)' }}
              </span>
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                :class="item.status === 'translated' ? 'bg-emerald-500' : 'bg-slate-600'"
                :title="item.status"
              />
            </button>
          </li>
        </ul>
      </aside>

      <!-- content -->
      <main ref="scrollEl" class="min-w-0 flex-1 overflow-y-auto" @scroll="onScroll">
        <p v-if="loading" class="p-8 text-sm" :class="themeClass.muted">Memuat…</p>

        <div v-else-if="error" class="p-8 text-sm text-rose-400">{{ error }}</div>

        <div
          v-else-if="!chapters.length"
          class="mx-auto max-w-md px-6 py-24 text-center text-sm"
          :class="themeClass.muted"
        >
          Novel ini belum punya bab.
          <button class="ml-1 underline" @click="router.push(`/novels/${novelId}`)">
            Kembali ke workspace
          </button>
        </div>

        <template v-else-if="chapter">
          <article class="mx-auto px-6 py-10" :class="widthClass">
            <h1 class="mb-1 text-2xl font-semibold leading-snug">
              {{ chapter.title_translated || chapter.title }}
            </h1>
            <p class="mb-6 text-xs" :class="themeClass.muted">
              Bab {{ chapter.chapter_number }}
              <span v-if="chapter.title_translated && chapter.title !== chapter.title_translated">
                · {{ chapter.title }}
              </span>
              <span v-if="chapter.quality_score !== null && chapter.quality_score !== undefined">
                · skor {{ Math.round(chapter.quality_score) }}
              </span>
            </p>

            <div
              v-if="!hasTranslation"
              class="mb-6 rounded-lg border px-4 py-3 text-sm"
              :class="themeClass.soft"
            >
              Bab ini belum diterjemahkan — menampilkan teks sumber.
              <button class="ml-1 underline" @click="router.push(`/novels/${novelId}`)">
                Buka workspace
              </button>
            </div>

            <div
              class="space-y-4 leading-relaxed"
              :style="{ fontSize: `${fontSize}px` }"
            >
              <p v-for="(paragraph, index) in hasTranslation ? paragraphs : rawParagraphs" :key="index">
                {{ paragraph }}
              </p>
            </div>

            <!-- raw peek -->
            <section v-if="showRaw" class="mt-10 border-t pt-6" :class="themeClass.panel">
              <h2 class="mb-2 text-xs uppercase tracking-wide" :class="themeClass.muted">
                Teks sumber (raw)
              </h2>
              <div
                class="space-y-3 whitespace-pre-wrap font-mono text-[13px] leading-relaxed opacity-80"
              >
                <p v-for="(paragraph, index) in rawParagraphs" :key="index">{{ paragraph }}</p>
              </div>
            </section>

            <!-- bottom nav -->
            <nav class="mt-12 flex items-center justify-between gap-3 border-t pt-6 text-sm">
              <button
                class="rounded border px-3 py-2 disabled:opacity-30"
                :class="themeClass.panel"
                :disabled="!prevChapter"
                @click="goTo(prevChapter)"
              >
                ← {{ prevChapter ? prevChapter.title_translated || prevChapter.title : 'Prev' }}
              </button>
              <button
                class="rounded border px-3 py-2 text-right disabled:opacity-30"
                :class="themeClass.panel"
                :disabled="!nextChapter"
                @click="goTo(nextChapter)"
              >
                {{ nextChapter ? nextChapter.title_translated || nextChapter.title : 'Next' }} →
              </button>
            </nav>

            <p class="mt-4 text-center text-[11px]" :class="themeClass.muted">
              <span v-if="chapterLoading">memuat…</span>
              <span v-else-if="savedAt">progres tersimpan {{ savedAt }}</span>
              <span class="ml-2 opacity-60">← → untuk pindah bab</span>
            </p>
          </article>
        </template>
      </main>
    </div>
  </div>
</template>
