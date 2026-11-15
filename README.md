# 数据结构 AI 助教（AI-DataStructure-Assistant）

面向本科《数据结构》课程的 RAG（检索增强生成）学习助手：从课程资料中检索证据，辅助概念理解、习题解析和代码分析，并展示可核对的资料来源。

> **进展更新：2026-11-15。** 当前开发重点是 **V2（FastAPI + PostgreSQL/pgvector + Vue 3）**。V2 已具备独立的真实 Qwen 演示环境、会话历史、主题项目及受限跨项目学习记忆；旧 V1 原型仍保留在仓库中。**演示可用不等于已正式生产开放，也不代表课程回答的正确率已通过人工评测。**

## 1. 体验入口与环境区别

| 环境 | 入口 | 用途与边界 |
| --- | --- | --- |
| **Qwen 演示** | [qwen.dsassistant.cn](https://qwen.dsassistant.cn/) | 调用真实的 Embedding、Reranking 和生成模型；独立账号、数据库及文件目录；受控试用 |
| **确定性 QA** | [qa.dsassistant.cn](https://qa.dsassistant.cn/) | 使用测试 Provider 检验接口、安全和工程流程；**不能据此判断模型回答质量** |
| **本地开发** | `127.0.0.1:5173`（前端）、`127.0.0.1:8001`（API） | 支持 Mock 前端联调或隔离数据库的真实后端联调 |

两个云环境的数据、账号和发布版本相互独立；请勿将 QA 数据当作 Qwen 实测结果。Qwen 演示分支为 [`deploy/qwen-demo`](https://github.com/Felice0021/AI-DataStructure-Assistant/tree/deploy/qwen-demo)，其 CI 通过后自动发布该演示入口；**合并到 `main` 不会触发 Qwen 服务器部署**。

## 2. 当前能力

| 模块 | 状态与说明 |
| --- | --- |
| 账号与权限 | 注册/登录、Cookie Session、CSRF、角色授权、私人/公共知识库及用户隔离已实现；演示环境的注册开放策略单独配置 |
| 资料处理 | PDF/DOCX/TXT 上传、隔离解析、Chunk、Embedding 任务、状态及失败重试已实现 |
| 检索与回答 | BM25、Dense、Hybrid RRF、Reranking、证据构建、来源引用与证据不足拒答已实现；默认学生界面使用自动回答 + 混合检索 |
| 专项答题 | 支持概念、习题及代码分析；BST/AVL 等部分结构题增加有界算法校验与可视化；**不保证覆盖所有题型** |
| 多轮会话 | 服务端会话/消息持久化、历史重命名与删除、有限上下文（近期最多 3 轮）、Markdown/代码/数学公式展示已实现 |
| 流式体验 | 支持 SSE 分阶段状态和回答草稿预览；**草稿未经最终引用校验，不作为最终答案保存** |
| 主题项目 | 可建立如“复杂度”“二叉树”等项目并整理会话；项目内存储简短学习记录，可明确选择允许读取的其他项目，默认不共享 |
| 课程知识库 | 真实 Qwen 演示库包含 10 份 `ready` 文档、1011 个 V2 Chunk 与 1011 条向量；源于 V1 的 1010 条记录，重切分后数量可能不同 |
| 尚未完成 | 图片/VLM 问答、完整人工语义质量评测、公开生产环境所需的运营/费用/权限保障及跨设备充分验收 |

主题项目的“记忆”仅是经校验回答的**有界文本摘录**，不是对学生掌握水平的判断；不会跨用户共享，也不能代替本轮检索证据。引用 `[S1]` 等只指向当前有权限且仍有效的课程 Chunk。对无法证实的页码或来源映射，界面应显示“未知”或“待核实”，不补造出处。

### 已验证与尚待验证

- 工程链路：真实模型的课程库导入、Embedding、检索、问答、引用及账户隔离已做过 HTTP/浏览器回归；12 道课程问题的返回状态和引用映射经过检查，**不等同于 12 道答案均经人工判定正确**。
- 安全边界：云端用途授权需由后端逐次校验；私有资料、凭据与用户会话不应写入仓库或公开文档。
- 质量边界：还需对概念、构造题、代码题开展人工评审，统计答案事实性与引用忠实性；Windows 独立设备验收及真实账单核对仍需补齐。
- 详情及历史测试证据见 [真实 Qwen QA 记录](docs/v2/QWEN_QA_STATUS.md)、[评测计划](docs/v2/EVALUATION_PLAN.md)；单次 CI 通过数以对应 GitHub Actions 运行记录为准，不把早期测试数当成当前总数。

## 3. 新成员阅读顺序

| 目的 | 文档 |
| --- | --- |
| 后端安装、Worker、验收及 Windows/WSL 建议 | [团队开发指南](docs/v2/TEAM_ONBOARDING.md) |
| Vue 前端与当前学生聊天页 | [前端 README](frontend-v2/README.md) · [学生聊天页说明](frontend-v2/docs/STUDENT_CHAT_REVIEW.md) |
| V2 分层、安全、数据库与接口 | [架构](docs/v2/ARCHITECTURE.md) · [数据模型](docs/v2/DATABASE_SCHEMA.md) · [OpenAPI](docs/v2/openapi.json) |
| 云环境与真实模型验收 | [Qwen QA 记录](docs/v2/QWEN_QA_STATUS.md) · [QA 安全说明](docs/v2/TENCENT_QA_SECURITY.md) |
| 主题项目/学习记忆的设计及边界 | [主题项目说明](docs/v2/TOPIC_PROJECTS.md) |
| 第一轮协作背景、分工和遗留任务 | [Sprint 01 计划（历史）](docs/v2/SPRINT_01.md) · [下一阶段 Backlog](docs/v2/NEXT_PHASE_BACKLOG.md) |

部分 10 月编写的模块交接文档保留了当时的待开发/Mock 描述；**判断当前实现以代码、OpenAPI、最近的 CI 和验收记录为准**。对外介绍不要把历史规划直接写成已交付能力。

## 4. 本地运行

后端需要 Python 3.12、Docker Desktop/Compose（数据库为 PostgreSQL 17 + pgvector）；前端使用 Node.js 24。Windows 开发前端可以原生运行；完整后端/隔离 Worker 建议 WSL2 Ubuntu + Docker Desktop WSL integration。

```bash
git clone https://github.com/Felice0021/AI-DataStructure-Assistant.git
cd AI-DataStructure-Assistant

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/v2/requirements-dev.txt
python deploy/v2/init_env.py
chmod 600 deploy/v2/.env

# macOS ARM64；x86/WSL 按团队开发指南设置所需 DB 平台
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml up -d db
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m backend.v2.tools.dev status
```

Linux/WSL 上运行解析 Worker 前，应按 [团队开发指南](docs/v2/TEAM_ONBOARDING.md) 准备隔离解析镜像和仓库外的私有存储。分别在三个终端激活同一 Python 环境并运行：

```bash
python -m backend.v2.tools.dev api --test-providers
python -m backend.v2.tools.dev parser --test-providers
python -m backend.v2.tools.dev embedding --test-providers
```

前端使用另一个终端：

```bash
cd frontend-v2
npm ci
cp .env.development.example .env.development.local
npm run dev
```

默认 `VITE_USE_MOCK=true`，可先独立查看界面。连接后端时在 `.env.development.local` 设置 `VITE_USE_MOCK=false` 和正确的 `VITE_API_BASE`；真实课程库还需要设置当前环境中账户有权访问的 `VITE_COURSE_KB_ID`。`VITE_` 变量会被编入前端产物，**不得填入 Key/密码**。后端使用 `127.0.0.1` 的 Origin 白名单，避免与 `localhost` 混用。

测试命令：

```bash
# 在仓库根目录运行：普通前端回归 + 构建
npm --prefix frontend-v2 run test
npm --prefix frontend-v2 run build

# 后端（需依照指南准备数据库、隔离解析容器等）
python -m pytest -q backend/v2/tests
```

完整 Linux、macOS 解析隔离与生产前端构建由 [V2 CI](.github/workflows/v2-ci.yml) 在 PR 时运行。不要删除开发数据库卷，不要执行 `docker compose down -v`；不要把真实模型凭据或私人资料用于自动化测试。

## 5. API 与安全约定

V2 API 前缀为 `/api/v2`，重要入口如下：

| 用途 | 端点 |
| --- | --- |
| 认证 | `/auth/csrf`、`/auth/register`、`/auth/login`、`/auth/me`、`/auth/logout` |
| 知识库、文档和处理任务 | `/knowledge-bases`、`/knowledge-bases/{id}/documents`、对应 ingestion/embedding |
| 检索与单轮回答 | `/retrieval/search`、`/retrieval/prepare-context`、`/rag/ask` |
| 会话与流式回答 | `/conversations`、`/conversations/{id}/messages`、`/conversations/{id}/ask`、`/conversations/{id}/ask-stream` |
| 主题项目与记忆 | `/projects`、`/projects/{id}/memories` |
| 模型用途授权 | `/knowledge-bases/{id}/cloud-consents` |

具体方法、请求体和响应体以 [OpenAPI 3.1](docs/v2/openapi.json) 和实现为准。浏览器请求携带 `credentials: 'include'`，写请求附上 `X-CSRF-Token`；身份只由服务端会话决定。`insufficient_evidence` 是资料不足，不应与 502/503 生成故障混为一谈。私人资料未获授权时返回 404，不得绕过访问控制或用前端拼出的路径访问文件。

## 6. 协作、分支与后续工作

- **`main`**：团队集成基线。成员从最新 `main` 新建 `feature/*`/`fix/*` 分支、经 PR 和 CI 验收后合并；禁止强推或把未审核配置直接写入主分支。
- **`deploy/qwen-demo`**：独立 Qwen 演示的发布分支；更改该分支可能触发自动部署，应先通过 PR 与安全检查。`main` 与演示分支是不同用途，不能混为一谈。
- **数据库迁移**：V2 已包含 `0008_conversations` 与 `0009_topic_projects`；已有 revision 不得改写，新迁移需提前协调。
- **第一轮 Sprint**（2026-10-27 至 11-05）已有若干成果进入演示分支；测试/标注与成员交付仍以各 Issues、PR 和实际文档为准，不把未合并的工作写成已验收。
- **近期优先级**：完成中期答辩前的真实课程案例人工核验、Windows/移动端体验检查、演示稳定性与备份恢复抽查；之后再推进多模态、质量评测及生产级配额与运维。

仓库主要目录：

```text
backend/v2/       FastAPI、鉴权、会话/项目、RAG、Worker、迁移与测试
frontend-v2/      Vue 3 + Vite 学生端
deploy/v2/        本地 Compose、隔离解析镜像、云环境部署脚本
docs/v2/          API、架构、QA/评测、团队交接材料
knowledge_base/   V1 数据与审查资产；勿覆盖或直接改写原始资料
backend/、rag/、frontend/  V1 历史原型及参考代码
```

V1 的历史设计不等于 V2 当前行为；旧 README 存档于 [V1 README](docs/v1/README_LEGACY.md)。
