import { request } from './http'
import type { AskRequest, AskResponse } from '@/types/api'
import { requestStream, type WireEvent } from './stream'
export interface Conversation { id: string; title: string; updated_at: string; project_id?: string | null }
export interface ChatMessage { id: string; seq: number; role: 'user' | 'assistant'; content: string; metadata_json: { result?: AskResponse; request_id?: string } }
export const conversationsApi = {
  list: (offset = 0) => request<{items: Conversation[]; total: number}>(`/conversations?limit=100&offset=${offset}`),
  get: (id: string) => request<{conversation: Conversation}>(`/conversations/${id}`),
  create: (title: string, project_id: string | null = null) => request<{conversation: Conversation}>('/conversations', {method: 'POST', body: {title, project_id}}),
  rename: (id: string, title: string) => request(`/conversations/${id}`, {method: 'PATCH', body: {title}}),
  move: (id: string, project_id: string | null) => request(`/conversations/${id}`, {method: 'PATCH', body: {project_id}}),
  remove: (id: string) => request(`/conversations/${id}`, {method: 'DELETE'}),
  messages: (id: string, offset = 0) => request<{items: ChatMessage[]; total: number}>(`/conversations/${id}/messages?limit=100&offset=${offset}`),
  ask: (id: string, payload: AskRequest & {request_id: string}) => request<AskResponse>(`/conversations/${id}/ask`, {method: 'POST', body: payload, timeoutMs: 90000}),
  askStream: (id: string, payload: AskRequest & {request_id: string}, onEvent: (e: WireEvent)=>void, signal: AbortSignal) => requestStream(`/conversations/${id}/ask-stream`, payload, onEvent, signal),
}
