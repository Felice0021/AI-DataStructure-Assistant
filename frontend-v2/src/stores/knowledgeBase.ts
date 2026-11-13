import { defineStore } from 'pinia'

import { ApiError } from '@/api/http'
import { knowledgeBaseApi } from '@/api/knowledgeBases'
import { currentEpoch } from '@/api/session'
import { configuredCourseId } from '@/api/courseConfig'
import type { KnowledgeBase } from '@/types/api'

/** 后端 AskRequest.knowledge_base_ids 的上限（backend/v2/schemas/rag.py:9） */
export const MAX_SELECTION = 20
/** 单页请求量：后端 limit 最大 100（backend/v2/routers/knowledge_bases.py:28） */
const PAGE_SIZE = 100
/** 最多翻几页：防止异常 total 导致无限请求（500 个库以内都能完整加载） */
const MAX_PAGES = 5

interface KnowledgeBaseState {
  items: KnowledgeBase[]
  total: number
  loading: boolean
  errorCode: string | null
  selectedIds: string[]
  /** 超过选择上限时给用户看的提示；空串表示没有提示 */
  limitNotice: string
  /** 请求序号：只让最后一次 load 写回状态 */
  seq: number
}

export const useKnowledgeBaseStore = defineStore('knowledgeBase', {
  state: (): KnowledgeBaseState => ({
    items: [],
    total: 0,
    loading: false,
    errorCode: null,
    selectedIds: [],
    limitNotice: '',
    seq: 0,
  }),

  getters: {
    course: (state): KnowledgeBase | null => {
      const id = configuredCourseId()
      const matches = id ? state.items.filter(kb => kb.id.toLowerCase() === id) : []
      return matches.length === 1 ? matches[0]! : null
    },
    courseIssue(): string {
      if (this.loading || this.errorCode) return ''
      if (!configuredCourseId()) return '课程知识库尚未正确配置，请联系管理员。'
      return this.course ? '' : '当前账号没有可用的指定课程知识库，请联系管理员核对配置与权限。'
    },
    courseSelected(): boolean {
      return !this.loading && !this.errorCode && !!this.course && this.selectedIds.length === 1 && this.selectedIds[0] === this.course.id
    },
    /** private 必为本人所有（服务端只返回自己的 private）*/
    mine: (state): KnowledgeBase[] => state.items.filter((kb) => kb.visibility === 'private'),
    shared: (state): KnowledgeBase[] => state.items.filter((kb) => kb.visibility === 'public'),
    selectedCount: (state): number => state.selectedIds.length,
    isEmpty: (state): boolean => !state.loading && state.items.length === 0,
    /** 是否已达选择上限（界面据此禁用未选项） */
    selectionFull: (state): boolean => state.selectedIds.length >= MAX_SELECTION,
    /** 是否还有没加载出来的知识库（超过翻页上限时） */
    truncated: (state): boolean => state.items.length < state.total,
  },

  actions: {
    async load(): Promise<void> {
      const epoch = currentEpoch()
      const seq = ++this.seq
      const isCurrent = (): boolean => seq === this.seq && epoch === currentEpoch()

      this.loading = true
      this.errorCode = null
      try {
        // 逐页取完：只取前 50 条会让 total 大于实际可选项，用户看到"共 80"却只能选 50 个
        const collected: KnowledgeBase[] = []
        let total = 0
        for (let page = 0; page < MAX_PAGES; page += 1) {
          const res = await knowledgeBaseApi.list({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })
          total = res.total
          collected.push(...res.items)
          if (res.items.length === 0 || collected.length >= total) break
        }
        // 会话已切换或又发起了新的 load：丢弃这次结果
        if (!isCurrent()) return
        this.items = collected
        this.total = total
        // Only select the configured course when the authenticated API actually returned it.
        this.selectCourse()
      } catch (error) {
        if (!isCurrent()) return
        this.items = []
        this.total = 0
        this.selectedIds = []
        this.limitNotice = ''
        this.errorCode = error instanceof ApiError ? error.code : 'network_error'
      } finally {
        if (isCurrent()) this.loading = false
      }
    },

    selectCourse(): void {
      this.selectedIds = this.course ? [this.course.id] : []
      this.limitNotice = ''
    },

    isSelected(id: string): boolean {
      return this.selectedIds.includes(id)
    },

    toggle(id: string): void {
      const index = this.selectedIds.indexOf(id)
      if (index >= 0) {
        this.selectedIds.splice(index, 1)
        this.limitNotice = ''
        return
      }
      if (this.selectedIds.length >= MAX_SELECTION) {
        this.limitNotice = `一次最多选择 ${MAX_SELECTION} 个知识库，请先取消部分选择`
        return
      }
      this.selectedIds.push(id)
      this.limitNotice = ''
    },

    selectAll(): void {
      const ids = this.items.map((kb) => kb.id)
      this.selectedIds = ids.slice(0, MAX_SELECTION)
      this.limitNotice =
        ids.length > MAX_SELECTION
          ? `共 ${ids.length} 个知识库，一次最多选择 ${MAX_SELECTION} 个，已选中前 ${MAX_SELECTION} 个`
          : ''
    },

    clearSelection(): void {
      this.selectedIds = []
      this.limitNotice = ''
    },

    /** 401 或退出时调用：列表和选中项都属于私人上下文，必须一起清掉 */
    clear(): void {
      // 作废在飞的 load：它的结果不再有机会写回
      this.seq += 1
      this.items = []
      this.total = 0
      this.loading = false
      this.errorCode = null
      this.selectedIds = []
      this.limitNotice = ''
    },
  },
})
