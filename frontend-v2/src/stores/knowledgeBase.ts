import { defineStore } from 'pinia'

import { knowledgeBaseApi } from '@/api/knowledgeBases'
import { ApiError } from '@/api/http'
import type { KnowledgeBase } from '@/types/api'

interface KnowledgeBaseState {
  items: KnowledgeBase[]
  total: number
  loading: boolean
  errorCode: string | null
  selectedIds: string[]
}

export const useKnowledgeBaseStore = defineStore('knowledgeBase', {
  state: (): KnowledgeBaseState => ({
    items: [],
    total: 0,
    loading: false,
    errorCode: null,
    selectedIds: [],
  }),

  getters: {
    /** private 必为本人所有（服务端只返回自己的 private）*/
    mine: (state): KnowledgeBase[] => state.items.filter((kb) => kb.visibility === 'private'),
    shared: (state): KnowledgeBase[] => state.items.filter((kb) => kb.visibility === 'public'),
    selectedCount: (state): number => state.selectedIds.length,
    isEmpty: (state): boolean => !state.loading && state.items.length === 0,
  },

  actions: {
    async load(): Promise<void> {
      this.loading = true
      this.errorCode = null
      try {
        const page = await knowledgeBaseApi.list({ limit: 50, offset: 0 })
        this.items = page.items
        this.total = page.total
        // 列表变化后丢弃已不存在的选中项，避免把无效 id 提交给后端（会整单 404）
        const available = new Set(page.items.map((kb) => kb.id))
        this.selectedIds = this.selectedIds.filter((id) => available.has(id))
      } catch (error) {
        this.items = []
        this.total = 0
        this.selectedIds = []
        this.errorCode = error instanceof ApiError ? error.code : 'network_error'
      } finally {
        this.loading = false
      }
    },

    isSelected(id: string): boolean {
      return this.selectedIds.includes(id)
    },

    toggle(id: string): void {
      const index = this.selectedIds.indexOf(id)
      if (index >= 0) {
        this.selectedIds.splice(index, 1)
        return
      }
      this.selectedIds.push(id)
    },

    selectAll(): void {
      this.selectedIds = this.items.map((kb) => kb.id)
    },

    clearSelection(): void {
      this.selectedIds = []
    },

    /** 401 或退出时调用：列表和选中项都属于私人上下文，必须一起清掉 */
    clear(): void {
      this.items = []
      this.total = 0
      this.loading = false
      this.errorCode = null
      this.selectedIds = []
    },
  },
})
