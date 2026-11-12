import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { mockAnswered, mockRefused } from '@/mocks/fixtures'

import AnswerView from './AnswerView.vue'

const baseProps = {
  result: null,
  errorCode: null,
  errorStatus: 0,
  errorMessage: '',
} as const

describe('AnswerView 状态分发', () => {
  it('keeps sources folded until a citation is clicked', async () => {
    const wrapper = mount(AnswerView, { props: { ...baseProps, phase: 'answered', result: mockAnswered } })
    expect(wrapper.find('details').attributes('open')).toBeUndefined()
    await wrapper.find('button.cite').trigger('click')
    expect(wrapper.find('details').attributes('open')).toBeDefined()
    expect(wrapper.find('.source-item.is-active').exists()).toBe(true)
  })
  it('answered 渲染成功卡片', () => {
    const wrapper = mount(AnswerView, {
      props: { ...baseProps, phase: 'answered', result: mockAnswered },
    })

    expect(wrapper.find('[data-testid="answer-success"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="answer-refused"]').exists()).toBe(false)
    expect(wrapper.findAll('button.cite').length).toBeGreaterThan(0)
  })

  it('200 拒答渲染成「资料不足」，绝不能显示成成功', () => {
    const wrapper = mount(AnswerView, {
      props: { ...baseProps, phase: 'refused', result: mockRefused },
    })

    expect(wrapper.find('[data-testid="answer-refused"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="answer-success"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('资料不足')
  })

  it('503 与 502 的提示不同，且都不显示为成功', () => {
    const unavailable = mount(AnswerView, {
      props: {
        ...baseProps,
        phase: 'failed',
        errorCode: 'generation_unavailable',
        errorStatus: 503,
        errorMessage: '服务暂不可用，请稍后重试',
      },
    })
    const validation = mount(AnswerView, {
      props: {
        ...baseProps,
        phase: 'failed',
        errorCode: 'validation_failed',
        errorStatus: 502,
        errorMessage: '生成结果未通过校验，未作为答案展示',
      },
    })

    // 503 的徽标是「服务不可用」，502 是「生成结果未通过校验」，两者必须一眼能分开
    expect(unavailable.find('.badge').text()).toBe('服务不可用')
    expect(validation.find('.badge').text()).toBe('生成结果未通过校验')
    expect(unavailable.text()).toContain('服务暂不可用，请稍后重试')
    expect(unavailable.find('[data-testid="answer-success"]').exists()).toBe(false)
    expect(validation.find('[data-testid="answer-success"]').exists()).toBe(false)
  })

  it('does not present missing cloud authorization as a model outage', () => {
    const wrapper = mount(AnswerView, { props: { ...baseProps, phase: 'failed', errorCode: 'generation_cloud_consent_required', errorStatus: 503, errorMessage: '请联系管理员' } })
    expect(wrapper.find('.badge').text()).toBe('需要处理授权')
    expect(wrapper.text()).not.toContain('这是服务端出错')
  })

  it('401 不提供重试按钮（应重新登录）', () => {
    const wrapper = mount(AnswerView, {
      props: {
        ...baseProps,
        phase: 'failed',
        errorCode: 'unauthorized',
        errorStatus: 401,
        errorMessage: '登录状态已失效，请重新登录',
      },
    })

    expect(wrapper.find('button.retry').exists()).toBe(false)
  })

  it('503 提供重试按钮并抛出事件', async () => {
    const wrapper = mount(AnswerView, {
      props: {
        ...baseProps,
        phase: 'failed',
        errorCode: 'generation_unavailable',
        errorStatus: 503,
        errorMessage: '生成服务暂不可用',
      },
    })

    await wrapper.find('button.retry').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('loading 与 idle 状态不残留旧答案', () => {
    const idle = mount(AnswerView, { props: { ...baseProps, phase: 'idle' } })
    const loading = mount(AnswerView, { props: { ...baseProps, phase: 'loading' } })

    expect(idle.find('[data-testid="answer-success"]').exists()).toBe(false)
    expect(loading.find('[data-testid="answer-success"]').exists()).toBe(false)
    expect(loading.find('[data-testid="answer-loading"]').exists()).toBe(true)
  })
})
