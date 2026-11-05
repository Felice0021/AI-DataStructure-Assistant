/**
 * V2 后端字段契约（手写，来源：docs/v2/openapi.json + backend/v2/schemas）。
 *
 * 与 OpenAPI 声明不一致的 3 处运行时行为，在本文件中已被显式建模：
 * 1. `/rag/ask` 的 502/503 响应体是「完整 AskResponse + 额外 error 字段」，
 *    而 openapi.json 只声明了 200/422 —— 见 AskErrorResponse。
 * 2. 所有 422 实际返回 `{ error: { code, message } }`，openapi 声明的
 *    HTTPValidationError 是滞后信息 —— 解析层需同时兼容两种形态。
 * 3. 业务 404 是 `{ error: ... }`，只有「路由不存在」才是 `{ detail: "Not Found" }`。
 *
 * 字段名易错点（写错就是 422 或空白页）：
 *   question            → query
 *   mode                → retrieval_mode + answer_mode
 *   file_name           → source_filename
 *   page                → page_number
 *   chunk               → chunk_index
 *   visibacy / scope    → visibility
 */

export type UUID = string
/** ISO-8601 date-time 字符串 */
export type DateTime = string

/* ---------------------------------- 错误体 --------------------------------- */

export interface ErrorDetail {
  code: string
  message: string
}

export interface ErrorResponse {
  error: ErrorDetail
}

/** openapi 对写接口声明的 422 形态；运行时实际不返回它，仅作兼容 */
export interface ValidationError {
  loc: (string | number)[]
  msg: string
  type: string
  input?: unknown
  ctx?: Record<string, unknown>
}

export interface HTTPValidationError {
  detail?: ValidationError[]
}

/* ---------------------------------- 认证 ---------------------------------- */

export type UserRole = 'student' | 'admin'

export interface User {
  id: UUID
  email: string
  role: UserRole
  is_active: boolean
  created_at: DateTime
  updated_at: DateTime
}

export interface UserEnvelope {
  user: User
}

/** GET /auth/csrf 的响应体：token 在 body 里，不在响应头 */
export interface CsrfResponse {
  csrf_token: string
}

/** POST /auth/register 与 POST /auth/login 的请求体完全相同；额外字段会 422 */
export interface Credentials {
  email: string
  password: string
}

export type Registration = Credentials

/* --------------------------------- 知识库 --------------------------------- */

export type KnowledgeBaseVisibility = 'private' | 'public'

export interface KnowledgeBase {
  id: UUID
  /** 公共库恒为 null；private 必为本人的 id */
  owner_id: UUID | null
  name: string
  description: string
  visibility: KnowledgeBaseVisibility
  index_version: number
  created_at: DateTime
  updated_at: DateTime
}

/** GET /knowledge-bases 返回的是分页对象，不是裸数组 */
export interface KnowledgeBaseList {
  items: KnowledgeBase[]
  total: number
  limit: number
  offset: number
}

export interface KnowledgeBaseEnvelope {
  knowledge_base: KnowledgeBase
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string
}

export interface KnowledgeBaseUpdate {
  name?: string
  description?: string
}

/* -------------------------------- 单轮问答 -------------------------------- */

export type RetrievalMode = 'bm25' | 'dense' | 'hybrid'

/** 请求可传 auto；响应中的 answer_mode 已被解析，不含 auto */
export type AnswerModeRequest = 'auto' | 'qa' | 'exercise' | 'code'
export type AnswerModeResponse = 'qa' | 'exercise' | 'code'

export type RerankPolicy = 'off' | 'optional' | 'required'

/**
 * out_of_scope 保留在枚举中，但当前后端不会返回
 * （模型自报越界会转成 insufficient_evidence / scope_not_verified）。
 */
export type AskStatus =
  | 'answered'
  | 'insufficient_evidence'
  | 'out_of_scope'
  | 'generation_unavailable'
  | 'validation_failed'

/** POST /rag/ask 请求体。后端 extra='forbid'，多一个字段即 422。 */
export interface AskRequest {
  query: string
  knowledge_base_ids: UUID[]
  retrieval_mode?: RetrievalMode
  answer_mode?: AnswerModeRequest
  top_k?: number
  rerank?: RerankPolicy
  allow_cloud?: boolean
  allow_cloud_rerank?: boolean
  allow_cloud_generation?: boolean
}

export interface AnswerSource {
  /** 形如 "[S1]"，与 answer 正文中的标记一一对应 */
  citation_id: string
  chunk_id: UUID
  document_id: UUID
  knowledge_base_id: UUID
  source_filename: string
  /** PDF 从 1 开始；TXT/DOCX 常为 null */
  page_number: number | null
  section_title: string | null
  /** 从 0 开始 */
  chunk_index: number
  content_hash: string
  generation: number
  index_revision: number
  embedding_space_id: string
}

export interface AskResponse {
  status: AskStatus
  reason: string | null
  answer: string | null
  sources: AnswerSource[]
  retrieval_mode: RetrievalMode
  answer_mode: AnswerModeResponse
  rerank_applied: boolean
  generation_model: string | null
  execution_performed?: false
  latency_ms: number
}

/**
 * 运行时补丁：生成不可用返回 503、生成校验失败返回 502，
 * 两种情况的 body 都是「完整 AskResponse + error」。openapi 未声明。
 */
export interface AskErrorResponse extends AskResponse {
  error?: ErrorDetail
}

/** 后端拒答时的固定文案（services/rag_service.py 的 REFUSAL 常量） */
export const REFUSAL_TEXT = '根据当前授权资料无法确定。'

/* --------------------------------- 类型守卫 -------------------------------- */

export function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== 'object' || value === null) return false
  const error = (value as { error?: unknown }).error
  return typeof error === 'object' && error !== null && typeof (error as ErrorDetail).code === 'string'
}

/** 502/503 的混合体：既有 AskResponse 的 status，又有 error */
export function isAskErrorResponse(value: unknown): value is AskErrorResponse {
  if (typeof value !== 'object' || value === null) return false
  const status = (value as { status?: unknown }).status
  return typeof status === 'string' && isErrorResponse(value)
}
