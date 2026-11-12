import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloudConsentApi } from '@/api/cloudConsent'
import { mockKnowledgeBases } from '@/mocks/fixtures'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import CloudConsentPanel from './CloudConsentPanel.vue'

vi.mock('@/api/cloudConsent', () => ({
  cloudConsentApi: { list: vi.fn(), targets: vi.fn(), change: vi.fn() },
}))

describe('cloud consent controls', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(cloudConsentApi.list).mockResolvedValue([])
    vi.mocked(cloudConsentApi.targets).mockResolvedValue(['embedding', 'reranking', 'generation'].map((purpose) => ({ purpose, model: 'test-model', service_key: purpose })) as Awaited<ReturnType<typeof cloudConsentApi.targets>>)
  })
  it('requires a selected accessible knowledge base and issues explicit per-purpose actions', async () => {
    const store = useKnowledgeBaseStore()
    const wrapper = mount(CloudConsentPanel)
    expect(wrapper.text()).toContain('请先选择有权访问的知识库')
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    store.items = [...mockKnowledgeBases]
    const id = store.items[0]!.id
    store.selectedIds = [id]
    await flushPromises()
    expect(cloudConsentApi.list).toHaveBeenCalledWith(id)
    await wrapper.findAll('button')[0]!.trigger('click')
    await flushPromises()
    expect(cloudConsentApi.change).toHaveBeenCalledWith(id, 'embedding', true, 'embedding')
    await wrapper.findAll('button')[5]!.trigger('click')
    await flushPromises()
    expect(cloudConsentApi.change).toHaveBeenCalledWith(id, 'generation', false, 'generation')
  })
})
