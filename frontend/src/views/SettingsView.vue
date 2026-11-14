<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { settingsApi } from '@/api/settings'

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
})

const savingProvider = ref(false)
const deletingId = ref(null)
const testingId = ref(null)
const testResults = reactive({})

const taskDrafts = reactive({})
const savingTask = ref(null)
const taskSaved = reactive({})

const providerTypes = computed(() => meta.value.provider_types ?? [])
const currentType = computed(() =>
  providerTypes.value.find((item) => item.value === form.provider_type),
)
const isEditing = computed(() => form.id !== null)
const keyRequired = computed(() => currentType.value?.requires_api_key !== false)
const hasProviders = computed(() => providers.value.length > 0)

function providerLabel(type) {
  return providerTypes.value.find((item) => item.value === type)?.label ?? type
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
  if (!form.display_name) form.display_name = type.label
}

function resetForm() {
  form.id = null
  form.provider_type = 'gemini'
  form.display_name = ''
  form.api_key = ''
  form.base_url = ''
  form.is_enabled = true
  applyTypeDefaults()
}

function onTypeChange() {
  const type = currentType.value
  if (!type) return
  form.base_url = type.default_base_url ?? ''
  if (!form.display_name || providerTypes.value.some((t) => t.label === form.display_name)) {
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
    const [metaData] = await Promise.all([settingsApi.meta(), loadProviders(), loadTasks()])
    meta.value = metaData
    if (!form.base_url) applyTypeDefaults()
  } catch (error) {
    loadError.value = error.message
  } finally {
    loading.value = false
  }
}

async function saveProvider() {
  savingProvider.value = true
  try {
    const payload = {
      provider_type: form.provider_type,
      display_name: form.display_name || providerLabel(form.provider_type),
      base_url: form.base_url,
      is_enabled: form.is_enabled,
    }
    if (form.id !== null) payload.id = form.id
    // Empty key on edit = keep the stored one (backend enforces this too).
    if (form.api_key) payload.api_key = form.api_key

    const saved = await settingsApi.saveProvider(payload)
    await loadProviders()
    resetForm()
    flash('success', `Provider "${saved.display_name}" disimpan.`)
  } catch (error) {
    flash('error', `Gagal menyimpan provider: ${error.message}`)
  } finally {
    savingProvider.value = false
  }
}

async function removeProvider(provider) {
  if (!window.confirm(`Hapus provider "${provider.display_name}"?`)) return
  deletingId.value = provider.id
  try {
    await settingsApi.deleteProvider(provider.id)
    delete testResults[provider.id]
    if (form.id === provider.id) resetForm()
    await Promise.all([loadProviders(), loadTasks()])
    flash('success', `Provider "${provider.display_name}" dihapus.`)
  } catch (error) {
    flash('error', `Gagal menghapus provider: ${error.message}`)
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
  } catch (error) {
    testResults[provider.id] = { ok: false, message: error.message }
  } finally {
    testingId.value = null
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
    flash('error', `Gagal menyimpan routing ${task.label}: ${error.message}`)
  } finally {
    savingTask.value = null
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <header class="mb-8">
      <h1 class="text-2xl font-semibold tracking-tight text-white">Settings</h1>
      <p class="mt-1 text-sm text-slate-400">
        Kelola kredensial provider LLM dan model yang dipakai untuk tiap proses.
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
      Gagal memuat settings: {{ loadError }}
      <button class="ml-2 underline" @click="loadAll">coba lagi</button>
    </div>

    <p v-if="loading" class="text-sm text-slate-500">Memuat…</p>

    <template v-else>
      <!-- ============================ PROVIDERS ============================ -->
      <section class="mb-12">
        <div class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold text-white">LLM Providers</h2>
          <span class="text-xs text-slate-500">{{ providers.length }} tersimpan</span>
        </div>

        <div class="grid gap-6 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
          <!-- form -->
          <form class="card space-y-4 self-start" @submit.prevent="saveProvider">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-slate-200">
                {{ isEditing ? 'Edit provider' : 'Tambah provider' }}
              </h3>
              <button
                v-if="isEditing"
                type="button"
                class="text-xs text-slate-400 underline hover:text-slate-200"
                @click="resetForm"
              >
                batal
              </button>
            </div>

            <div>
              <label class="label" for="provider-type">Provider</label>
              <select
                id="provider-type"
                v-model="form.provider_type"
                class="input"
                @change="onTypeChange"
              >
                <option v-for="type in providerTypes" :key="type.value" :value="type.value">
                  {{ type.label }}
                </option>
              </select>
            </div>

            <div>
              <label class="label" for="display-name">Display name</label>
              <input
                id="display-name"
                v-model="form.display_name"
                class="input"
                type="text"
                :placeholder="currentType?.label ?? 'Nama provider'"
              />
            </div>

            <div>
              <label class="label" for="api-key">
                API Key
                <span v-if="!keyRequired" class="normal-case text-slate-500">(opsional)</span>
              </label>
              <input
                id="api-key"
                v-model="form.api_key"
                class="input font-mono"
                type="password"
                autocomplete="off"
                :placeholder="
                  isEditing ? 'Kosongkan untuk mempertahankan key lama' : 'Masukkan API key'
                "
              />
              <p class="mt-1 text-[11px] text-slate-500">
                Key disimpan lokal di SQLite dan hanya ditampilkan dalam bentuk masking
                (<code class="text-slate-400">****1234</code>).
              </p>
            </div>

            <div>
              <label class="label" for="base-url">Base URL</label>
              <input
                id="base-url"
                v-model="form.base_url"
                class="input font-mono text-xs"
                type="text"
                placeholder="https://…"
              />
              <p class="mt-1 text-[11px] text-slate-500">
                Terisi otomatis sesuai provider, tetap bisa diubah.
              </p>
            </div>

            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input
                v-model="form.is_enabled"
                type="checkbox"
                class="h-4 w-4 rounded border-ink-600 bg-ink-850 text-indigo-600 focus:ring-indigo-500"
              />
              Aktif (bisa dipakai untuk routing)
            </label>

            <button type="submit" class="btn-primary w-full" :disabled="savingProvider">
              {{ savingProvider ? 'Menyimpan…' : isEditing ? 'Update provider' : 'Tambah provider' }}
            </button>
          </form>

          <!-- list -->
          <div class="space-y-3">
            <p
              v-if="!hasProviders"
              class="rounded-xl border border-dashed border-ink-700 px-5 py-10 text-center text-sm text-slate-500"
            >
              Belum ada provider. Tambahkan satu di form sebelah kiri.
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
                      v-if="!provider.is_enabled"
                      class="badge bg-amber-950/60 text-amber-400"
                      >nonaktif</span
                    >
                  </div>
                  <p class="mt-1 font-mono text-[11px] text-slate-500">
                    {{ provider.base_url || '—' }}
                  </p>
                </div>
                <div class="flex items-center gap-2">
                  <button
                    class="btn-ghost !px-2.5 !py-1 text-xs"
                    :disabled="testingId === provider.id"
                    @click="testProvider(provider)"
                  >
                    {{ testingId === provider.id ? 'Menguji…' : 'Test Connection' }}
                  </button>
                  <button class="btn-ghost !px-2.5 !py-1 text-xs" @click="editProvider(provider)">
                    Edit
                  </button>
                  <button
                    class="btn-danger !px-2.5 !py-1 text-xs"
                    :disabled="deletingId === provider.id"
                    @click="removeProvider(provider)"
                  >
                    Hapus
                  </button>
                </div>
              </div>

              <div class="flex items-center gap-2 text-xs">
                <span class="text-slate-500">API key</span>
                <code
                  class="rounded bg-ink-850 px-2 py-0.5 font-mono text-slate-300"
                  :class="{ 'text-slate-600': !provider.has_api_key }"
                >
                  {{ provider.api_key || 'belum diisi' }}
                </code>
              </div>

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
                  {{ testResults[provider.id].ok ? 'Berhasil' : 'Gagal' }}
                </span>
                <span v-if="testResults[provider.id].model" class="text-slate-400">
                  · model {{ testResults[provider.id].model }}
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
          <h2 class="text-lg font-semibold text-white">Model Routing per Proses</h2>
          <span class="text-xs text-slate-500">3 slot</span>
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
              <h3 class="text-sm font-semibold text-slate-100">{{ task.label }}</h3>
              <p class="mt-0.5 font-mono text-[11px] text-slate-500">{{ task.task_name }}</p>
            </div>

            <div>
              <label class="label" :for="`provider-${task.task_name}`">Provider</label>
              <select
                :id="`provider-${task.task_name}`"
                v-model="taskDrafts[task.task_name].provider_id"
                class="input"
              >
                <option :value="null">— belum dipilih —</option>
                <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                  {{ provider.display_name }}
                  <template v-if="!provider.is_enabled"> (nonaktif)</template>
                </option>
              </select>
            </div>

            <div>
              <label class="label" :for="`model-${task.task_name}`">Model</label>
              <input
                :id="`model-${task.task_name}`"
                v-model="taskDrafts[task.task_name].model_name"
                class="input font-mono text-xs"
                type="text"
                placeholder="mis. gemini-2.0-flash"
              />
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="label" :for="`temp-${task.task_name}`">Temperature</label>
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
                <label class="label" :for="`tokens-${task.task_name}`">Max tokens</label>
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

            <div class="mt-auto flex items-center gap-3">
              <button type="submit" class="btn-primary" :disabled="savingTask === task.task_name">
                {{ savingTask === task.task_name ? 'Menyimpan…' : 'Save' }}
              </button>
              <span v-if="taskSaved[task.task_name]" class="text-xs text-emerald-400">
                tersimpan ✓
              </span>
              <span
                v-else-if="!task.provider_id"
                class="text-xs text-amber-500/80"
              >
                belum dikonfigurasi
              </span>
            </div>
          </form>
        </div>
      </section>
    </template>
  </div>
</template>
