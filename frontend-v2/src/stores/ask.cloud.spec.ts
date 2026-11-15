import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ragApi } from '@/api/rag'
import { mockAnswered } from '@/mocks/fixtures'
import { useAskStore } from './ask'

vi.mock('@/api/rag', () => ({ ragApi: { ask: vi.fn() } }))
describe('per-request cloud flags', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.mocked(ragApi.ask).mockResolvedValue(mockAnswered) })
  it('defaults to no cloud consent and forwards only explicit options', async () => {
    const store = useAskStore()
    const base = { query: 'q', knowledgeBaseIds: ['k'], answerMode: 'qa' as const, retrievalMode: 'hybrid' as const }
    await store.ask(base)
    expect(ragApi.ask).toHaveBeenLastCalledWith(expect.objectContaining({ allow_cloud: false, allow_cloud_rerank: false, allow_cloud_generation: false, rerank: 'off' }))
    await store.ask({ ...base, allowCloud: true, allowCloudRerank: true, allowCloudGeneration: true })
    expect(ragApi.ask).toHaveBeenLastCalledWith(expect.objectContaining({ allow_cloud: true, allow_cloud_rerank: true, allow_cloud_generation: true, rerank: 'required' }))
  })
})
