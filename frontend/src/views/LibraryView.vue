<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi } from '@/api/novels'
import { scrapersApi } from '@/api/scrapers'
import { useI18n } from '@/i18n'

const router = useRouter()
const { t } = useI18n()

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
const supportedScrapers = ref([])

const manualForm = reactive({
  title: '',
  author: '',
  source_lang: 'zh',
  target_lang: 'id',
  synopsis: '',
})
const savingManual = ref(false)

const deletingId = ref(null)

const sourceLangs = computed(() => [
  { value: 'zh', label: t('library.langZh') },
  { value: 'ja', label: t('library.langJa') },
  { value: 'ko', label: t('library.langKo') },
  { value: 'en', label: t('library.langEn') },
])
const targetLangs = computed(() => [
  { value: 'id', label: t('library.langId') },
  { value: 'en', label: t('library.langEn') },
])

const novelCountLabel = computed(() =>
  t(novels.value.length === 1 ? 'library.countOne' : 'library.count', {
    count: novels.value.length,
  }),
)

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
  if (!supportedScrapers.value.length) {
    scrapersApi
      .list()
      .then((list) => {
        supportedScrapers.value = list
      })
      .catch(() => {})
  }
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
    preview.value = await scrapersApi.preview(urlForm.url.trim(), urlForm.target_lang)
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
      t('library.addedFromUrl', {
        title: novel.title_translated || novel.title,
        count: novel.chapter_count,
      }),
    )
  } catch (err) {
    flash('error', t('library.addFailed', { message: err.message }))
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
    flash('success', t('library.added', { title: novel.title_translated || novel.title }))
  } catch (err) {
    flash('error', t('library.addFailed', { message: err.message }))
  } finally {
    savingManual.value = false
  }
}

async function remove(novel) {
  const title = novel.title_translated || novel.title
  if (!window.confirm(t('library.confirmDelete', { title, count: novel.chapter_count }))) return
  deletingId.value = novel.id
  try {
    await novelsApi.remove(novel.id)
    await load()
    flash('success', t('library.deleted', { title }))
  } catch (err) {
    flash('error', t('library.deleteFailed', { message: err.message }))
  } finally {
    deletingId.value = null
  }
}

function openWorkspace(novel) {
  router.push(`/novels/${novel.id}`)
}

function openReader(novel) {
  router.push(`/novels/${novel.id}/read`)
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <header class="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-strong">{{ t('library.title') }}</h1>
        <p class="mt-1 text-sm text-slate-400">
          {{ t('library.subtitle') }}
          <span class="text-slate-500">{{ novelCountLabel }}</span>
        </p>
      </div>
      <button class="btn-primary" @click="openModal">{{ t('library.addNovel') }}</button>
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
      {{ t('library.loadFailed', { message: error }) }}
      <button class="ml-2 underline" @click="load">{{ t('common.actions.retry') }}</button>
    </div>

    <p v-if="loading" class="text-sm text-slate-500">{{ t('common.actions.loading') }}</p>

    <div
      v-else-if="!novels.length"
      class="rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-6 py-16 text-center"
    >
      <p class="text-sm font-medium text-slate-300">{{ t('library.emptyTitle') }}</p>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-500">
        {{ t('library.emptyHint') }}
        <code class="rounded bg-ink-800 px-1 py-0.5 text-xs text-slate-400">.txt</code>.
      </p>
      <button class="btn-primary mt-6" @click="openModal">{{ t('library.addNovel') }}</button>
    </div>

    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="novel in novels"
        :key="novel.id"
        class="card flex flex-col gap-3 transition-colors hover:border-ink-600"
      >
        <div class="flex items-start gap-3">
          <img
            v-if="novel.cover_url"
            :src="novel.cover_url"
            :alt="novel.title_translated || novel.title"
            class="aspect-[2/3] w-14 shrink-0 rounded-lg border border-ink-700 object-cover"
          />
          <div
            v-else
            class="flex aspect-[2/3] w-14 shrink-0 items-center justify-center rounded-lg border border-dashed border-ink-700 bg-ink-850 text-[10px] font-medium uppercase tracking-wider text-slate-500"
          >
            N/A
          </div>
          <div class="min-w-0 flex-1 space-y-1">
            <div class="flex items-start justify-between gap-2">
              <h2 class="text-sm font-semibold leading-snug text-slate-100">
                {{ novel.title_translated || novel.title }}
              </h2>
              <span
                class="badge shrink-0"
                :class="
                  novel.source_type === 'scraper'
                    ? 'bg-indigo-950/70 text-indigo-300'
                    : 'bg-ink-800 text-slate-400'
                "
              >
                {{
                  novel.source_type === 'scraper'
                    ? t('library.sourceScraper')
                    : t('library.sourceManual')
                }}
              </span>
            </div>

            <p class="text-xs text-slate-400">
              {{ novel.author || t('library.unknownAuthor') }}
            </p>
          </div>
        </div>

        <p
          v-if="novel.synopsis_translated || novel.synopsis"
          class="line-clamp-2 text-[11px] leading-relaxed text-slate-500"
        >
          {{ novel.synopsis_translated || novel.synopsis }}
        </p>

        <p class="font-mono text-[11px] text-slate-500">
          {{ novel.source_lang }} → {{ novel.target_lang }}
          <span v-if="novel.scraper_name"> · {{ novel.scraper_name }}</span>
        </p>

        <div class="flex flex-wrap gap-1.5 text-[11px]">
          <span class="badge bg-ink-800 text-slate-300">{{
            t('common.units.chapters', { count: novel.chapter_count })
          }}</span>
          <span class="badge bg-emerald-950/50 text-emerald-400">{{
            t('library.rawCount', { count: novel.raw_count })
          }}</span>
          <span class="badge bg-sky-950/50 text-sky-400">
            {{ t('library.translatedCount', { count: novel.translated_count }) }}
          </span>
          <span v-if="novel.pending_count" class="badge bg-amber-950/50 text-amber-400">
            {{ t('library.pendingCount', { count: novel.pending_count }) }}
          </span>
        </div>

        <div class="mt-auto flex flex-wrap items-center gap-2 pt-1">
          <button
            class="btn-primary !px-2.5 !py-1 text-xs"
            :disabled="!novel.translated_count"
            :title="
              novel.translated_count ? t('library.openReader') : t('library.noTranslatedChapters')
            "
            @click="openReader(novel)"
          >
            {{ novel.last_read_chapter_id ? t('library.continueReading') : t('library.read') }}
          </button>
          <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="openWorkspace(novel)">
            {{ t('library.workspace') }}
          </button>
          <button
            class="btn-danger ml-auto !px-2.5 !py-1 text-xs"
            :disabled="deletingId === novel.id"
            @click="remove(novel)"
          >
            {{ t('common.actions.delete') }}
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
          <h2 class="text-sm font-semibold text-strong">{{ t('library.addNovel') }}</h2>
          <button class="text-slate-500 hover:text-slate-200" @click="closeModal">✕</button>
        </div>

        <div class="flex gap-1 border-b border-ink-800 px-5 pt-3">
          <button
            class="rounded-t-lg px-3 py-2 text-sm font-medium"
            :class="
              tab === 'url'
                ? 'border-b-2 border-indigo-500 text-strong'
                : 'text-slate-400 hover:text-slate-200'
            "
            @click="tab = 'url'"
          >
            {{ t('library.tabUrl') }}
          </button>
          <button
            class="rounded-t-lg px-3 py-2 text-sm font-medium"
            :class="
              tab === 'manual'
                ? 'border-b-2 border-indigo-500 text-strong'
                : 'text-slate-400 hover:text-slate-200'
            "
            @click="tab = 'manual'"
          >
            {{ t('library.tabManual') }}
          </button>
        </div>

        <!-- tab: URL -->
        <form v-if="tab === 'url'" class="space-y-4 p-5" @submit.prevent="saveFromUrl">
          <div>
            <label class="label" for="novel-url">{{ t('library.novelUrl') }}</label>
            <div class="flex gap-2">
              <input
                id="novel-url"
                v-model="urlForm.url"
                class="input font-mono text-xs"
                type="url"
                :placeholder="t('library.urlPlaceholder')"
              />
              <button
                type="button"
                class="btn-ghost shrink-0"
                :disabled="previewing || !urlForm.url.trim()"
                @click="doPreview"
              >
                {{ previewing ? t('library.previewing') : t('library.preview') }}
              </button>
            </div>
            <p class="mt-1 text-[11px] text-slate-500">
              {{ t('library.scraperHint') }}
            </p>
            <div v-if="supportedScrapers.length" class="mt-2 flex flex-wrap items-center gap-1.5">
              <span class="text-[11px] text-slate-500">{{ t('library.supportedSites') }}</span>
              <span
                v-for="item in supportedScrapers"
                :key="item.name"
                class="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300"
                :title="`${item.display_name} (${item.domains.join(', ')})`"
              >
                {{ item.domains[0] }} ({{ item.source_lang }})
              </span>
            </div>
          </div>

          <div>
            <label class="label" for="url-target">{{ t('library.translateTo') }}</label>
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
                  {{ t('library.generic') }}
                </span>
                <span class="badge bg-ink-800 text-slate-400">{{ preview.kind }}</span>
              </div>
              <p class="mt-2 font-medium text-slate-100">
                {{ preview.title_translated || preview.title }}
              </p>
              <p
                v-if="preview.title_translated && preview.title_translated !== preview.title"
                class="text-[11px] text-slate-500"
              >
                {{ t('library.original', { title: preview.title }) }}
              </p>
              <p v-if="preview.author" class="text-xs text-slate-400">{{ preview.author }}</p>
              <p
                v-if="preview.synopsis_translated || preview.synopsis"
                class="mt-2.5 max-h-28 overflow-y-auto whitespace-pre-line rounded-md border border-ink-800 bg-ink-900/60 px-3 py-2 text-xs leading-relaxed text-slate-300"
              >
                {{ preview.synopsis_translated || preview.synopsis }}
              </p>
              <p class="mt-2.5 text-xs font-medium text-slate-400">
                <template v-if="preview.kind === 'novel'">
                  {{ t('library.chaptersDetected', { count: preview.chapter_count }) }}
                </template>
                <template v-else>
                  {{ t('library.singleChapterDetected', { count: preview.content_length }) }}
                </template>
              </p>
              <ul
                v-if="preview.chapters?.length"
                class="mt-2 grid max-h-32 grid-cols-3 gap-x-3 gap-y-1 overflow-y-auto text-[11px] text-slate-400"
              >
                <li
                  v-for="chapter in preview.chapters"
                  :key="chapter.url"
                  class="truncate"
                  :title="`${chapter.chapter_number}. ${chapter.title}`"
                >
                  {{ chapter.chapter_number }}. {{ chapter.title }}
                </li>
              </ul>
            </template>
            <template v-else>{{ preview.error }}</template>
          </div>

          <div class="flex justify-end gap-2 pt-1">
            <button type="button" class="btn-ghost" @click="closeModal">
              {{ t('common.actions.cancel') }}
            </button>
            <button type="submit" class="btn-primary" :disabled="!canSaveUrl">
              {{ savingUrl ? t('common.actions.saving') : t('library.saveNovel') }}
            </button>
          </div>
        </form>

        <!-- tab: manual -->
        <form v-else class="space-y-4 p-5" @submit.prevent="saveManual">
          <div>
            <label class="label" for="manual-title">{{ t('library.fieldTitle') }}</label>
            <input
              id="manual-title"
              v-model="manualForm.title"
              class="input"
              type="text"
              :placeholder="t('library.titlePlaceholder')"
            />
          </div>
          <div>
            <label class="label" for="manual-author">{{ t('library.fieldAuthor') }}</label>
            <input
              id="manual-author"
              v-model="manualForm.author"
              class="input"
              type="text"
              :placeholder="t('common.state.optional')"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="label" for="manual-source">{{ t('library.fieldSourceLang') }}</label>
              <select id="manual-source" v-model="manualForm.source_lang" class="input">
                <option v-for="lang in sourceLangs" :key="lang.value" :value="lang.value">
                  {{ lang.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="label" for="manual-target">{{ t('library.translateTo') }}</label>
              <select id="manual-target" v-model="manualForm.target_lang" class="input">
                <option v-for="lang in targetLangs" :key="lang.value" :value="lang.value">
                  {{ lang.label }}
                </option>
              </select>
            </div>
          </div>
          <div>
            <label class="label" for="manual-synopsis">{{ t('library.fieldSynopsis') }}</label>
            <textarea
              id="manual-synopsis"
              v-model="manualForm.synopsis"
              class="input h-24 resize-y"
              :placeholder="t('common.state.optional')"
            />
          </div>
          <div class="flex justify-end gap-2 pt-1">
            <button type="button" class="btn-ghost" @click="closeModal">
              {{ t('common.actions.cancel') }}
            </button>
            <button
              type="submit"
              class="btn-primary"
              :disabled="savingManual || !manualForm.title.trim()"
            >
              {{ savingManual ? t('common.actions.saving') : t('library.saveNovel') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
