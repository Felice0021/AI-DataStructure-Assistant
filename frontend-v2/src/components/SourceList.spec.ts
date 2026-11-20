import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import type { AnswerSource } from '@/types/api'
import SourceList from './SourceList.vue'

const source: AnswerSource = {
  citation_id: '[S1]', chunk_id: 'chunk', document_id: 'doc', knowledge_base_id: 'kb',
  source_filename: 'v1-course-chapter-03.txt', page_number: null, section_title: 'V1:record',
  chunk_index: 0, content_hash: 'hash', generation: 1, index_revision: 1, embedding_space_id: 'space',
}

it('hides internal import filenames when no verified mapping is available', () => {
  const wrapper = mount(SourceList, { props: { sources: [source], highlight: null } })
  expect(wrapper.text()).toContain('来源待核实')
  expect(wrapper.text()).toContain('页码未知')
  expect(wrapper.text()).not.toContain('v1-course-chapter-03.txt')
})

it('shows verified source, chapter and known page', () => {
  const wrapper = mount(SourceList, { props: { sources: [{ ...source, source_filename: '课程资料.pdf', section_title: '第三章 · 栈', page_number: 12 }], highlight: null } })
  expect(wrapper.text()).toContain('课程资料.pdf')
  expect(wrapper.text()).toContain('第三章 · 栈')
  expect(wrapper.text()).toContain('第 12 页')
})

it('groups identical known locations while keeping every citation anchor', () => {
  const located = { ...source, source_filename: '课程资料.pdf', section_title: '第六章 · 哈夫曼树', page_number: 145 }
  const wrapper = mount(SourceList, { props: {
    sources: [located, { ...located, chunk_id: 'two', citation_id: '[S2]' },
      { ...located, chunk_id: 'three', citation_id: '[S3]', section_title: '第六章 · 构造' },
      { ...located, chunk_id: 'four', citation_id: '[S4]', page_number: null },
      { ...located, chunk_id: 'five', citation_id: '[S5]', page_number: null }],
    highlight: '[S2]', idPrefix: 'turn',
  } })
  expect(wrapper.findAll('.source-item')).toHaveLength(4)
  const second = wrapper.get('#turn-source-S2')
  expect(second.text()).toBe('[S2]')
  expect(second.element.closest('.source-item')?.classList.contains('is-active')).toBe(true)
  expect(wrapper.get('#turn-source-S1').element.closest('li')).toBe(second.element.closest('li'))
})
