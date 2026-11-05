/**
 * 统一 HTTP 客户端。
 *
 * 负责：baseURL、credentials、CSRF 注入、超时、错误体解析、401 全局兜底、
 * CSRF 失效自动重试一次。
 *
 * 安全约束（docs/v2/FRONTEND_HANDOFF.md:26）：
 * - 一律 credentials: 'include'
 * - Origin 由浏览器自动生成，前端不得手工设置
 * - 不设置任何自定义请求头（CORS 只允许 Content-Type 与 X-CSRF-Token）
 */

import { apiUrl } from './config'
import { ensureCsrf, invalidateCsrf } from './csrf'

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE'

/** 归一化后的接口错误。业务代码只看 status + code，不直接展示后端 message。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryAfter: number | null
  readonly payload: unknown

  constructor(
    status: number,
    code: string,
    message: string,
    retryAfter: number | null = null,
    payload: unknown = null,
  ) {
    super(message || code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
    this.payload = payload
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isCsrfRejected(): boolean {
    return this.status === 403 && this.code === 'csrf_rejected'
  }
}

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  timeoutMs?: number
  /** 登录接口用：401 表示密码错，不应触发全局「会话失效」清理 */
  skipAuthHandler?: boolean
  /** csrf_rejected 时是否自动重取 token 重试一次 */
  retryOnCsrf?: boolean
}

const DEFAULT_TIMEOUT_MS = 30_000

let unauthorizedHandler: (() => void) | null = null

/** 由 main.ts 注入，指向 stores/reset.ts 的 resetAllPrivateState */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

interface ParsedError {
  code: string
  message: string
  body: unknown
}

function parseRetryAfter(response: Response): number | null {
  const raw = response.headers.get('Retry-After')
  if (!raw) return null
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

async function parseErrorBody(response: Response): Promise<ParsedError> {
  let body: unknown = null
  const raw = await response.text()
  if (raw) {
    try {
      body = JSON.parse(raw)
    } catch {
      body = null
    }
  }

  const record = (body ?? {}) as Record<string, unknown>

  // 运行时真实形态：{ error: { code, message } }（含 422）
  const error = record.error as Record<string, unknown> | undefined
  if (error && typeof error.code === 'string') {
    return {
      code: error.code,
      message: typeof error.message === 'string' ? error.message : '',
      body,
    }
  }

  // openapi 声明的 422 形态，运行时已不返回，仅作兼容
  if (Array.isArray(record.detail)) {
    return { code: 'invalid_request', message: 'Invalid request', body }
  }

  // 路由不存在时 FastAPI 的默认 404
  if (typeof record.detail === 'string') {
    return {
      code: response.status === 404 ? 'not_found' : 'internal_error',
      message: record.detail,
      body,
    }
  }

  return {
    code: response.status === 404 ? 'not_found' : 'internal_error',
    message: '',
    body,
  }
}

async function send(
  path: string,
  method: HttpMethod,
  body: unknown,
  timeoutMs: number,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let payload: BodyInit | undefined

  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  if (method !== 'GET') {
    headers['X-CSRF-Token'] = await ensureCsrf()
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    return await fetch(apiUrl(path), {
      method,
      headers,
      body: payload,
      credentials: 'include',
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'timeout', '请求超时', null)
    }
    throw new ApiError(0, 'network_error', '无法连接后端服务', null)
  } finally {
    clearTimeout(timer)
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const retryOnCsrf = options.retryOnCsrf ?? true

  let response = await send(path, method, options.body, timeoutMs)

  // 只有 CSRF 被拒才重试；普通 403 forbidden 不重试
  if (response.status === 403 && retryOnCsrf) {
    const probe = await parseErrorBody(response.clone())
    if (probe.code === 'csrf_rejected') {
      invalidateCsrf()
      response = await send(path, method, options.body, timeoutMs)
    }
  }

  if (response.status === 401) {
    // 会话已失效，旧 token 必然无效
    invalidateCsrf()
    if (!options.skipAuthHandler) unauthorizedHandler?.()
  }

  if (response.status === 204) {
    return undefined as T
  }

  if (response.ok) {
    const raw = await response.text()
    if (!raw) return undefined as T
    try {
      return JSON.parse(raw) as T
    } catch {
      throw new ApiError(response.status, 'invalid_response', '响应不是合法 JSON', null, raw)
    }
  }

  const parsed = await parseErrorBody(response)
  throw new ApiError(
    response.status,
    parsed.code,
    parsed.message,
    parseRetryAfter(response),
    parsed.body,
  )
}
