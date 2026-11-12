import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { AnswerSource } from '@/types/api'

import AnswerText from './AnswerText.vue'

function makeSource(citationId: string): AnswerSource {
  return {
    citation_id: citationId,
    chunk_id: 'chunk-1',
    document_id: 'doc-1',
    knowledge_base_id: 'kb-1',
    source_filename: '第03章-栈与队列.pdf',
    page_number: 42,
    section_title: '3.2 栈的定义',
    chunk_index: 3,
    content_hash: 'hash',
    generation: 1,
    index_revision: 1,
    embedding_space_id: 'space',
  }
}

describe('AnswerText 引用渲染', () => {
  it('renders nested Markdown and keeps code citations inert', () => {
    const wrapper = mount(AnswerText, { props: { text: '# 标题\n\n**粗体和 *斜体*** [S1]\n\n- 项目\n\n`[S1]`\n\n```python\nprint("[S1]")\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |', sources: [makeSource('[S1]')] } })
    expect(wrapper.find('h1').text()).toBe('标题')
    expect(wrapper.find('strong em').text()).toBe('斜体')
    expect(wrapper.find('li').text()).toBe('项目')
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.find('pre code').classes()).toContain('language-python')
    expect(wrapper.findAll('button.cite')).toHaveLength(1)
    expect(wrapper.findAll('code').every((code) => code.find('button').exists() === false)).toBe(true)
  })

  it('never renders HTML or dangerous links', () => {
    const wrapper = mount(AnswerText, { props: { text: '<img src=x onerror=alert(1)> [坏链接](javascript:alert(1))', sources: [] } })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('[onerror]').exists()).toBe(false)
    expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
  })
  it('把 [S1] 渲染成可点击标记', () => {
    const wrapper = mount(AnswerText, {
      props: { text: '栈是后进先出的线性表[S1]。', sources: [makeSource('[S1]')] },
    })

    const buttons = wrapper.findAll('button.cite')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]?.text()).toBe('[S1]')
  })

  it('点击引用时抛出 citation_id', async () => {
    const wrapper = mount(AnswerText, {
      props: { text: '结论见资料[S1]。', sources: [makeSource('[S1]')] },
    })

    await wrapper.find('button.cite').trigger('click')

    expect(wrapper.emitted('cite')?.[0]).toEqual(['[S1]'])
  })

  it('sources 里没有的引用降级为纯文本，不可点击', () => {
    const wrapper = mount(AnswerText, {
      props: { text: '这个结论来自[S9]。', sources: [makeSource('[S1]')] },
    })

    expect(wrapper.findAll('button.cite')).toHaveLength(0)
    expect(wrapper.find('.cite-unknown').text()).toBe('[S9]')
  })

  it('多个引用按顺序渲染，文本片段不丢字', () => {
    const wrapper = mount(AnswerText, {
      props: {
        text: 'A[S1]B[S2]C',
        sources: [makeSource('[S1]'), makeSource('[S2]')],
      },
    })

    expect(wrapper.findAll('button.cite')).toHaveLength(2)
    expect(wrapper.text()).toContain('A')
    expect(wrapper.text()).toContain('B')
    expect(wrapper.text()).toContain('C')
  })

  it('模型输出里的 HTML 被转义，不会产生 DOM 节点', () => {
    const wrapper = mount(AnswerText, {
      props: { text: '<script>alert(1)</script>正常文本', sources: [] },
    })

    expect(wrapper.element.querySelector('script')).toBeNull()
    expect(wrapper.element.querySelector('img')).toBeNull()
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
  })

  it('没有引用标记时原样输出正文', () => {
    const wrapper = mount(AnswerText, {
      props: { text: '没有引用的回答。', sources: [] },
    })

    expect(wrapper.findAll('button.cite')).toHaveLength(0)
    expect(wrapper.text()).toBe('没有引用的回答。')
  })
})
