import { request } from './http'

export interface TopicProject {
  id: string
  title: string
  description: string
  memory_source_ids: string[]
  created_at: string
  updated_at: string
}

export interface StudyMemory { id: string; topic: string; summary: string; created_at: string }

export const projectsApi = {
  list: () => request<{items: TopicProject[]}>('/projects'),
  create: (title: string, description = '') => request<TopicProject>('/projects', {
    method: 'POST', body: {title, description, memory_source_ids: []},
  }),
  update: (id: string, data: {title?: string; description?: string; memory_source_ids?: string[]}) =>
    request<TopicProject>(`/projects/${id}`, {method: 'PATCH', body: data}),
  remove: (id: string) => request<void>(`/projects/${id}`, {method: 'DELETE'}),
  memories: (id: string) => request<{items: StudyMemory[]}>(`/projects/${id}/memories`),
  forget: (id: string, memoryId: string) => request<void>(`/projects/${id}/memories/${memoryId}`, {method: 'DELETE'}),
}
