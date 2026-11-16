<template>
  <div
    ref="hostRef"
    class="cm-line-editor h-[55vh] min-h-[320px] resize-y overflow-hidden rounded-lg border border-ink-700 bg-ink-950 text-xs focus-within:border-indigo-500"
  />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Compartment, EditorState, RangeSetBuilder, StateEffect, StateField } from '@codemirror/state'
import { Decoration, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder as cmPlaceholder } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  highlightedLines: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue'])

const hostRef = ref(null)
let view = null
let suppressEmit = false
const placeholderCompartment = new Compartment()

const setHighlightedLinesEffect = StateEffect.define()
const flaggedLineDeco = Decoration.line({ class: 'cm-flagged-line' })

const highlightedLinesField = StateField.define({
  create() {
    return Decoration.none
  },
  update(decos, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setHighlightedLinesEffect)) {
        return buildHighlightDecos(tr.state.doc, effect.value)
      }
    }
    if (tr.docChanged) {
      return decos.map(tr.changes)
    }
    return decos
  },
  provide: (field) => EditorView.decorations.from(field),
})

function buildHighlightDecos(doc, lineNumbersList) {
  const builder = new RangeSetBuilder()
  const uniqueSorted = [...new Set((lineNumbersList || []).filter((n) => Number.isInteger(n) && n >= 1 && n <= doc.lines))].sort((a, b) => a - b)
  for (const lineNo of uniqueSorted) {
    const line = doc.line(lineNo)
    builder.add(line.from, line.from, flaggedLineDeco)
  }
  return builder.finish()
}

const editorTheme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'rgb(var(--ink-950))',
    color: 'rgb(var(--slate-200))',
    fontSize: '12px',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
    lineHeight: '1.6',
  },
  '.cm-content': {
    padding: '8px 0',
  },
  '.cm-line': {
    padding: '0 10px',
  },
  '.cm-gutters': {
    backgroundColor: 'rgb(var(--ink-900))',
    color: 'rgb(var(--slate-500))',
    borderRight: '1px solid rgb(var(--ink-700))',
    userSelect: 'none',
  },
  '.cm-lineNumbers .cm-gutterElement': {
    padding: '0 8px 0 10px',
    minWidth: '36px',
  },
  '.cm-activeLine': {
    backgroundColor: 'rgba(99, 102, 241, 0.08)',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'rgba(99, 102, 241, 0.14)',
    color: 'rgb(var(--slate-200))',
  },
  '.cm-flagged-line': {
    backgroundColor: 'rgba(245, 158, 11, 0.16)',
  },
  '.cm-cursor': {
    borderLeftColor: 'rgb(var(--slate-200))',
  },
  '.cm-placeholder': {
    color: 'rgb(var(--slate-500))',
  },
})

onMounted(() => {
  const startState = EditorState.create({
    doc: props.modelValue || '',
    extensions: [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.lineWrapping,
      placeholderCompartment.of(cmPlaceholder(props.placeholder || '')),
      highlightedLinesField,
      editorTheme,
      EditorView.updateListener.of((update) => {
        if (update.docChanged && !suppressEmit) {
          emit('update:modelValue', update.state.doc.toString())
        }
      }),
    ],
  })

  view = new EditorView({
    state: startState,
    parent: hostRef.value,
  })

  if (props.highlightedLines?.length) {
    view.dispatch({
      effects: setHighlightedLinesEffect.of(props.highlightedLines),
    })
  }
})

watch(
  () => props.modelValue,
  (next) => {
    if (!view) return
    const current = view.state.doc.toString()
    const target = next || ''
    if (current === target) return
    suppressEmit = true
    view.dispatch({
      changes: { from: 0, to: current.length, insert: target },
    })
    suppressEmit = false
  },
)

watch(
  () => props.highlightedLines,
  (lines) => {
    if (!view) return
    view.dispatch({
      effects: setHighlightedLinesEffect.of(lines || []),
    })
  },
  { deep: true },
)

watch(
  () => props.placeholder,
  (next) => {
    if (!view) return
    view.dispatch({
      effects: placeholderCompartment.reconfigure(cmPlaceholder(next || '')),
    })
  },
)

onBeforeUnmount(() => {
  view?.destroy()
  view = null
})
</script>
