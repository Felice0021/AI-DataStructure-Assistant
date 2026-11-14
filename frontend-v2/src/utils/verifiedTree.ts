/** Only a validated server DTO can reach SVG. No Markdown/ASCII/model JSON inference. */
export interface TreeNode { id: string; keys: number[]; children: (string | null)[] }
export interface TreeGraph { root: string; nodes: TreeNode[] }
export interface TreeFrame { stage: 'before' | 'intermediate' | 'after'; graph: TreeGraph }
export interface TreeRotation { kind: 'LL' | 'RR' | 'LR' | 'RL'; frames: TreeFrame[] }
export interface VerifiedTree {
  version: 1; origin: 'server_verified_tree_v1'; family: 'AVL' | 'BST' | 'B' | 'B+'
  explanation: string; source_citations: string[]; final: TreeGraph; rotations: TreeRotation[]
}
function object(value: unknown, fields: string[]): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join() !== fields.sort().join()) throw Error('shape')
}
function list(value: unknown, max: number, min = 0): asserts value is unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) throw Error('limit')
}
const id = (v: unknown): v is string => typeof v === 'string' && /^n(?:[0-9]|[1-5][0-9]|6[0-3])$/.test(v)
function checkGraph(raw: unknown, family: string, balanced: boolean): { graph: TreeGraph; keys: number[] } {
  object(raw, ['root', 'nodes']); list(raw.nodes, 64, 1)
  if (!id(raw.root)) throw Error('root')
  const nodes = new Map<string, TreeNode>()
  for (const item of raw.nodes) {
    object(item, ['id', 'keys', 'children']); list(item.keys, 8, 1); list(item.children, 8)
    if (!id(item.id) || nodes.has(item.id) || !item.keys.every(k => typeof k === 'number' && Number.isSafeInteger(k) && Math.abs(k) <= 999999999)
      || !item.keys.every((k, i, a) => !i || (a[i - 1] as number) < (k as number)) || !item.children.every(c => c === null || id(c))) throw Error('node')
    nodes.set(item.id, { id: item.id, keys: [...item.keys] as number[], children: [...item.children] as (string | null)[] })
  }
  const seen = new Set<string>(), leaves: number[] = []
  function visit(nodeId: string, depth: number, low: number, high: number): { keys: number[]; height: number } {
    const n = nodes.get(nodeId)
    if (!n || seen.has(nodeId) || depth > 16) throw Error('graph')
    seen.add(nodeId)
    if (family === 'AVL' || family === 'BST') {
      const k = n.keys[0]!
      if (n.keys.length !== 1 || n.children.length !== 2 || !(low < k && k < high)) throw Error('binary')
      const l = n.children[0] ? visit(n.children[0], depth + 1, low, k) : { keys: [], height: 0 }
      const r = n.children[1] ? visit(n.children[1], depth + 1, k, high) : { keys: [], height: 0 }
      if (balanced && Math.abs(l.height - r.height) > 1) throw Error('balance')
      return { keys: [...l.keys, k, ...r.keys], height: 1 + Math.max(l.height, r.height) }
    }
    if (!n.children.length) { leaves.push(depth); return { keys: n.keys, height: 1 } }
    if (n.children.length !== n.keys.length + 1 || n.children.includes(null)) throw Error('children')
    const parts = n.children.map(c => visit(c!, depth + 1, -Infinity, Infinity))
    n.keys.forEach((key, i) => {
      if (!(Math.max(...parts[i]!.keys) < key && (family === 'B+' ? key === Math.min(...parts[i + 1]!.keys) : key < Math.min(...parts[i + 1]!.keys)))) throw Error('order')
    })
    return { keys: [...parts.flatMap(p => p.keys), ...(family === 'B' ? n.keys : [])].sort((a, b) => a - b), height: 0 }
  }
  const result = visit(raw.root, 0, -Infinity, Infinity)
  if (seen.size !== nodes.size || new Set(result.keys).size !== result.keys.length || new Set(leaves).size > 1) throw Error('records')
  return { graph: { root: raw.root, nodes: [...nodes.values()] }, keys: result.keys }
}

export function parseVerifiedTree(value: unknown, citations: string[]): VerifiedTree | null {
  try {
    object(value, ['version', 'origin', 'family', 'explanation', 'source_citations', 'final', 'rotations'])
    if (value.version !== 1 || value.origin !== 'server_verified_tree_v1' || !['AVL', 'BST', 'B', 'B+'].includes(String(value.family))
      || typeof value.explanation !== 'string' || !value.explanation.length || value.explanation.length > 20000) return null
    list(value.source_citations, 20, 1); list(value.rotations, 16)
    if (value.source_citations.some((c, i) => typeof c !== 'string' || !/^\[S[1-9][0-9]?\]$/.test(c) || c !== citations[i])
      || value.source_citations.length !== citations.length || new Set(citations).size !== citations.length) return null
    const family = value.family as VerifiedTree['family']
    const final = checkGraph(value.final, family, family === 'AVL').graph
    let total = final.nodes.length
    const rotations = value.rotations.map(rotation => {
      object(rotation, ['kind', 'frames']); list(rotation.frames, 3, 2)
      if (family !== 'AVL' || !['LL', 'RR', 'LR', 'RL'].includes(String(rotation.kind))) throw Error('rotation')
      const stages = ['LR', 'RL'].includes(String(rotation.kind)) ? ['before', 'intermediate', 'after'] : ['before', 'after']
      if (rotation.frames.length !== stages.length) throw Error('stages')
      let previous = ''
      const frames = rotation.frames.map((frame, i) => {
        object(frame, ['stage', 'graph']); if (frame.stage !== stages[i]) throw Error('stage')
        const checked = checkGraph(frame.graph, family, frame.stage === 'after')
        const keys = checked.keys.join(',')
        if (i && previous !== keys) throw Error('changed_keys')
        previous = keys; total += checked.graph.nodes.length
        return { stage: frame.stage as TreeFrame['stage'], graph: checked.graph }
      })
      return { kind: rotation.kind as TreeRotation['kind'], frames }
    })
    if (total > 512) return null
    return { version: 1, origin: 'server_verified_tree_v1', family, explanation: value.explanation,
      source_citations: [...citations], final, rotations }
  } catch { return null }
}

export interface PositionedNode extends TreeNode { x: number; y: number; width: number; height: number }
export interface TreeEdge { from: string; to: string; x1: number; y1: number; x2: number; y2: number; side: string }
export interface TreeLayout { width: number; height: number; nodes: PositionedNode[]; edges: TreeEdge[] }
/** Subtree intervals never overlap; absent binary slots reserve space to preserve left/right. */
export function layoutTree(graph: TreeGraph, binary: boolean): TreeLayout {
  const map = new Map(graph.nodes.map(n => [n.id, n])), gap = 24, padding = 24
  const dimensions = (n: TreeNode) => {
    const cell = Math.max(38, ...n.keys.map(k => String(k).length * 9 + 20))
    return { width: binary ? Math.max(48, cell) : cell * n.keys.length, height: binary ? Math.max(48, cell) : 44 }
  }
  const row = Math.max(...graph.nodes.map(n => dimensions(n).height)) + 48
  const spans = new Map<string, number>()
  function measure(nodeId: string): number {
    const n = map.get(nodeId)!, d = dimensions(n)
    const childrenWidth = n.children.some(Boolean) ? n.children.reduce((s, c) => s + (c ? measure(c) : 48), 0) + (n.children.length - 1) * gap : 0
    const width = Math.max(d.width, childrenWidth); spans.set(nodeId, width); return width
  }
  const width = measure(graph.root) + 2 * padding, nodes: PositionedNode[] = [], edges: TreeEdge[] = []
  function place(nodeId: string, start: number, depth: number): void {
    const n = map.get(nodeId)!, span = spans.get(nodeId)!, d = dimensions(n)
    nodes.push({ ...n, ...d, x: start + span / 2, y: padding + d.height / 2 + depth * row })
    const used = n.children.reduce((s, c) => s + (c ? spans.get(c)! : 48), 0) + Math.max(0, n.children.length - 1) * gap
    let offset = start + (span - used) / 2
    for (const c of n.children) { if (c) place(c, offset, depth + 1); offset += (c ? spans.get(c)! : 48) + gap }
  }
  place(graph.root, padding, 0)
  const positioned = new Map(nodes.map(n => [n.id, n]))
  for (const parent of nodes) parent.children.forEach((c, i) => {
    if (!c) return
    const child = positioned.get(c)!
    let x1 = parent.x, y1 = parent.y, x2 = child.x, y2 = child.y
    if (binary) {
      const dx = x2 - x1, dy = y2 - y1, distance = Math.hypot(dx, dy)
      x1 += dx / distance * parent.width / 2; y1 += dy / distance * parent.height / 2
      x2 -= dx / distance * child.width / 2; y2 -= dy / distance * child.height / 2
    } else {
      x1 += -parent.width / 2 + parent.width * (i + 0.5) / parent.children.length
      y1 += parent.height / 2; y2 -= child.height / 2
    }
    edges.push({ from: parent.id, to: c, x1, y1, x2, y2, side: binary ? (i === 0 ? '左' : '右') : '' })
  })
  return { width, height: Math.max(...nodes.map(n => n.y + n.height / 2)) + padding, nodes, edges }
}
