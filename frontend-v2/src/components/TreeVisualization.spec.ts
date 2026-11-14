import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { describe, expect, it } from 'vitest'
import cases from '@/__tests__/fixtures/verified-trees.json'
import { parseVerifiedTree } from '@/utils/verifiedTree'
import { mockAnswered } from '@/mocks/fixtures'
import AnswerView from './AnswerView.vue'
import TreeVisualization from './TreeVisualization.vue'
const props = { phase: 'answered' as const, errorCode:null, errorStatus:0, errorMessage:'' }
const result = (tree: unknown) => ({...mockAnswered,sources:mockAnswered.sources.slice(0,1), tree_visualization:tree as never, answer:'旧版正文与文字树 [S1]\n```text\n根: 20\n```'})
describe('verified SVG display', () => {
  for (const kind of ['LR','RL'] as const) it(`renders three ${kind} stages as circles`, () => {
    const wrapper=mount(TreeVisualization,{props:{tree:parseVerifiedTree(cases[kind],['[S1]'])!}})
    expect(wrapper.findAll('svg')).toHaveLength(3)
    expect(wrapper.findAll('circle')).toHaveLength(9)
    expect(wrapper.findAll('figcaption').map(n=>n.text())).toEqual([`${kind} · 旋转前`,`${kind} · 第一次旋转后`,`${kind} · 旋转后`])
    const ids=wrapper.findAll('svg title').map(n=>n.attributes('id'))
    expect(new Set(ids).size).toBe(ids.length)
    expect(wrapper.text()).toContain('局部子树')
    expect(wrapper.text()).toContain('最终完整树')
    expect(wrapper.findAll('[role="region"]').every(n=>n.attributes('tabindex')==='0')).toBe(true)
    expect(wrapper.find('script, foreignObject, image, a').exists()).toBe(false)
  })
  for (const name of ['B','B+'] as const) it(`renders multi-level ${name} as rectangular nodes`, () => {
    const wrapper=mount(TreeVisualization,{props:{tree:parseVerifiedTree(cases[name],['[S1]'])!}})
    expect(wrapper.findAll('rect')).toHaveLength(cases[name].final.nodes.length)
    expect(wrapper.findAll('circle')).toHaveLength(0)
    expect(wrapper.findAll('.tree-edges line')).toHaveLength(cases[name].final.nodes.length-1)
    if (name==='B+') expect(wrapper.findAll('.tree-divider').length).toBeGreaterThan(0)
  })
  it('keeps Markdown/math and per-answer citations without duplicate ASCII; copy slot stays intact', async () => {
    const tree={...cases.LR, explanation:'**参考算法** $O(1)$ [S1]'}
    const host=mount({render:()=>h('div',[
      h(AnswerView,{...props,result:result(tree)},{'answer-actions':()=>h('button','复制回答')}),
      h(AnswerView,{...props,result:result(tree)}),
    ])},{attachTo:document.body})
    const [a,b]=host.findAllComponents(AnswerView)
    if (!a || !b) throw Error('missing replies')
    expect(a.find('.answer-text strong').text()).toBe('参考算法')
    expect(a.find('.katex').exists()).toBe(true)
    expect(a.find('pre').exists()).toBe(false)
    expect(a.text()).toContain('复制回答')
    await a.find('button.cite').trigger('click')
    expect(a.find('details.sources').attributes('open')).toBeDefined()
    expect(b.find('details.sources').attributes('open')).toBeUndefined()
    expect(a.find('.source-item').attributes('id')).not.toBe(b.find('.source-item').attributes('id'))
    host.unmount()
  })
  it('uses safe legacy Markdown for absent/invalid structures; never infers graphics from model text', () => {
    for (const tree of [undefined,{...cases.LR, origin:'model'}, {...cases.LR, svg:'<svg onload="alert(1)"/>'}]) {
      const wrapper=mount(AnswerView,{props:{...props,result:result(tree)}})
      expect(wrapper.find('.tree-svg').exists()).toBe(false)
      expect(wrapper.find('pre').text()).toContain('根: 20')
      expect(wrapper.find('script, [onload]').exists()).toBe(false)
    }
  })
  it('does not display graphics on refusal or error', () => {
    for (const phase of ['failed','refused'] as const) {
      const wrapper=mount(AnswerView,{props:{...props,phase,result:result(cases.LR)}})
      expect(wrapper.find('.tree-svg').exists()).toBe(false)
    }
  })
})

it('keeps a separate final whole-tree graph after a local subtree rotation', () => {
  const tree=parseVerifiedTree(cases.LR,['[S1]'])!
  tree.final={root:'n0',nodes:[
    {id:'n0',keys:[40],children:['n1','n4']}, {id:'n1',keys:[20],children:['n2','n3']},
    {id:'n2',keys:[10],children:[null,null]}, {id:'n3',keys:[30],children:[null,null]},
    {id:'n4',keys:[50],children:[null,null]},
  ]}
  const checked=parseVerifiedTree(tree,['[S1]'])!
  const wrapper=mount(TreeVisualization,{props:{tree:checked}})
  expect(wrapper.findAll('svg')).toHaveLength(4)
  expect(wrapper.findAll('figcaption').map(n=>n.text())).toContain('最终完整树')
  expect(wrapper.text()).not.toContain('最后一幅旋转后结构即最终完整树')
})
