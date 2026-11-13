/**
 * 错误码 → 中文文案。
 *
 * 为什么必须查表而不是直接显示后端 message：
 * docs/v2/FRONTEND_HANDOFF.md:80 明确要求「422 不回显原始输入，不能依赖底层异常文字」，
 * 后端 message 是英文固定串（如 "Invalid request"），直接展示对用户无意义。
 * 未知 code 一律走兜底，绝不把原始 message 插进 DOM。
 */

const CODE_MESSAGES: Record<string, string> = {
  // 传输 / 网络
  network_error: '无法连接后端服务，请确认后端已在 127.0.0.1:8001 启动',
  timeout: '请求超时，请稍后重试',
  invalid_response: '服务返回了无法解析的内容',

  // 认证
  unauthorized: '登录状态已失效，请重新登录',
  invalid_credentials: '邮箱或密码不正确',
  email_exists: '该邮箱已注册，请直接登录',
  invalid_email: '邮箱格式不正确',
  weak_password: '密码强度不足：至少 15 位，且包含 4 类字符',

  // 权限 / 安全
  forbidden: '没有权限执行该操作',
  origin_rejected: '请求来源被拒绝。请用 http://127.0.0.1:5173 打开页面，不要用 localhost',
  csrf_rejected: '安全校验失败，已自动重试；若持续失败请刷新页面',
  https_required: '该环境要求 HTTPS',
  loopback_required: '该环境只允许本机访问',
  cloud_consent_required: '所选知识库尚未获得所需的处理授权，请联系管理员。',
  generation_cloud_consent_required: '所选知识库尚未获得回答生成授权，请联系管理员。',
  rerank_cloud_consent_required: '所选知识库尚未获得资料处理授权，请联系管理员。',

  // 资源
  not_found: '资源不存在或无权访问',
  knowledge_base_not_found: '知识库不存在，或不是你可访问的资料',
  document_not_found: '文档不存在或无权访问',
  knowledge_base_name_exists: '同名知识库已存在，请换个名字',

  // 生成
  generation_unavailable: '服务暂不可用，请稍后重试',
  validation_failed: '生成结果未通过校验，未作为答案展示',
  service_unavailable: '服务暂不可用，请稍后再试',
  dense_unavailable: '向量检索暂不可用',

  // 限流 / 通用
  login_rate_limited: '尝试次数过多，请稍后再试',
  internal_error: '服务内部错误，请稍后再试',
  // 仅开发环境：mock 没覆盖该接口（已被本地拦下，未发到后端）
  mock_unhandled: '该接口尚未被 Mock 覆盖（开发环境）',
  invalid_request: '请求参数不合法',
}

const STATUS_FALLBACK: Record<number, string> = {
  401: '登录状态已失效，请重新登录',
  403: '没有权限执行该操作',
  404: '资源不存在或无权访问',
  429: '操作过于频繁，请稍后再试',
  500: '服务内部错误，请稍后再试',
  502: '生成结果未通过校验',
  503: '服务暂不可用，请稍后再试',
}

/** 拒答原因（AskResponse.reason）→ 中文 */
const REASON_MESSAGES: Record<string, string> = {
  conversation_context_required: '缺少可用的上文，请明确所指的数据结构或算法。',
  conversation_context_ambiguous: '上文可能涉及多个对象，请说明本次要问哪一个。',
  no_evidence: '检索没有命中可依据的资料',
  no_lexical_support: '资料中缺少与问题关键词直接对应的内容',
  conflicting_assertions: '检索到的资料之间存在冲突表述',
  model_refusal: '模型认为现有资料不足以回答此问题',
  model_reported_conflict: '模型判断资料互相矛盾，无法给出确定结论',
  scope_not_verified: '问题超出所选资料的范围',
}

export function errorMessage(code: string, status = 0): string {
  const mapped = CODE_MESSAGES[code]
  if (mapped) return mapped
  // 生成链路的细分原因（generation_timeout / generation_rate_limited / ...）
  // 统一收口，避免几十个 code 各写一条文案还漏掉
  if (code.startsWith('generation_')) return '服务暂不可用，请稍后重试'
  const byStatus = STATUS_FALLBACK[status]
  if (byStatus) return byStatus
  return '请求失败，请稍后重试'
}

export function reasonMessage(reason: string | null): string {
  if (!reason) return '资料中没有足够依据'
  return REASON_MESSAGES[reason] ?? '资料中没有足够依据'
}
