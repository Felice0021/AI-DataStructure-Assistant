import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { conversationsApi } from '@/api/conversations'
import { cloudConsentApi } from '@/api/cloudConsent'
import { bumpEpoch } from '@/api/session'
import { useChatStore } from './chat'
import { mockAnswered } from '@/mocks/fixtures'
vi.mock('@/api/conversations', () => ({conversationsApi: {list: vi.fn(), get: vi.fn(), create: vi.fn(), messages: vi.fn(), ask: vi.fn(), askStream: vi.fn(), rename: vi.fn(), remove: vi.fn(), move: vi.fn()}}))
vi.mock('@/api/projects', () => ({projectsApi: {list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), memories: vi.fn(), forget: vi.fn()}}))
vi.mock('@/api/cloudConsent', () => ({cloudConsentApi: {list: vi.fn(), targets: vi.fn()}}))
const grants = ['embedding', 'reranking', 'generation'].map(purpose => ({purpose, service_key: purpose, revoked_at: null}))
beforeEach(() => {
  setActivePinia(createPinia()); vi.clearAllMocks()
  vi.mocked(cloudConsentApi.list).mockResolvedValue(grants as never)
  vi.mocked(cloudConsentApi.targets).mockResolvedValue(grants as never)
  vi.mocked(conversationsApi.create).mockResolvedValue({conversation: {id: 'one', title: 'AVL', updated_at: ''}})
  vi.mocked(conversationsApi.get).mockResolvedValue({conversation: {id: 'one', title: 'AVL', project_id: null, updated_at: ''}})
  vi.mocked(conversationsApi.messages).mockResolvedValue({items: [], total: 0})
  vi.mocked(conversationsApi.list).mockResolvedValue({items: [], total: 0})
  vi.mocked(conversationsApi.askStream).mockResolvedValue(mockAnswered)
})
it('creates an owned conversation and fixes auto/hybrid using only active grants', async () => {
  const chat = useChatStore(); await chat.send('AVL', ['kb'])
  expect(conversationsApi.create).toHaveBeenCalledWith('AVL', null)
  expect(conversationsApi.askStream).toHaveBeenCalledWith('one', expect.objectContaining({query: 'AVL', answer_mode: 'auto', retrieval_mode: 'hybrid', allow_cloud: true, allow_cloud_rerank: true, allow_cloud_generation: true}), expect.any(Function), expect.any(AbortSignal))
  expect(chat.pending).toBeNull()
})
it('keeps project selection scoped to new conversations and wipes private projects on logout', async () => {
  const chat = useChatStore()
  chat.projects = [{id: 'project-1', title: '二叉树', description: '', memory_source_ids: [], created_at: '', updated_at: ''}]
  chat.selectProject('project-1')
  await chat.send('AVL', ['kb'])
  expect(conversationsApi.create).toHaveBeenCalledWith('AVL', 'project-1')
  chat.newChat()
  expect(chat.activeProject).toBe('project-1')
  chat.selectProject(null)
  expect(chat.activeProject).toBeNull()
  chat.clear()
  expect(chat.projects).toEqual([])
  expect(chat.activeProject).toBeNull()
})
it('reuses request id and original scope after timeout; blocks duplicate in-flight sends', async () => {
  const chat = useChatStore()
  vi.mocked(conversationsApi.askStream).mockRejectedValueOnce(new Error('timeout'))
  await chat.send('AVL', ['kb']); const original = chat.pending!.payload
  await chat.send('ignored', ['different'])
  expect(conversationsApi.create).toHaveBeenCalledTimes(1)
  expect(conversationsApi.askStream).toHaveBeenLastCalledWith('one', original, expect.any(Function), expect.any(AbortSignal))
})
it('does not request cloud permission without matching active grants', async () => {
  vi.mocked(cloudConsentApi.list).mockResolvedValue([])
  await useChatStore().send('AVL', ['kb'])
  expect(conversationsApi.askStream).toHaveBeenCalledWith('one', expect.objectContaining({allow_cloud: false, allow_cloud_generation: false}), expect.any(Function), expect.any(AbortSignal))
})
it('logout invalidates late replies and clears all private history', async () => {
  let resolve!: (value: typeof mockAnswered) => void
  vi.mocked(conversationsApi.askStream).mockImplementation(() => new Promise(r => {resolve = r}))
  const chat = useChatStore(); const pending = chat.send('AVL', ['kb'])
  await vi.waitFor(() => expect(conversationsApi.askStream).toHaveBeenCalled())
  await chat.send('duplicate', ['kb']); expect(conversationsApi.askStream).toHaveBeenCalledTimes(1)
  chat.clear(); bumpEpoch(); resolve(mockAnswered); await pending
  expect(chat.messages).toEqual([]); expect(chat.active).toBeNull(); expect(chat.pending).toBeNull()
})
it('ignores an older conversation load after switching', async () => {
  let resolve!: (value: {items: never[]; total: number}) => void
  vi.mocked(conversationsApi.messages).mockImplementationOnce(() => new Promise(r => {resolve = r}))
  const chat = useChatStore(); const first = chat.open('old')
  await vi.waitFor(() => expect(conversationsApi.messages).toHaveBeenCalledTimes(1))
  await chat.open('new')
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

it('updates an unverified draft only from event callbacks and withdraws it on validation failure', async () => {
  const { ApiError } = await import('@/api/http')
  let reject!: (error: Error)=>void
  vi.mocked(conversationsApi.askStream).mockImplementation((_id,payload,onEvent)=>{
    onEvent({type:'status',seq:1,request_id:payload.request_id,payload:{stage:'generating',preview:true}})
    onEvent({type:'draft',seq:2,request_id:payload.request_id,payload:{text:'尚未验证 [S99]'}})
    return new Promise((_r,j)=>{reject=j})
  })
  const chat=useChatStore(),job=chat.send('Dijkstra',['kb'])
  await vi.waitFor(()=>expect(chat.draft).toBe('尚未验证 [S99]'))
  expect(chat.messages).toEqual([]);expect(chat.streamStage).toBe('generating')
  reject(new ApiError(502,'invalid_citations','invalid'));await job
  expect(chat.draft).toBe('');expect(chat.streamStage).toBe('failed')
  expect(chat.messages).toEqual([]);expect(chat.pending).not.toBeNull()
})

it.each([
  ['truncated_or_invalid_completion', '生成长度限制'],
  ['generation_timeout', '生成或流式连接超时'],
  ['invalid_citations', '最终格式或来源校验'],
  ['network_error', '流式连接中断'],
] as const)('shows a safe actionable error for %s without persisting drafts', async (code, description) => {
  const { ApiError } = await import('@/api/http')
  vi.mocked(conversationsApi.askStream).mockRejectedValueOnce(new ApiError(503,code,'synthetic-secret-must-not-leak'))
  const chat=useChatStore();await chat.send('快速排序',['kb'])
  expect(chat.error).toContain(description)
  expect(chat.error).toContain(`诊断码：${code}`)
  expect(chat.error).not.toContain('synthetic-secret')
  expect(chat.draft).toBe('');expect(chat.messages).toEqual([])
  expect(chat.pending).not.toBeNull()
})

it('cancel aborts fetch and preserves the same request id for a safe retry', async () => {
  let resolve!: (value:typeof mockAnswered)=>void,signal:AbortSignal|undefined
  vi.mocked(conversationsApi.askStream).mockImplementation((_id,_payload,_event,current)=>{signal=current;return new Promise(r=>{resolve=r})})
  const chat=useChatStore(),job=chat.send('AVL',['kb'])
  await vi.waitFor(()=>expect(signal).toBeDefined())
  const original=chat.pending!.payload
  chat.draft='temporary';chat.cancel()
  expect(signal!.aborted).toBe(true);expect(chat.draft).toBe('');expect(chat.sending).toBe(false)
  expect(chat.pending!.payload).toEqual(original)
  resolve(mockAnswered);await job;expect(chat.messages).toEqual([])
  vi.mocked(conversationsApi.askStream).mockResolvedValue(mockAnswered)
  await chat.send('different',['other'])
  expect(conversationsApi.askStream).toHaveBeenLastCalledWith('one',original,expect.any(Function),expect.any(AbortSignal))
})

it('switching conversation cancels old generation and late events cannot fill the new history', async () => {
  let emit!: Parameters<typeof conversationsApi.askStream>[2],resolve!: (r:typeof mockAnswered)=>void,signal:AbortSignal|undefined
  vi.mocked(conversationsApi.askStream).mockImplementation((_id,_payload,onEvent,current)=>{emit=onEvent;signal=current;return new Promise(r=>{resolve=r})})
  const chat=useChatStore(),job=chat.send('AVL',['kb'])
  await vi.waitFor(()=>expect(signal).toBeDefined())
  await chat.open('new-conversation');expect(signal!.aborted).toBe(true)
  emit({type:'draft',seq:2,request_id:'old',payload:{text:'must not return'}})
  resolve(mockAnswered);await job
  expect(chat.active).toBe('new-conversation');expect(chat.draft).toBe('');expect(chat.messages).toEqual([])
})
