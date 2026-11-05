import type { Credentials, Registration, UserEnvelope } from '@/types/api'

import { invalidateCsrf, refreshCsrf } from './csrf'
import { request } from './http'

export const authApi = {
  /** 注册成功只返回 user，不会建立会话；必须再调 login */
  register(payload: Registration): Promise<UserEnvelope> {
    return request<UserEnvelope>('/auth/register', {
      method: 'POST',
      body: payload,
      skipAuthHandler: true,
    })
  },

  async login(payload: Credentials): Promise<UserEnvelope> {
    const result = await request<UserEnvelope>('/auth/login', {
      method: 'POST',
      body: payload,
      skipAuthHandler: true,
    })
    // 登录会轮换会话 Cookie 并删除预认证 Cookie，旧 token 必然失效
    await refreshCsrf()
    return result
  },

  /** 401 属正常「未登录」，交给 store 处理，不触发全局清理 */
  me(): Promise<UserEnvelope> {
    return request<UserEnvelope>('/auth/me', { skipAuthHandler: true })
  },

  async logout(): Promise<void> {
    await request<void>('/auth/logout', { method: 'POST', retryOnCsrf: false })
    // 服务端已删除 Cookie，token 作废；下次写请求时惰性重取
    invalidateCsrf()
  },
}
