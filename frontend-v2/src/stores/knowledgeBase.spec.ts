import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { knowledgeBaseApi } from '@/api/knowledgeBases'
import type { KnowledgeBase } from '@/types/api'

import { MAX_SELECTION, useKnowledgeBaseStore } from './knowledgeBase'

vi.mock('@/api/knowledgeBases', () => ({
  knowledgeBaseApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}))

function makeKb(index: number): KnowledgeBase {
  return {
    id: `kb-${index}`,
    owner_id: 'owner-1',
    name: `知识库 ${index}`,
    description: '',
    visibility: index % 2 === 0 ? 'private' : 'public',
    index_version: 0,
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}

describe('知识库选择上限与分页', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('全选时按后端上限截断，并给出提示', () => {
    const kb = useKnowledgeBaseStore()
    kb.items = Array.from({ length: 25 }, (_, i) => makeKb(i))
    kb.total = 25

    kb.selectAll()

    expect(kb.selectedIds).toHaveLength(MAX_SELECTION)
    expect(kb.selectionFull).toBe(true)
    expect(kb.limitNotice).toContain(`最多选择 ${MAX_SELECTION}`)
  })

  it('少于上限时全选不提示', () => {
    const kb = useKnowledgeBaseStore()
    kb.items = Array.from({ length: 3 }, (_, i) => makeKb(i))
    kb.total = 3

    kb.selectAll()

    expect(kb.selectedIds).toHaveLength(3)
    expect(kb.limitNotice).toBe('')
  })

  it('逐个勾选时第 21 个被拒绝', () => {
    const kb = useKnowledgeBaseStore()
    kb.items = Array.from({ length: 25 }, (_, i) => makeKb(i))

    for (let i = 0; i < MAX_SELECTION; i += 1) kb.toggle(`kb-${i}`)
    expect(kb.selectedIds).toHaveLength(MAX_SELECTION)

    kb.toggle('kb-24') // 第 21 个
    expect(kb.selectedIds).toHaveLength(MAX_SELECTION)
    expect(kb.selectedIds).not.toContain('kb-24')
    expect(kb.limitNotice).toContain('请先取消')
  })

  it('取消一个后可以再选别的', () => {
    const kb = useKnowledgeBaseStore()
    kb.items = Array.from({ length: 25 }, (_, i) => makeKb(i))
    for (let i = 0; i < MAX_SELECTION; i += 1) kb.toggle(`kb-${i}`)

    kb.toggle('kb-0')
    kb.toggle('kb-24')

    expect(kb.selectedIds).toContain('kb-24')
    expect(kb.limitNotice).toBe('')
  })

  it('知识库超过单页上限时逐页取全，不再只显示前 50 条', async () => {
    vi.mocked(knowledgeBaseApi.list)
      .mockResolvedValueOnce({
        items: Array.from({ length: 100 }, (_, i) => makeKb(i)),
        total: 130,
        limit: 100,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: Array.from({ length: 30 }, (_, i) => makeKb(100 + i)),
        total: 130,
        limit: 100,
        offset: 100,
      })

    const kb = useKnowledgeBaseStore()
    await kb.load()

    expect(knowledgeBaseApi.list).toHaveBeenCalledTimes(2)
    expect(kb.items).toHaveLength(130)
    expect(kb.total).toBe(130)
    expect(kb.truncated).toBe(false)
  })
})
