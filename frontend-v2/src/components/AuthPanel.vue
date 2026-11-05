<script setup lang="ts">
import { computed, ref } from 'vue'

import { errorMessage } from '@/composables/useErrorMessage'
import { useAuthStore } from '@/stores/auth'
import { resetPrivateData } from '@/stores/reset'

/**
 * 注册 / 登录。安全要点：
 * - 不读 Cookie、不存 token 到 localStorage，身份完全由服务端 Cookie 决定
 * - 注册成功后不当作已登录（后端也不会建立会话），必须再登录一次
 * - 密码不落任何本地存储
 */

type Mode = 'login' | 'register'

const auth = useAuthStore()

const mode = ref<Mode>('login')
const email = ref('')
const password = ref('')
const submitting = ref(false)
const localError = ref('')

const isRegister = computed(() => mode.value === 'register')
const errorText = computed(
  () => localError.value || (auth.errorCode ? errorMessage(auth.errorCode) : ''),
)
/** 会话失效提示只在登录表单显示（注册表单里说这个没意义） */
const showExpiredNotice = computed(() => auth.sessionExpired && !isRegister.value && !errorText.value && !auth.notice)
/** 退出请求失败：本机已清，但服务端会话可能仍有效，必须明确告知 */
const showLogoutWarning = computed(() => auth.logoutFailed && !isRegister.value)

function switchMode(next: Mode): void {
  mode.value = next
  localError.value = ''
  auth.errorCode = null
  auth.notice = null
}

async function submit(): Promise<void> {
  localError.value = ''
  const mail = email.value.trim()

  if (!mail) {
    localError.value = '请输入邮箱'
    return
  }
  if (!mail.includes('@')) {
    localError.value = '邮箱格式不正确'
    return
  }
  if (!password.value) {
    localError.value = '请输入密码'
    return
  }
  if (isRegister.value && password.value.length < 15) {
    localError.value = '注册密码至少 15 位，且需包含大写、小写、数字、符号中的 4 类'
    return
  }

  submitting.value = true
  try {
    if (isRegister.value) {
      const ok = await auth.register(mail, password.value)
      if (ok) {
        // 注册不自动登录：切回登录表单，让用户用刚设置的密码登录
        mode.value = 'login'
        password.value = ''
      }
    } else {
      // 登录「前」清掉上一段会话的残留（旧错误卡片、旧答案、旧选中项）：
      // 放在登录后会把刚挂载的知识库列表加载结果一起作废，导致列表空掉。
      resetPrivateData()
      await auth.login(mail, password.value)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth">
    <div class="auth-card">
      <h1 class="title">数据结构 AI 助教</h1>
      <p class="subtitle">登录后可基于课程资料提问，回答会附带可核对的来源。</p>

      <p v-if="showExpiredNotice" class="banner banner-warn" role="status">
        登录状态已失效，请重新登录
      </p>

      <p v-else-if="showLogoutWarning" class="banner banner-warn" role="status">
        本机登录状态已清除，但服务端会话可能仍然有效。在公共设备上请关闭浏览器以彻底退出。
      </p>

      <div class="tabs" role="tablist">
        <button
          type="button"
          class="tab"
          :class="{ 'is-active': !isRegister }"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          class="tab"
          :class="{ 'is-active': isRegister }"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <form class="form" @submit.prevent="submit">
        <label class="field">
          <span class="label">邮箱</span>
          <input
            v-model="email"
            type="email"
            class="input"
            autocomplete="username"
            placeholder="student@example.edu"
          />
        </label>

        <label class="field">
          <span class="label">密码</span>
          <input
            v-model="password"
            type="password"
            class="input"
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
            :placeholder="isRegister ? '至少 15 位' : '输入密码'"
          />
        </label>

        <p v-if="errorText" class="msg msg-error">{{ errorText }}</p>
        <p v-else-if="auth.notice" class="msg msg-ok">{{ auth.notice }}</p>

        <button type="submit" class="submit" :disabled="submitting">
          {{ submitting ? '处理中…' : isRegister ? '注册' : '登录' }}
        </button>
      </form>

      <p class="foot">
        注册不会自动登录，注册成功后请用同一邮箱密码登录。
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth {
  display: flex;
  justify-content: center;
  padding: 64px 20px;
}

.auth-card {
  width: 100%;
  max-width: 380px;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
}

.title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 500;
  color: var(--ink);
}

.subtitle {
  margin: 0 0 20px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--muted);
}

.banner {
  margin: 0 0 16px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.banner-warn {
  border: 1px solid #e6c07a;
  background: #fff8e8;
  color: #8a6114;
}

.tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 18px;
  padding: 3px;
  border-radius: 8px;
  background: #f2f4f7;
}

.tab {
  flex: 1;
  padding: 7px 0;
  border: 0;
  border-radius: 6px;
  background: none;
  font-family: inherit;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
}

.tab.is-active {
  background: #fff;
  color: var(--ink);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.label {
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
}

.input {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  color: var(--ink);
  background: #fff;
}

.input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(24, 95, 165, 0.12);
}

.msg {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}

.msg-error {
  color: #9c322d;
}

.msg-ok {
  color: #2f6f45;
}

.submit {
  margin-top: 4px;
  padding: 10px 0;
  border: 0;
  border-radius: 8px;
  background: var(--brand);
  color: #fff;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.submit:disabled {
  background: #b9c2cc;
  cursor: not-allowed;
}

.foot {
  margin: 16px 0 0;
  font-size: 11px;
  line-height: 1.7;
  color: #9aa2ac;
}
</style>
