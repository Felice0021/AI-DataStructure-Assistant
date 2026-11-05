/** 后端地址与路径前缀。前端一律用 127.0.0.1，不要用 localhost。 */

const rawBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8001'

export const API_BASE = String(rawBase).replace(/\/+$/, '')

export const API_PREFIX = '/api/v2'

export function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${API_PREFIX}${normalized}`
}
