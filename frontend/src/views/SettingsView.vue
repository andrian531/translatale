<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { settingsApi } from '@/api/settings'
import ModelSelect from '@/components/ModelSelect.vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const meta = ref({ provider_types: [], tasks: [] })
const providers = ref([])
const tasks = ref([])

const loading = ref(true)
const loadError = ref('')
const notice = ref(null)

const form = reactive({
  id: null,
  provider_type: 'gemini',
  display_name: '',
  api_key: '',
  base_url: '',
  is_enabled: true,
  //: Free-text model list: one per line or comma separated.
  modelsText: '',
})

const savingProvider = ref(false)
const deletingId = ref(null)
const testingId = ref(null)
const syncingId = ref(null)
const testResults = reactive({})
const syncResults = reactive({})

const scraperForm = reactive({
  fetch_batch_size: 50,
  fetch_delay_seconds: 1,
  fetch_max_consecutive_errors: 3,
})
const savingScraper = ref(false)

const taskDrafts = reactive({})
const savingTask = ref(null)
const taskSyncing = ref(null)
const taskSaved = reactive({})

const providerTypes = computed(() => meta.value.provider_types ?? [])
const currentType = computed(() =>
  providerTypes.value.find((item) => item.value === form.provider_type),
)
const isEditing = computed(() => form.id !== null)
const keyRequired = computed(() => currentType.value?.requires_api_key !== false)
const hasProviders = computed(() => providers.value.length > 0)
const isCustom = computed(() => form.provider_type === 'custom')
//: A Custom provider must be named by the user, otherwise several of them
//: collapse into the same generic label in the routing dropdowns.
const nameMissing = computed(() => isCustom.value && !form.display_name.trim())
const canSaveProvider = computed(() => !savingProvider.value && !nameMissing.value)

function parseModelText(text) {
  return [
    ...new Set(
      String(text || '')
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function providerById(id) {
  return providers.value.find((item) => item.id === id) ?? null
}

//: Short type names keep the routing dropdown readable
//: ("Kenari (Custom · kenari.id)").
function shortTypeLabel(type) {
  const key = `settings.providerTypesShort.${type}`
  const label = t(key)
  return label === key ? providerLabel(type) : label
}

function providerOptionLabel(provider) {
  const type = shortTypeLabel(provider.provider_type)
  let host = ''
  try {
    host = new URL(provider.base_url).host
  } catch {
    host = ''
  }
  return host ? `${provider.display_name} (${type} · ${host})` : `${provider.display_name} (${type})`
}

function modelsForTask(task) {
  const draft = taskDrafts[task.task_name]
  return providerById(draft?.provider_id)?.available_models ?? []
}

function fallbackModelsForTask(task) {
  const draft = taskDrafts[task.task_name]
  return providerById(draft?.fallback_provider_id)?.available_models ?? []
}

function providerLabel(type) {
  const fallback = providerTypes.value.find((item) => item.value === type)?.label ?? type
  const key = `settings.providerTypes.${type}`
  const label = t(key)
  return label === key ? fallback : label
}

function taskLabel(task) {
  const key = `settings.taskNames.${task.task_name}`
  const label = t(key)
  return label === key ? task.label : label
}

function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => {
    if (notice.value?.text === text) notice.value = null
  }, 5000)
}

function applyTypeDefaults() {
  const type = currentType.value
  if (!type) return
  form.base_url = type.default_base_url ?? ''
  // Custom providers stay unnamed: the user must give each one a distinct name.
  if (form.provider_type !== 'custom' && !form.display_name) {
    form.display_name = type.label
  }
}

function resetForm() {
  form.id = null
  form.provider_type = 'gemini'
  form.display_name = ''
  form.api_key = ''
  form.base_url = ''
  form.is_enabled = true
  form.modelsText = ''
  applyTypeDefaults()
}

function onTypeChange() {
  const type = currentType.value
  if (!type) return
  form.base_url = type.default_base_url ?? ''
  if (form.provider_type === 'custom') {
    // Drop the generic label a previous type may have filled in.
    if (
      providerTypes.value.some((item) => item.value !== 'custom' && item.label === form.display_name)
    ) {
      form.display_name = ''
    }
    return
  }
  if (!form.display_name || providerTypes.value.some((item) => item.label === form.display_name)) {
    form.display_name = type.label
  }
}

function editProvider(provider) {
  form.id = provider.id
  form.provider_type = provider.provider_type
  form.display_name = provider.display_name
  form.api_key = ''
  form.base_url = provider.base_url
  form.is_enabled = provider.is_enabled
  form.modelsText = (provider.available_models ?? []).join('\n')
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function loadProviders() {
  providers.value = await settingsApi.listProviders()
}

async function loadTasks() {
  const data = await settingsApi.listTasks()
  tasks.value = data
  for (const task of data) {
    taskDrafts[task.task_name] = {
      provider_id: task.provider_id,
      model_name: task.model_name,
      fallback_provider_id: task.fallback_provider_id ?? null,
      fallback_model_name: task.fallback_model_name ?? '',
      temperature: task.temperature,
      max_tokens: task.max_tokens,
    }
    taskSaved[task.task_name] = false
  }
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [metaData] = await Promise.all([
      settingsApi.meta(),
      loadProviders(),
      loadTasks(),
      loadScraperSettings(),
    ])
    meta.value = metaData
    if (!form.base_url) applyTypeDefaults()
  } catch (error) {
    loadError.value = error.message
  } finally {
    loading.value = false
  }
}

async function loadScraperSettings() {
  try {
    const data = await settingsApi.getScraperSettings()
    scraperForm.fetch_batch_size = data.fetch_batch_size
    scraperForm.fetch_delay_seconds = data.fetch_delay_seconds
    scraperForm.fetch_max_consecutive_errors = data.fetch_max_consecutive_errors
  } catch {
    // Non-fatal: the form keeps its defaults and a save will still work.
  }
}

async function saveScraperSettings() {
  savingScraper.value = true
  try {
    const saved = await settingsApi.saveScraperSettings({
      fetch_batch_size: Number(scraperForm.fetch_batch_size),
      fetch_delay_seconds: Number(scraperForm.fetch_delay_seconds),
      fetch_max_consecutive_errors: Number(scraperForm.fetch_max_consecutive_errors),
    })
    scraperForm.fetch_batch_size = saved.fetch_batch_size
    scraperForm.fetch_delay_seconds = saved.fetch_delay_seconds
    scraperForm.fetch_max_consecutive_errors = saved.fetch_max_consecutive_errors
    flash('success', t('settings.scraper.flashSaved'))
  } catch (error) {
    flash('error', t('settings.scraper.flashSaveFailed', { message: error.message }))
  } finally {
    savingScraper.value = false
  }
}

async function saveProvider() {
  if (nameMissing.value) {
    flash('error', t('settings.providers.nameMissing'))
    return
  }
  savingProvider.value = true
  try {
    const payload = {
      provider_type: form.provider_type,
      display_name: form.display_name.trim() || providerLabel(form.provider_type),
      base_url: form.base_url,
      is_enabled: form.is_enabled,
      available_models: parseModelText(form.modelsText),
    }
    if (form.id !== null) payload.id = form.id
    // Empty key on edit = keep the stored one (backend enforces this too).
    if (form.api_key) payload.api_key = form.api_key

    const saved = await settingsApi.saveProvider(payload)
    await loadProviders()
    resetForm()
    flash('success', t('settings.providers.flashSaved', { name: saved.display_name }))
  } catch (error) {
    flash('error', t('settings.providers.flashSaveFailed', { message: error.message }))
  } finally {
    savingProvider.value = false
  }
}

async function removeProvider(provider) {
  if (!window.confirm(t('settings.providers.confirmDelete', { name: provider.display_name }))) return
  deletingId.value = provider.id
  try {
    await settingsApi.deleteProvider(provider.id)
    delete testResults[provider.id]
    if (form.id === provider.id) resetForm()
    await Promise.all([loadProviders(), loadTasks()])
    flash('success', t('settings.providers.flashDeleted', { name: provider.display_name }))
  } catch (error) {
    flash('error', t('settings.providers.flashDeleteFailed', { message: error.message }))
  } finally {
    deletingId.value = null
  }
}

async function testProvider(provider) {
  testingId.value = provider.id
  testResults[provider.id] = null
  try {
    const result = await settingsApi.testProvider(provider.id)
    testResults[provider.id] = result
    // The backend syncs the model list opportunistically on a successful test.
    if (result.models_synced) await loadProviders()
  } catch (error) {
    testResults[provider.id] = { ok: false, message: error.message }
  } finally {
    testingId.value = null
  }
}

async function syncModels(provider) {
  syncingId.value = provider.id
  syncResults[provider.id] = null
  try {
    const result = await settingsApi.syncProviderModels(provider.id)
    await loadProviders()
    syncResults[provider.id] = {
      ok: true,
      text: t('settings.providers.syncSaved', { count: result.count }),
    }
    if (form.id === provider.id) form.modelsText = (result.models ?? []).join('\n')
    flash(
      'success',
      t('settings.providers.flashSyncSaved', {
        name: provider.display_name,
        count: result.count,
      }),
    )
  } catch (error) {
    syncResults[provider.id] = { ok: false, text: error.message }
    flash('error', t('settings.providers.flashSyncFailed', { message: error.message }))
  } finally {
    syncingId.value = null
  }
}

async function saveTask(task) {
  const draft = taskDrafts[task.task_name]
  savingTask.value = task.task_name
  taskSaved[task.task_name] = false
  try {
    const updated = await settingsApi.saveTask(task.task_name, {
      provider_id: draft.provider_id ?? null,
      model_name: draft.model_name ?? '',
      fallback_provider_id: draft.fallback_provider_id ?? null,
      fallback_model_name: draft.fallback_model_name ?? '',
      temperature: Number(draft.temperature),
      max_tokens: Number(draft.max_tokens),
    })
    const index = tasks.value.findIndex((item) => item.task_name === updated.task_name)
    if (index !== -1) tasks.value[index] = updated
    taskSaved[task.task_name] = true
    window.setTimeout(() => {
      taskSaved[task.task_name] = false
    }, 2500)
  } catch (error) {
    flash(
      'error',
      t('settings.tasks.flashSaveFailed', { label: taskLabel(task), message: error.message }),
    )
  } finally {
    savingTask.value = null
  }
}

async function syncForTask(task) {
  const provider = providerById(taskDrafts[task.task_name]?.provider_id)
  if (!provider) return
  taskSyncing.value = task.task_name
  try {
    const result = await settingsApi.syncProviderModels(provider.id)
    await loadProviders()
    flash(
      'success',
      t('settings.providers.flashSyncSaved', {
        name: provider.display_name,
        count: result.count,
      }),
    )
  } catch (error) {
    flash('error', t('settings.providers.flashSyncFailed', { message: error.message }))
  } finally {
    taskSyncing.value = null
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <header class="mb-8">
      <h1 class="text-2xl font-semibold tracking-tight text-strong">{{ t('settings.title') }}</h1>
      <p class="mt-1 text-sm text-slate-400">
        {{ t('settings.subtitle') }}
      </p>
    </header>

    <div
      v-if="notice"
      class="mb-6 rounded-lg border px-4 py-3 text-sm"
      :class="
        notice.type === 'success'
          ? 'border-emerald-900/60 bg-emerald-950/40 text-emerald-300'
          : 'border-rose-900/60 bg-rose-950/40 text-rose-300'
      "
    >
      {{ notice.text }}
    </div>

    <div
      v-if="loadError"
      class="mb-6 rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300"
    >
      {{ t('settings.loadError', { message: loadError }) }}
      <button class="ml-2 underline" @click="loadAll">{{ t('common.actions.retry') }}</button>
    </div>

    <p v-if="loading" class="text-sm text-slate-500">{{ t('common.actions.loading') }}</p>

    <template v-else>
      <!-- ============================ PROVIDERS ============================ -->
      <section class="mb-12">
        <div class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold text-strong">{{ t('settings.providers.title') }}</h2>
          <span class="text-xs text-slate-500">
            {{ t('settings.providers.savedCount', { count: providers.length }) }}
          </span>
        </div>

        <div class="grid gap-6 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
          <!-- form -->
          <form class="card space-y-4 self-start" @submit.prevent="saveProvider">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-slate-200">
                {{ isEditing ? t('settings.providers.formEdit') : t('settings.providers.formAdd') }}
              </h3>
              <button
                v-if="isEditing"
                type="button"
                class="text-xs text-slate-400 underline hover:text-slate-200"
                @click="resetForm"
              >
                {{ t('common.actions.cancel') }}
              </button>
            </div>

            <div>
              <label class="label" for="provider-type">{{ t('settings.providers.type') }}</label>
              <select
                id="provider-type"
                v-model="form.provider_type"
                class="input"
                @change="onTypeChange"
              >
                <option v-for="type in providerTypes" :key="type.value" :value="type.value">
                  {{ providerLabel(type.value) }}
                </option>
              </select>
            </div>

            <div>
              <label class="label" for="display-name">
                {{ t('settings.providers.name') }}
                <span v-if="isCustom" class="normal-case text-rose-400">
                  ({{ t('common.state.required') }})
                </span>
              </label>
              <input
                id="display-name"
                v-model="form.display_name"
                class="input"
                type="text"
                :class="{ '!border-rose-700': nameMissing }"
                :placeholder="
                  isCustom
                    ? t('settings.providers.nameExample')
                    : (currentType?.label ?? t('settings.providers.namePlaceholder'))
                "
              />
              <p v-if="nameMissing" class="mt-1 text-[11px] text-rose-400">
                {{ t('settings.providers.nameRequiredHint') }}
              </p>
              <p v-else-if="isCustom" class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.providers.customHint') }}
              </p>
            </div>

            <div>
              <label class="label" for="api-key">
                {{ t('settings.providers.apiKey') }}
                <span v-if="!keyRequired" class="normal-case text-slate-500">
                  ({{ t('common.state.optional') }})
                </span>
              </label>
              <input
                id="api-key"
                v-model="form.api_key"
                class="input font-mono"
                type="password"
                autocomplete="off"
                :placeholder="
                  isEditing
                    ? t('settings.providers.apiKeyPlaceholderEdit')
                    : t('settings.providers.apiKeyPlaceholder')
                "
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.providers.apiKeyHintBefore') }}<code class="text-slate-400">****1234</code>{{ t('settings.providers.apiKeyHintAfter') }}
              </p>
            </div>

            <div>
              <label class="label" for="base-url">{{ t('settings.providers.baseUrl') }}</label>
              <input
                id="base-url"
                v-model="form.base_url"
                class="input font-mono text-xs"
                type="text"
                placeholder="https://…"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.providers.baseUrlHint') }}
              </p>
            </div>

            <div>
              <label class="label" for="models-text">
                {{ t('settings.providers.modelsLabel') }}
              </label>
              <textarea
                id="models-text"
                v-model="form.modelsText"
                class="input h-24 resize-y font-mono text-xs"
                :placeholder="t('settings.providers.modelsPlaceholder')"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.providers.modelsHintBefore') }}
                <span class="text-slate-400">{{ t('settings.providers.fetchModels') }}</span>
                {{ t('settings.providers.modelsHintAfter') }}
                <span v-if="parseModelText(form.modelsText).length" class="text-slate-400">
                  ({{ t('common.units.models', { count: parseModelText(form.modelsText).length }) }})
                </span>
              </p>
            </div>

            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input
                v-model="form.is_enabled"
                type="checkbox"
                class="h-4 w-4 rounded border-ink-600 bg-ink-850 text-indigo-600 focus:ring-indigo-500"
              />
              {{ t('settings.providers.enabled') }}
            </label>

            <button type="submit" class="btn-primary w-full" :disabled="!canSaveProvider">
              {{
                savingProvider
                  ? t('common.actions.saving')
                  : isEditing
                    ? t('settings.providers.submitUpdate')
                    : t('settings.providers.formAdd')
              }}
            </button>
          </form>

          <!-- list -->
          <div class="space-y-3">
            <p
              v-if="!hasProviders"
              class="rounded-xl border border-dashed border-ink-700 px-5 py-10 text-center text-sm text-slate-500"
            >
              {{ t('settings.providers.empty') }}
            </p>

            <article
              v-for="provider in providers"
              :key="provider.id"
              class="card space-y-3"
              :class="{ 'opacity-60': !provider.is_enabled }"
            >
              <div class="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div class="flex items-center gap-2">
                    <h3 class="text-sm font-semibold text-slate-100">
                      {{ provider.display_name }}
                    </h3>
                    <span class="badge bg-ink-800 text-slate-400">
                      {{ providerLabel(provider.provider_type) }}
                    </span>
                    <span
                      class="badge"
                      :class="
                        (provider.available_models ?? []).length
                          ? 'bg-sky-950/60 text-sky-400'
                          : 'bg-ink-850 text-slate-500'
                      "
                    >
                      {{
                        t('common.units.models', {
                          count: (provider.available_models ?? []).length,
                        })
                      }}
                    </span>
                    <span
                      v-if="!provider.is_enabled"
                      class="badge bg-amber-950/60 text-amber-400"
                      >{{ t('settings.providers.disabledBadge') }}</span
                    >
                  </div>
                  <p class="mt-1 font-mono text-[11px] text-slate-500">
                    {{ provider.base_url || '—' }}
                  </p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <button
                    class="btn-ghost !px-2.5 !py-1 text-xs"
                    :disabled="syncingId === provider.id"
                    @click="syncModels(provider)"
                  >
                    {{
                      syncingId === provider.id
                        ? t('settings.providers.syncing')
                        : t('settings.providers.fetchModels')
                    }}
                  </button>
                  <button
                    class="btn-ghost !px-2.5 !py-1 text-xs"
                    :disabled="testingId === provider.id"
                    @click="testProvider(provider)"
                  >
                    {{
                      testingId === provider.id
                        ? t('settings.providers.testing')
                        : t('settings.providers.test')
                    }}
                  </button>
                  <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="editProvider(provider)">
                    {{ t('common.actions.edit') }}
                  </button>
                  <button
                    class="btn-danger !px-2.5 !py-1 text-xs"
                    :disabled="deletingId === provider.id"
                    @click="removeProvider(provider)"
                  >
                    {{ t('common.actions.delete') }}
                  </button>
                </div>
              </div>

              <div class="flex items-center gap-2 text-xs">
                <span class="text-slate-500">{{ t('settings.providers.apiKey') }}</span>
                <code
                  class="rounded bg-ink-850 px-2 py-0.5 font-mono text-slate-300"
                  :class="{ 'text-slate-500': !provider.has_api_key }"
                >
                  {{ provider.api_key || t('settings.providers.apiKeyEmpty') }}
                </code>
              </div>

              <p
                v-if="syncResults[provider.id]"
                class="rounded-lg border px-3 py-2 text-xs"
                :class="
                  syncResults[provider.id].ok
                    ? 'border-sky-900/60 bg-sky-950/30 text-sky-300'
                    : 'border-rose-900/60 bg-rose-950/30 text-rose-300'
                "
              >
                {{ syncResults[provider.id].text }}
              </p>

              <p
                v-if="testResults[provider.id]"
                class="rounded-lg border px-3 py-2 text-xs"
                :class="
                  testResults[provider.id].ok
                    ? 'border-emerald-900/60 bg-emerald-950/30 text-emerald-300'
                    : 'border-rose-900/60 bg-rose-950/30 text-rose-300'
                "
              >
                <span class="font-semibold">
                  {{
                    testResults[provider.id].ok
                      ? t('settings.providers.testOk')
                      : t('settings.providers.testFailed')
                  }}
                </span>
                <span v-if="testResults[provider.id].model" class="text-slate-400">
                  · {{ t('settings.providers.testModel', { name: testResults[provider.id].model }) }}
                </span>
                <br />
                {{ testResults[provider.id].message }}
              </p>
            </article>
          </div>
        </div>
      </section>

      <!-- ============================== TASKS ============================== -->
      <section>
        <div class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold text-strong">{{ t('settings.tasks.title') }}</h2>
          <span class="text-xs text-slate-500">{{ t('settings.tasks.slotCount') }}</span>
        </div>

        <div class="grid gap-4 md:grid-cols-3">
          <form
            v-for="task in tasks"
            v-show="taskDrafts[task.task_name]"
            :key="task.task_name"
            class="card flex flex-col gap-4"
            @submit.prevent="saveTask(task)"
          >
            <div>
              <h3 class="text-sm font-semibold text-slate-100">{{ taskLabel(task) }}</h3>
              <p class="mt-0.5 font-mono text-[11px] text-slate-500">{{ task.task_name }}</p>
            </div>

            <div>
              <label class="label" :for="`provider-${task.task_name}`">
                {{ t('settings.tasks.provider') }}
              </label>
              <select
                :id="`provider-${task.task_name}`"
                v-model="taskDrafts[task.task_name].provider_id"
                class="input"
              >
                <option :value="null">{{ t('settings.tasks.providerNone') }}</option>
                <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                  {{ providerOptionLabel(provider) }}
                  <template v-if="!provider.is_enabled">
                    {{ t('settings.tasks.disabledSuffix') }}
                  </template>
                </option>
              </select>
            </div>

            <div>
              <label class="label">{{ t('settings.tasks.model') }}</label>
              <ModelSelect
                v-model="taskDrafts[task.task_name].model_name"
                :models="modelsForTask(task)"
                :disabled="!taskDrafts[task.task_name].provider_id"
                :placeholder="t('settings.tasks.modelPlaceholder')"
                :empty-hint="
                  taskDrafts[task.task_name].provider_id
                    ? t('settings.tasks.modelEmptyHint')
                    : t('settings.tasks.modelEmptyHintNoProvider')
                "
              />
              <div class="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  class="btn-ghost !px-2.5 !py-1 text-[11px]"
                  :disabled="
                    !taskDrafts[task.task_name].provider_id || taskSyncing === task.task_name
                  "
                  @click="syncForTask(task)"
                >
                  {{
                    taskSyncing === task.task_name
                      ? t('settings.providers.syncing')
                      : t('settings.tasks.sync')
                  }}
                </button>
                <span class="text-[11px] text-slate-500">
                  {{ t('settings.tasks.modelsSaved', { count: modelsForTask(task).length }) }}
                </span>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="label" :for="`temp-${task.task_name}`">
                  {{ t('settings.tasks.temperature') }}
                </label>
                <input
                  :id="`temp-${task.task_name}`"
                  v-model.number="taskDrafts[task.task_name].temperature"
                  class="input"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                />
              </div>
              <div>
                <label class="label" :for="`tokens-${task.task_name}`">
                  {{ t('settings.tasks.maxTokens') }}
                </label>
                <input
                  :id="`tokens-${task.task_name}`"
                  v-model.number="taskDrafts[task.task_name].max_tokens"
                  class="input"
                  type="number"
                  min="1"
                  step="1"
                />
              </div>
            </div>

            <div class="rounded-lg border border-ink-800/80 bg-ink-950/40 p-3 space-y-2.5">
              <div>
                <p class="text-xs font-medium text-slate-300">
                  {{ t('settings.tasks.fallbackTitle') }}
                </p>
                <p class="text-[11px] text-slate-500">
                  {{ t('settings.tasks.fallbackHint') }}
                </p>
              </div>
              <div>
                <label class="label" :for="`fb-provider-${task.task_name}`">
                  {{ t('settings.tasks.fallbackProvider') }}
                </label>
                <select
                  :id="`fb-provider-${task.task_name}`"
                  v-model="taskDrafts[task.task_name].fallback_provider_id"
                  class="input"
                >
                  <option :value="null">{{ t('settings.tasks.fallbackNone') }}</option>
                  <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                    {{ providerOptionLabel(provider) }}
                    <template v-if="!provider.is_enabled">
                      {{ t('settings.tasks.disabledSuffix') }}
                    </template>
                  </option>
                </select>
              </div>
              <div>
                <label class="label">{{ t('settings.tasks.fallbackModel') }}</label>
                <ModelSelect
                  v-model="taskDrafts[task.task_name].fallback_model_name"
                  :models="fallbackModelsForTask(task)"
                  :disabled="!taskDrafts[task.task_name].fallback_provider_id"
                  :placeholder="t('settings.tasks.fallbackPlaceholder')"
                  :empty-hint="
                    taskDrafts[task.task_name].fallback_provider_id
                      ? t('settings.tasks.fallbackEmptyHint')
                      : t('settings.tasks.fallbackEmptyHintNoProvider')
                  "
                />
              </div>
            </div>

            <div class="mt-auto flex items-center gap-3">
              <button type="submit" class="btn-primary" :disabled="savingTask === task.task_name">
                {{
                  savingTask === task.task_name
                    ? t('common.actions.saving')
                    : t('common.actions.save')
                }}
              </button>
              <span v-if="taskSaved[task.task_name]" class="text-xs text-emerald-400">
                {{ t('settings.tasks.saved') }}
              </span>
              <span v-else-if="!task.provider_id" class="text-xs text-amber-500/80">
                {{ t('settings.tasks.notConfigured') }}
              </span>
            </div>
          </form>
        </div>
      </section>

      <!-- ========================= SCRAPER SETTINGS ========================= -->
      <section class="mt-12">
        <div class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold text-strong">{{ t('settings.scraper.title') }}</h2>
          <span class="text-xs text-slate-500">{{ t('settings.scraper.subtitle') }}</span>
        </div>

        <form class="card space-y-4" @submit.prevent="saveScraperSettings">
          <div class="grid gap-4 sm:grid-cols-3">
            <div>
              <label class="label" for="fetch-batch">{{ t('settings.scraper.batchSize') }}</label>
              <input
                id="fetch-batch"
                v-model.number="scraperForm.fetch_batch_size"
                class="input"
                type="number"
                min="1"
                max="500"
                step="1"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.scraper.batchSizeHint') }}
              </p>
            </div>
            <div>
              <label class="label" for="fetch-delay">{{ t('settings.scraper.delay') }}</label>
              <input
                id="fetch-delay"
                v-model.number="scraperForm.fetch_delay_seconds"
                class="input"
                type="number"
                min="0"
                max="10"
                step="0.1"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.scraper.delayHint') }}
              </p>
            </div>
            <div>
              <label class="label" for="fetch-errors">{{ t('settings.scraper.maxErrors') }}</label>
              <input
                id="fetch-errors"
                v-model.number="scraperForm.fetch_max_consecutive_errors"
                class="input"
                type="number"
                min="1"
                max="20"
                step="1"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                {{ t('settings.scraper.maxErrorsHint') }}
              </p>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <button type="submit" class="btn-primary" :disabled="savingScraper">
              {{ savingScraper ? t('common.actions.saving') : t('common.actions.save') }}
            </button>
            <span class="text-[11px] text-slate-500">
              {{ t('settings.scraper.note') }}
            </span>
          </div>
        </form>
      </section>
    </template>
  </div>
</template>
