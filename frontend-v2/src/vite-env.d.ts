/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端地址，必须是 127.0.0.1，避免 Origin 被拒 */
  readonly VITE_API_BASE?: string
  /** 'true' 时启用 MSW 模拟 */
  readonly VITE_USE_MOCK?: string
  readonly VITE_REGISTRATION_ENABLED?: string
  /** Non-secret, environment-specific course UUID; must also be in the authorized API list. */
  readonly VITE_COURSE_KB_ID?: string
  /** mock 场景：answered | refuse | unavailable | unauthorized */
  readonly VITE_MOCK_SCENARIO?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
