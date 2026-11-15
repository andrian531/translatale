<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { healthApi } from '@/api/settings'
import { useI18n } from '@/i18n'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const apiOnline = ref(null)

const { t, locale, setLocale, locales } = useI18n()
const { theme, toggleTheme } = useTheme()

const nav = [
  { to: '/library', key: 'common.nav.library' },
  { to: '/scrapers', key: 'common.nav.scrapers' },
  { to: '/settings', key: 'common.nav.settings' },
]

const apiLabel = computed(() => {
  if (apiOnline.value === null) return t('common.api.checking')
  return apiOnline.value ? t('common.api.online') : t('common.api.offline')
})

function isActive(item) {
  // The workspace lives under /novels/:id but belongs to the Library section.
  if (item.to === '/library') {
    return route.path === '/library' || route.path.startsWith('/novels')
  }
  return route.path === item.to
}

onMounted(async () => {
  try {
    await healthApi.check()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
  }
})
</script>

<template>
  <div class="flex min-h-full flex-col">
    <header class="border-b border-ink-800 bg-ink-900/80 backdrop-blur">
      <div class="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
        <RouterLink to="/library" class="flex items-center gap-2">
          <span
            class="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-sm font-bold text-white"
            >T</span
          >
          <span class="text-sm font-semibold tracking-tight text-strong">{{
            t('common.appName')
          }}</span>
        </RouterLink>

        <nav class="flex items-center gap-1">
          <RouterLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
            :class="
              isActive(item)
                ? 'bg-ink-800 text-strong'
                : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
            "
          >
            {{ t(item.key) }}
          </RouterLink>
        </nav>

        <div class="ml-auto flex items-center gap-3 text-xs">
          <div
            class="flex items-center overflow-hidden rounded-lg border border-ink-700"
            role="group"
            :aria-label="t('common.language')"
          >
            <button
              v-for="code in locales"
              :key="code"
              type="button"
              class="px-2 py-1 font-medium uppercase transition-colors"
              :class="
                locale === code
                  ? 'bg-indigo-600 text-white'
                  : 'bg-ink-850 text-slate-400 hover:text-slate-200'
              "
              :aria-pressed="locale === code"
              :title="code === 'en' ? 'English' : 'Bahasa Indonesia'"
              @click="setLocale(code)"
            >
              {{ code }}
            </button>
          </div>

          <button
            type="button"
            class="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-850 px-2 py-1 font-medium text-slate-300 transition-colors hover:bg-ink-800"
            :title="t('common.theme.label')"
            :aria-label="t('common.theme.label')"
            @click="toggleTheme()"
          >
            <svg
              v-if="theme === 'dark'"
              class="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path
                d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
              />
            </svg>
            <svg
              v-else
              class="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            >
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
            </svg>
            <span>{{ theme === 'dark' ? t('common.theme.dark') : t('common.theme.light') }}</span>
          </button>

          <div class="flex items-center gap-2">
            <span
              class="h-2 w-2 rounded-full"
              :class="
                apiOnline === null
                  ? 'bg-slate-600'
                  : apiOnline
                    ? 'bg-emerald-500'
                    : 'bg-rose-500'
              "
            />
            <span class="text-slate-500">{{ apiLabel }}</span>
          </div>
        </div>
      </div>
    </header>

    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>
