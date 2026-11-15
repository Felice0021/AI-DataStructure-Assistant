import { defineStore } from 'pinia'

import { ApiError } from '@/api/http'
import { ragApi } from '@/api/rag'
import { currentEpoch } from '@/api/session'
import { errorMessage } from '@/composables/useErrorMessage'
import type { AnswerModeRequest, AskResponse, RetrievalMode } from '@/types/api'

/**
 * phase 与后端 status 的对应关系（不要混用 HTTP 成功与业务成功）：
 * answered  ← 200 + status='answered'
 * refused   ← 200 + status='insufficient_evidence'（正常拒答，不是错误）
 * failed    ← 502/503/401/403/404/422/429/网络错误
 */
export type AskPhase = 'idle' | 'loading' | 'answered' | 'refused' | 'failed'

/** 后端 AskRequest.knowledge_base_ids 的上限（backend/v2/schemas/rag.py:9） */
export const MAX_KNOWLEDGE_BASES = 20

export interface AskParams {
  query: string
  knowledgeBaseIds: string[]
  answerMode: AnswerModeRequest
  retrievalMode: RetrievalMode
  allowCloud?: boolean
  allowCloudRerank?: boolean
  allowCloudGeneration?: boolean
}

interface AskState {
  phase: AskPhase
  result: AskResponse | null
  errorCode: string | null
  errorStatus: number
  errorMessage: string
  lastQuery: string
  /** 请求序号：只让「最后一次发起的请求」写回状态，防止慢响应覆盖新结果 */
  seq: number
}

export const useAskStore = defineStore('ask', {
  state: (): AskState => ({
    phase: 'idle',
    result: null,
    errorCode: null,
    errorStatus: 0,
    errorMessage: '',
    lastQuery: '',
    seq: 0,
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

      if (params.knowledgeBaseIds.length > MAX_KNOWLEDGE_BASES) {
        this.phase = 'failed'
        this.errorCode = 'too_many_knowledge_bases'
        this.errorStatus = 0
        this.errorMessage = `一次最多选择 ${MAX_KNOWLEDGE_BASES} 个知识库，请减少后重试`
        return
      }

      // 记录「这次请求属于哪个会话、第几次请求」：返回时两者任一变化都丢弃结果
      const epoch = currentEpoch()
      const seq = ++this.seq
      const isCurrent = (): boolean => seq === this.seq && epoch === currentEpoch()

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
          allow_cloud: params.allowCloud === true,
          allow_cloud_rerank: params.allowCloudRerank === true,
          allow_cloud_generation: params.allowCloudGeneration === true,
          rerank: params.allowCloudRerank ? 'required' : 'off',
        })
        // 退出登录/切换账号/已发起新请求：旧结果绝不能再写回页面
        if (!isCurrent()) return
        this.result = result
        this.phase = result.status === 'answered' ? 'answered' : 'refused'
      } catch (error) {
        if (!isCurrent()) return
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
      // 作废在飞的请求：它的结果不再有机会写回
      this.seq += 1
      this.phase = 'idle'
      this.result = null
      this.errorCode = null
      this.errorStatus = 0
      this.errorMessage = ''
      this.lastQuery = ''
    },
  },
})
