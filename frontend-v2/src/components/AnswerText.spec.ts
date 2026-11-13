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

describe('AnswerText 安全数学渲染', () => {
  const render = (text: string) => mount(AnswerText, { props: { text, sources: [makeSource('[S1]')] } })

  it.each([String.raw`$O(n \log n)$`, '$O(n^2)$', String.raw`$O(\log n)$`, '$a[i]$', String.raw`$\sum_{i=1}^{n} i$`, String.raw`\( a[i] \)`])('renders inline formula %s as accessible KaTeX', (text) => {
    const wrapper = render(text)
    expect(wrapper.findAll('.math-inline .katex')).toHaveLength(1)
    expect(wrapper.find('math annotation').text()).toBe(text.startsWith('$') ? text.slice(1, -1) : text.slice(2, -2).trim())
    expect(wrapper.find('.math-fallback').exists()).toBe(false)
  })

  it.each(['$$\n\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\n$$', String.raw`\[ a[i] = n^2 \]`, String.raw`前文 $$n^2$$ 后文`, '> $$\n> n^2\n> $$', '- 条目\n\n  \\[\n  n^2\n  \\]'])('renders display formulas with Markdown block nesting: %s', (text) => {
    const wrapper = render(text)
    expect(wrapper.findAll('.math-display .katex-display')).toHaveLength(1)
    expect(wrapper.find('.math-fallback').exists()).toBe(false)
  })

  it('preserves Markdown, table math and interactive citations', async () => {
    const wrapper = render('# 复杂度\n\n**归并排序** $O(n \\log n)$ [S1]\n\n| low | high | 复杂度 |\n|---|---|---|\n| $a[i]$ | \\(n^2\\) | $O(\\log n)$ [S1] |')
    expect(wrapper.find('h1').text()).toBe('复杂度')
    expect(wrapper.find('strong').text()).toBe('归并排序')
    expect(wrapper.findAll('td .katex')).toHaveLength(3)
    expect(wrapper.find('.answer-table-scroll[tabindex="0"] table').exists()).toBe(true)
    expect(wrapper.findAll('button.cite')).toHaveLength(2)
    await wrapper.findAll('button.cite')[1]!.trigger('click')
    expect(wrapper.emitted('cite')).toEqual([['[S1]']])
  })

  it('keeps all delimiters and citations in code literal', () => {
    const code = String.raw`$n^2$ $$n$$ \(n\) \[n\] [S1]`
    const wrapper = render('`' + code + '`\n\n```latex\n' + code + '\n```\n\n    $n^2$')
    expect(wrapper.findAll('code').map((node) => node.text())).toEqual([code, code, '$n^2$'])
    expect(wrapper.find('.katex').exists()).toBe(false)
    expect(wrapper.find('button.cite').exists()).toBe(false)
  })

  it('respects escaped dollars, escaped backslashes and currency', () => {
    const wrapper = render(String.raw`价格 \$5，\$10；\$n^2\$；\\(n\\)；$20 and $30；公式 $a\$b$`)
    expect(wrapper.findAll('.katex')).toHaveLength(1)
    expect(wrapper.text()).toContain('价格 $5，$10；$n^2$；\\(n\\)；$20 and $30')
  })

  it.each([String.raw`$\frac{1}{$`, '$n^2', String.raw`\(n`, String.raw`\[n`, '$$\n\\frac{1}{\n$$'])('degrades incomplete LaTeX safely: %s', (text) => {
    const wrapper = render(text)
    expect(wrapper.find('.katex').exists()).toBe(false)
    expect(wrapper.text()).toContain(text)
  })

  it.each([
    String.raw`\href{javascript:alert(1)}{click}`, String.raw`\url{https://evil.example/x}`,
    String.raw`\includegraphics{https://evil.example/track.png}`, String.raw`\htmlClass{injected}{x}`,
    String.raw`\htmlId{injected}{x}`, String.raw`\htmlStyle{background:url(https://evil.example/x)}{x}`,
    String.raw`\htmlData{onclick=alert(1)}{x}`, String.raw`\def\loop{\loop}\loop`,
    String.raw`\frac{<img src=x onerror=alert(1)>}{`,
  ])('blocks dangerous formula without executable nodes: %s', (formula) => {
    const wrapper = render(`$${formula}$`)
    expect(wrapper.find('a, img, script, iframe, [onclick], [onerror], .injected, #injected, [src], [href]').exists()).toBe(false)
    expect(wrapper.html()).not.toMatch(/style="[^"]*(?:url\(|expression\()/i)
  })

  it('bounds length, depth, dimensions and isolates macros between formulas', () => {
    const wrapper = render(`$${'x'.repeat(4097)}$ $${'{'.repeat(101)}x${'}'.repeat(101)}$ $\\gdef\\secret{n}\\secret$ $\\secret$ $\\rule{99999em}{99999em}$`)
    expect(wrapper.findAll('.math-fallback')).toHaveLength(3)
    expect(wrapper.findAll('[style]').every((node) => !node.attributes('style')?.includes('99999em'))).toBe(true)
    expect(wrapper.findAll('.katex')).toHaveLength(2)
  })

  it('keeps model HTML inert alongside valid math and citations', () => {
    const wrapper = render('<script>alert(1)</script><img src=x onerror=alert(1)> $n^2$ [S1]')
    expect(wrapper.find('script, img, [onerror]').exists()).toBe(false)
    expect(wrapper.findAll('.katex')).toHaveLength(1)
    expect(wrapper.findAll('button.cite')).toHaveLength(1)
  })

  it('retains fractions, roots, stretchy SVG and MathML', () => {
    const wrapper = render(String.raw`$$\sqrt{x^2} + \frac{1}{n} + \overbrace{a+b}^{n}$$`)
    expect(wrapper.find('svg path').exists()).toBe(true)
    expect(wrapper.find('math mfrac').exists()).toBe(true)
    expect(wrapper.find('[style*="height"]').exists()).toBe(true)
  })
})
