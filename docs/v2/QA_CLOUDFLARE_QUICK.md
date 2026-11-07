# V2 临时跨设备测试网址（Cloudflare Quick Tunnel + 邮箱验证）

**适用**：常慧思的功能 QA，仅组内短期使用。**本文件是部署指引，不表示服务已经上线。**
本方案不使用 Tailscale，也不要求测试者安装软件或拥有 Cloudflare 账号。Cloudflare Quick Tunnel 的 `--allowed-mail`（2026-10 引入）提供访问前的邮箱一次性验证码。
参考：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ ；https://developers.cloudflare.com/changelog/post/2026-10-02-protected-quick-tunnels/

**管理设备约束**：本机有腾讯 IOA。先确认该服务符合设备管理及网络使用政策，且 `cloudflared` 的外连未被阻止。不得通过禁用 IOA、修改网络控制或绕过管理策略来建立隧道；若政策不允许或连通性失败，部署到经批准的独立云服务器，而不是继续在受管 Mac 上试探绕过。

## 1. 预备状态与访问范围

- macOS 本机已准备独立 `ds_assistant_v2_qa`，不要动三个旧库；再次检查 `0008_conversations` 迁移与 `alembic check`。
- 需要本人 Mac 上的 Caddy、Python V2 环境、Docker/PostgreSQL；前端 `frontend-v2/` 使用 Node/Vite 只构建**生产静态页面且禁用 Mock**。
- 请先向常慧思确认接收 OTP 的**具体邮箱**，只用 `--allowed-mail 某一个邮箱`，不要用 `*@domain`、不要启用匿名公开 Quick Tunnel。
- Quick Tunnel 地址每次启动会改变，进程退出就失效，**无可用性保证**。Mac 必须保持供电、联网，相关服务运行。Windows 端可直接浏览器访问，网络可达性必须真实验证。
- 不要在 GitHub 发布 URL、密码、Cookie、Token、完整教材正文。Cloudflare 会传输本次 QA 请求；只使用原创合成内容或经允许的数据。

## 2. 构建前端、开启本机代理

从本 PR 的分支/审核后 main，在仓库根目录运行：

```bash
cd frontend-v2
npm ci
VITE_USE_MOCK=false VITE_API_BASE='' npm run build
cd ..
# 验证本地反代配置实际只监听 127.0.0.1:8088（而非 0.0.0.0）
caddy validate --config deploy/v2/qa/Caddyfile
DS_V2_QA_WEB_ROOT="$PWD/frontend-v2/dist" caddy run --config deploy/v2/qa/Caddyfile
```

上述 Caddy 在专用终端运行。站点块是 `:8088 { bind 127.0.0.1 ... }`，接受动态公网 Host，但**网络监听仍限 loopback**。Caddy 将 `/api/v2/*` 反代到 `127.0.0.1:8001`，并设置由可信反代提供的 `X-Forwarded-Proto: https`。Uvicorn 只信任 loopback 来自 Caddy 的转发头。

## 3. 创建仅限测试邮箱访问的 HTTPS 临时网址

若 IOA 的管理政策允许，安装当前官方版本 `cloudflared`（例如经批准的 Homebrew 安装）；先运行 `cloudflared --version` 和 `cloudflared tunnel --help` 核对 **`--allowed-mail` 是否支持**。

在另一个终端运行（把占位邮箱改为常慧思实际使用的邮箱）：

```bash
cloudflared tunnel --url http://127.0.0.1:8088 --allowed-mail 'tester@example.com'
```

不要删掉 `--allowed-mail`；若当前安装版本不支持，先升级到支持该标志的官方版本，仍不支持则停止该方案。输出的 `https://<随机>.trycloudflare.com` 是唯一给常慧思的浏览器入口；这里只是地址**格式示例**，没有真实分配。

**注意**：即便随机网址泄露，未在允许邮箱列表中的访问者也不能通过邮箱验证；但这是开发临时方案，不是生产级部署。测试结束直接停止 cloudflared，旧地址立即失效。

## 4. 使用生成的临时 HTTPS Origin 启动 V2

取得实际 `https://<随机>.trycloudflare.com` 后，在所有服务终端设置同一个完整 HTTPS origin：

```bash
export DS_V2_QA_ORIGIN='https://实际随机字符串.trycloudflare.com'
bash deploy/v2/qa/run-secure-test-provider.sh migrate
bash deploy/v2/qa/run-secure-test-provider.sh check
# 以下各在单独终端运行，传入同一个 DS_V2_QA_ORIGIN：
bash deploy/v2/qa/run-secure-test-provider.sh api
bash deploy/v2/qa/run-secure-test-provider.sh parser
bash deploy/v2/qa/run-secure-test-provider.sh embedding
```

必须沿用 QA 数据库/存储及 deterministic 三 Provider，云开关保持关闭。若端口占用，先调查现有进程，不要杀掉不属于本次 QA 的进程。QA 与开发数据库不要共用存储。

FastAPI 当前 secure-cookie 模式要求 `request.url.scheme=https`、Origin 精确匹配 `DS_V2_QA_ORIGIN`。该路径通过受信任的 loopback Caddy/Uvicorn 转发让 HTTPS 检查成立，不关闭安全校验。

## 5. 初始化独立学生账号与原创合成知识库

有邮箱验证的 Quick Tunnel 需要人通过网页输入 OTP，因此原先从终端直接请求公开 URL 的 Python 脚本可能被访问层拒绝。本 PR 的账号脚本提供 `--in-process` 模式，使用真实 V2 FastAPI 应用路由与隔离 QA 数据库，在本机完成同等的注册、登录、CSRF、会话、私人知识库及上传逻辑，但**不声称该步骤验证了云端访问链路**：

```bash
python deploy/v2/qa/provision_test_accounts.py --origin "$DS_V2_QA_ORIGIN" --in-process
```

脚本默认只上传仓库原创 `docs/v2/qa_synthetic_ds.txt`，账号 A 用于常慧思测试、账号 B 供负责人校验跨用户 404。随机凭证仅保存在 `~/.local/share/ds-assistant-v2/qa/credentials.json`，文件 0600。脚本拒绝覆盖已有凭证文件；失败后检查已创建对象，不要删除凭证反复运行。

**索引后续步骤**：上传会建立 Parser 任务；等待文档从 `uploaded/processing` 到 `parsed`；随后由负责人使用已认证 API（或经审查的本机辅助脚本）明确请求 `POST /api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/embedding`，请求体 `{"allow_cloud":false}`；确认 `ready` 且当前空间检索可用，再让常慧思测试问答。脚本目前只完成上传，不自动执行向量化；没有 READY 不得声称可问答。

**数据授权**：郭星辰的 V1 1010 条/100 候选权限仅有未独立核验的非商用研究试验陈述；电子教材 PDF 也可能受到著作权限制。暂不导入整本 PDF 或公开课程全文；测试优先原创合成资料，更多内容需确认来源、授权与共享范围。不得使用 `import_course.py --apply` 绕过私人库限制。

## 6. 真正跨设备验收（必做）

- 负责人 Mac 浏览器和常慧思 Windows 浏览器访问 **同一临时 HTTPS 地址**。常慧思输入获允许邮箱、收到一次性 PIN、验证后看见 V2 页面；无权邮箱拒绝访问。
- 浏览器开发工具 Network 里 API 请求必须指向同源 `https://...trycloudflare.com/api/v2/*`，不能指向 `127.0.0.1` 或出现 Mock 提示。
- 使用学生 A 完成登录、`/auth/me`、列出 private KB、问答及本次 `[S1]` 引用；登录后的 Cookie 必须是 Secure/HttpOnly、无浏览器 Mixed Content；异常 Origin、缺 CSRF 应被拒绝。
- 学生 B 不能看到 A 私人 KB 或会话（404）；不把学生 B 的密码交给常慧思，如需双账号现场验证由负责人单独配合。
- 记录数据库迁移、文档 `ready`、实际浏览器截图、HTTP 状态、账号隔离结果；去敏，不能公开 Cookie 或凭证。
- 只有真实 Windows 访问成功，才在 Issue #6 标记为真实跨设备 QA 可用。

**交付信息**：临时 HTTPS 网址、常慧思允许通过的邮箱、学生 A 登录账号和独立安全渠道传递的密码、QA KB 名称、使用时段以及环境为 deterministic（工程演示，非真实问答准确率）。

## 7. 关闭

停止 `cloudflared` 令临时网址失效，再停止 Caddy、API、两个 Worker。保持 QA DB 和凭证在本机受限目录（仅在明确授权后的清理计划内删除）。若 Quick Tunnel 地址变化，旧 Origin 不再适用，必须同步更新三个服务的 `DS_V2_QA_ORIGIN` 并重新构建/验证，不要自行关闭 HTTPS/Origin 检查。

**备选**：如果 IOA 不允许 Cloudflare Tunnel 或网络不通，则换非受管、经授权的云主机运行同一套 FastAPI+PostgreSQL+Caddy，并配置私有身份访问。不要在受管 Mac 上通过关闭 IOA、改网络策略、强推隧道来解决。
