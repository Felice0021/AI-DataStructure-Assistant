> 当前集成交付版本：2026-10-26，Alembic **0007_cloud_consents**，Generator **qwen3.8-flash**。当前启动、用途授权与API以 TEAM_ONBOARDING.md、FRONTEND_HANDOFF.md、openapi.json 及本文“最终集成”章节为准。以下旧阶段验收（0006、NOT VERIFIED、云生成硬阻塞）是历史记录，不代表当前状态。

# V2 API 合约：健康检查、认证、知识库、文件、检索与RAG

路径前缀 `/api/v2`，除文件上传/下载外使用 JSON 请求与响应；OpenAPI `/api/v2/openapi.json`，文档 `/api/v2/docs`。
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
仅知道 UUID 或具有 admin 角色都不能代替私人资料所有权检查。3B-1 原始文件接口见下节；没有解析或检索接口。

## 3B-1：原始文件

所有路径均要求有效会话。POST/DELETE 必须携带现有 Origin 与 X-CSRF-Token。
前端使用 FormData.append('file', file)，credentials: include；由浏览器设置 multipart boundary，
不要手工写入没有 boundary 的 Content-Type。仅接受一个 file，拒绝额外表单字段和多文件。

|方法与路径|成功响应|
|---|---|
|POST /knowledge-bases/{kb_id}/documents|201 {"document": Document}|
|GET /knowledge-bases/{kb_id}/documents?limit=50&offset=0|200 {"items":[Document],"total":0,"limit":50,"offset":0}；limit 1–100，offset >=0|
|GET /knowledge-bases/{kb_id}/documents/{doc_id}|200 {"document": Document}|
|GET /knowledge-bases/{kb_id}/documents/{doc_id}/download|200 附件字节流，application/octet-stream|
|DELETE /knowledge-bases/{kb_id}/documents/{doc_id}|204，无正文；允许重复，物理失败可重试|

Document 的安全字段：id、knowledge_base_id、uploaded_by、original_filename、mime_type、size_bytes、
sha256、status、created_at、updated_at；UUID 为字符串、时间为 ISO-8601，storage_key/磁盘路径/删除标记不返回。
新上传 status 初始 uploaded，自动创建后台任务；parsed 仅表示文本/Chunk 完成，不能当作可检索的 ready；无任何客户端 owner/path/status 设置入口。

读取公共文件允许所有激活用户；公共上传/删除仅管理员。私人文件仅所属知识库所有者，管理员不能绕过。
跨知识库拼接 doc_id 返回 404；父知识库删除后所有列表、详情、下载和写入都不可访问。
文档删除后详情/下载 404，列表不含该文档；重复 DELETE 在有效且授权父知识库下仍 204。
已开始的授权下载可以完成，后续下载返回 404，不尝试召回已发送的数据。
下载为 attachment + RFC5987 UTF-8 文件名（ASCII fallback download）、nosniff、no-store、sandbox CSP；
不返回真实磁盘路径，不提供 inline 预览或公开静态链接。

格式：PDF 的版本标识与 EOF；DOCX ZIP/Office content-types、关系和必要主文档条目；
TXT 仅 UTF-8（含 BOM），拒绝二进制控制符、空白/BOM-only、PDF/ZIP/可执行签名伪装。
扩展名 .pdf/.docx/.txt 大小写均可；声明 MIME 须匹配检测结果，允许通用 application/octet-stream 或空声明。
文件名 <=255 字符且 <=255 UTF-8 字节，拒绝路径分隔符、冒号、控制/格式字符和首尾空白。

DOCX 不落地解压、不抽取正文，仅做有界 ZIP 结构及包元数据 CRC 验证：最多 256 条目，中央目录 <=256 KiB，
ZIP 声明单条目解压 <=32 MiB、累计 <=64 MiB、压缩比 <=200；拒绝加密、ZIP64/多卷、不支持算法、
目录穿越、重复条目、符号链接、宏/嵌入对象/ActiveX 和损坏容器。某些合法大型/高压缩 Office 文件会被拒绝。
只解压校验包元数据 XML，不解压正文/媒体；正文压缩流与完整文档语义需未来隔离解析器验证。
这不是完整文档语义校验或恶意软件扫描，PDF 基础标识通过不代表内容安全。

|HTTP|code|含义|
|---|---|---|
|401/403|沿用认证错误|未登录、CSRF/来源错误或公共写入无权限|
|404|knowledge_base_not_found / document_not_found|不存在、墓碑、无权访问的私人知识库或文档不匹配|
|408|upload_timeout|multipart 实际接收/解析超过时限|
|409|storage_quota_exceeded|文件数或已占用容量达到配置上限|
|413|file_too_large|请求体、文件或剩余可用容量不足；实际流计数，不依赖 Content-Length|
|422|invalid_file / invalid_request|文件格式/名称、multipart、UUID、分页或额外字段无效|
|429|upload_busy|跨进程单上传槽占用，Retry-After: 2|
|503|storage_unavailable / service_unavailable|存储或数据库失败，响应已脱敏|

错误仍为 {"error":{"code":"...","message":"..."}}。204 仅承诺逻辑删除生效，不承诺物理清理立即成功。

## 3B-2A：解析状态、重试和 Chunk

上传 POST 仍返回 201 document（初始 uploaded），同一事务创建 queued 任务；异步 Worker 启动后自动执行。
Document.status 可为 uploaded、processing、parsed、failed；ready 仍保留但本轮不写入。

下面路径前缀为 /api/v2/knowledge-bases/{kb_id}/documents/{doc_id}：

|方法/后缀|请求|响应|
|---|---|---|
|GET /ingestion|有效 Cookie，可读父知识库与文档|200 {"job": Job}|
|POST /ingestion|可写权限 + Origin/CSRF；JSON {} 或 {"reprocess":true}，拒绝其他字段|202 {"job": Job}|
|GET /chunks?limit=50&offset=0|可读；limit 1–100，offset >=0|200 {"items":[Chunk],"total":N,"limit":50,"offset":0}|

Job 安全字段：id、document_id、generation、status、attempts、max_attempts、created_at、started_at、
finished_at、next_retry_at、error_code。租约 token、执行用户、存储路径不返回。不提供脱离文档授权的任务 ID 查询。
Chunk 字段：id、document_id、generation、chunk_index、content、content_hash、page_number、section_title、
source_metadata（block_start/block_end）；index 从 0 开始，PDF 页号从 1 开始。
Chunk 属于敏感正文，仅经过同一父资源权限检查后返回，响应 no-store；不得把全文写入前端/代理日志。

在途 queued/running 重复 POST 幂等，不重置尝试次数或租约。尚未处理/失败/取消可显式重试；
已 parsed（或未来 ready）默认 409 already_parsed，需明确 reprocess=true 才增加代次重新解析。
重新解析期间旧 Chunk 列表为空，成功后只返回新代次。当前无法配置自定义解析器或客户端处理状态。
普通学生不能处理公共文档；管理员仍不能查看其他学生的私人任务/Chunk。
父/文档墓碑及跨 kb_id 拼接 doc_id 均按既有规则 404。写请求缺失/错误 CSRF 返回 403，非法字段/UUID/分页 422。
尚无任务（例如 0004 遗留文件、Worker 尚未对账）时 GET /ingestion 返回 404 ingestion_not_found；POST 可立即建立任务。
数据库故障沿用脱敏 503。解析失败通过 Job.error_code 和文档 failed 表示，不在 HTTP 响应返回异常堆栈或正文片段。

主要固定 error_code：no_text（包括扫描 PDF）、invalid_format、unsafe_xml、encrypted_pdf、page_limit、
text_limit、chunk_limit、parse_timeout、memory_limit、output_limit、content_changed、storage_unavailable、
resource_unavailable、stale_generation、attempts_exhausted、worker_stopped、parser_process_failed、isolation_unavailable。
永久性解析/资源限制错误不会自动重试；临时存储故障/主动停止可退避重试，数据库断连靠租约恢复。
本阶段 Chunk 可用于核对文本，不存在 embedding、向量状态、检索或问答接口。

## 3B-2B：索引状态与显式云端处理

文档 status 新增 indexing、index_failed；ready 现在表示当前解析代次在当前目标空间全量向量成功。
parsed、indexing、index_failed、ready 均可通过原授权 /chunks 读取当前文本；重新解析时立即隐藏旧文本/旧向量。

路径前缀仍为 /api/v2/knowledge-bases/{kb_id}/documents/{doc_id}：

|方法|请求|响应|
|---|---|---|
|GET /embedding|有效 Cookie、可读父知识库与文档|200 {"job": IndexJob}；当前配置空间尚无任务返回404|
|POST /embedding|可写 + Origin/CSRF；{}，云端须 {"allow_cloud":true}；拒绝其他字段|202 {"job": IndexJob}|

IndexJob 继承解析 Job 的安全字段，增加 space_id、index_revision、expected_chunks、api_calls、max_api_calls；不返回 token、Key、向量或原文。
在途/已成功的同一代次请求幂等；失败可明确重试，复用合法缓存。未 parsed 返回409 document_not_parsed，配置关闭503 embedding_not_configured，
未明确云同意409 cloud_consent_required，队列满429 embedding_queue_full。私人无权限/已删除/跨KB文档仍404，学生公共写入403。
同意只针对本次解析代次；开启部署级开关不代表所有用户同意，重新解析不继承旧同意。
当前无前端同意 UI 或独立同意撤销接口；不应在未做用户告知的产品中自动调用此接口。全局关闭可停止该部署后续云请求；在途已发送批次不能撤回。

索引错误为固定码，如 embedding_timeout、embedding_rate_limited、embedding_budget_exhausted、embedding_input_limit、
invalid_vector_dimension/values/norm、chunk_content_changed、model_replaced；实际不回显提供商异常正文。
解析错误仍通过 /ingestion 查看，两阶段失败不得混淆。

本轮不暴露检索 HTTP/聊天接口。内部 vector_search.embed_query 要求可信认证用户、授权 KB 范围及云查询单独 allow_cloud；
exact_search 要求带配置空间标识的 QueryEmbedding，同一模型分别以 document/query 模式生成，不能接收客户端自报模型或裸向量冒充。
返回 top_k（1–100）、offset（0–10000）、Chunk/文档/KB UUID、页码、标题、index/hash、距离与相似度，不返回完整向量。
距离是 pgvector 精确余弦距离，similarity=1-distance，理论 [-1,1]，没有沿用 V1 的阈值，也不保证语义排序质量。


## 3C-1：统一检索接口

`POST /api/v2/retrieval/search`，要求会话 Cookie、合法 Origin 和 `X-CSRF-Token`，返回 Cache-Control: no-store。

```json
{"query":"AVL 红黑树","knowledge_base_ids":["00000000-0000-0000-0000-000000000001"],"mode":"hybrid","top_k":5,"allow_cloud":false}
```

- mode 为 bm25/dense/hybrid，默认 hybrid。KB 列表 1–20 个不同 UUID，未知字段（包括 user_id/document_id）拒绝。
- top_k 为严格整数，Schema 上限 100，部署默认上限 20；query Schema 上限 2000 字符，部署默认 512。
- query 可为空；空白或纯停用词查询不调用 Provider并返回空结果，但仍验证全部 KB 和会话。scope 不能省略或默认为所有语料。
- allow_cloud 为每次查询的外发同意，不会覆盖全局云端关闭或缺少凭证等限制。不要把它默认设置为 true。
- bm25 也只检索当前空间的 ready 文档，不提供 parsed 模式。

成功 200 的形状：

```json
{
  "requested_mode":"hybrid","actual_mode":"hybrid","degradation_reason":null,
  "results":[{
    "chunk_id":"00000000-0000-0000-0000-000000000002",
    "document_id":"00000000-0000-0000-0000-000000000003",
    "knowledge_base_id":"00000000-0000-0000-0000-000000000001",
    "content":"合成示例片段","page_number":1,"section_title":"AVL",
    "source_filename":"synthetic.pdf","chunk_index":0,
    "fused_score":0.032266458495966696,"dense_score":-0.019690511059195837,
    "bm25_score":1.1414373853110722,"dense_rank":3,"bm25_rank":1
  }],
  "elapsed_ms":12.0,"candidate_k":20,"eligible_chunks":3
}
```

ID、正文和耗时是结构示例；上面的排名/分数来自合成语料确定性 Provider 的真实 HTTP 验证，不表示模型语义效果。
fused_score 只在 hybrid 中有值；dense_score=1−余弦距离，bm25_score 是原始 Okapi 分数，rank 从1开始。
缺席的路线分数及 rank 为 null。按最终分数降序、Chunk UUID 升序稳定排序，返回不超过 top_k 个去重结果。
默认不应用最低相似度阈值，不能用 0.58 解释 RRF 分数。eligible_chunks 仅反映已授权范围。

错误沿用 `{"error":{"code":"...","message":"..."}}`：

|状态|码|含义|
|---|---|---|
|401|unauthorized|未登录、会话失效或用户禁用|
|403|csrf_rejected/origin_rejected|写式 POST 安全检查失败|
|403|cloud_consent_required|未明确同意云查询|
|404|knowledge_base_not_found|选定范围含不存在、删除或无权访问的知识库，整单拒绝|
|413|retrieval_corpus_limit|候选 Chunk、字节或分词 Token 超限，请缩小范围|
|422|invalid_request/retrieval_limit|非法参数或部署查询/结果上限|
|429|retrieval_busy|跨进程检索槽已满|
|503|dense_unavailable|Dense Provider 未启用、未验证、限流、超时或失败；不降级为成功 Hybrid|
|503|service_unavailable|数据库不可用，响应不含驱动异常/凭证|

本轮没有自动降级，因此成功响应 actual_mode 始终等于 requested_mode，degradation_reason 为 null；
服务不可用通过上述错误明确表达。生产网关应限制请求体、设置用户请求频率/费用额度，并保护查询文本不进入 access/body 日志。


## 3C-2A：证据上下文接口

`POST /api/v2/retrieval/prepare-context`，复用会话Cookie、合法Origin和X-CSRF-Token，响应no-store。

```json
{
  "query":"AVL 红黑树","knowledge_base_ids":["00000000-0000-0000-0000-000000000001"],
  "mode":"hybrid","top_k":20,"allow_cloud":false,
  "rerank":"optional","allow_cloud_rerank":false,
  "max_evidence":5,"context_max_chars":12000,"context_token_budget":4000
}
```

继承搜索参数与未知字段拒绝策略；top_k在此表示进入重排的候选数，受检索部署上限、rerank_max_candidates和batch_size共同限制。
默认hybrid，也可明确选择既有bm25或dense，不发生静默检索模式切换。
rerank=off保留顺序；optional在Provider=disabled时显式跳过；required在禁用时503。
启用的Provider失败均报错，不fallback。无候选时不调用模型，返回空证据且rerank_reason=empty_candidates；这不代表模型健康检查成功。
allow_cloud只同意查询Embedding，allow_cloud_rerank独立同意发送问题及候选文本，不能互相替代。

响应主要字段：

- requested_mode/actual_mode：原检索模式；rerank_applied/model/reason明确是否执行重排。
- context_format=json_evidence_v1、trust_boundary=untrusted_reference_data。
- context_text：JSON数组字符串（空证据时空字符串），每块含citation_id、source、content；source含chunk/document/KB UUID、文件名、页码、章节和Chunk顺序。
- evidence：与context_text同序、同引用的结构化证据，每条保留SearchHit全部分数及来源，新增citation_id、original_rank、rerank_score/rank/applied/model、content_hash、generation、index_revision、embedding_space_id、sanitized和truncated。
- excluded：仅含已授权候选chunk_id和固定原因duplicate_chunk/overlapping_evidence/document_limit/evidence_limit/empty_content/chunk_limit/context_budget，不含旧正文。
- used_chars：序列化context_text实际字符数；estimated_tokens：其UTF-8字节数，token_estimate_method=utf8_bytes_conservative_not_tokenizer。不是精确Token计费。
- elapsed_ms：整个处理耗时。不含向量数组、磁盘路径或凭证。

重排未执行时每条rerank_score/rank/model均为null，applied=false；reason为requested_off/provider_disabled/empty_candidates之一。
已执行时reason=null。原始fused_score、dense_score、bm25_score和rank不会被rerank_score覆盖，不使用0.58阈值。
只选择完整Chunk，truncated固定false。正文控制字符可见化后sanitized=true，content_hash对应原始DB文本而非可见化副本。
资料内的[S99]不是服务端引用；只使用结构化citation_id及source映射解释引用。

新错误（统一error封装，现有401/403/404/422/429/503策略继续适用）：

|状态|code|含义|
|---|---|---|
|422|context_limit|候选数或预算超过部署上限|
|403|rerank_cloud_consent_required|缺少独立云重排同意|
|409|context_stale|任意候选的有效状态/hash/代次/空间变化，整个上下文拒绝发布|
|413|rerank_input_limit|单批数量、单项文本或总输入预算超限|
|503|rerank_disabled/rerank_not_configured|required但禁用，或云端未完成独立配置/人工模型核查|
|503|rerank_timeout/rerank_rate_limited/rerank_model_unavailable/rerank_parameter_error|超时、限流、模型或参数错误，有限重试后失败|
|503|rerank_invalid_count/index/score/response|不合法模型响应，永久失败|
|503|service_unavailable|数据库故障，禁止返回未完成最终验证的旧证据|

最终授权失败仍返回401或统一404，而不是带旧正文的部分成功。对外网络发送和接收存在时间窗口；此接口提供最终数据库授权快照，不提供已返回内容的撤回机制。
本轮没有/chat，也不会返回LLM答案。


## 3C-2B：单轮RAG回答

`POST /api/v2/rag/ask`，从Cookie取得身份，要求合法Origin和X-CSRF-Token；响应no-store、nosniff。
不接受user_id、sources、Prompt、messages或文档ID等额外字段，不提供stream/history/chat接口。

请求示例：

```json
{
  "query":"AVL是什么","knowledge_base_ids":["00000000-0000-0000-0000-000000000001"],
  "retrieval_mode":"hybrid","answer_mode":"auto","top_k":20,
  "rerank":"optional","allow_cloud":false,"allow_cloud_rerank":false,"allow_cloud_generation":false
}
```

- query非空、合法UTF-8，Schema最多2000字符，部署仍受retrieval_max_query_chars默认512限制。
- KB列表1–20个不同UUID，任何一个无权/删除/不存在就整单404，管理员也无私人资料豁免。
- retrieval_mode为bm25/dense/hybrid；answer_mode为auto/qa/exercise/code，响应返回实际选定模式。
- top_k是候选数，默认20，仍受检索和重排部署限制；Context Builder使用既有默认预算。
- 三个allow_cloud字段相互独立。allow_cloud_generation仅表达本请求意图，**不是已审计的生成服务授权**，本轮不能用它开启Qwen外发。

answered示例（UUID、正文和耗时为形状示例，非真实用户数据）：

```json
{
  "status":"answered","reason":null,"answer":"资料原文：合成课程片段[S1]",
  "sources":[{
    "citation_id":"[S1]","chunk_id":"00000000-0000-0000-0000-000000000002",
    "document_id":"00000000-0000-0000-0000-000000000003",
    "knowledge_base_id":"00000000-0000-0000-0000-000000000001",
    "source_filename":"synthetic.txt","page_number":null,"section_title":"AVL","chunk_index":0,
    "content_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generation":1,"index_revision":1,
    "embedding_space_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }],
  "retrieval_mode":"hybrid","answer_mode":"qa","rerank_applied":false,
  "generation_model":"deterministic-evidence-quote-v1","execution_performed":false,"latency_ms":30.0
}
```

sources只含本次有效且实际引用的来源，不含整份证据、向量、系统Prompt、存储路径或凭证。
模型的used_source_ids仅作内部校验，不直接信任为来源元数据；最终来源由数据库构建。

|HTTP/status|含义|
|---|---|
|200 answered|结构、引用、最终授权与版本通过，不代表自然语言事实已被逐项证明|
|200 insufficient_evidence|正常拒答，answer固定为“根据当前授权资料无法确定。”，sources为空|
|out_of_scope（预留）|暂无权威课程范围规则，不直接输出；模型自报会转为scope_not_verified拒答|
|503 generation_unavailable|Provider禁用、生成授权阻塞、超时、429、服务或调用预算故障；answer=null，sources=[]|
|502 validation_failed|无效结构、截断、空/非法引用、来源或执行声明未通过校验；answer=null，sources=[]|

正常拒答reason区分no_evidence、no_lexical_support、conflicting_assertions、model_refusal、model_reported_conflict、scope_not_verified。
503/502响应保留AskResponse的安全字段，并附标准error对象，例如：

```json
{"status":"generation_unavailable","reason":"generation_disabled","answer":null,"sources":[],"retrieval_mode":"hybrid","answer_mode":"qa","rerank_applied":false,"generation_model":null,"execution_performed":false,"latency_ms":1.0,"error":{"code":"generation_disabled","message":"Generation unavailable"}}
```

生成错误code包括generation_disabled、generation_cloud_consent_required、generation_consent_not_configured、generation_timeout、
generation_rate_limited、generation_model_unavailable、generation_http_error、generation_budget_exhausted。
结构校验错误reason包括missing_citations、invalid_citations、invalid_citation_format、invalid_output_schema、invalid_output_budget、
truncated_or_invalid_completion、unsupported_source_metadata、unsupported_execution_claim等固定码，不回显坏答案。
最多可配置一次完整重新生成，仍受总调用预算限制；不会删除坏引用后保留其事实陈述。

认证/授权/数据库/版本错误沿用统一error封装：401 unauthorized、403 Origin/CSRF、404 knowledge_base_not_found、
409 context_stale、422 generation_input_limit/现有请求上限、429 retrieval_busy、503 service_unavailable。
这些错误不包含旧答案。检索或重排阶段不可用也沿用已有错误码，不假装已完成生成。


## 最终集成：冻结契约与云端用途授权

当前机器契约为[openapi.json](openapi.json)，通过 `python -m backend.v2.tools.export_openapi` 无凭证导出；契约回归测试验证与运行时一致。完整浏览器用法、状态和错误见[FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md)。API文档地址 `/api/v2/docs`，动态Schema `/api/v2/openapi.json`。旧章节中的云生成硬阻塞已由以下持久用途授权代替，安全默认不变。

|方法/路径|成功|
|---|---|
|GET /api/v2/knowledge-bases/{kb_id}/cloud-consents|200，当前用户此KB的Consent数组（含历史service_key/revoked_at）|
|POST /api/v2/knowledge-bases/{kb_id}/cloud-consents/{purpose}|200，显式授予，空body；purpose仅embedding/reranking/generation|
|DELETE 同上|200，撤销当前配置指纹授权；可重复，安全更新revoked_at|
|GET /api/v2/knowledge-bases/{kb_id}/cloud-consents/audit|200，当前用户此KB的审计数组；limit默认50/上限100，offset默认0/上限10000|

Consent字段：id、knowledge_base_id、purpose、provider、model、service_key、granted_at、revoked_at。Audit字段：id、purpose、event、service_key、details、created_at。不能指定user_id、任意模型或代学生授权。所有读操作需有效会话与readable，写操作另需Origin+CSRF；私人越权404，缺用途同意403 cloud_consent_required。

授权覆盖该KB当前及未来版本；服务指纹变化需再次授予。使用云模型需要部署开关/有效独立凭证与模型配置、当前用户各用途授权、请求对应allow_cloud/allow_cloud_rerank/allow_cloud_generation；云端文档还需当前解析代次embedding授权。允许公共阅读不等于允许普通学生触发公共文档索引，写权限仍限制管理员。

问答接口与既有AskRequest/AskResponse字段兼容。Generator默认qwen3.8-flash但provider=disabled，不再由无持久授权的旧硬阻塞实现安全。空证据拒答200；模型不可用503 generation_unavailable；生成格式/引用失败502 validation_failed，均无旧答案/原证据回退。不要把HTTP 200的拒答当作answered。

PATCH知识库的name/description可省略但显式null为422，OpenAPI已移除null类型和null默认。非预期500保留安全错误格式，对明确允许的Origin返回CORS+credentials响应头；不允许来源不会获此头。所有私人API继续no-store。

合成真实模型测试可用性通过不改变任何接口默认云授权；前端必须说明外发数据、用途、服务商、模型、当前及未来版本范围、可撤销及无法撤回历史调用。正式上线前还需确认服务商保留策略。
