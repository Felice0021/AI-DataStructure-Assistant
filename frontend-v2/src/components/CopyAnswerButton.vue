<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue'

const props = defineProps<{ text: string }>()
const state = ref<'idle' | 'copying' | 'copied' | 'failed'>('idle')
const tooltipId = useId()
let timer: ReturnType<typeof setTimeout> | undefined
let revision = 0
const label = computed(() => state.value === 'copied' ? '已复制' : state.value === 'failed' ? '复制失败，请手动选择正文' : '复制回答')
function reset() { revision++; clearTimeout(timer); state.value = 'idle' }
watch(() => props.text, reset)
onUnmounted(reset)
async function copy() {
  if (state.value === 'copying') return
  const current = ++revision
  clearTimeout(timer)
  state.value = 'copying'
  try {
    await navigator.clipboard.writeText(props.text)
    if (current !== revision) return
    state.value = 'copied'
  } catch {
    if (current !== revision) return
    state.value = 'failed'
  }
  timer = setTimeout(() => { state.value = 'idle' }, 2200)
}
</script>

<template>
  <span class="copy-answer" :data-state="state">
    <button type="button" class="copy-button" :aria-label="label" :aria-describedby="tooltipId" :disabled="state === 'copying'" @click="copy">
      <svg v-if="state === 'copied'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m5 12 4 4L19 6" stroke-linecap="round" stroke-linejoin="round" /></svg>
      <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h1" stroke-linecap="round" /></svg>
    </button>
    <span :id="tooltipId" role="tooltip" class="copy-tooltip">{{ label }}</span>
    <span class="sr-only" role="status" aria-live="polite">{{ state === 'copied' || state === 'failed' ? label : '' }}</span>
  </span>
</template>

<style scoped>
.copy-answer { position: relative; display: inline-flex; margin: 4px 0 0 -10px; }
.copy-button { display: grid; place-items: center; width: 40px; height: 40px; padding: 0; border: 0; border-radius: 8px; color: #737373; background: transparent; cursor: pointer; }
.copy-button:hover { background: #f5f5f5; color: #262626; }
.copy-button:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.copy-button:disabled { cursor: progress; }
.copy-tooltip { position: absolute; z-index: 4; left: 0; bottom: calc(100% + 3px); padding: 6px 9px; border-radius: 6px; font-size: 12px; line-height: 1.5; color: #fff; background: #262626; white-space: nowrap; visibility: hidden; pointer-events: none; }
.copy-answer:hover .copy-tooltip, .copy-answer:focus-within .copy-tooltip, .copy-answer[data-state="copied"] .copy-tooltip, .copy-answer[data-state="failed"] .copy-tooltip { visibility: visible; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (max-width: 760px) { .copy-button { width: 44px; height: 44px; } }
</style>
