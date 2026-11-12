# Qwen 演示 CI/CD（准备阶段）

本方案默认关闭自动发布；尚未完成服务器端安装和端到端验收前，不要设置 `QWEN_AUTO_DEPLOY=enabled` 或创建 `/etc/ds-v2-qa/qwen-ci-enabled`。它只针对 `qwen.dsassistant.cn`，不更改 `qa.dsassistant.cn`、数据库、索引或凭据。旧 release 保留。

部署分支受到保护：开发者先提交功能分支并通过 PR 审查与检查，合并后才进入发布流程；直接推送不会替代审查。

## 发布门槛

1. 在 GitHub **Settings → Rules → Rulesets** 创建针对 `deploy/qwen-demo` 的分支规则：禁止强推和删除；限制直接推送，仅授权负责人；要求通过 PR 合并、审查及 `V2 backend tests`、`V2 frontend tests and build` 和 `V2 macOS parser isolation` 状态检查。确认仓库套餐实际支持并生效，避免管理员绕过。
2. 在 **Settings → Environments → New environment** 创建 `qwen-demo`，将 Deployment branches 限定为 `deploy/qwen-demo`，按仓库支持情况设置负责人审批。Environment 内添加 `QWEN_SSH_KNOWN_HOST` 变量（通过独立可信渠道验证的服务器 SSH 主机公钥行）和 `QWEN_DEPLOY_SSH_KEY` secret（专用部署私钥）。不要粘贴到仓库或日志。注意 workflow 顶层的 `if` 使用仓库变量，开关须在 **Settings → Secrets and variables → Actions → Variables** 设置 `QWEN_AUTO_DEPLOY=enabled`；在验收前不要设置。
3. 服务器需要经独立审核安装此目录的 root 所有部署脚本到 `/usr/local/libexec/ds-v2-qwen-deploy`，使用无其他权限的 `qwen-ci` SSH 用户、受限 authorized_keys 强制命令及只允许该固定命令的 sudoers；单独 `qwen-build` 用户用于构建，不加入 sudo、docker 或业务用户组，不可读取业务凭据。SSH 公钥及主机密钥须验证身份，禁止禁用主机密钥校验。`qwen-ci` 的部署能力等同于可以改变该应用运行代码，分支写权限、CI 工作流与审批必须受保护。
4. 验证 GitHub runner 到服务器 SSH 的连接与防火墙、安全回滚、两个必需检查的 GitHub API 返回、生产 release 与新基线的依赖/迁移/解析器文件一致，以及受限用户无额外权限。当前脚本不自动安装这些系统配置。只有全部验证通过后，服务器管理员才能创建 root 所有的开关文件并启用 GitHub 变量。

## 行为和限制

PR 只运行测试；部署分支 push 运行测试，只有三个 job 成功、SSH 指纹预检成功、开关开启且环境保护允许后才请求部署。首次受控验收可将仓库变量 `QWEN_DEPLOY_TRIAL_SHA` 设为指定完整提交 SHA，仅允许该提交的 push 运行部署；不需要开启常规自动发布变量，服务器开关、环境保护及全部检查仍然必须满足。验收后移除该变量。Linux 运行数据库和 Docker 解析测试，macOS 单独运行仅支持 Seatbelt 的三项测试。服务器再次核对最新分支 SHA 和 GitHub Actions 的检查结果，串行构建独立 release，以非特权用户安装前端依赖并构建，切换后重启 Qwen API 和两个 Worker，检查服务、数据库健康及 HTTPS 版本标记。失败时切回旧 release 并重启服务。自动流程不执行 Alembic 和重新索引，也不删除 release；已有后台队列仍可能由原 Worker 按现有规则继续处理。

依赖、迁移和关键解析器文件一旦与线上 release 不一致，部署拒绝执行，需要人工单独审查并制定迁移方案。服务器需能够以 HTTPS 访问 GitHub，GitHub 的 check-runs API 限流或不可用会安全拒绝部署。API health 与版本标记不代表问答、授权或浏览器功能通过；首次启用前须进行真实功能验收。构建执行锁定依赖的安装脚本，构建账号仍必须与所有生产凭据隔离。

## 回滚

发布前记录 `readlink -f /opt/ds-v2-qa/qwen-demo`。如需人工回滚，由服务器管理员核对旧 release 后，原子替换 `/opt/ds-v2-qa/qwen-demo` 符号链接到该旧目录，并重启 `ds-v2-qwen@api`、`ds-v2-qwen@parser`、`ds-v2-qwen@embedding`，验证 HTTPS、登录和 RAG。不得更改 `/opt/ds-v2-qa/current`。自动回滚依赖 systemd 可用及旧 release 完整，无法保证机器掉电期间的事务性；应在启用前实际演练。
