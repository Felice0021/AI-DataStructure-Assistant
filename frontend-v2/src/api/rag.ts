import type { AskRequest, AskResponse } from '@/types/api'

import { request } from './http'

/** 生成走模型，比普通接口慢，给到 60s */
export const ASK_TIMEOUT_MS = 60_000

export const ragApi = {
  /**
   * 单轮问答。
   *
   * 注意返回的三种情况都要区分，不能只看 HTTP 是否成功：
   * - 200 + status='answered'              → 正常回答
   * - 200 + status='insufficient_evidence' → 正常拒答（不是错误，也不是成功）
   * - 502 / 503                            → 抛 ApiError，code 为 validation_failed / generation_unavailable
   */
  ask(payload: AskRequest): Promise<AskResponse> {
    return request<AskResponse>('/rag/ask', {
      method: 'POST',
      body: payload,
      timeoutMs: ASK_TIMEOUT_MS,
    })
  },
}
