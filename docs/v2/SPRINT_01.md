# V2.0 第一轮团队开发计划（Windows 协作版）

**周期**：2026-10-27—2026-11-05，含首尾共 10 天。**中间检查**：10 月 29 日（环境/方案）、11 月 2 日（主要功能联调）；**最终交付**：11 月 5 日。任务进度以 GitHub Issues #3–#7 为准；每个任务可在 Issue 中反馈截图、错误、阻塞，不需要每天提交代码。

**阶段目标**：不修改 V1、不降低 V2 多用户权限要求的前提下，完成新的 Vue 前端与已有单轮 RAG 对接、多轮会话的独立后端基础、课程资料导入核查、人工标注和系统测试准备。这是开发版，不是正式对外开放的生产版。不要因为真实质量尚未评测就阻止确定性 Provider 的开发联调。

## 一、所有成员使用 Windows 怎么开发

| 人员和方向 | 推荐环境 | 说明 |
| --- | --- | --- |
| 张圣江：Vue 前端 | **Windows 原生 VS Code + Node.js 24** 即可；或 VS Code + WSL2 | `npm`、Vite、TypeScript 可原生运行。真实 HTTP 联调所需后端可以由负责人统一提供，或在本机 WSL2 启动。 |
| 祝晟译：FastAPI、SQLAlchemy/Alembic、数据库 | **Windows + WSL2 Ubuntu + Docker Desktop**，VS Code WSL 扩展 | V2 文件安全依赖 POSIX 特性，不支持用原生 Windows Python 运行完整后端。 |
| 郭星辰：公共资料 | **Windows 原生编辑器/表格**即可做人工审查；运行 V2 导入工具时用 WSL2 | 先 dry-run，不直接改旧知识库；不需要为文献核查安装全套环境。 |
| 常慧思：标注与验收 | **Windows 原生浏览器、表格、VS Code**即可；脚本验收可由负责人/后端成员协助 | 主要任务是人工核对答案和用例，不要求独立部署全部 Worker。 |
| 李均乐：系统集成 | macOS 当前环境 + Windows/WSL 兼容性审核 | 负责合并、迁移协调、可演示数据与测试环境，不共享个人密钥。 |

**注意**：Windows 参与开发没有障碍，但 **V2 完整后端在 Windows 原生 Python 上尚未支持、Windows/WSL 实机尚未通过团队验证**。因此 10 月 29 日以前应在至少一台组员 Windows 机器完成 WSL 实际启动；若 WSL 安装受系统权限或硬件限制，先安排前端远程联调/数据与标注工作，不要求全部人卡在环境上。

### 需要完整后端的 Windows 组员：首次环境步骤

1. 在 Windows 的 PowerShell（建议管理员身份安装系统组件）运行 `wsl --install -d Ubuntu`。如果系统已有 WSL，运行 `wsl -l -v` 检查 Ubuntu 为版本 2。系统可能需要重启；校方管控电脑可能需要管理员协助。**这些是 Windows 命令，不是在 Ubuntu 中运行。**
2. 安装 VS Code + **WSL** 扩展、Docker Desktop；在 Docker Desktop 的 `Settings → General` 启用 WSL 2 engine，并在 `Settings → Resources → WSL Integration` 启用 Ubuntu。确认 Docker Desktop 处于运行状态。
3. 进入 Ubuntu（WSL 终端），在 Linux 用户家目录克隆仓库，不放在 `/mnt/c`。WSL 中运行 `code .` 打开 VS Code。若 VS Code 显示 WSL: Ubuntu，说明后续终端命令执行在 Linux 环境。
4. 在 Ubuntu 安装/确认 Python 3.12、pip/venv、Git、Docker CLI 可用，按 `TEAM_ONBOARDING.md` 创建 V2 虚拟环境并安装依赖；开发环境可能未自带 Python 3.12，请按适合当前 Ubuntu 版本的受信任渠道安装，不要随意覆盖系统 Python。
5. 运行 `docker version` 和 `docker compose version`，确认 Docker CLI 已联通 Docker Desktop。按开发指南创建 `deploy/v2/.env`，不要索取负责人私钥。
6. WSL 中为 V2 配置 Linux 私有存储绝对路径：`DS_V2_FILE_STORAGE_ROOT=$HOME/.local/share/ds-assistant-v2/files`，确保 API、parser Worker、embedding Worker 同值。不要把私人存储建在仓库内。
7. 先用 `--test-providers` 启动三个进程，访问 `http://127.0.0.1:8001/api/v2/docs`；浏览器/前端统一 `127.0.0.1`，不混用 `localhost`。Windows 浏览器若不能访问 WSL 服务，先检查 WSL 本地端口转发和防火墙/监听设置，**不要直接把后端绑定到 0.0.0.0 或关闭 Cookie/CSRF**。
8. 若要运行解析容器，WSL 首次使用 `docker build -f deploy/v2/parser.Dockerfile -t ds-assistant-v2-parser:local backend/v2`；具体 Compose 和验收命令见 `TEAM_ONBOARDING.md`。
9. 遇到安装问题先报告 Windows 版本、`wsl -l -v`、`docker version`、`python3.12 --version`、错误码；不贴密钥、Cookie、原始私人文本或完整 .env。

官方参考：[Microsoft VS Code + WSL](https://learn.microsoft.com/windows/wsl/tutorials/wsl-vscode)；[Docker Desktop WSL2](https://docs.docker.com/desktop/features/wsl)。

**Windows 前端独立开发**：只安装 Git、Node 24、VS Code 即可克隆仓库、新建 `frontend-v2/`（独立于 V1 `frontend/`）、运行 `npm install` / `npm run dev`。先用 MSW/静态 fixture 模拟冻结 OpenAPI（不伪造真实效果），后期联调接 `127.0.0.1:8001`；如果 API 运行在 WSL 中，必须实际检查 Windows 浏览器可访问性。

## 二、所有人都要遵守的 Git 协作规则

- 从最新 `main` 拉取：`git fetch origin`、`git switch main`、`git pull --ff-only origin main`，随后创建自己功能分支。已有本地修改时先保护当前工作区，不要强行切换、reset 或 clean。
- 推荐分支名：`feature/v2-frontend-zhang`、`feature/v2-conversations-zhu`、`data/v2-course-audit-guo`、`qa/v2-annotations-chang`。负责人负责统一审核，不需要所有人把代码提交 main。
- 每人只修改自己负责的路径；PR（合并请求）描述本次改动、测试方法和证据。**不共享 API Key，不提交 .env、真实用户资料、数据库、缓存或日志。**
- 祝晟译新增迁移前向负责人提交 schema 草案；`0001–0007` 不可改写，`0008` 只能由会话模块占用。
- 前端必须以 `docs/v2/openapi.json` 为最终字段契约，特别注意 Cookie、CSRF、`[S1]` 映射、`ready` 文档状态。已有 V2 路由仍维持不变。
- 文件和标注任务如暂不适合写代码，也可以提交 Issue 评论 + 审查表；不要把未确认的资料直接写入系统正式库。

## 三、工作拆分与验收标准

| 成员 | 详细执行任务 | 第 10 天交付 |
| --- | --- | --- |
| **张圣江**（前端） | 建立 `frontend-v2/` 独立 Vue 3 + Vite + TS；注册/登录/退出、`auth/me`；知识库列表/多选；单轮提问与模式选择；安全渲染 `[S1]` 引用及错误/拒答。先用 fixture 再接真实 V2 API。 | 可运行前端工程和 README、运行截图；能登录、选库、单轮请求、查看引用，`npm run build` 通过；异常页面不显示旧私人答案。 |
| **祝晟译**（后端） | 审查现有 ORM/auth/CSRF；提交 conversations/messages 模型草案和 API 方案；批准后开发迁移 0008、会话 CRUD/分页/消息存储与跨用户隔离测试；单轮 RAG 行为保持不变。 | API 及迁移、测试报告、OpenAPI/文档变更；不同学生和管理员无法越权；`pytest` 全量无回归。 |
| **郭星辰**（资料） | 查验 V1 1010 条课程 Chunk：来源授权、章节、重复、乱码、空文本、错误页码；执行导入 dry-run，整理首批约 100 条优质候选，准备安全测试使用说明。 | 审查表（旧 ID、主题、文件/章节、缺陷、处理建议）、dry-run 结果、首批 100 条候选清单；**不对全库自动发起付费 Embedding**。 |
| **常慧思**（测试/标注） | 阅读 36 道待标注合成题，先完成约 12 道初审：参考答案、相关证据、是否充分、需复核项；按 API/前端流程建立注册、知识库、上传、问答、权限、引用的测试表。 | 12 道可追踪初审、功能用例表（步骤/预期/实际/状态）、至少一次前端联调反馈；未复核不能标成最终 Ground Truth。 |
| **李均乐**（负责人） | 协助 Windows WSL 环境问题、准备合成/已授权演示数据、审查会话迁移和前端接口、维护稳定 main、进行演示流程与验收。 | 演示流程和集成验收记录；PR 合并计划；未完成风险与下一轮待办。 |

### 进度节奏

- **10/27–10/29：环境与设计**。前端 `npm run dev` 可启动；后端 WSL + Docker 连通、会话 schema 草案；资料/标注任务领到清单。10/29 汇报阻塞点。
- **10/30–11/02：核心实现**。前端完成登录 + KB 列表 + RAG Ask 骨架；后端实现经审核的数据模型及 CRUD；资料整理首批候选；评测初审已开展。11/02 展示能运行的中间成果。
- **11/03–11/05：联调、修复与交付**。前端对真实 API 联调、处理引用/CSRF/错误；后端执行隔离测试和迁移回归；资料和验收报告提交；11/05 完成 PR 审查。

**优先级**：P0 是开发环境/接口连通和账户隔离；P1 是首版功能、资料和测试可追踪；P2 是动画、页面美化、额外模式、性能调优。进度不足时可以缩减 P2，但不能跳过权限和错误处理。

## 四、协作和资源边界

- 负责人不得用测试结果宣称真实语义质量；测试 Provider 不理解课程内容。真实批量索引只有在材料来源授权、费用预算和用途同意均满足时才能单独批准。
- 云端真实 API 使用 `qwen3.8-flash` 等模型曾做过合成文本冒烟，不等于允许组员使用负责人的 Key 或私人课程资料。
- PR 和日志不要包含私人文本、Key、完整 Cookie；截图打码邮箱、私人数据。
- Windows/WSL 实机验收是本轮待验证项；任何阻塞尽早反馈，不等到 11/05。
- 本轮**不要求** Vue 多轮聊天、流式返回、VLM 图片题、全量生产部署或真实课程指标提高。这些作为后续阶段单独安排。

## 五、入口与问题反馈

- [仓库 README](../../README.md)、[团队环境指南](TEAM_ONBOARDING.md)、[前端交接](FRONTEND_HANDOFF.md)、[OpenAPI](openapi.json)
- 详细任务与打卡：[前端 #3](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/3)、[后端 #4](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/4)、[资料 #5](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/5)、[测试 #6](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/6)、[集成 #7](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/7)

进度反馈采用统一格式：**已完成 / 正在做 / 遇到的问题 / 需要负责人协助 / 预计下次可验证的结果**。无需每天长篇报告。
