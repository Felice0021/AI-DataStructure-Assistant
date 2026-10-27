# V2 团队开发指南（2026-10-27 更新：Windows 与 10 天 Sprint）

本页是当前启动入口。**全体组员使用 Windows**：按 [SPRINT_01.md](SPRINT_01.md) 的分角色 Windows/WSL2 指南选择环境。首轮周期 **2026-10-27 至 2026-11-05**，10/29 环境/方案检查，11/02 中期联调，11/05 最终验收。既往阶段验收记录中的旧版本、NOT VERIFIED 和云生成阻塞描述仅代表当时状态；当前结果见 INTEGRATION_REPORT.md。main 是已验收基线，所有开发经功能分支和 PR，不直接在 main 上长期开发。

## 1. 克隆与独立环境

```sh
git clone https://github.com/Felice0021/AI-DataStructure-Assistant.git
cd AI-DataStructure-Assistant
git switch -c feature/your-module
python3.12 -m venv ~/.virtualenvs/ai-datastructure-v2
source ~/.virtualenvs/ai-datastructure-v2/bin/activate
python -m pip install -r backend/v2/requirements-dev.txt
python -m pip check
node --version   # 24.x；前端组员用于 Vue 3 新工程
```

已有虚拟环境不要重建。当前负责人的 Mac 也可 `source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh`。不要使用 V1 `.venv`，不要复制负责人私钥或根目录 .env。

**Windows 执行环境按任务区分**：Vue 3 前端可以在原生 Windows + Node.js 24/VS Code 开发，资料与人工标注亦无需全部后端依赖；而 V2 后端及隔离 Worker 应在 **WSL2 Ubuntu + Docker Desktop WSL integration** 中运行。仓库、Python 虚拟环境和私有存储放在 WSL Linux 文件系统（如 `~/projects`，不要放 `/mnt/c`），使用 VS Code 的 WSL 扩展，在 Ubuntu 终端执行本页的 POSIX 命令。原生 PowerShell 虚拟环境不能补足 POSIX `dir_fd/O_NOFOLLOW` 安全机制，**不支持原生 Windows Python 运行完整后端**。实际 Windows/WSL 主机尚未验证；Linux ARM64 解析容器已实测。Mac 使用 zsh/bash 均可。

首次配置 WSL 的 PowerShell 命令：`wsl --install -d Ubuntu`；检测：`wsl -l -v`。安装 Docker Desktop 后，在 Settings → Resources → WSL Integration 启用 Ubuntu，在 WSL 执行 `docker version` / `docker compose version` 进行验证；从 Ubuntu 家目录 `git clone`，再执行 `code .`。Windows 前端如果连接 WSL 后端，应先验证 `http://127.0.0.1:8001/api/v2/docs` 在 Windows 浏览器可达，不得为了排障关闭 CSRF/CORS。详细准备及出现阻塞时的处理见 [SPRINT_01.md](SPRINT_01.md)。

Python 使用 3.12，Node 使用 24；Docker Desktop 需手动完成首次许可及 Engine 启动。无需安装本机 PostgreSQL。Apple Silicon 默认 ARM64；x86/WSL 使用下面的 platform 变量。

## 2. 数据库与配置

```sh
python deploy/v2/init_env.py   # 独占创建；已有 .env 原样保留
chmod 600 deploy/v2/.env
# x86/WSL 在 Compose 命令前设置 DS_V2_DB_PLATFORM=linux/amd64；Mac ARM64 可省略
DS_V2_DB_PLATFORM=linux/amd64 docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml up -d db
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
python -m backend.v2.tools.dev status
```

Mac 上去掉命令前的 `DS_V2_DB_PLATFORM=linux/amd64`。Compose 项目固定 ds-assistant-v2；DB 仅绑定 127.0.0.1:5433，命名卷独立。停止使用 `docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml stop db`，**不要 down -v**。

init_env 只建立数据库凭证，安全默认是 production + Secure Cookie。普通本地联调推荐下一节 `--test-providers`，只对该进程覆盖环境变量，不改 .env。其他本地模式须明确配置 development、ALLOW_INSECURE_LOOPBACK=true、精确 ALLOWED_ORIGINS；不能让正式部署降级。

默认存储在仓库外 `~/Library/Application Support/AI-DataStructure-Assistant/v2/files`。Linux/WSL 建议显式 `DS_V2_FILE_STORAGE_ROOT=$HOME/.local/share/ds-assistant-v2/files`，API 和两个 Worker 必须同值。路径必须绝对、私有且不在仓库内，不可共用真实用户存储做测试。

## 3. 解析隔离与三个进程

Mac auto 使用 Seatbelt 受限子进程。Linux/WSL auto 使用 Docker，无不受限解析回退；先构建隔离镜像：

```sh
docker build -f deploy/v2/parser.Dockerfile -t ds-assistant-v2-parser:local backend/v2
# 三个独立终端，激活同一个 V2 环境，各自执行一条：
python -m backend.v2.tools.dev api --test-providers
python -m backend.v2.tools.dev parser --test-providers
python -m backend.v2.tools.dev embedding --test-providers
```

测试 Provider 仅验证工程链路，不理解课程内容，不适合真实学生资料。三进程均使用相同测试模型空间；不要只在 API 设置测试 Provider，却让 Worker 使用其他空间。API 绑定 127.0.0.1:8001，文档 `/api/v2/docs`；Ctrl-C 安全停止。租约到期后新 Worker 可恢复崩溃任务。

Docker 解析容器无网络、只读 rootfs、无 capabilities、不提升权限、有限 CPU/内存/PID，只挂载一个输入文件；不挂载 .env、Docker socket 或整个存储目录。实际 Docker CLI 仍需宿主开发者权限，正式部署应隔离 Worker 主机与 Docker 管理权限。

## 4. 无付费一键验收

```sh
DS_V2_RUN_DOCKER_TESTS=1 python -m backend.v2.tools.acceptance
# 不测试 Docker fallback 时可省略该变量；其 3 项测试会明确 skipped
python -m backend.v2.evaluation.score
```

验收包含 pip check、开发库无损 upgrade/check、随机隔离数据库 pytest、8 个真实 HTTP/Worker 冒烟。DB 测试角色需能 CREATE DATABASE；正式应用角色不应具备该权限，应与测试/迁移角色拆分。测试结束只清理本轮随机库/临时文件，不清空开发库。HTTP 服务使用 OS 分配的端口，不占用或终止已有 8001 服务。

失败先排查 Docker Engine、5433、数据库密码、独立虚拟环境、镜像及 parser_backend、来源 Origin、CSRF、三进程模型空间和 ready 状态。503 不等于空检索；查看安全错误码，不打印请求正文、Key 或完整异常到共享日志。

## 5. 云端处理（默认关闭）

成员不需要私人 Key 即可开发。负责人如单独配置账号，只写 V2 .env 或 DS_V2_* 环境变量。现有 V2 文件中的 DASHSCOPE_API_KEY/WORKSPACE_ID/REGION 可作为兼容别名；**全局旧 DASHSCOPE 环境和根 .env 不会被读取为别名**。单独 DS_V2_* 优先。workspace/region 共同构造官方端点；没有 workspace 时按账户使用官方通用端点。不要把 workspace 地址或 Key 贴入工单。

真实模式须显式设置 EMBEDDING_PROVIDER=dashscope、RERANK_PROVIDER=qwen、GENERATION_PROVIDER=qwen，以及各自 CLOUD_ENABLED=true；RERANK_MODEL_VERIFIED / GENERATION_MODEL_VERIFIED=true 仅在核查账户后设置。Embedding 使用独立的稳定 MODEL_REVISION，变更需重新建索引。设置之后也不会绕过用途授权：每位用户对每个 KB 分别授予 embedding/reranking/generation，文档还须按当前解析代次 POST embedding allow_cloud=true；查询/问答还须对应 allow_cloud* 请求标志。不要默认批量同意或替学生同意。

真实合成测试入口 `python -m backend.v2.tools.cloud_smoke --allow-paid-synthetic` **不会由 pytest 调用**。本轮已用 9/12 次预算，固定 /tmp 账本限制重复执行，不得删账本重复消耗本轮授权；后续重新测试须获得新的独立预算与授权。普通开发请运行离线验收。

## 6. PR 与迁移协作

从最新 main 创建 feature 分支；每个 PR 说明问题、变更、真实测试、隐私/成本影响。API 变动更新 OpenAPI、API_CONTRACT 与前端示例；不破坏已有字段语义。新增迁移提前协调唯一 revision，不能改写已执行的 0001–0007；分叉迁移由维护者审查，禁止随意合并 heads 或重置数据库。

合并前执行验收、diff --check、敏感文件检查。真实 .env、上传内容、向量、日志、缓存、虚拟环境不进 Git。V1 资产与 V2 功能 PR 分开。长期待办范围见 NEXT_PHASE_BACKLOG.md；2026-10-27—11-05 **10 天首轮计划**见 [SPRINT_01.md](SPRINT_01.md)，任务见仓库 GitHub Issues #3–#7。请以对应 Issue 和最新 main 作为协作入口。
