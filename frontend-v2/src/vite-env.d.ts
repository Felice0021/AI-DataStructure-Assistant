/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端地址，必须是 127.0.0.1，避免 Origin 被拒 */
  readonly VITE_API_BASE?: string
  /** 'true' 时启用 MSW 模拟 */
  readonly VITE_USE_MOCK?: string
  /** mock 场景：answered | refuse | unavailable | unauthorized */
  readonly VITE_MOCK_SCENARIO?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
