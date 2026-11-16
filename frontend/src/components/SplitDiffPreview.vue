<template>
  <div class="rounded-xl border border-ink-700 bg-ink-950 overflow-hidden">
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 bg-ink-900 px-3 py-2 text-xs">
      <div class="flex flex-wrap items-center gap-2">
        <span class="font-semibold text-strong">{{ title }}</span>
        <span class="rounded border border-emerald-700/70 bg-emerald-950/60 px-1.5 py-0.5 font-mono text-[11px] text-emerald-400">
          +{{ stats.added }}
        </span>
        <span class="rounded border border-rose-700/70 bg-rose-950/40 px-1.5 py-0.5 font-mono text-[11px] text-rose-400">
          -{{ stats.removed }}
        </span>
        <span v-if="stats.added === 0 && stats.removed === 0" class="text-[11px] text-slate-400">
          {{ noChangesLabel }}
        </span>
      </div>
      <label class="flex cursor-pointer select-none items-center gap-1.5 text-[11px] text-slate-300">
        <input
          v-model="onlyChanged"
          type="checkbox"
          class="h-3.5 w-3.5 rounded border-ink-600 bg-ink-850 text-indigo-600"
        />
        {{ changesOnlyLabel }}
      </label>
    </div>

    <div class="grid grid-cols-2 border-b border-ink-700 bg-ink-850 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
      <div class="border-r border-ink-700 px-3 py-1.5">{{ beforeLabel }}</div>
      <div class="px-3 py-1.5">{{ afterLabel }}</div>
    </div>

    <div class="max-h-[62vh] overflow-y-auto font-mono text-xs leading-relaxed">
      <div
        v-for="(row, idx) in visibleRows"
        :key="idx"
        class="grid grid-cols-2 border-b border-ink-800/70 last:border-b-0"
      >
        <!-- Left (Before) -->
        <div
          class="flex min-w-0 border-r border-ink-700"
          :class="
            row.leftType === 'removed'
              ? 'bg-rose-950/30 text-rose-300'
              : row.leftType === 'empty'
                ? 'bg-ink-900/50 text-slate-600'
                : 'text-slate-300'
          "
        >
          <span class="w-10 shrink-0 select-none border-r border-ink-800/70 px-1.5 py-1 text-right text-[10px] text-slate-500">
            {{ row.leftNo ?? '' }}
          </span>
          <span class="w-5 shrink-0 select-none py-1 text-center font-bold" :class="row.leftType === 'removed' ? 'text-rose-400' : 'text-slate-600'">
            {{ row.leftType === 'removed' ? '-' : '' }}
          </span>
          <div class="min-w-0 flex-1 whitespace-pre-wrap break-words py-1 pr-2">
            {{ row.leftText }}
          </div>
        </div>

        <!-- Right (After) -->
        <div
          class="flex min-w-0"
          :class="
            row.rightType === 'added'
              ? 'bg-emerald-950/30 text-emerald-300'
              : row.rightType === 'empty'
                ? 'bg-ink-900/50 text-slate-600'
                : 'text-slate-300'
          "
        >
          <span class="w-10 shrink-0 select-none border-r border-ink-800/70 px-1.5 py-1 text-right text-[10px] text-slate-500">
            {{ row.rightNo ?? '' }}
          </span>
          <span class="w-5 shrink-0 select-none py-1 text-center font-bold" :class="row.rightType === 'added' ? 'text-emerald-400' : 'text-slate-600'">
            {{ row.rightType === 'added' ? '+' : '' }}
          </span>
          <div class="min-w-0 flex-1 whitespace-pre-wrap break-words py-1 pr-2">
            {{ row.rightText }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  beforeText: { type: String, default: '' },
  afterText: { type: String, default: '' },
  title: { type: String, default: 'Preview' },
  beforeLabel: { type: String, default: 'Before' },
  afterLabel: { type: String, default: 'After' },
  changesOnlyLabel: { type: String, default: 'Show changes only' },
  noChangesLabel: { type: String, default: 'No changes' },
})

const onlyChanged = ref(false)

function computeLineOps(aLines, bLines) {
  const m = aLines.length
  const n = bLines.length
  // Guard for very large texts: fall back to simple index-by-index pairing
  if (m * n > 250000) {
    const ops = []
    const len = Math.max(m, n)
    for (let i = 0; i < len; i++) {
      if (i < m && i < n) {
        if (aLines[i] === bLines[i]) {
          ops.push({ type: 'equal', left: aLines[i], right: bLines[i], leftNo: i + 1, rightNo: i + 1 })
        } else {
          ops.push({ type: 'removed', left: aLines[i], leftNo: i + 1 })
          ops.push({ type: 'added', right: bLines[i], rightNo: i + 1 })
        }
      } else if (i < m) {
        ops.push({ type: 'removed', left: aLines[i], leftNo: i + 1 })
      } else {
        ops.push({ type: 'added', right: bLines[i], rightNo: i + 1 })
      }
    }
    return ops
  }

  const dp = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (aLines[i] === bLines[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1
      } else {
        dp[i][j] = dp[i + 1][j] >= dp[i][j + 1] ? dp[i + 1][j] : dp[i][j + 1]
      }
    }
  }

  const ops = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    if (aLines[i] === bLines[j]) {
      ops.push({ type: 'equal', left: aLines[i], right: bLines[j], leftNo: i + 1, rightNo: j + 1 })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'removed', left: aLines[i], leftNo: i + 1 })
      i++
    } else {
      ops.push({ type: 'added', right: bLines[j], rightNo: j + 1 })
      j++
    }
  }
  while (i < m) {
    ops.push({ type: 'removed', left: aLines[i], leftNo: i + 1 })
    i++
  }
  while (j < n) {
    ops.push({ type: 'added', right: bLines[j], rightNo: j + 1 })
    j++
  }
  return ops
}

const splitRows = computed(() => {
  const aLines = (props.beforeText || '').split(/\r?\n/)
  const bLines = (props.afterText || '').split(/\r?\n/)
  const ops = computeLineOps(aLines, bLines)

  const rows = []
  let k = 0
  while (k < ops.length) {
    const op = ops[k]
    if (op.type === 'equal') {
      rows.push({
        leftType: 'equal',
        rightType: 'equal',
        leftNo: op.leftNo,
        rightNo: op.rightNo,
        leftText: op.left,
        rightText: op.right,
      })
      k++
      continue
    }

    const removed = []
    const added = []
    while (k < ops.length && ops[k].type !== 'equal') {
      if (ops[k].type === 'removed') removed.push(ops[k])
      else added.push(ops[k])
      k++
    }
    const maxLen = Math.max(removed.length, added.length)
    for (let idx = 0; idx < maxLen; idx++) {
      const r = removed[idx]
      const a = added[idx]
      rows.push({
        leftType: r ? 'removed' : 'empty',
        rightType: a ? 'added' : 'empty',
        leftNo: r ? r.leftNo : null,
        rightNo: a ? a.rightNo : null,
        leftText: r ? r.left : '',
        rightText: a ? a.right : '',
      })
    }
  }
  return rows
})

const stats = computed(() => {
  let added = 0
  let removed = 0
  for (const r of splitRows.value) {
    if (r.leftType === 'removed') removed++
    if (r.rightType === 'added') added++
  }
  return { added, removed }
})

const visibleRows = computed(() => {
  if (!onlyChanged.value) return splitRows.value
  return splitRows.value.filter((r) => r.leftType !== 'equal' || r.rightType !== 'equal')
})
</script>
