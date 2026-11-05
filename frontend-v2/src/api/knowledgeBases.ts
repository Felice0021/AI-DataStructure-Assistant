import type {
  KnowledgeBaseCreate,
  KnowledgeBaseEnvelope,
  KnowledgeBaseList,
  KnowledgeBaseUpdate,
} from '@/types/api'

import { request } from './http'

export interface ListParams {
  limit?: number
  offset?: number
}

function buildQuery(params: ListParams): string {
  const search = new URLSearchParams()
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  const query = search.toString()
  return query ? `?${query}` : ''
}

export const knowledgeBaseApi = {
  /** 返回分页对象；范围由服务端决定（自己的 private + 全部 public） */
  list(params: ListParams = {}): Promise<KnowledgeBaseList> {
    return request<KnowledgeBaseList>(`/knowledge-bases${buildQuery(params)}`)
  },

  create(payload: KnowledgeBaseCreate): Promise<KnowledgeBaseEnvelope> {
    return request<KnowledgeBaseEnvelope>('/knowledge-bases', {
      method: 'POST',
      body: payload,
    })
  },

  update(id: string, payload: KnowledgeBaseUpdate): Promise<KnowledgeBaseEnvelope> {
    return request<KnowledgeBaseEnvelope>(`/knowledge-bases/${id}`, {
      method: 'PATCH',
      body: payload,
    })
  },

  remove(id: string): Promise<void> {
    return request<void>(`/knowledge-bases/${id}`, { method: 'DELETE' })
  },
}
