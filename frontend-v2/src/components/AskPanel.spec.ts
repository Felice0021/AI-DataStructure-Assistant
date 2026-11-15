import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { cloudConsentApi } from '@/api/cloudConsent'
import { ragApi } from '@/api/rag'
import { mockAnswered } from '@/mocks/fixtures'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import AskPanel from './AskPanel.vue'

vi.mock('@/api/cloudConsent', () => ({ cloudConsentApi: { list: vi.fn(), targets: vi.fn() } }))
vi.mock('@/api/rag', () => ({ ragApi: { ask: vi.fn() } }))
const targets = ['embedding', 'reranking', 'generation'].map((purpose) => ({ purpose, model: 'model', service_key: purpose })) as Awaited<ReturnType<typeof cloudConsentApi.targets>>
beforeEach(() => {
  setActivePinia(createPinia()); vi.clearAllMocks()
  useKnowledgeBaseStore().selectedIds = ['kb']
  vi.mocked(cloudConsentApi.targets).mockResolvedValue(targets)
  vi.mocked(ragApi.ask).mockResolvedValue(mockAnswered)
})
it('automatically uses matching active grants without showing cloud checkboxes', async () => {
  vi.mocked(cloudConsentApi.list).mockResolvedValue(targets.map((x) => ({ ...x, revoked_at: null })))
  const wrapper = mount(AskPanel)
  await wrapper.find('textarea').setValue('栈是什么？')
  await wrapper.find('button.submit').trigger('click'); await flushPromises()
  expect(wrapper.find('input[type=checkbox]').exists()).toBe(false)
  expect(ragApi.ask).toHaveBeenCalledWith(expect.objectContaining({ allow_cloud: true, allow_cloud_rerank: true, allow_cloud_generation: true }))
})
it('does not treat revoked, missing, or different-model grants as authorization', async () => {
  vi.mocked(cloudConsentApi.list).mockResolvedValue([{ ...targets[0]!, revoked_at: '2026-01-01' }, { ...targets[1]!, service_key: 'old', revoked_at: null }])
  const wrapper = mount(AskPanel)
  await wrapper.find('textarea').setValue('栈是什么？')
  await wrapper.find('button.submit').trigger('click'); await flushPromises()
  expect(ragApi.ask).toHaveBeenCalledWith(expect.objectContaining({ allow_cloud: false, allow_cloud_rerank: false, allow_cloud_generation: false }))
})
