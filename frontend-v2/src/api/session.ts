/**
 * 会话代际（epoch）。
 *
 * 解决的问题：用户退出、切换账号或会话失效后，**之前还没返回的异步请求**
 * 不能再把数据写回页面，它的 401 也不能把新账号踢下线。
 *
 * 做法：任何会改变「当前是谁」的动作（登录成功、登出、401 清理）都 bump 一次。
 * 请求发出时记下当时的 epoch，返回时若 epoch 已变，说明会话已换人 —— 直接丢弃。
 *
 * 刻意不依赖 Pinia / Vue：http 层需要读它，而 store 又依赖 http，
 * 放独立模块可以避免循环引用。
 */

let epoch = 0

export function currentEpoch(): number {
  return epoch
}

/** 会话发生变更时调用；返回新的 epoch 便于测试断言 */
export function bumpEpoch(): number {
  epoch += 1
  return epoch
}
