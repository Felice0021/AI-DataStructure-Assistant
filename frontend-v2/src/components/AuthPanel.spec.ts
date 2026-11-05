import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'

import AuthPanel from './AuthPanel.vue'

const EXPIRED_TEXT = '登录状态已失效，请重新登录'

describe('AuthPanel 会话失效提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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
