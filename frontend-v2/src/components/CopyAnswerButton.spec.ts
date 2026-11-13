import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import CopyAnswerButton from './CopyAnswerButton.vue'

enableAutoUnmount(afterEach)
const writeText = vi.fn()
beforeEach(() => { vi.useFakeTimers(); writeText.mockReset().mockResolvedValue(undefined); vi.stubGlobal('navigator', {clipboard: {writeText}}) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('uses an accessible icon, tooltip and live success feedback; copies the exact Markdown body', async () => {
  const text = '**结论** [S1]\n```cpp\nreturn 0;\n```'
  const w = mount(CopyAnswerButton, {props: {text}})
  const button = w.find('button')
  expect(button.text()).toBe('')
  expect(button.attributes('type')).toBe('button')
  expect(button.attributes('aria-label')).toBe('复制回答')
  expect(button.attributes('aria-describedby')).toBe(w.find('[role="tooltip"]').attributes('id'))
  expect(w.find('svg rect').exists()).toBe(true)
  await button.trigger('click'); await flushPromises()
  expect(writeText).toHaveBeenCalledExactlyOnceWith(text)
  expect(w.find('[role="status"]').text()).toBe('已复制')
  expect(w.attributes('data-state')).toBe('copied')
  await vi.advanceTimersByTimeAsync(2200)
  expect(button.attributes('aria-label')).toBe('复制回答')
})

it('reports clipboard failure without claiming success', async () => {
  writeText.mockRejectedValue(new Error('denied'))
  const w = mount(CopyAnswerButton, {props: {text: '正文'}})
  await w.find('button').trigger('click'); await flushPromises()
  expect(w.find('[role="status"]').text()).toContain('复制失败')
  expect(w.attributes('data-state')).toBe('failed')
})

it('blocks duplicate copies and ignores late clipboard completion after the text changes', async () => {
  let resolve!: () => void
  writeText.mockImplementation(() => new Promise<void>(r => {resolve = r}))
  const w = mount(CopyAnswerButton, {props: {text: '旧正文'}})
  await w.find('button').trigger('click'); await w.find('button').trigger('click')
  expect(writeText).toHaveBeenCalledTimes(1)
  await w.setProps({text: '新正文'}); resolve(); await flushPromises()
  expect(w.attributes('data-state')).toBe('idle')
  expect(w.find('[role="status"]').text()).toBe('')
})

it('uses independent tooltip ids and cleans feedback timers on unmount', async () => {
  const parent = mount({components: {CopyAnswerButton}, template: '<div><CopyAnswerButton text="a"/><CopyAnswerButton text="b"/></div>'})
  const ids = parent.findAll('[role="tooltip"]').map(e => e.attributes('id'))
  expect(new Set(ids).size).toBe(2)
  await parent.find('button').trigger('click'); await flushPromises()
  parent.unmount(); expect(vi.getTimerCount()).toBe(0)
})
