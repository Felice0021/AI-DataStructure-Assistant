# V2 前端交接与接口冻结

机器可读契约：`openapi.json`（FastAPI 实际导出）。本轮不开发 Vue。全部接口前缀 `/api/v2`，身份来自 Cookie，不能传 user_id、owner_id、role 或内部 storage_key。未授权私人资源统一 404；管理员也不能读取其他学生私人资料。

## 浏览器连接、CSRF 与 Cookie

本地统一使用 `http://127.0.0.1:5173` 前端和 `http://127.0.0.1:8001` API，不要混用 localhost。API 需明确 development + allow_insecure_loopback，CORS 来源白名单包含上述 Origin。生产要求 HTTPS、Secure HttpOnly Host Cookie、精确 HTTPS Origin；不使用带凭证通配符。所有 POST/PATCH/DELETE（含只读 POST）必须携带正确 Origin 和 X-CSRF-Token。

```js
const API = 'http://127.0.0.1:8001/api/v2';
async function csrf() {
  const r = await fetch(`${API}/auth/csrf`, {credentials: 'include'});
  if (!r.ok) throw new Error('csrf_unavailable');
  return (await r.json()).csrf_token;
}
async function write(path, body, method = 'POST') {
  return fetch(API + path, {method, credentials: 'include',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': await csrf()},
    body: body === undefined ? undefined : JSON.stringify(body)});
}
const login = await write('/auth/login', {email: '<local-test-email>', password: '<local-input>'});
// 登录改变 Cookie，下一次写请求重新 csrf()，不要复用登录前 Token。
const me = await fetch(API + '/auth/me', {credentials: 'include'});
```

Cookie 是 HttpOnly，JavaScript 不能也不应读取。csrf 返回派生 Token，仅存内存，不写 localStorage/日志。跨域 fetch 必须 credentials:include，浏览器自动发送 Origin，不手工伪造。上传用 FormData + X-CSRF-Token，**不要手动设置 Content-Type**；下载同样鉴权，可 fetch→Blob→临时 object URL，使用后 revoke，不持久存储私人 Blob。

## 已有接口清单

|模块|方法/路径（省略 /api/v2）|成功与主要结构|
|---|---|---|
|认证|GET /auth/csrf；POST /auth/register、/login；GET /auth/me；POST /auth/logout|csrf_token；注册201/登录200/me200 的 {user:{id,email,role,is_active,created_at,updated_at}}；logout204|
|知识库|GET/POST /knowledge-bases；GET/PATCH/DELETE /knowledge-bases/{id}|列表 {items,total,limit,offset}；单项 {knowledge_base:{…}}；POST201/DELETE204|
|公共库|POST /admin/knowledge-bases|仅 admin；201；普通创建永远private|
|文件|POST/GET /knowledge-bases/{kb}/documents；GET/DELETE /{doc}；GET /{doc}/download|上传201/详情200 {document:{…}}；列表分页；删除204；download二进制attachment|
|解析|GET/POST /knowledge-bases/{kb}/documents/{doc}/ingestion；GET /chunks|{job:{…}}；POST202 body {reprocess:false}；chunks分页|
|索引|GET/POST /knowledge-bases/{kb}/documents/{doc}/embedding|{job:{…}}；POST202 body {allow_cloud:false}|
|用途授权|GET /knowledge-bases/{kb}/cloud-consents；POST/DELETE /{purpose}|用途 embedding/reranking/generation；授予/撤销200，返回当前授权；GET含历史服务标识授权|
|审计|GET /knowledge-bases/{kb}/cloud-consents/audit?limit=50&offset=0|仅当前用户该KB的元数据事件数组，最多100/页|
|检索|POST /retrieval/search|requested_mode、actual_mode、results、elapsed_ms、candidate_k、eligible_chunks|
|上下文|POST /retrieval/prepare-context|context_text、evidence、各路诊断和预算；低信任资料，不是答案|
|回答|POST /rag/ask|status、reason、answer、sources、retrieval_mode、answer_mode、rerank_applied、generation_model、execution_performed:false、latency_ms|

全部字段、长度及可空性以 OpenAPI 为准。PATCH 名称/说明可省略，但不可显式 null；禁止额外身份/可见性字段。注册不会自动登录。

## 文件生命周期与发问条件

uploaded → processing → parsed → indexing → ready。failed 表示解析失败，index_failed 表示向量失败；任务还有 queued/running/succeeded/failed/cancelled，不能混为文档状态。parsed **尚未可问答**；三种检索当前均仅接受有效 ready 的当前模型空间资料。上传自动建立解析任务，Worker 对账补索引；云端文档必须另授当前解析代次同意。轮询详情/任务，退避且组件卸载停止；不要不停重试失败任务制造费用。失败后仅资源可写用户显式重试；重新解析会使旧引用/向量立即失效。

普通学生选择自己的 private 和可读 public，可混合；管理员也只看自己的 private + public。混合请求含任一无权 ID 会整单404，不能默默去掉。空库/空结果展示资料不足，不能自动扩大到全局资料。

```js
const result = await write('/rag/ask', {
  query: 'AVL树的平衡条件是什么？', knowledge_base_ids: selectedIds,
  retrieval_mode: 'hybrid', answer_mode: 'qa', top_k: 20, rerank: 'optional',
  allow_cloud: false, allow_cloud_rerank: false, allow_cloud_generation: false
});
const data = await result.json();
```

上述 false 在测试 Provider 下可完成工程联调；真实云模式应先由用户明确阅读并按KB/用途授予，再在本次请求主动开启三个对应标志，不能因数据库中已有同意而默认勾选。云开关/Key/模型不满足时展示不可用，不能伪装离线成功。授权覆盖该KB**当前及未来版本**、该用户、该用途和该模型/端点标识；用户应能查看、撤销。模型/端点/Embedding revision 改变后需重新授权。撤销阻止新调用，不能撤回已发起调用或保证服务商删除历史数据。

## 回答、引用和错误

`answer` 中 `[S1]` 对应本次 `sources[].citation_id`；来源包括 chunk/document/KB UUID、文件名、页号、章节、顺序、hash及代次。仅渲染返回的 sources，不能凭模型文本拼下载路径；下载仍走鉴权API。Markdown 禁止原始 HTML，代码只展示、不执行。execution_performed 固定 false。合法编号不代表语义事实已被证明。不要跨请求缓存私人答案；退出/401/权限变化清空当前界面状态。

|状态|前端行为|
|---|---|
|200 answered|展示答案及合法来源|
|200 insufficient_evidence / out_of_scope|展示 reason 对应拒答提示，不拼接旧答案；课程外自动判断尚未可靠实现|
|401|会话失效，清理本地状态并登录|
|403|CSRF/来源/角色或用途授权不满足；重新获取csrf或引导用户操作，禁止静默同意|
|404|资源不存在或不可访问，不透露其他用户名称|
|409|重名或证据/代次已变；刷新资料，用户决定是否重试|
|413 / 422 / 429|文件过大/字段校验/限流或资源容量；显示安全错误码并退避|
|502 validation_failed|生成格式/引用校验失败，无可发布答案；不得显示旧证据代替答案|
|503 generation_unavailable 或安全 error|模型/数据库/存储暂不可用，明确失败；不当作空结果|
|500|统一脱敏错误；精确允许Origin仍有CORS头，可正常显示通用错误|

通用错误 `{error:{code,message}}`；RAG 的502/503保留 AskResponse 字段并增加 error。422不回显原始输入，不能依赖底层异常文字。未开发：聊天历史、多轮、流式、图片题、前端、工具执行、查询扩展；不能把这些列为现有接口。
