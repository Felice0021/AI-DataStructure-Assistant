import { describe, expect, it } from 'vitest'
import cases from '@/__tests__/fixtures/verified-trees.json'
import { layoutTree, parseVerifiedTree, type TreeGraph } from './verifiedTree'
const copy = (name = 'LR'): Record<string, any> => JSON.parse(JSON.stringify(cases[name as keyof typeof cases]))
describe('bounded server tree DTO', () => {
  for (const [name, raw] of Object.entries(cases)) it(`lays out server-calculated ${name} without overlaps`, () => {
    const tree = parseVerifiedTree(raw, ['[S1]'])!
    expect(tree).not.toBeNull()
    for (const graph of [tree.final, ...tree.rotations.flatMap(r => r.frames.map(f => f.graph))]) {
      const layout = layoutTree(graph, ['AVL', 'BST'].includes(tree.family))
      expect(layout.nodes).toHaveLength(graph.nodes.length)
      expect(layout.edges).toHaveLength(graph.nodes.length - 1)
      for (const node of layout.nodes) {
        expect(node.x - node.width / 2).toBeGreaterThanOrEqual(0)
        expect(node.x + node.width / 2).toBeLessThanOrEqual(layout.width)
        expect(node.y + node.height / 2).toBeLessThanOrEqual(layout.height)
        for (const other of layout.nodes) if (other.id !== node.id && Math.abs(other.y - node.y) < 1)
          expect(Math.abs(node.x - other.x)).toBeGreaterThanOrEqual((node.width + other.width) / 2 + 20)
      }
      for (const edge of layout.edges) {
        expect(Object.values(edge).filter(v => typeof v === 'number').every(Number.isFinite)).toBe(true)
        const parent = layout.nodes.find(n => n.id === edge.from)!, child = layout.nodes.find(n => n.id === edge.to)!
        expect(edge.y1).toBeLessThan(edge.y2)
        if (edge.side) {
          expect(Math.hypot(edge.x1-parent.x, edge.y1-parent.y)).toBeCloseTo(parent.width/2)
          expect(Math.hypot(edge.x2-child.x, edge.y2-child.y)).toBeCloseTo(child.width/2)
          expect(child.x < parent.x).toBe(edge.side === '左')
        }
      }
    }
  })
  const invalid: ((d: Record<string, any>) => void)[] = [
    d => { d.svg = '<svg onload="alert(1)"/>' }, d => { d.final.nodes[0].onclick = 'alert(1)' },
    d => { d.final.nodes[0].keys = ['<script>alert(1)</script>'] }, d => { d.final.nodes[0].keys = [NaN] },
    d => { d.final.nodes[0].keys = [true] }, d => { d.final.nodes[0].keys = [1000000000] },
    d => { d.final.nodes[0].children = ['n0', null] }, d => { d.final.nodes[0].children = ['n1', 'n1'] },
    d => { d.final.nodes[0].children = ['n63', null] }, d => { d.final.nodes[1].keys = [99] },
    d => { d.final.nodes.push({ id: 'n63', keys: [99], children: [null, null] }) },
    d => { d.final.nodes.push(d.final.nodes[0]) }, d => { d.final.nodes = Array(65).fill(d.final.nodes[0]) },
    d => { d.rotations[0].frames.splice(1, 1) }, d => { d.rotations[0].frames[1].stage = 'after' },
    d => { d.rotations[0].frames[0].graph.nodes[0].keys = [31] }, d => { d.rotations = Array(17).fill(d.rotations[0]) },
    d => { d.family = '<foreignObject>' }, d => { d.source_citations = ['[S2]'] }, d => { d.origin = 'qwen-generated' },
  ]
  invalid.forEach((mutate, index) => it(`rejects malformed/injected data ${index}`, () => {
    const data = copy(); mutate(data); expect(parseVerifiedTree(data, ['[S1]'])).toBeNull()
  }))
  it('rejects excessive depth and missing sources', () => {
    const data = copy('BST')
    data.final = { root: 'n0', nodes: Array.from({ length: 18 }, (_, i) => ({ id: `n${i}`, keys: [i], children: [null, i < 17 ? `n${i+1}` : null] })) }
    expect(parseVerifiedTree(data, ['[S1]'])).toBeNull()
    expect(parseVerifiedTree(cases.LR, [])).toBeNull()
    expect(parseVerifiedTree(null, [])).toBeNull()
  })
  it('keeps a single left or right child on its correct side', () => {
    for (const side of [0, 1]) {
      const graph: TreeGraph = { root:'n0', nodes:[{id:'n0', keys:[20], children:side ? [null,'n1'] : ['n1',null]}, {id:'n1',keys:[side ? 30:10],children:[null,null]}] }
      const layout = layoutTree(graph,true)
      expect(layout.nodes[1]!.x > layout.nodes[0]!.x).toBe(side === 1)
    }
  })
})

it('rejects incorrect B/B+ separators and multiway child counts', () => {
  for (const name of ['B','B+']) {
    const bad=copy(name);bad.final.nodes[0].keys=[999]
    expect(parseVerifiedTree(bad,['[S1]'])).toBeNull()
    const missing=copy(name);missing.final.nodes[0].children.pop()
    expect(parseVerifiedTree(missing,['[S1]'])).toBeNull()
  }
})

it('bounds aggregate rotation nodes and accommodates large negative/positive keys', () => {
  const graph: TreeGraph={root:'n0',nodes:[]}
  function make(lo:number,hi:number):string|null {
    if(lo>hi)return null
    const key=Math.floor((lo+hi)/2),id=`n${graph.nodes.length}`,node={id,keys:[key],children:[] as (string|null)[]}
    graph.nodes.push(node);node.children=[make(lo,key-1),make(key+1,hi)];return id
  }
  make(1,15)
  const bad=copy();bad.final=graph
  bad.rotations=Array.from({length:16},()=>({kind:'LR',frames:['before','intermediate','after'].map(stage=>({stage,graph}))}))
  expect(parseVerifiedTree(bad,['[S1]'])).toBeNull()
  const extreme:TreeGraph={root:'n0',nodes:[{id:'n0',keys:[0],children:['n1','n2']},{id:'n1',keys:[-999999999],children:[null,null]},{id:'n2',keys:[999999999],children:[null,null]}]}
  const layout=layoutTree(extreme,true)
  const [left,right]=[layout.nodes[1]!,layout.nodes[2]!]
  expect(right.x-left.x).toBeGreaterThan((left.width+right.width)/2)
  expect(layout.nodes.every(n=>Number.isFinite(n.x)&&Number.isFinite(n.y))).toBe(true)
})
