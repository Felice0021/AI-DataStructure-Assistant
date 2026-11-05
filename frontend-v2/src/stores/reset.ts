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

import { useAskStore } from './ask'
import { useAuthStore } from './auth'
import { useKnowledgeBaseStore } from './knowledgeBase'

/** 只清私人数据（答案、知识库列表与选中项），不动登录态。
 *  用于「登录成功后」——防止上一段会话的错误卡片或旧答案残留到新会话（用户会看到一条过时的"登录已失效"）。 */
export function resetPrivateData(): void {
  useAskStore().clear()
  useKnowledgeBaseStore().clear()
}

/** 清理顺序：先清答案，再清选中与列表，最后清用户 */
export function resetAllPrivateState(): void {
  resetPrivateData()
  useAuthStore().clear()
}

/** 退出登录：即使服务端登出失败（会话已过期），本地也一定要清干净 */
export async function logoutAndReset(): Promise<void> {
  try {
    await authApi.logout()
  } catch {
    // 忽略：会话可能已失效，本地清理才是关键
  } finally {
    resetAllPrivateState()
  }
}
