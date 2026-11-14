<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { healthApi } from '@/api/settings'

const route = useRoute()
const apiOnline = ref(null)

const nav = [
  { to: '/library', label: 'Library' },
  { to: '/settings', label: 'Settings' },
]

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
          <span class="text-sm font-semibold tracking-tight text-slate-100">Translatale</span>
        </RouterLink>

        <nav class="flex items-center gap-1">
          <RouterLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
            :class="
              route.path === item.to
                ? 'bg-ink-800 text-white'
                : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
            "
          >
            {{ item.label }}
          </RouterLink>
        </nav>

        <div class="ml-auto flex items-center gap-2 text-xs">
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
          <span class="text-slate-500">
            {{ apiOnline === null ? 'checking API…' : apiOnline ? 'API online' : 'API offline' }}
          </span>
        </div>
      </div>
    </header>

    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>
