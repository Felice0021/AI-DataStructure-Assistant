import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import { ApiError } from '@/api/http'
import type { User } from '@/types/api'

export type AuthStatus = 'anonymous' | 'loading' | 'authenticated'

interface AuthState {
  user: User | null
  status: AuthStatus
  errorCode: string | null
  notice: string | null
  /** 是否因会话失效（401）被动登出；用于在登录页给出明确提示，而不是静默跳转 */
  sessionExpired: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    user: null,
    status: 'anonymous',
    errorCode: null,
    notice: null,
    sessionExpired: false,
  }),

  getters: {
    isAuthenticated: (state): boolean => state.status === 'authenticated' && state.user !== null,
    email: (state): string => state.user?.email ?? '',
    roleLabel: (state): string => (state.user?.role === 'admin' ? '管理员' : '学生'),
  },

  actions: {
    /** 启动时探测会话；401 属正常「未登录」，不当作错误 */
    async fetchMe(): Promise<void> {
      this.errorCode = null
      try {
        const { user } = await authApi.me()
        this.user = user
        this.status = 'authenticated'
      } catch (error) {
        this.user = null
        this.status = 'anonymous'
        if (error instanceof ApiError && error.status !== 401) {
          this.errorCode = error.code
        }
      }
    },

    /** 注册不会自动登录，成功后只提示，不建立登录态 */
    async register(email: string, password: string): Promise<boolean> {
      this.errorCode = null
      this.notice = null
      try {
        await authApi.register({ email, password })
        this.notice = '注册成功，请用刚才的邮箱和密码登录'
        return true
      } catch (error) {
        this.errorCode = error instanceof ApiError ? error.code : 'network_error'
        return false
      }
    },

    async login(email: string, password: string): Promise<boolean> {
      this.errorCode = null
      this.notice = null
      this.status = 'loading'
      try {
        const { user } = await authApi.login({ email, password })
        this.user = user
        this.status = 'authenticated'
        // 登录成功后清除「会话失效」提示，避免提示语残留到新会话
        this.sessionExpired = false
        return true
      } catch (error) {
        this.user = null
        this.status = 'anonymous'
        this.errorCode = error instanceof ApiError ? error.code : 'network_error'
        return false
      }
    },

    /** 401 被动登出时调用：由 main.ts 在 resetAllPrivateState 之后设置，
     *  保证登录页能说明「为什么被踢出来」，而不是静默跳转。 */
    markSessionExpired(): void {
      this.sessionExpired = true
    },

    clear(): void {
      this.user = null
      this.status = 'anonymous'
      this.errorCode = null
      this.notice = null
      this.sessionExpired = false
    },
  },
})
