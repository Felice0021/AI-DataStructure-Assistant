# V2 前端 HTTP Fixture

基线：`b56b88bdde6ac31e9a5d7c33ced7aaf6c7f7ef2b`。供 Windows + Vue 3 + Vite + TypeScript 独立开发使用，不包含 Vue 工程或 Mock 服务器。

所有数据均专门合成，**不是服务器抓包**；未读取演示凭证、数据库、`.env` 或 V1 资料。邮箱未在后端注册，密码是说明性占位符；模拟 CSRF 明确不符合真实 Token 格式，不能用于后端。Mock 登录不建立真实 Session。

## 场景索引

共 **14 个响应场景、4 个请求文件、1 个索引（19 个 JSON）**。`index.json` 只记录 method/path/http_status 和文件映射，**不是 API body**。其余文件均为原始请求或响应 body，不含 HTTP 状态、Cookie 或响应头。下表路径统一以 `/api/v2` 为前缀。

|场景|方法/路径|HTTP|请求 JSON|响应 JSON|
|---|---|---|---|---|
|CSRF|GET /auth/csrf|200|—|auth-csrf.response.json|
|登录|POST /auth/login|200|auth-login.request.json|auth-login.response.json|
|当前用户|GET /auth/me|200|—|auth-me.response.json|
|知识库列表|GET /knowledge-bases|200|—|knowledge-bases.response.json|
|正常回答|POST /rag/ask|200|rag-ask.request.json|rag-answered.response.json|
|证据不足|POST /rag/ask|200|rag-insufficient.request.json|rag-insufficient.response.json|
|生成校验失败|POST /rag/ask|502|rag-ask.request.json|rag-validation-failed.response.json|
|Generator 禁用|POST /rag/ask|503|rag-ask.request.json|rag-generation-unavailable.response.json|
|CSRF 拒绝|POST /rag/ask|403|rag-ask.request.json|csrf-rejected.response.json|
|缺用途授权|POST /rag/ask|403|rag-cloud-consent.request.json|cloud-consent-required.response.json|
|未登录|GET /auth/me|401|—|unauthorized.response.json|
|学生尝试管理员操作|POST /admin/knowledge-bases|403|—|forbidden.response.json|
|KB 不存在或无权访问|GET /knowledge-bases/{private_id}|404|—|knowledge-base-not-found.response.json|
|数据库故障|GET /auth/me|503|—|service-unavailable.response.json|

索引已将 `{private_id}` 替换为合成 UUID。同一路径的成功和错误是不同可选场景，不是同时发生。管理员操作未提供请求 Fixture；合法请求仍需 name/description，角色来自会话，不能传 role。

缺用途授权场景假定服务端已配置云重排，但当前用户没有相应 KB 用途授权，因此外发前被拒绝。其请求含云处理标志，**仅供 Mock，不能作为真实模式默认请求**。默认 rag-ask 的三个 allow_cloud* 均为 false。请求布尔值不能替代部署配置和持久授权。

## 标识、引用和可空字段

- 用户：`11111111-1111-4111-8111-111111111111`，登录与 me 一致。
- 私人 KB：`22222222-2222-4222-8222-222222222222`，owner_id 指向该用户。
- 公共 KB：`33333333-3333-4333-8333-333333333333`，owner_id 为 null。
- 文档：`44444444-4444-4444-8444-444444444444`；Chunk：`55555555-5555-4555-8555-555555555555`。

answered 的 `[S1]` 对应完整 AnswerSource；TXT 的 page_number 为 null。content_hash 为合成文本摘要，embedding_space_id 为专用模拟摘要，不对应真实数据库索引。不要凭文件名/UUID拼接存储路径，不跨回答复用引用编号。

拒答无 sources 和虚构引用；生成失败 answer 为 null、sources 为空。Schema 中的 null 必须保留为 JSON null，不能改成字符串。登录、KB 和来源不允许随意增加前端展示字段。

## Vue / Vite / TypeScript 使用

由张圣江将所需 JSON 放到其 Vue 项目的 `src/mocks/v2/`，通过 Vite JSON import 消费；本轮未触碰 `frontend-v2/`。类型复用 OpenAPI DTO，错误响应还需结合下面的运行时差异处理。

仅作为前端 adapter 示例，不是完整 Mock 服务器：

```ts
import answered from './rag-answered.response.json';
import unavailable from './rag-generation-unavailable.response.json';

const cases = {
  answered: { status: 200, body: answered },
  unavailable: { status: 503, body: unavailable },
} as const;

export function mockAsk(scene: keyof typeof cases): Response {
  const entry = cases[scene];
  return new Response(JSON.stringify(entry.body), {
    status: entry.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
```

建议用 `VITE_API_MODE=mock` / `backend` 显式切换 adapter。Mock 模式不向后端发送数据，未支持的路径报错，不能静默转发真实后端。切到 backend 时关闭拦截、清理模拟登录与旧答案状态，重新执行真实 CSRF/login。Vite 环境变量只能存公开地址/模式，不能存模型 Key。

若使用 MSW，将 method/path 映射到 handler，并分别设置 HTTP status 和 JSON body；安装及集成由前端组员完成，本轮未安装任何依赖。不需要在 Mock 模式伪造后端 Cookie。

### 真实后端模式

- 本地统一 `http://127.0.0.1:5173` → `http://127.0.0.1:8001`，不要混用 localhost。
- fetch 使用 `credentials: 'include'`；真实 Session 由 HttpOnly Cookie 携带，不在 JSON 中，JavaScript 不应读取。
- GET `/auth/csrf` 获取真实 Token；所有 POST/PATCH/DELETE（包括只读 POST `/rag/ask`）携带 `X-CSRF-Token`。登录更换 Cookie 后重新获取，Token 不存 localStorage/日志。
- 浏览器自动提供 Origin，服务端须明确允许；CORS/SameSite 不是单独的 CSRF 防线。生产 HTTPS 使用 Secure Cookie，本地 HTTP 仅限显式 loopback development。
- Mock 成功不证明真实 Cookie、CORS、会话和权限配置正确；不得把占位密码或模拟 Token 发给真实后端用于登录。

## 错误处理与 OpenAPI 差异

|HTTP/业务状态|前端行为|
|---|---|
|200 answered|显示答案与本次 sources，安全渲染 Markdown，不执行代码|
|200 insufficient_evidence|正常拒答提示，不视作网络故障，不沿用旧引用|
|401 unauthorized|清理登录及私人内容状态，引导登录|
|403 csrf_rejected|检查 Origin/刷新 CSRF，不能无限重试写操作|
|403 forbidden|提示权限不足，不信任客户端自报角色|
|403 cloud_consent_required|引导明确授权，不自动同意或打开云开关|
|404 knowledge_base_not_found|统一显示不存在/不可访问，不泄露其他用户资料|
|502 validation_failed|丢弃无效答案和来源，显示生成校验失败|
|503 generation_unavailable|显示模型不可用，不伪装为空结果或回答成功|
|503 service_unavailable|通用服务/数据库故障，安全提示并有限退避|

已知差异，本轮只记录、不修改后端或 OpenAPI：

1. `routers/rag.py` 的 502/503 返回 **AskResponse 全部字段加 error**。502 的顶层 status 是 validation_failed，error.code/reason 则是具体原因 invalid_citations；503 同理，本例为 generation_disabled。不要混淆顶层状态与错误码。
2. `main.py` 的数据库故障返回仅含 error 的通用503，普通401/403/404也是 ErrorResponse。不能用一种生成503 DTO处理所有503。
3. `/rag/ask` 的 OpenAPI 仅显式声明200与422，未描述运行时401/403/404和502/503。生成客户端需要补充这些联合分支，不能认定它们不存在。
4. 该接口 OpenAPI 的422仍指向 HTTPValidationError，运行时全局处理使用 ErrorResponse。本轮未提供422 Fixture。

依据：schemas/auth.py、schemas/knowledge_base.py、schemas/rag.py、routers/auth.py、routers/rag.py、services/rag_service.py、services/answer_validation.py、dependencies/auth.py、core/errors.py、main.py。完整浏览器约定见上级 FRONTEND_HANDOFF.md。

## 验证范围

本轮只做纯本地字段校验，**没有运行 HTTP/数据库/Worker 或付费模型**。此前任务 A 已用真实确定性 HTTP 验证同类登录、ready、正常/拒答、来源和跨用户拒绝；现有 http_smoke.py、rag_http_smoke.py 可复现相关链路。其他故障示例按运行时代码及 test_rag.py、test_security.py 编写，不声称本轮实际制造了502/503故障，也不把这些合成文件称为抓包。

新增测试只导入 Pydantic Schema 和纯引用校验函数，不创建 App/Settings；禁止网络、子进程和凭证读取。严格校验所有JSON、嵌套字段集合、必填项/null/枚举/类型/UUID/日期、HTTP状态与错误体、引用映射；包含故意错误样本，验证额外字段和伪造引用确实被拒绝。

在仓库根目录、已有 V2 Python 环境中运行，macOS/zsh：

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest --noconftest -p no:cacheprovider backend/v2/tests/test_frontend_fixtures.py -q
```

Windows PowerShell（已有 Python3.12 与V2测试依赖）：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest --noconftest -p no:cacheprovider backend/v2/tests/test_frontend_fixtures.py -q
```

只运行这个文件，不运行完整 acceptance，不需要 Docker/数据库/云凭证。当前 macOS Python3.12 实测 **37 passed**；Windows命令尚未实机执行，不代表完整Parser/Worker已支持原生Windows。
