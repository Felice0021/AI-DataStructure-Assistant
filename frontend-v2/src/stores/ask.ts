import { defineStore } from 'pinia'

import { ApiError } from '@/api/http'
import { ragApi } from '@/api/rag'
import { errorMessage } from '@/composables/useErrorMessage'
import type { AnswerModeRequest, AskResponse, RetrievalMode } from '@/types/api'

/**
 * phase 与后端 status 的对应关系（不要混用 HTTP 成功与业务成功）：
 * answered  ← 200 + status='answered'
 * refused   ← 200 + status='insufficient_evidence'（正常拒答，不是错误）
 * failed    ← 502/503/401/403/404/422/429/网络错误
 */
export type AskPhase = 'idle' | 'loading' | 'answered' | 'refused' | 'failed'

export interface AskParams {
  query: string
  knowledgeBaseIds: string[]
  answerMode: AnswerModeRequest
  retrievalMode: RetrievalMode
}

interface AskState {
  phase: AskPhase
  result: AskResponse | null
  errorCode: string | null
  errorStatus: number
  errorMessage: string
  lastQuery: string
}

export const useAskStore = defineStore('ask', {
  state: (): AskState => ({
    phase: 'idle',
    result: null,
    errorCode: null,
    errorStatus: 0,
    errorMessage: '',
    lastQuery: '',
  }),

  getters: {
    isLoading: (state): boolean => state.phase === 'loading',
    canRetry: (state): boolean => state.phase === 'failed' && state.errorStatus !== 401 && state.errorStatus !== 403,
  },

  actions: {
    async ask(params: AskParams): Promise<void> {
      const query = params.query.trim()

      // 本地先挡一道，避免发一个必然 422 的请求
      if (!query) {
        this.phase = 'failed'
        this.errorCode = 'empty_query'
        this.errorStatus = 0
        this.errorMessage = '请输入问题'
        return
      }
      if (params.knowledgeBaseIds.length === 0) {
        this.phase = 'failed'
        this.errorCode = 'no_knowledge_base'
        this.errorStatus = 0
        this.errorMessage = '请先选择至少一个知识库'
        return
      }

      this.phase = 'loading'
      this.result = null
      this.errorCode = null
      this.errorStatus = 0
      this.errorMessage = ''
      this.lastQuery = query

      try {
        const result = await ragApi.ask({
          query,
          knowledge_base_ids: params.knowledgeBaseIds,
          answer_mode: params.answerMode,
          retrieval_mode: params.retrievalMode,
        })
        this.result = result
        this.phase = result.status === 'answered' ? 'answered' : 'refused'
      } catch (error) {
        this.result = null
        this.phase = 'failed'
        if (error instanceof ApiError) {
          this.errorCode = error.code
          this.errorStatus = error.status
          this.errorMessage = errorMessage(error.code, error.status)
        } else {
          this.errorCode = 'internal_error'
          this.errorStatus = 0
          this.errorMessage = errorMessage('internal_error')
        }
      }
    },

    /** 401 / 切换账户 / 退出时调用：绝不能让上一个账户的答案留在界面上 */
    clear(): void {
      this.phase = 'idle'
      this.result = null
      this.errorCode = null
      this.errorStatus = 0
      this.errorMessage = ''
      this.lastQuery = ''
    },
  },
})
