import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { conversationsApi } from '@/api/conversations'
import { cloudConsentApi } from '@/api/cloudConsent'
import { bumpEpoch } from '@/api/session'
import { useChatStore } from './chat'
import { mockAnswered } from '@/mocks/fixtures'
vi.mock('@/api/conversations', () => ({conversationsApi: {list: vi.fn(), create: vi.fn(), messages: vi.fn(), ask: vi.fn(), rename: vi.fn(), remove: vi.fn()}}))
vi.mock('@/api/cloudConsent', () => ({cloudConsentApi: {list: vi.fn(), targets: vi.fn()}}))
const grants = ['embedding', 'reranking', 'generation'].map(purpose => ({purpose, service_key: purpose, revoked_at: null}))
beforeEach(() => {
  setActivePinia(createPinia()); vi.clearAllMocks()
  vi.mocked(cloudConsentApi.list).mockResolvedValue(grants as never)
  vi.mocked(cloudConsentApi.targets).mockResolvedValue(grants as never)
  vi.mocked(conversationsApi.create).mockResolvedValue({conversation: {id: 'one', title: 'AVL', updated_at: ''}})
  vi.mocked(conversationsApi.messages).mockResolvedValue({items: [], total: 0})
  vi.mocked(conversationsApi.list).mockResolvedValue({items: [], total: 0})
  vi.mocked(conversationsApi.ask).mockResolvedValue(mockAnswered)
})
it('creates an owned conversation and fixes auto/hybrid using only active grants', async () => {
  const chat = useChatStore(); await chat.send('AVL', ['kb'])
  expect(conversationsApi.ask).toHaveBeenCalledWith('one', expect.objectContaining({query: 'AVL', answer_mode: 'auto', retrieval_mode: 'hybrid', allow_cloud: true, allow_cloud_rerank: true, allow_cloud_generation: true}))
  expect(chat.pending).toBeNull()
})
it('reuses request id and original scope after timeout; blocks duplicate in-flight sends', async () => {
  const chat = useChatStore()
  vi.mocked(conversationsApi.ask).mockRejectedValueOnce(new Error('timeout'))
  await chat.send('AVL', ['kb']); const original = chat.pending!.payload
  await chat.send('ignored', ['different'])
  expect(conversationsApi.create).toHaveBeenCalledTimes(1)
  expect(conversationsApi.ask).toHaveBeenLastCalledWith('one', original)
})
it('does not request cloud permission without matching active grants', async () => {
  vi.mocked(cloudConsentApi.list).mockResolvedValue([])
  await useChatStore().send('AVL', ['kb'])
  expect(conversationsApi.ask).toHaveBeenCalledWith('one', expect.objectContaining({allow_cloud: false, allow_cloud_generation: false}))
})
it('logout invalidates late replies and clears all private history', async () => {
  let resolve!: (value: typeof mockAnswered) => void
  vi.mocked(conversationsApi.ask).mockImplementation(() => new Promise(r => {resolve = r}))
  const chat = useChatStore(); const pending = chat.send('AVL', ['kb'])
  await vi.waitFor(() => expect(conversationsApi.ask).toHaveBeenCalled())
  await chat.send('duplicate', ['kb']); expect(conversationsApi.ask).toHaveBeenCalledTimes(1)
  chat.clear(); bumpEpoch(); resolve(mockAnswered); await pending
  expect(chat.messages).toEqual([]); expect(chat.active).toBeNull(); expect(chat.pending).toBeNull()
})
it('ignores an older conversation load after switching', async () => {
  let resolve!: (value: {items: never[]; total: number}) => void
  vi.mocked(conversationsApi.messages).mockImplementationOnce(() => new Promise(r => {resolve = r}))
  const chat = useChatStore(); const first = chat.open('old'); await chat.open('new')
  resolve({items: [], total: 9}); await first
  expect(chat.active).toBe('new'); expect(chat.messageTotal).toBe(0)
})
it('new conversation resets paging and loading after a stale history load', () => {
  const chat = useChatStore(); chat.messageOffset = 200; chat.messageTotal = 300; chat.loading = true
  chat.newChat(); expect(chat.messageOffset).toBe(0); expect(chat.messageTotal).toBe(0); expect(chat.loading).toBe(false)
})
it('loads latest history first, then prepends older messages without duplicates', async () => {
  const chat = useChatStore()
  const msg = (seq: number) => ({id: String(seq), seq, role: 'user' as const, content: String(seq), metadata_json: {}})
  vi.mocked(conversationsApi.messages).mockResolvedValueOnce({items: [msg(1)], total: 201}).mockResolvedValueOnce({items: [msg(102),msg(103)], total: 201}).mockResolvedValueOnce({items: [msg(2),msg(102)], total: 201})
  await chat.open('one'); expect(chat.messageOffset).toBe(101)
  await chat.moreMessages(); expect(chat.messages.map(m => m.seq)).toEqual([2,102,103]); expect(chat.messageOffset).toBe(1)
})
