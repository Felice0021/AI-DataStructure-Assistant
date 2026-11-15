/**
 * 私人界面状态的唯一清理入口。
 *
 * 验收要求：「登录过期或切换账户后，异常页面不显示旧的私人答案」。
 * 如果清理逻辑散落在各组件里，一定会漏；所以统一走这里，
 * 由 main.ts 注入到 apiClient 的 401 兜底，并由退出登录复用。
 *
 * 注意 import 方向：本文件依赖 store，store 不反向依赖本文件（避免循环引用）。
 */

import { authApi } from '@/api/auth'
import { invalidateCsrf } from '@/api/csrf'
import { ApiError } from '@/api/http'

import { useChatStore } from './chat'
import { useAskStore } from './ask'
import { useAuthStore } from './auth'
import { useKnowledgeBaseStore } from './knowledgeBase'

/** 只清私人数据（答案、知识库列表与选中项），不动登录态。
 *  用于「登录成功后」——防止上一段会话的错误卡片或旧答案残留到新会话（用户会看到一条过时的"登录已失效"）。 */
export function resetPrivateData(): void {
  useChatStore().clear()
  useAskStore().clear()
  useKnowledgeBaseStore().clear()
}

/** 清理顺序：先清答案，再清选中与列表，最后清用户 */
export function resetAllPrivateState(): void {
  resetPrivateData()
  useAuthStore().clear()
}

/**
 * 退出登录的结果：
 * - ok       服务端已吊销会话（204）
 * - expired  会话本来就失效了（401），等同于退出成功
 * - failed   真正失败了（网络/500）：本机已清，但服务端会话可能仍有效
 */
export type LogoutOutcome = 'ok' | 'expired' | 'failed'

/**
 * 退出登录。
 *
 * 本地一律清干净（安全优先）；但必须把「服务端到底有没有退成功」如实返回，
 * 否则会出现「界面显示已退出、服务端 Session 仍有效」的错觉。
 */
export async function logoutAndReset(): Promise<LogoutOutcome> {
  useChatStore().clear() // stop the upstream reader and withdraw drafts before waiting for logout
  let outcome: LogoutOutcome = 'ok'
  try {
    await authApi.logout()
  } catch (error) {
    outcome = error instanceof ApiError && error.status === 401 ? 'expired' : 'failed'
  } finally {
    // 退出后会话 Cookie 已变（或可能已变）：缓存的 CSRF token 一律作废。
    // 失败时更要清——否则重试退出会用上一个会话派生的 token。
    invalidateCsrf()
    resetAllPrivateState()
  }
  return outcome
}
