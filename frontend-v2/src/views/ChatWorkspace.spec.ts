import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ChatWorkspace from './ChatWorkspace.vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'
import { mockAnswered, mockUser } from '@/mocks/fixtures'
enableAutoUnmount(afterEach)
const courseId = '11111111-1111-4111-8111-111111111111'
vi.mock('@/stores/reset', () => ({logoutAndReset: vi.fn()}))
beforeEach(() => { vi.unstubAllEnvs(); vi.stubEnv('VITE_COURSE_KB_ID', courseId); window.history.replaceState(null, '', '/'); HTMLElement.prototype.scrollTo = vi.fn(); setActivePinia(createPinia()); useAuthStore().user = mockUser; useAuthStore().status = 'authenticated'; useKnowledgeBaseStore().items = [{id: courseId, name: 'API 返回的真实课程名称', visibility: 'private'} as never]; vi.spyOn(useKnowledgeBaseStore(), 'load').mockResolvedValue(); vi.spyOn(useChatStore(), 'list').mockResolvedValue(); vi.spyOn(useChatStore(), 'listProjects').mockResolvedValue() })
it('welcomes students without advanced controls; Enter sends and Shift+Enter preserves a newline', async () => {
  const send = vi.spyOn(useChatStore(), 'send').mockResolvedValue()
  const w = mount(ChatWorkspace); await flushPromises()
  expect(w.text()).toContain('把知识连成思路'); expect(w.text()).not.toContain('高级选项')
  await w.find('textarea').setValue('AVL'); await w.find('textarea').trigger('keydown', {key: 'Enter', shiftKey: true}); expect(send).not.toHaveBeenCalled()
  await w.find('textarea').trigger('keydown', {key: 'Enter'}); expect(send).toHaveBeenCalledWith('AVL', [courseId])
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
  kb.items = [{ id: courseId, name: 'API 返回的授权课程', description: '无需在侧栏重复的说明', visibility: 'private' } as never]
  kb.total = 1
  const w = mount(ChatWorkspace); await flushPromises()
  expect(w.find('.brand').text()).toBe('数据结构 AI 助教')
  expect(w.find('.knowledge').text()).toContain('课程知识库')
  expect(w.find('.knowledge').text()).not.toContain('无需在侧栏重复的说明')
  expect(w.find('.knowledge').findAll('h2')).toHaveLength(1)
  const children = Array.from(w.find('.sidebar').element.children)
  expect(children.indexOf(w.find('.new-chat').element)).toBeLessThan(children.indexOf(w.find('.knowledge').element))
  expect(children.indexOf(w.find('.knowledge').element)).toBeLessThan(children.indexOf(w.find('.history').element))
  expect(children.indexOf(w.find('.history').element)).toBeLessThan(children.indexOf(w.find('.account').element))
  expect(w.find('.history-list').exists()).toBe(true)
  expect(kb.selectedIds).toEqual([courseId])
})

it('selects only the configured authorized course, hiding synthetic names and all multi-select controls', async () => {
  const kb = useKnowledgeBaseStore()
  kb.items = [{id: courseId, name: '任意课程名称', visibility: 'private'}, {id: '22222222-2222-4222-8222-222222222222', name: 'Synthetic Qwen Demo', visibility: 'private'}] as never
  kb.total = 2
  const w = mount(ChatWorkspace); await flushPromises()
  expect(kb.selectedIds).toEqual([courseId])
  expect(w.find('.knowledge').text()).toBe('课程知识库')
  expect(w.text()).not.toContain('Synthetic Qwen Demo')
  expect(w.text()).not.toMatch(/已选|全选|清空/)
  expect(w.find('.knowledge input').exists()).toBe(false)
})

it('fails closed if only synthetic or an unauthorized course is available', async () => {
  const kb = useKnowledgeBaseStore()
  kb.items = [{id: '22222222-2222-4222-8222-222222222222', name: '课程知识库', visibility: 'private'}] as never
  const send = vi.spyOn(useChatStore(), 'send').mockResolvedValue()
  const w = mount(ChatWorkspace); await flushPromises()
  expect(kb.selectedIds).toEqual([])
  expect(w.find('[role="alert"]').text()).toContain('当前账号没有可用的指定课程知识库')
  expect(w.find('.composer-wrap [role="alert"]').text()).toContain('当前账号没有可用的指定课程知识库')
  await w.find('textarea').setValue('AVL'); await w.find('form.composer').trigger('submit')
  expect(send).not.toHaveBeenCalled()
})

it('copies only the response body and never adds hidden diagnostics', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', {...navigator, clipboard: {writeText}})
  useChatStore().messages = [{id: 'reply', seq: 2, role: 'assistant', content: 'legacy diagnostic text', metadata_json: {result: mockAnswered}}]
  const w = mount(ChatWorkspace); await flushPromises()
  const card = w.find('[data-testid="answer-success"]')
  const sections = Array.from(card.element.children)
  expect(sections.indexOf(card.find('.answer-text').element)).toBeLessThan(sections.indexOf(card.find('.copy-answer').element))
  expect(sections.indexOf(card.find('.copy-answer').element)).toBeLessThan(sections.indexOf(card.find('.sources').element))
  await w.find('button[aria-label="复制回答"]').trigger('click'); await flushPromises()
  expect(writeText).toHaveBeenCalledWith(mockAnswered.answer)
  expect(w.find('.answer-details').exists()).toBe(false)
  expect(useChatStore().messages[0]!.metadata_json.result?.generation_model).toBe(mockAnswered.generation_model)
  vi.unstubAllGlobals()
})

it('retains conversation controls and restores a saved conversation URL', async () => {
  const chat = useChatStore()
  chat.items = [{id: 'saved', title: '旧对话', updated_at: ''}]
  const open = vi.spyOn(chat, 'open').mockImplementation(async id => { chat.active = id })
  window.history.replaceState(null, '', '/?conversation=saved')
  const rename = vi.spyOn(chat, 'rename').mockResolvedValue()
  const remove = vi.spyOn(chat, 'remove').mockResolvedValue()
  const newChat = vi.spyOn(chat, 'newChat')
  vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
  const w = mount(ChatWorkspace); await flushPromises()
  expect(open).toHaveBeenCalledWith('saved')
  await w.find('.history-title').trigger('click'); expect(open).toHaveBeenCalledTimes(2)
  await w.find('.history-more').trigger('click')
  await w.findAll('.history-actions button')[0]!.trigger('click')
  await w.find('input[aria-label="对话标题"]').setValue('改名')
  await w.find('.history-row form').trigger('submit'); await flushPromises()
  expect(rename).toHaveBeenCalledWith('saved', '改名')
  await w.find('.history-more').trigger('click')
  await w.findAll('.history-actions button')[2]!.trigger('click'); expect(remove).toHaveBeenCalledWith('saved')
  await w.find('.new-chat').trigger('click'); expect(newChat).toHaveBeenCalledOnce()
  vi.unstubAllGlobals()
})

it('allows only one conversation menu, dismisses it outside or with Escape, and collapses history', async () => {
  const chat = useChatStore()
  chat.items = [{id: 'one', title: '复杂度', updated_at: ''}, {id: 'two', title: '二叉树', updated_at: ''}]
  const w = mount(ChatWorkspace, {attachTo: document.body}); await flushPromises()
  const menus = w.findAll('.history-more')
  await menus[0]!.trigger('click')
  expect(w.findAll('.history-actions')).toHaveLength(1)
  expect(menus[0]!.attributes('aria-expanded')).toBe('true')
  await menus[1]!.trigger('click')
  expect(w.findAll('.history-actions')).toHaveLength(1)
  expect(menus[0]!.attributes('aria-expanded')).toBe('false')
  expect(menus[1]!.attributes('aria-expanded')).toBe('true')
  document.body.click(); await flushPromises()
  expect(w.findAll('.history-actions')).toHaveLength(0)
  await menus[0]!.trigger('click')
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await flushPromises()
  expect(w.findAll('.history-actions')).toHaveLength(0)
  const toggle = w.find('.history-toggle')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect((w.find('#history-conversations').element as HTMLElement).style.display).toBe('none')
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  expect((w.find('#history-conversations').element as HTMLElement).style.display).not.toBe('none')
})

it('positions an opened historical conversation at the bottom without smooth scrolling', async () => {
  const chat = useChatStore()
  chat.items = [{id: 'saved', title: '长对话', updated_at: ''}]
  vi.spyOn(chat, 'open').mockImplementation(async id => {
    chat.active = id
    chat.messages = [{id: 'reply', seq: 2, role: 'assistant', content: '最后一条', metadata_json: {}}]
  })
  const w = mount(ChatWorkspace); await flushPromises()
  const stream = w.find('.stream').element as HTMLElement
  Object.defineProperty(stream, 'scrollHeight', {configurable: true, value: 3200})
  await w.find('.history-title').trigger('click'); await flushPromises()
  expect(stream.scrollTo).toHaveBeenCalledWith({top: 3200, behavior: 'instant'})
  expect(w.text()).toContain('最后一条')
})

it('groups conversations by project while keeping ordinary history independent', async () => {
  const chat = useChatStore()
  chat.projects = [{id: 'trees', title: '二叉树', description: '', memory_source_ids: [], created_at: '', updated_at: ''}]
  chat.items = [{id: 'inside', title: '树的遍历', project_id: 'trees', updated_at: ''}, {id: 'outside', title: '栈', project_id: null, updated_at: ''}]
  const w = mount(ChatWorkspace); await flushPromises()
  expect(w.find('#group-trees').text()).toContain('树的遍历')
  expect(w.find('#group-trees').text()).not.toContain('栈')
  expect(w.find('#history-conversations').text()).toContain('栈')
  await w.find('button[aria-label="在二叉树中新建对话"]').trigger('click')
  expect(chat.activeProject).toBe('trees')
  await w.find('.new-chat').trigger('click')
  expect(chat.activeProject).toBeNull()
})

it('creates a topic project and selects an explicit cross-project memory source', async () => {
  const chat = useChatStore()
  const base = {description: '', memory_source_ids: [] as string[], created_at: '', updated_at: ''}
  chat.projects = [{id: 'trees', title: '二叉树', ...base}, {id: 'complexity', title: '复杂度', ...base}]
  vi.spyOn(chat, 'projectMemories').mockResolvedValue([{id: 'memory-1', topic: 'BST', summary: '二叉搜索树性质', created_at: ''}])
  const update = vi.spyOn(chat, 'updateProject').mockResolvedValue({...chat.projects[0]!, memory_source_ids: ['complexity']})
  const create = vi.spyOn(chat, 'createProject').mockResolvedValue({...chat.projects[0]!, id: 'new'})
  const forget = vi.spyOn(chat, 'forgetMemory').mockResolvedValue()
  const w = mount(ChatWorkspace); await flushPromises()
  await w.find('button[aria-label="新建项目"]').trigger('click')
  await w.find('input[aria-label="项目名称"]').setValue('快速排序')
  await w.find('.project-create').trigger('submit'); await flushPromises()
  expect(create).toHaveBeenCalledWith('快速排序', '')
  await w.find('button[aria-label="设置项目：二叉树"]').trigger('click'); await flushPromises()
  expect(w.find('.memory-panel').text()).toContain('二叉搜索树性质')
  await w.find('.memory-panel button').trigger('click'); await flushPromises()
  expect(forget).toHaveBeenCalledWith('trees', 'memory-1')
  await w.find('.source-choice input').setValue(true)
  await w.find('.project-dialog form').trigger('submit'); await flushPromises()
  expect(update).toHaveBeenCalledWith('trees', expect.objectContaining({memory_source_ids: ['complexity']}))
})

it('never rewrites a pending request from a hidden knowledge-base scope', async () => {
  const chat = useChatStore()
  chat.pending = {id: 'old', payload: {query: '旧问题', knowledge_base_ids: ['hidden'], request_id: 'request'} as never}
  chat.error = '尚未完成'
  const send = vi.spyOn(chat, 'send').mockResolvedValue()
  const w = mount(ChatWorkspace); await flushPromises()
  await w.find('.error button').trigger('click')
  expect(send).not.toHaveBeenCalled()
  expect(chat.pending.payload.knowledge_base_ids).toEqual(['hidden'])
  expect(w.find('.notice').text()).toContain('不会自动更换')
})

it('previews streamed Markdown but never grants unverified draft copy, links or citations', async () => {
  const w=mount(ChatWorkspace);await flushPromises()
  const chat=useChatStore()
  chat.sending=true;chat.streamStage='generating';chat.draft='## 课程知识\n\n**正在生成** [S1] [外链](https://example.com) <svg onload="alert(1)"></svg>'
  await flushPromises()
  expect(w.find('.stream-draft').text()).toContain('尚未校验')
  expect(w.find('.draft-text').text()).toContain('<svg')
  expect(w.find('.draft-text h2').text()).toBe('课程知识')
  expect(w.find('.draft-text strong').text()).toBe('正在生成')
  expect(w.find('.stream-draft button.cite,.stream-draft .copy-answer,.stream-draft a,.stream-draft svg,.stream-draft script').exists()).toBe(false)
  expect(w.find('.thinking').text()).toContain('正在生成回答')
  const stop=vi.spyOn(chat,'cancel')
  await w.find('button[aria-label="停止生成"]').trigger('click')
  expect(stop).toHaveBeenCalled();expect(w.find('.draft-text').exists()).toBe(false)
})

it('changing the configured course cancels an in-flight draft instead of keeping its old scope', async () => {
  mount(ChatWorkspace);await flushPromises()
  const chat=useChatStore(),cancel=vi.spyOn(chat,'cancel')
  chat.sending=true;chat.draft='private old scope'
  vi.stubEnv('VITE_COURSE_KB_ID','22222222-2222-4222-8222-222222222222')
  const kb=useKnowledgeBaseStore();kb.items=[{id:'22222222-2222-4222-8222-222222222222',name:'new course',visibility:'private'} as never]
  await flushPromises()
  expect(cancel).toHaveBeenCalled();expect(chat.draft).toBe('')
})
