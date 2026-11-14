# 会话流式回答

## 接口与兼容性

聊天页使用 `POST /api/v2/conversations/{id}/ask-stream`，请求仍是 `ConversationAskRequest`（含原 `request_id`、知识库范围和逐用途云处理标志）。原会话 `/ask`、单轮 `/api/v2/rag/ask`、历史 JSON 和已校验树图保持兼容；没有数据库迁移。

Cookie Session、CSRF、严格 Origin/HTTPS、知识库授权在开始 SSE 前检查。参数、登录、资源或容量检查失败时仍返回相应的普通 HTTP 错误。流建立后 HTTP 状态已是 200，**不能把 200 当作回答成功**，必须等待 `result` 或 `error` 终态。

每帧格式：

```text
event: status
id: 1
data: {"type":"status","seq":1,"request_id":"11111111-1111-4111-8111-111111111111","payload":{"stage":"accepted","preview":false}}

```

| 事件 | payload | 行为 |
|---|---|---|
| status | stage、preview | accepted → retrieving → generating → validating → saving；重试/缓存重放可省略阶段或重新进入生成 |
| reset | {} | 清除上次生成尝试的临时草稿 |
| draft | text | 真实模型增量解码后的正文片段；尚未通过最终校验 |
| result | result: AskResponse | 唯一成功终态；包括合法回答或正常拒答，已完成成对保存或幂等重放 |
| error | code、status、message | 唯一失败终态；status 是逻辑错误状态（例如 401/403/409/502/503），立即撤回草稿 |

`seq` 从 1 严格递增，所有事件绑定同一请求 UUID。前端使用 `fetch` + `ReadableStream`，不使用无法携带 POST/CSRF 的 EventSource。无终态的 EOF 是失败，不自动重发。5 秒心跳仅保持连接，不冒充处理阶段或模型文本。

## 真正的增量与草稿边界

Qwen 适配器调用原官方 HTTPS Chat Completions 入口，设置 `stream=true`、`stream_options.include_usage=true`，处理 `choices[0].delta.content`、结束原因、usage 和 `[DONE]`，不在完整生成后定时逐字打印。参见 [阿里云官方流式协议](https://www.alibabacloud.com/help/en/model-studio/stream)。

模型输出仍然是 JSON。SSE UTF-8 解码器接受跨字节字符、BOM、CR/LF 和多行 data；有线大小、事件、事件数、正文与 token 上限。正文前缀词法器只解码顶层 `answer` 字符串，正确处理引号、反斜杠、换行、Unicode/代理项，等待 `status=answered` 才放出草稿；其他字段不展示。完整结果仍由原 `parse_draft`、`validate_answer` 和所有来源快照校验决定。

临时稿显示“尚未校验，可能修正或撤回”，使用原安全 Markdown VNode 渲染器对**当前累计正文**增量排版（标题、列表、加粗、代码块、表格及闭合的公式）。模型 HTML 永不解析成 DOM，草稿 Markdown 链接只显示文本，`[S1]` 等引用只显示文字，不形成交互引用、不提供复制按钮或历史写入。普通界面复制事件被阻止；这不是 DRM，不能阻止使用者自行记录已看到的文字。尚未闭合的 Markdown/公式可能暂时以文本出现，待新片段到达后变成格式化内容；草稿排版本身**不代表来源或答案校验成功**。失败、取消、退出、切换会话/账户/课程时清空草稿。最终通过后才替换为原正式答案、每回答独立引用、来源和复制组件。

树构造、树形原理及已有参考分区算法路径在生成期间只显示阶段，**不显示模型自由生成的树或过程草稿**。最终仍由服务端已验证结果及 SVG DTO 展示。deterministic/旧测试 Provider 没有真正的增量接口时只发阶段和终态，不模拟 token。

第一段可解码正文立即送出，后续合并到约 64 字符或换行，减少每 token 数据库开销；合并由实际收到的数据驱动，没有打字计时器。首草稿可以早于完整答案，但检索、首 token、授权复核时间仍存在，正式答案必须等待完整校验。

## 安全、取消与持久化

- 复用原生成调用预算、并发约束、超时、Cloud Consent、Guard 和审计；每次真实云尝试重新检查，模型片段不进日志。实际 usage 继续写现有审计。开始流不等于允许云调用。
- 每批草稿重新检查当前会话、会话所有权、知识库授权、原候选来源及代次；Qwen 草稿另检查当前 generation Consent。保存前及终态投递前再复核。历史 assistant 内容不升级为课程证据。
- 使用原会话 advisory lock、`request_id` 指纹、最终行锁和用户/assistant 成对事务。流式与旧接口共享幂等；已保存结果重试不再调用模型。失败未保存时显式重试可发起新的受限模型尝试，仍用原 request_id/原 payload。
- 取消/断线关闭真实生成读取（取消观察间隔 50ms），不继续自动重试已经发出草稿的生成。首次尚未发出正文的临时错误仍按原调用次数和指数退避上限重试。检索/重排已经开始的同步请求按原有超时结束，取消后禁止其后续云尝试。
- 取消在提交检查前生效时不写消息；若成对的已验证结果恰好在断线前提交，无法承诺撤销该有效提交。前端保留原 request_id，重试/刷新确认结果。来源在有效提交后撤销时，历史沿用原脱敏逻辑，不删除既有成对记录。
- 每进程有活动生产者门槛，跨进程复用原 PostgreSQL 并发门槛。事件队列最多 16 帧；慢消费者背压 1 秒后安全结束。生成网络读取不持有长数据库事务，草稿复核使用短事务。
- `DS_V2_CONVERSATION_STREAM_TIMEOUT_SECONDS` 默认 120 秒（允许 1–300）；浏览器总时限 125 秒、无网络数据 30 秒。服务端提高到 125 秒以上不会自动延长客户端预算，浏览器仍可能先取消。

## Caddy 与部署边界

响应使用 `text/event-stream`、`Cache-Control: no-store, no-transform`、`X-Accel-Buffering: no`，不设置 Content-Length。仓库 Qwen Caddy 模板无 response_buffers、额外 encode 或过短 stream_timeout。

[Caddy 官方文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#streaming)说明 SSE 会即时 flush；不要为了流式机械加入 `flush_interval -1`，该模式还会改变客户端断开后的上游取消行为。当前默认反向代理可识别 SSE；本 PR 不改 Caddy、Cloudflare、线上服务或发布开关。实际 Cloudflare/Caddy HTTPS 链路须在负责人审核合并后再受控验收，本地通过不冒充线上通过。

## 测试与单次真实调用

```bash
DS_V2_RUN_DB_TESTS=1 python -m pytest backend/v2/tests -q
cd frontend-v2
npm test
npm run build
npm run test:production
npm run test:browser
```

自动化测试使用随机隔离数据库和临时文件。真实 TCP 测试运行临时 Uvicorn 和受控模型 HTTP 服务器，证明正文在上游完成前到达、断线关闭上游、失败无半条消息、重试幂等。浏览器使用真实网络 SSE 和受控 API 路由，覆盖桌面/390px、草稿安全、错误撤回、停止、刷新、退出、Markdown/公式、引用和 SVG。它们不是模型质量测试。

2026-11-14 本地复验：完整隔离后端 **940 passed、4 skipped**（4 项要求显式启用预构建 Docker Parser；Linux CI 负责此路径），完整前端 **176 passed**，Chrome 桌面/390px **32 passed**，生产产物检查 **2 passed**。生产构建通过，未包含 MSW Worker。截图位于 `frontend-v2/docs/screenshots/streaming/`；浏览器资料均为原创合成测试数据。GitHub 必需 CI 以 PR 当前 SHA 对应运行记录为准。

显式手动入口（普通 pytest 和 CI 从不执行）：

```bash
python -m backend.v2.tools.stream_cloud_smoke --allow-one-cloud-request --report /absolute/private/new-report.json
```

此工具仅在随机库中导入内置原创合成资料，通过正常 API 注册临时学生、授予 generation Consent，使用 BM25/关闭 rerank；真实生成最多 1 次、零重试、512 输出 tokens。复用独立 V2 配置和现有持久化合成预算，不读取 V1 .env、不重置账本、不发送课程资料；凭据不输出。模型开关仅在隔离进程启用，QA 和 `.env` 不变。报告 0600 且必须是新路径。调用前上传路径使用真实绝对路径，保留 LocalFileStorage 严格检查。

2026-11-14 实测：真实 `qwen3.8-flash` / 官方 HTTPS streaming，1 次生成尝试，3 个草稿片段，首草稿 1108.17ms、终态 1979.38ms，`answered`、`[S1]` 与来源一致、2 条消息成对保存。usage 为输入 554、输出 82、合计 636 tokens；未查询实际账单，不推算为免费或质量分数。前两次本地初始化在上传阶段失败，未进入模型调用，修正临时路径 `.resolve()` 后通过；原失败记录保留。随机库、临时原文件和进程随后清理，持久预算账本保留。

这是一次原创合成资料的工程测量，不能据此宣称课程问答准确率或普遍延迟改善。真实云记录保存在仓库外私有验收目录；本 PR 不提交 Key、账号密码、Cookie、全文日志或真实文档。
