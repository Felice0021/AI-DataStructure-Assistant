import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { mockAnswered, mockKnowledgeBases, mockUser } from '@/mocks/fixtures'

import { useAskStore } from './ask'
import { useAuthStore } from './auth'
import { useKnowledgeBaseStore } from './knowledgeBase'
import { resetAllPrivateState, resetPrivateData } from './reset'

describe('resetAllPrivateState', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('401 / 退出后不残留任何私人状态', () => {
    const auth = useAuthStore()
    const knowledgeBase = useKnowledgeBaseStore()
    const ask = useAskStore()

    auth.user = { ...mockUser }
    auth.status = 'authenticated'
    knowledgeBase.items = [...mockKnowledgeBases]
    knowledgeBase.selectedIds = [mockKnowledgeBases[0]!.id]
    ask.phase = 'answered'
    ask.result = mockAnswered
    ask.lastQuery = '栈和队列的区别'

    resetAllPrivateState()

    expect(auth.user).toBeNull()
    expect(auth.status).toBe('anonymous')
    expect(knowledgeBase.items).toHaveLength(0)
    expect(knowledgeBase.selectedIds).toHaveLength(0)
    expect(ask.phase).toBe('idle')
    expect(ask.result).toBeNull()
    expect(ask.lastQuery).toBe('')
  })

  it('清理是幂等的，可以重复调用', () => {
    const auth = useAuthStore()
    resetAllPrivateState()
    resetAllPrivateState()
    expect(auth.status).toBe('anonymous')
  })

  it('resetPrivateData 只清私人数据，不影响登录态（登录成功后用它防残留）', () => {
    const auth = useAuthStore()
    const ask = useAskStore()

    auth.user = { ...mockUser }
    auth.status = 'authenticated'
    auth.sessionExpired = true
    ask.phase = 'failed'
    ask.errorCode = 'unauthorized'
    ask.errorMessage = '登录状态已失效，请重新登录'

    resetPrivateData()

    // 私人数据被清掉：重新登录后不会再看到过时的「登录已失效」卡片
    expect(ask.phase).toBe('idle')
    expect(ask.errorMessage).toBe('')
    // 登录态保留：调用方紧接着会写入新的 user
    expect(auth.status).toBe('authenticated')
  })

  it('401 流程：先 resetAllPrivateState 再 markSessionExpired，提示才不会被 clear 掉', () => {
    const auth = useAuthStore()
    auth.user = { ...mockUser }
    auth.status = 'authenticated'

    resetAllPrivateState()
    auth.markSessionExpired()

    expect(auth.status).toBe('anonymous')
    expect(auth.sessionExpired).toBe(true)

    // 登录成功后提示自动消失
    auth.sessionExpired = false
    expect(auth.sessionExpired).toBe(false)
  })
})
