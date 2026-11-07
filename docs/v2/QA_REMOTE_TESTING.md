# V2 组内跨设备 QA 测试入口（预备运行手册）

本文件是**待在负责人 Mac 上实测的部署方案**，不是已上线证明。请由负责人在最新 main 的独立工作分支内核验，避免覆盖已有数据库、存储、.env 或本机其他服务。

## 目标与架构

采用 **Tailscale Serve（仅私有 tailnet，HTTPS） → 本机 Caddy（127.0.0.1:8088） → 静态 Vue `dist/` / FastAPI（127.0.0.1:8001）**。浏览器只访问一个 HTTPS origin，前端 API 地址使用相对路径 `/api/v2`，因此无需跨源 Cookie/CORS。Tailscale 受设备与 ACL 约束，禁止用公开的 `tailscale funnel` 代替 Serve。Tailscale 的组员共享功能可能把该设备的其他可访问端口也共享出去，必须核对访问控制策略，原则上仅允许授权测试者访问 Serve 的 443/TCP。Mac 与 Windows 客户端都需要 Tailscale 已登录且实际联网。若 Tailscale 与已有 VPN/路由冲突，先停止并记录，不能降低后端权限或公网裸露端口。

## 准备（仅 Mac，本机操作）

1. 在 Mac 安装并登录 Tailscale（可参考 https://tailscale.com/docs/install/mac），由负责人在客户端启用 Serve 所需的 HTTPS，并仅邀请指定测试者访问。确认 `tailscale status` 可用；Standalone 版可在设置中安装 CLI。不要把实际 tailnet URL、用户凭证写入 GitHub。
2. 安装 Caddy（例如通过 Homebrew），确认 `caddy version`。用 `tailscale serve status` 核对这台设备已有 Serve 设置，**不要无差别 reset 他人配置**。
3. 拉取最新 main，使用已有 V2 Python 3.12 环境和 Node/npm；保留已有 `deploy/v2/.env`、Docker 卷、V1 与本地未提交资产。
4. **必须单独创建**数据库 `ds_assistant_v2_qa`，与现有 `ds_assistant_v2`、`ds_assistant_v2_demo`、`ds_assistant_v2_integration` 分开。使用当前受控 PostgreSQL 服务和账号创建，若数据库已存在，不要删除/覆盖/重建；先检查迁移版本和用途。后续启动脚本通过 `DS_V2_DB_NAME` 选择 QA 库，存储固定在 `~/.local/share/ds-assistant-v2/qa/files`，不会操作其他库的数据。Docker 如未启动，依照 TEAM_ONBOARDING.md 仅启动 db。
5. 获取实际 HTTPS 站点名（形如 `https://your-mac.your-tailnet.ts.net`），在 Mac 终端设置环境变量：
   ```bash
   export DS_V2_QA_ORIGIN="https://实际设备名.实际tailnet.ts.net"
   ```
   这是示意占位符，不要原样复制。启动脚本要求标准 ASCII 的 `https://*.ts.net` 域名。

## 启动及验证

从仓库根目录执行（各独立终端均继承 `DS_V2_QA_ORIGIN`；API、Parser、Embedding 使用相同 DB、存储与 deterministic 模型空间）：

```bash
# 先建好独立 QA 数据库，再运行唯一 head 的迁移
bash deploy/v2/qa/run-secure-test-provider.sh migrate
bash deploy/v2/qa/run-secure-test-provider.sh check

# 构建纯静态前端；明确禁用 mock，API 用同源相对路径
cd frontend-v2
npm ci
VITE_USE_MOCK=false VITE_API_BASE='' npm run build
cd ..

# 3 个终端各运行一条
bash deploy/v2/qa/run-secure-test-provider.sh api
bash deploy/v2/qa/run-secure-test-provider.sh parser
bash deploy/v2/qa/run-secure-test-provider.sh embedding

# 第 4 个终端：本机 Caddy（必须在 repo 根目录）
DS_V2_QA_WEB_ROOT="$PWD/frontend-v2/dist" caddy run --config deploy/v2/qa/Caddyfile

# 另一个终端：仅向 tailnet 内开放 HTTPS（不要用 funnel）
tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

如已经占用 API 8001 或 Caddy 8088，先查明占用者，**不要 kill 未确认的已有进程**。需要禁用本次 Serve 时使用 `tailscale serve off`，执行前确认 443 没有承载其他服务。若命令行入口/标志随 Tailscale 版本变化，以当前官方 `tailscale serve --help` 核对。

## 自动创建专用账号与私人知识库（服务启动后）

在 Mac 的仓库根目录，且 Tailscale Serve、API 与两个 Worker 都正常运行时：

```bash
python deploy/v2/qa/provision_test_accounts.py --origin "$DS_V2_QA_ORIGIN"
```

脚本将通过 **真实 HTTPS API**（带真实 CSRF/Origin/Cookie）创建学生 A、隔离验证学生 B，并在 A 名下创建 private KB、上传默认的原创 `docs/v2/qa_synthetic_ds.txt`，最后确认 B 读取 A 的 KB 返回 404。生成的随机密码**不会出现在终端和 Git 仓库**，只保存到 Mac 本地 `~/.local/share/ds-assistant-v2/qa/credentials.json`（0600）。脚本如发现该凭证文件已存在就会拒绝覆盖；出现部分失败时先检查已有账户与私有文件，不要删除凭证后盲目反复注册。

**上传不等于可问答。** 等待解析完成（document.status=parsed），由负责人调用已存在的 `POST /api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/embedding`，请求体 `{"allow_cloud": false}`；等待 `ready` 后再交付给常慧思。若需要通过脚本调用，可以由本机 Codex 使用该专用账号和真实 Cookie/CSRF 执行，所有秘密仅在本机读取。

如选择本机已获明确授权的 PDF 或经筛选的 V1 资料，运行 `--source /本机/路径/资料.pdf --confirm-source-rights`；使用者必须先核查权限，不得仅凭选项将任何版权材料视为公开可分发。

## 必须通过的验证

- Mac 与常慧思的 Windows 电脑均能通过 Tailscale 登录访问 **同一** `https://*.ts.net` 页面，证书有效；不需要在 Windows 上配置 Python、Docker 或 DB。
- 网站无 MSW/Mock 标识，网络请求指向 **同源** `https://.../api/v2/*` 而不是访问者的 `127.0.0.1`。后端 `/api/v2/health` 返回 200。
- `GET /api/v2/auth/csrf` 设置 Secure、HttpOnly、Host-only Cookie；注册 201，登录 200，`auth/me` 返回当前用户；POST 必须具备正确 Origin 和 CSRF，非法来源仍应 403。
- 账户 A 的私有 KB/会话不能被账户 B 访问（404）；退出后会话内容不再可读；API 返回 `Cache-Control: no-store`。
- 停止/关闭 Tailscale Serve 后，Windows 访问共享域名不再能打开 QA 网站。任何公网匿名访问不应成功。

## 账号与数据（单独执行，不能通过 GitHub 交付密码）

- 用真实 HTTPS 注册接口创建 **专用测试学生账号 A**（强随机密码 >=15 字符），再创建 **隔离测试学生账号 B**（用于验证越权 404）。不要共享管理员或个人账号。
- 凭证仅保存在负责人 Mac 的 `~/.local/share/ds-assistant-v2/qa/credentials.json`，目录权限 0700、文件权限 0600；仅通过独立安全渠道把账号 A 发给常慧思，账号 B 由负责人控制。不要提交 .env、cookie、完整日志或账号密码到 GitHub。
- 账号 A 创建自己的 **private** 知识库，优先导入仓库中的 `docs/v2/qa_synthetic_ds.txt` 作为首次工程验收材料；真实上传后等待 Parser 将文档标记 `parsed`，显式触发 `POST /api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/embedding`（`{"allow_cloud":false}`），等待 Embedding Worker 将状态推进到 **ready**。当前前端没有上传 UI，使用既有鉴权 API/API 调试器或负责人本地脚本完成，不修改主业务代码。
- 如果要改用 V1 的 1010 条 Chunk 或电子教材 PDF，必须先确认相关非商用组内测试授权、来源与可传输范围。郭星辰的 `docs/v2/course_audit/2026-11-04/authorization.md` 仅有组员权限陈述，未独立核验；100 条候选也尚未完成人工复核。**不能推定有公开传播许可、不能把完整教材直接放到公开可访问的公共库**。本轮选择已确认可用的小批量原文或自编合成材料，放 private KB。现有 `import_course.py --apply` 只允许管理员导入 public KB，不可用它绕过 private 范围；如需要课程内容，可将已获授权的少量文本转成合法 TXT，经该学生账号的上传 API 导入，保留来源映射。PDF 需满足后端上传大小和解析限制。
- 确定性 Provider 只用于联调，不说明回答准确率。真实 Qwen 的付费云调用需要另行预算、用户用途授权及逐项模型开关，不能擅自启用。

交付给常慧思的信息：一个实际可访问的 HTTPS 域名、独立账号 A（密码单独传递）、测试知识库名称、可测功能列表及后端版本、禁止公开的内容。**在实际跨设备 HTTP 验证完成前，不得在 Issue #6 声称已上线。**
