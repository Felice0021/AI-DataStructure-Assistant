<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { cloudConsentApi, type CloudConsent, type CloudPurpose, type CloudTarget } from '@/api/cloudConsent'
import { currentEpoch } from '@/api/session'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'

const kbStore = useKnowledgeBaseStore()
const selected = ref('')
const records = ref<CloudConsent[]>([])
const targets = ref<CloudTarget[]>([])
const error = ref('')
const busy = ref(false)
let sequence = 0
const selectedKbs = computed(() => kbStore.items.filter((kb) => kbStore.selectedIds.includes(kb.id)))
const purposes: { id: CloudPurpose; label: string }[] = [
  { id: 'embedding', label: '向量化及查询向量' },
  { id: 'reranking', label: '云端重排序' },
  { id: 'generation', label: '云端回答生成' },
]
// Historical consent records may refer to old models; show their model explicitly.
function activeFor(purpose: CloudPurpose): boolean {
  const target = targets.value.find((item) => item.purpose === purpose)
  return !!target && records.value.some((record) => record.purpose === purpose && record.service_key === target.service_key && !record.revoked_at)
}
async function load(): Promise<void> {
  const id = selected.value
  const epoch = currentEpoch()
  const seq = ++sequence
  records.value = []
  targets.value = []
  error.value = ''
  if (!id) return
  busy.value = true
  try {
    const [data, currentTargets] = await Promise.all([cloudConsentApi.list(id), cloudConsentApi.targets(id)])
    if (epoch === currentEpoch() && seq === sequence) { records.value = data; targets.value = currentTargets }
  } catch {
    if (epoch === currentEpoch() && seq === sequence) error.value = '无法读取授权状态，请重试。'
  } finally {
    if (seq === sequence) busy.value = false
  }
}
async function change(purpose: CloudPurpose, grant: boolean): Promise<void> {
  const id = selected.value
  const target = targets.value.find((item) => item.purpose === purpose)
  if (!id || !target || busy.value) return
  const epoch = currentEpoch()
  busy.value = true
  error.value = ''
  try {
    await cloudConsentApi.change(id, purpose, grant, target.service_key)
    if (epoch === currentEpoch() && id === selected.value) await load()
  } catch {
    if (epoch === currentEpoch() && id === selected.value) error.value = '授权操作失败，请检查权限及服务配置。'
  } finally {
    busy.value = false
  }
}
watch(selectedKbs, (items) => {
  if (!items.some((item) => item.id === selected.value)) selected.value = items[0]?.id ?? ''
}, { immediate: true })
watch(selected, () => { void load() }, { immediate: true })
</script>

<template>
  <details class="cloud-consent">
    <summary>管理知识库云端处理授权</summary>
    <p>授权允许所选知识库的资料或问题发送至云服务。按用途分别授权，可随时撤销；每次提问仍需单独选择云端用途。</p>
    <label>知识库
      <select v-model="selected" :disabled="busy || !selectedKbs.length">
        <option v-for="kb in selectedKbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
      </select>
    </label>
    <p v-if="!selectedKbs.length">请先选择有权访问的知识库。</p>
    <div v-for="purpose in purposes" :key="purpose.id" class="purpose">
      <span>{{ purpose.label }}（{{ targets.find((t) => t.purpose === purpose.id)?.model ?? '模型未知' }}）：{{ activeFor(purpose.id) ? '已授权' : '未授权' }}</span>
      <button type="button" :disabled="busy || !selected || !targets.find((t) => t.purpose === purpose.id)" @click="change(purpose.id, true)">授权当前模型</button>
      <button type="button" :disabled="busy || !selected || !targets.find((t) => t.purpose === purpose.id)" @click="change(purpose.id, false)">撤销当前模型</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
  </details>
</template>

<style scoped>
.cloud-consent { font-size: 13px; color: var(--ink); }
.purpose { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
</style>
