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
