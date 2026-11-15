<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from '@/i18n'

const props = defineProps({
  modelValue: { type: String, default: '' },
  models: { type: Array, default: () => [] },
  placeholder: { type: String, default: '' },
  emptyHint: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const root = ref(null)
const input = ref(null)
const open = ref(false)
const query = ref('')
const highlighted = ref(-1)

const placeholderText = computed(() => props.placeholder || t('common.modelSelect.placeholder'))
const emptyHintText = computed(() => props.emptyHint || t('common.modelSelect.emptyHint'))

const options = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const list = needle
    ? props.models.filter((model) => model.toLowerCase().includes(needle))
    : props.models
  return list.slice(0, 200)
})

const isEmpty = computed(() => props.models.length === 0)

function openList() {
  if (props.disabled) return
  open.value = true
  query.value = ''
  highlighted.value = options.value.length ? 0 : -1
}

function onFocus(event) {
  openList()
  event.target.select?.()
}

function onInput(event) {
  const value = event.target.value
  emit('update:modelValue', value)
  query.value = value
  open.value = true
  highlighted.value = options.value.length ? 0 : -1
}

function choose(model) {
  emit('update:modelValue', model)
  query.value = ''
  open.value = false
  highlighted.value = -1
  input.value?.blur()
}

function clear() {
  emit('update:modelValue', '')
  query.value = ''
  highlighted.value = -1
}

function move(delta) {
  if (!open.value) {
    openList()
    return
  }
  if (!options.value.length) return
  const count = options.value.length
  highlighted.value = (highlighted.value + delta + count) % count
}

function onKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (event.key === 'Enter') {
    if (open.value && highlighted.value >= 0 && options.value[highlighted.value]) {
      event.preventDefault()
      choose(options.value[highlighted.value])
    } else {
      open.value = false
    }
  } else if (event.key === 'Escape') {
    open.value = false
  }
}

function onBlur() {
  // Let an option's mousedown land first, then hide the list when focus leaves.
  window.setTimeout(() => {
    open.value = false
  }, 120)
}

function onPointerDownOutside(event) {
  if (root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onPointerDownOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onPointerDownOutside))
</script>

<template>
  <div ref="root" class="relative">
    <div class="relative">
      <input
        ref="input"
        :value="modelValue"
        :placeholder="placeholderText"
        :disabled="disabled"
        class="input !pr-16 font-mono text-xs"
        type="text"
        autocomplete="off"
        role="combobox"
        :aria-expanded="open"
        @focus="onFocus"
        @blur="onBlur"
        @input="onInput"
        @keydown="onKeydown"
        @click="openList"
      />
      <div class="absolute inset-y-0 right-2 flex items-center gap-1">
        <button
          v-if="modelValue"
          type="button"
          class="px-1 text-[11px] text-slate-500 hover:text-slate-200"
          :title="t('common.modelSelect.clear')"
          @click="clear"
        >
          ✕
        </button>
        <span
          class="text-[10px] tabular-nums text-slate-500"
          :title="t('common.modelSelect.savedCount', { count: models.length })"
        >
          {{ models.length }}
        </span>
        <span class="text-[10px] text-slate-500">▾</span>
      </div>
    </div>

    <div
      v-if="open"
      class="absolute z-30 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-ink-700 bg-ink-900 py-1 shadow-xl shadow-black/40"
    >
      <p v-if="isEmpty" class="px-3 py-2 text-[11px] leading-relaxed text-amber-400">
        {{ emptyHintText }}
      </p>
      <template v-else>
        <p
          v-if="!options.length"
          class="px-3 py-2 text-[11px] text-slate-500"
        >
          {{ t('common.modelSelect.noMatch') }}
        </p>
        <button
          v-for="(model, index) in options"
          :key="model"
          type="button"
          class="block w-full truncate px-3 py-1.5 text-left font-mono text-[11px]"
          :class="
            index === highlighted ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:bg-ink-800'
          "
          @mousedown.prevent="choose(model)"
        >
          {{ model }}
        </button>
      </template>
    </div>
  </div>
</template>
