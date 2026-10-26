# V2 API 合约：健康检查、认证与知识库

路径前缀 `/api/v2`，JSON 请求与响应；OpenAPI `/api/v2/openapi.json`，文档 `/api/v2/docs`。
本地 HTTP 必须显式启用 loopback 开发配置；默认生产配置要求 HTTPS。

## 前端 Cookie 与 CSRF 流程

1. 使用 `credentials: 'include'` 调用 `GET /api/v2/auth/csrf`。
2. 响应为 `{"csrf_token":"<opaque csrf value>"}`。在内存中保存该值，不存储会话 Cookie 的副本。
3. 所有 POST、PATCH、DELETE 同时携带 `X-CSRF-Token` 和浏览器自动生成的精确 `Origin`。
   浏览器不允许脚本自行设置 Origin；服务端不接受 Referer 或缺失 Origin 作为替代。
4. 登录成功后 Cookie 已轮换，必须重新 GET `/auth/csrf` 获取绑定新会话的 CSRF Token。
5. 退出后 Cookie 已删除，再次 POST（包括重复退出）前重新获取 CSRF Token。

会话凭证仅存在于 `Set-Cookie`/浏览器 Cookie 中，不在响应 JSON 中返回。
CSRF Token 是使用 HttpOnly 随机 Cookie 作为密钥、固定用途字符串作为消息的 HMAC-SHA256，
不是原始会话凭证，不能用于登录。登录前使用独立预认证 Cookie，登录后使用当前会话 Cookie。
Cookie 密钥不会向 JavaScript 暴露；生产 `__Host-` 前缀防止其他子域注入同名 Cookie。
GET `/csrf` 不承诺已登录，身份以 `/me` 为准。

| Cookie | 生产 HTTPS | 明确开启的本地 HTTP |
| --- | --- | --- |
| 会话名称 | `__Host-ds_v2_session` | `ds_v2_session` |
| 预认证名称 | `__Host-ds_v2_preauth` | `ds_v2_preauth` |
| 属性 | HttpOnly、Secure、SameSite=Lax、Path=/、无 Domain | HttpOnly、SameSite=Lax、Path=/、无 Domain |
| 有效期 | 会话默认 8 小时，预认证 30 分钟 | 同左 |

会话同时设置 Max-Age 和 Expires，服务端另行验证过期与吊销状态。
认证响应含 `Cache-Control: no-store`；CORS 仅允许显式配置来源并支持 credentials。
SameSite/CORS 只是额外防线，不能代替服务端 Origin 与 CSRF 校验。

## 认证接口

安全用户对象 `User`：

```json
{
  "id": "<uuid>",
  "email": "<canonical email>",
  "role": "student",
  "is_active": true,
  "created_at": "<ISO-8601 timestamp>",
  "updated_at": "<ISO-8601 timestamp>"
}
```

| 方法与路径 | 输入 / 条件 | 成功响应 |
| --- | --- | --- |
| GET `/auth/csrf` | 支持安全传输；如有 Origin 必须匹配白名单 | 200 `{"csrf_token":"..."}`，必要时设置预认证 Cookie |
| POST `/auth/register` | JSON `email`、`password`；Origin + CSRF | 201 `{"user":User}`，不自动登录 |
| POST `/auth/login` | JSON `email`、`password`；Origin + CSRF | 200 `{"user":User}`，设置新会话 Cookie |
| GET `/auth/me` | Cookie 中有效、未过期、未吊销会话；用户激活 | 200 `{"user":User}` |
| POST `/auth/logout` | Origin + 当前 Cookie 绑定 CSRF | 204，无正文，吊销当前会话并删除 Cookie |

注册和登录均拒绝额外字段，不能传入 `role`、`user_id` 等身份参数。
邮箱去首尾空白，经过 EmailStr 格式/规范化检查并 casefold；数据库 `lower(email)` 唯一索引兜底并发。
注册密码 15–128 字符，禁止空白/高度重复/少量常见弱口令及 NUL，不强制符号组合；密码不被 trim 后保存。
登录密码上限 128 字符。未注册、密码错误、禁用账户统一返回相同的 401。

退出不影响其他会话。携带已吊销/未知会话但 CSRF 正确时退出仍为 204；
浏览器已经清掉 Cookie 后，要先重新获取匿名 CSRF 才能重复退出。缺少 CSRF 依然返回 403。

## 认证错误格式

```json
{"error":{"code":"invalid_credentials","message":"Invalid email or password"}}
```

| HTTP | code | 含义 |
| --- | --- | --- |
| 401 | `invalid_credentials` | 登录邮箱/密码不正确，或账户禁用 |
| 401 | `unauthorized` | 当前会话缺失、伪造、过期、吊销，或用户被禁用 |
| 403 | `forbidden` | 有效身份没有所需角色 |
| 403 | `origin_rejected` / `csrf_rejected` | 来源或 CSRF 校验失败 |
| 403 | `https_required` / `loopback_required` | 传输环境不符合安全配置 |
| 409 | `email_exists` | 邮箱已注册；注册接口有意给出重复提示 |
| 422 | `invalid_email` / `weak_password` / `invalid_request` | 输入无效、密码不满足策略或额外字段 |
| 429 | `login_rate_limited` | 登录失败限流，含 Retry-After 秒数 |
| 503 | `service_unavailable` | 数据库不可用，认证失败关闭 |
| 500 | `internal_error` | 未预期内部错误 |

验证错误不会回显密码、原始输入或内部堆栈。404 保持 FastAPI 默认格式。

## 权限依赖复用

`dependencies/auth.py` 提供：

- `get_current_user`：从 Cookie 的摘要查询数据库会话并检查过期、吊销、用户激活状态。
- `require_active_user`：在上述规则上提供显式的激活用户依赖。
- `require_role("student", "admin")`：显式列出允许角色；`require_role("admin")` 只允许管理员。

将依赖作为 `Depends(...)` 放在后续路由中即可。用户 ID 和角色均来自数据库，不能信任请求自报值。
这些依赖对修改请求也执行 Origin/CSRF 校验。角色不是数据所有权校验；
知识库服务已按当前用户 ID 过滤资源；后续文件和检索模块必须复用该资源检查。
权限探测 `/test/student`、`/test/admin` 只存在于测试应用，不在正式应用中发布。

## 原有健康接口保持兼容

- GET `/health`：200 `{"status":"ok","service":"ds-assistant-v2","version":"2.0.0"}`，不依赖数据库。
- GET `/health/db`：真实执行 SELECT 1，成功 200 `{"status":"ok","database":"ok"}`，
  断连 503 `{"status":"unavailable","database":"unavailable"}`。
- 健康接口的未预期错误继续使用原 500 `{"detail":"Internal server error"}`。
- 健康检查不代替迁移/schema/pgvector 验证，也不依赖认证 Cookie。


## 第三阶段 3A：知识库 API

下列接口全部要求已登录、激活用户。写请求同时要求白名单 Origin 与当前会话绑定的 X-CSRF-Token。
请求禁止额外字段，不能传入 owner_id、visibility、index_version、name_key、deleted_at 或 user_id 伪造身份。

| 方法与路径 | 输入 | 成功 |
| --- | --- | --- |
| GET /api/v2/knowledge-bases | limit 默认 50（1–100），offset 默认 0（非负） | 200，分页列表 |
| POST /api/v2/knowledge-bases | name，description 可选 | 201，当前用户的 private |
| GET /api/v2/knowledge-bases/{knowledge_base_id} | UUID | 200，安全元数据 |
| PATCH /api/v2/knowledge-bases/{knowledge_base_id} | name/description 至少一个 | 200，修改后的元数据 |
| DELETE /api/v2/knowledge-bases/{knowledge_base_id} | UUID | 204，无正文 |
| POST /api/v2/admin/knowledge-bases | 仅管理员；name、description | 201，系统 public，owner_id=NULL |

管理员在普通创建入口创建的仍是自己的 private。公共资源使用同一个详情/PATCH/DELETE 路径，
由服务层检查管理员身份。管理员对其他用户私人资源的 GET/PATCH/DELETE 仍为 404。

创建请求示例：

    {"name":"数据结构","description":"课程资料"}

单项响应：

    {"knowledge_base":{"id":"<uuid>","owner_id":"<current-user-uuid>","name":"数据结构","description":"课程资料","visibility":"private","index_version":0,"created_at":"<ISO8601>","updated_at":"<ISO8601>"}}

列表响应：

    {"items":[<knowledge-base-object>],"total":1,"limit":50,"offset":0}

items 只包含自己的有效私人知识库和有效公共知识库；total 同样按该权限范围计数。
按 created_at、id 降序稳定排序。没有按任意 user_id 查询他人资料的功能。
响应不包含 name_key、deleted_at 或其他内部 ORM 状态。

name 先做 NFKC、首尾空白移除及连续空白合并，再校验 1–120 字符。
description 最多 4000 字符，默认空字符串。PATCH 只接受这两个字段，空请求或显式 null 返回 422；
使用 description="" 清空说明。name/description 中的 NUL 被拒绝。
index_version 固定由服务端管理，当前新建为 0，修改元数据不会推进内容索引版本。

统一错误格式：

    {"error":{"code":"knowledge_base_not_found","message":"Knowledge base not found"}}

| HTTP | code | 含义 |
| --- | --- | --- |
| 401 | unauthorized | 未登录/会话无效/账户禁用 |
| 403 | forbidden | 学生创建或修改/删除公共资源 |
| 403 | origin_rejected / csrf_rejected | 写请求的来源/CSRF 不符合要求 |
| 404 | knowledge_base_not_found | 不存在、已删除、或属于其他用户的私人资源 |
| 409 | knowledge_base_name_exists | 相同命名空间内已有同名有效资源 |
| 422 | invalid_request | 非法 UUID、名称/说明不合法、空 PATCH 或不可写字段 |
| 503 | service_unavailable | 数据库不可用，错误已脱敏 |
| 500 | internal_error | 未预期内部错误，不返回堆栈 |

已删除资源不在列表中，再次 GET/PATCH/DELETE 均为 404。删除后可创建同名新 UUID。
学生可读取 public，但不能修改/删除；对私人无权限情况统一 404，错误中不返回其名称、说明或所有者信息。
知识库及认证响应为 no-store。CORS 对白名单来源支持 PATCH/DELETE，来源列表没有放宽。

后续文件、解析及 RAG API 必须复用知识库服务层的可读/可写检查，再访问 documents/chunks；
仅知道 UUID 或具有 admin 角色都不能代替私人资料所有权检查。本轮没有内容或检索接口。
