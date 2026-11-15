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

const courseId = '11111111-1111-4111-8111-111111111111'
const syntheticId = '22222222-2222-4222-8222-222222222222'
describe('configured course presentation is authorization-bound and fail-closed', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); vi.unstubAllEnvs(); vi.stubEnv('VITE_COURSE_KB_ID', courseId) })
  const course = () => ({...makeKb(0), id: courseId, name: '任意名称均可重命名'})
  const synthetic = () => ({...makeKb(1), id: syntheticId, name: '课程知识库'})
  const page = (items: KnowledgeBase[]) => ({items, total: items.length, limit: 100, offset: 0})

  it('matches the configured resource, not a name, and selects it without checkboxes', async () => {
    vi.mocked(knowledgeBaseApi.list).mockResolvedValue(page([synthetic(),course()]))
    const kb = useKnowledgeBaseStore(); await kb.load()
    expect(kb.course?.id).toBe(courseId); expect(kb.selectedIds).toEqual([courseId]); expect(kb.courseSelected).toBe(true)
    expect(kb.items).toHaveLength(2)
  })
  it('does not fall back to the only available or similarly named synthetic KB', async () => {
    vi.mocked(knowledgeBaseApi.list).mockResolvedValue(page([synthetic()]))
    const kb = useKnowledgeBaseStore(); kb.selectedIds = [courseId]; await kb.load()
    expect(kb.course).toBeNull(); expect(kb.selectedIds).toEqual([]); expect(kb.courseIssue).toContain('当前账号')
  })
  it.each(['', 'not-a-uuid'])('requires explicit valid public configuration: %s', async value => {
    vi.stubEnv('VITE_COURSE_KB_ID', value)
    vi.mocked(knowledgeBaseApi.list).mockResolvedValue(page([course()]))
    const kb = useKnowledgeBaseStore(); await kb.load()
    expect(kb.selectedIds).toEqual([]); expect(kb.courseIssue).toContain('未正确配置')
  })
  it('clears a previous account selection and cannot recover it in a new account catalog', async () => {
    const kb = useKnowledgeBaseStore()
    vi.mocked(knowledgeBaseApi.list).mockResolvedValueOnce(page([course()])).mockResolvedValueOnce(page([synthetic()]))
    await kb.load(); expect(kb.selectedIds).toEqual([courseId])
    kb.clear(); await kb.load()
    expect(kb.course).toBeNull(); expect(kb.selectedIds).toEqual([])
  })
  it('refuses ambiguous duplicate API entries instead of choosing one', async () => {
    vi.mocked(knowledgeBaseApi.list).mockResolvedValue(page([course(),course()]))
    const kb = useKnowledgeBaseStore(); await kb.load()
    expect(kb.course).toBeNull(); expect(kb.selectedIds).toEqual([])
  })
})
