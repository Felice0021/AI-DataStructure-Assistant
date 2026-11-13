import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import ChatWorkspace from './ChatWorkspace.vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { mockAnswered, mockUser } from '@/mocks/fixtures'
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
