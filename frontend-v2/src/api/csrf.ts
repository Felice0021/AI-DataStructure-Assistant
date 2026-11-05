/**
 * CSRF token 生命周期管理。
 *
 * 后端规则（docs/v2/API_CONTRACT.md:11-15）：
 * - token 在 GET /auth/csrf 的 JSON body 里（字段 csrf_token），不是响应头。
 * - 写请求要放 X-CSRF-Token，值必须匹配 [0-9a-f]{64}。
 * - token 由服务端用 HttpOnly Cookie 作 HMAC 密钥派生，因此 Cookie 一变就失效。
 *   必须在「登录成功后 / 登出后 / 403 csrf_rejected 后」重新获取。
 *
 * 约束：token 只存内存，不写 localStorage、不打日志。
 */

import { apiUrl } from './config'

let cachedToken: string | null = null
let inFlight: Promise<string> | null = null

export function invalidateCsrf(): void {
  cachedToken = null
  inFlight = null
}

export function hasCsrf(): boolean {
  return cachedToken !== null
}

async function fetchCsrf(): Promise<string> {
  const response = await fetch(apiUrl('/auth/csrf'), {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw new Error(`获取 CSRF token 失败：HTTP ${response.status}`)
  }

  const body = (await response.json()) as { csrf_token?: unknown }
  if (typeof body.csrf_token !== 'string' || body.csrf_token.length === 0) {
    throw new Error('CSRF 响应缺少 csrf_token 字段')
  }

  return body.csrf_token
}

/**
 * 拿到一个可用的 token。并发调用共享同一个请求（单飞），
 * 避免列表页同时发多个写请求时连续打 3 次 /auth/csrf。
 */
export async function ensureCsrf(): Promise<string> {
  if (cachedToken) return cachedToken
  if (inFlight) return inFlight

  const task = fetchCsrf()
    .then((token) => {
      cachedToken = token
      return token
    })
    .finally(() => {
      if (inFlight === task) inFlight = null
    })

  inFlight = task
  return task
}

/** 作废旧 token 并立刻取新的（登录/登出/CSRF 被拒之后用） */
export async function refreshCsrf(): Promise<string> {
  invalidateCsrf()
  return ensureCsrf()
}
