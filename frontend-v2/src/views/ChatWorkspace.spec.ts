import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import ChatWorkspace from './ChatWorkspace.vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'
import { mockAnswered, mockUser } from '@/mocks/fixtures'
vi.mock('@/stores/reset', () => ({logoutAndReset: vi.fn()}))
beforeEach(() => { HTMLElement.prototype.scrollTo = vi.fn(); setActivePinia(createPinia()); useAuthStore().user = mockUser; useAuthStore().status = 'authenticated'; vi.spyOn(useKnowledgeBaseStore(), 'load').mockResolvedValue(); vi.spyOn(useChatStore(), 'list').mockResolvedValue() })
it('welcomes students without advanced controls; Enter sends and Shift+Enter preserves a newline', async () => {
  useKnowledgeBaseStore().selectedIds = ['kb']
  const send = vi.spyOn(useChatStore(), 'send').mockResolvedValue()
  const w = mount(ChatWorkspace); await flushPromises()
  expect(w.text()).toContain('把知识连成思路'); expect(w.text()).not.toContain('高级选项')
  await w.find('textarea').setValue('AVL'); await w.find('textarea').trigger('keydown', {key: 'Enter', shiftKey: true}); expect(send).not.toHaveBeenCalled()
  await w.find('textarea').trigger('keydown', {key: 'Enter'}); expect(send).toHaveBeenCalledWith('AVL', ['kb'])
})
it('keeps two S1 source lists independent', async () => {
  const chat = useChatStore(); chat.messages = [1, 2].map(i => ({id: String(i), seq: i, role: 'assistant', content: mockAnswered.answer!, metadata_json: {result: mockAnswered}}))
  const w = mount(ChatWorkspace, {attachTo: document.body}); await flushPromises()
  const answers = w.findAll('.answer-view'); await answers[1]!.find('button.cite').trigger('click'); await flushPromises()
  expect(answers[0]!.find('details').attributes('open')).toBeUndefined()
  expect(answers[1]!.find('details').attributes('open')).toBeDefined()
  const ids = w.findAll('.source-item').map(x => x.attributes('id')); expect(new Set(ids).size).toBe(ids.length)
  w.unmount()
})

it('reports a failed server logout instead of claiming the session was revoked', async () => {
  vi.mocked(logoutAndReset).mockResolvedValue('failed')
  const w = mount(ChatWorkspace); await flushPromises()
  const logout = w.findAll('button').find(b => b.text() === '退出')!
  await logout.trigger('click'); await flushPromises()
  expect(useAuthStore().logoutFailed).toBe(true)
})

it('places compact API knowledge bases between new chat and scrolling history', async () => {
  const kb = useKnowledgeBaseStore()
  kb.items = [{ id: 'api-kb', name: 'API 返回的授权课程', description: '无需在侧栏重复的说明', visibility: 'private' } as never]
  kb.total = 1
  const w = mount(ChatWorkspace); await flushPromises()
  expect(w.find('.brand').text()).toBe('数据结构 AI 助教')
  expect(w.find('.knowledge').text()).toContain('API 返回的授权课程')
  expect(w.find('.knowledge').text()).not.toContain('无需在侧栏重复的说明')
  expect(w.find('.knowledge').findAll('h2')).toHaveLength(1)
  const children = Array.from(w.find('.sidebar').element.children)
  expect(children.indexOf(w.find('.new-chat').element)).toBeLessThan(children.indexOf(w.find('.knowledge').element))
  expect(children.indexOf(w.find('.knowledge').element)).toBeLessThan(children.indexOf(w.find('.history').element))
  expect(children.indexOf(w.find('.history').element)).toBeLessThan(children.indexOf(w.find('.account').element))
  expect(w.find('.history-list').exists()).toBe(true)
  expect(kb.selectedIds).toEqual(['api-kb'])
})

it('does not silently select or combine multiple API knowledge bases', async () => {
  const kb = useKnowledgeBaseStore()
  kb.items = ['one', 'two'].map(id => ({id, name: `API 课程 ${id}`, visibility: 'private'} as never))
  kb.total = 2
  const w = mount(ChatWorkspace); await flushPromises()
  expect(kb.selectedIds).toEqual([])
  await w.find('.knowledge input').setValue(true)
  expect(kb.selectedIds).toEqual(['one'])
})
