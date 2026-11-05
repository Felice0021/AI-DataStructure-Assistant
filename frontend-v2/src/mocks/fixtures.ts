/**
 * Mock 数据。字段与 docs/v2/openapi.json 完全一致，
 * 目的是让 apiClient 的真实代码路径（Cookie / CSRF / 错误解析）在无后端时也能跑通。
 *
 * 注意：这些是合成数据，不代表真实课程问答质量。
 */

import type {
  AskErrorResponse,
  AskResponse,
  KnowledgeBase,
  User,
} from '@/types/api'

/**
 * 演示/取证用场景：
 * - answered / refuse / unavailable / unauthorized：答案与错误态
 * - logout-fail：POST /auth/logout 返回 500，用于验证「退出失败」提示
 * - many-kbs：返回 25 个知识库，用于验证 20 个选择上限与分页
 * 配合 ?delay=毫秒 可以让响应变慢，制造「请求还在飞」的时间窗。
 */
export type MockScenario =
  | 'answered'
  | 'refuse'
  | 'unavailable'
  | 'unauthorized'
  | 'logout-fail'
  | 'many-kbs'

export const mockUser: User = {
  id: '11111111-1111-4111-8111-111111111111',
  email: 'student@example.edu',
  role: 'student',
  is_active: true,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-01T08:00:00Z',
}

export const mockKnowledgeBases: KnowledgeBase[] = [
  {
    id: '22222222-2222-4222-8222-222222222222',
    owner_id: mockUser.id,
    name: '我的数据结构笔记',
    description: '私人上传的课程笔记与习题',
    visibility: 'private',
    index_version: 1,
    created_at: '2026-10-10T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
  },
  {
    id: '33333333-3333-4333-8333-333333333333',
    owner_id: null,
    name: '公共课程知识库',
    description: '教材原文与课件，全课程共享',
    visibility: 'public',
    index_version: 3,
    created_at: '2026-10-05T09:00:00Z',
    updated_at: '2026-10-22T09:00:00Z',
  },
]

/** 正常回答：answer 里的 [S1] / [S2] 与 sources[].citation_id 一一对应 */
export const mockAnswered: AskResponse = {
  status: 'answered',
  reason: null,
  answer:
    '栈是只允许在一端进行插入和删除的线性表，这一端称为栈顶，另一端称为栈底[S1]。由于操作只发生在栈顶，栈遵循后进先出（LIFO）原则，不支持按下标随机访问[S2]。因此用数组实现栈时，push 与 pop 都作用在末尾最自然。',
  sources: [
    {
      citation_id: '[S1]',
      chunk_id: 'a0000001-0000-4000-8000-000000000001',
      document_id: 'd0000001-0000-4000-8000-000000000001',
      knowledge_base_id: '33333333-3333-4333-8333-333333333333',
      source_filename: '第03章-栈与队列.pdf',
      page_number: 42,
      section_title: '3.2 栈的定义与基本操作',
      chunk_index: 3,
      content_hash: 'a3f1c9d2e8b74506f1a2c3d4e5f60718',
      generation: 1,
      index_revision: 3,
      embedding_space_id: 'qwen3.7-text-embedding-flash:1024',
    },
    {
      citation_id: '[S2]',
      chunk_id: 'a0000002-0000-4000-8000-000000000002',
      document_id: 'd0000001-0000-4000-8000-000000000001',
      knowledge_base_id: '33333333-3333-4333-8333-333333333333',
      source_filename: '第03章-栈与队列.pdf',
      page_number: 45,
      section_title: '3.2.3 顺序栈与链栈',
      chunk_index: 7,
      content_hash: 'b7e2d1c0a9f84635172b3c4d5e6f7081',
      generation: 1,
      index_revision: 3,
      embedding_space_id: 'qwen3.7-text-embedding-flash:1024',
    },
  ],
  retrieval_mode: 'hybrid',
  answer_mode: 'qa',
  rerank_applied: true,
  generation_model: 'qwen3.8-flash',
  execution_performed: false,
  latency_ms: 2180.4,
}

/** 正常拒答：HTTP 200，但绝不是「回答成功」 */
export const mockRefused: AskResponse = {
  status: 'insufficient_evidence',
  reason: 'no_evidence',
  answer: '根据当前授权资料无法确定。',
  sources: [],
  retrieval_mode: 'hybrid',
  answer_mode: 'qa',
  rerank_applied: false,
  generation_model: null,
  execution_performed: false,
  latency_ms: 640.2,
}

/** 503：body 是完整 AskResponse + error（openapi 未声明此形态） */
export const mockGenerationUnavailable: AskErrorResponse = {
  status: 'generation_unavailable',
  reason: 'generation_cloud_consent_required',
  answer: null,
  sources: [],
  retrieval_mode: 'hybrid',
  answer_mode: 'qa',
  rerank_applied: false,
  generation_model: null,
  execution_performed: false,
  latency_ms: 512.9,
  error: {
    code: 'generation_cloud_consent_required',
    message: 'Cloud generation consent is required',
  },
}

/** 32 位十六进制占位 token：仅用于 mock，真实 token 由后端派生 */
export const mockCsrfToken = 'a'.repeat(64)
