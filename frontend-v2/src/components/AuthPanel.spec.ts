import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'

import AuthPanel from './AuthPanel.vue'

const EXPIRED_TEXT = '登录状态已失效，请重新登录'
const LOGOUT_FAILED_TEXT = '服务端会话可能仍然有效'

vi.mock('@/stores/reset', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/reset')>()
  return { ...actual, logoutAndReset: vi.fn().mockResolvedValue('ok') }
})

describe('AuthPanel 会话失效提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('会话失效时在登录页给出明确说明，而不是静默跳转', () => {
    const auth = useAuthStore()
    auth.sessionExpired = true

    const wrapper = mount(AuthPanel)

    expect(wrapper.text()).toContain(EXPIRED_TEXT)
    // 提示是角色为 status 的横幅，屏幕阅读器能读到
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
  })

  it('首次访问（本来就没登录）不显示失效提示', () => {
    const wrapper = mount(AuthPanel)
    expect(wrapper.text()).not.toContain(EXPIRED_TEXT)
  })

  it('注册页不显示失效提示（那里说这个没意义）', async () => {
    const auth = useAuthStore()
    auth.sessionExpired = true

    const wrapper = mount(AuthPanel)
    const tabs = wrapper.findAll('button.tab')
    await tabs[1]!.trigger('click')

    expect(wrapper.text()).not.toContain(EXPIRED_TEXT)
  })

  it('出现表单校验错误时，错误优先于失效提示', async () => {
    const auth = useAuthStore()
    auth.sessionExpired = true

    const wrapper = mount(AuthPanel)
    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('请输入邮箱')
    expect(wrapper.text()).not.toContain(EXPIRED_TEXT)
  })
})

describe('AuthPanel 退出失败提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('退出失败时给出说明并提供「重试退出」，不再声称关浏览器就能彻底退出', () => {
    const auth = useAuthStore()
    auth.logoutFailed = true

    const wrapper = mount(AuthPanel)

    expect(wrapper.text()).toContain(LOGOUT_FAILED_TEXT)
    expect(wrapper.text()).toContain('重试退出')
    // 旧文案会误导用户以为关浏览器就一定安全
    expect(wrapper.text()).not.toContain('请关闭浏览器以彻底退出')
    // 用 alert 而非 status：这是需要用户处理的风险提示
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('点「重试退出」会再次调用退出接口，成功后提示消失', async () => {
    const auth = useAuthStore()
    auth.logoutFailed = true

    const wrapper = mount(AuthPanel)
    await wrapper.find('.banner-action').trigger('click')
    await flushPromises()

    expect(logoutAndReset).toHaveBeenCalledTimes(1)
    expect(auth.logoutFailed).toBe(false)
    expect(wrapper.text()).not.toContain(LOGOUT_FAILED_TEXT)
  })

  it('重试仍然失败时，提示继续保留', async () => {
    // 模拟真实 logoutAndReset 的副作用：它内部会 resetAllPrivateState，把 logoutFailed 复位
    vi.mocked(logoutAndReset).mockImplementationOnce(async () => {
      useAuthStore().logoutFailed = false
      return 'failed'
    })
    const auth = useAuthStore()
    auth.logoutFailed = true

    const wrapper = mount(AuthPanel)
    await wrapper.find('.banner-action').trigger('click')
    await flushPromises()

    expect(auth.logoutFailed).toBe(true)
    expect(wrapper.text()).toContain(LOGOUT_FAILED_TEXT)
  })
})
