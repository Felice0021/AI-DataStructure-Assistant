# 数据结构 AI 助教（AI-DataStructure-Assistant）

面向本科《数据结构》课程的 RAG（检索增强生成）学习助手：从课程资料中检索证据，辅助概念理解、习题解析和代码分析，并展示可核对的资料来源。

> **项目进展（2026-11-15）**：目前以 **V2（FastAPI + PostgreSQL/pgvector + Vue 3）** 为开发主线，已上线真实 Qwen 演示环境，支持多轮会话、主题项目和跨项目学习记忆。近期重点是完善课程问答效果与中期答辩演示。

## 1. 体验入口

| 环境 | 入口 | 用途 |
| --- | --- | --- |
| **Qwen 演示** | [qwen.dsassistant.cn](https://qwen.dsassistant.cn/) | 真实 Embedding、Reranking、生成模型与课程知识库 |
| **QA 测试** | [qa.dsassistant.cn](https://qa.dsassistant.cn/) | 使用确定性测试 Provider 验证接口、权限和处理流程 |
| **本地开发** | `127.0.0.1:5173`（前端）、`127.0.0.1:8001`（API） | 前端 Mock 或本地完整后端联调 |

Qwen 与 QA 使用独立的数据库和账号。Qwen 演示由 [`deploy/qwen-demo`](https://github.com/Felice0021/AI-DataStructure-Assistant/tree/deploy/qwen-demo) 分支通过 CI 自动发布，`main` 用于团队日常开发集成。

## 2. 当前能力

| 模块 | 状态与说明 |
| --- | --- |
| 账号与权限 | 注册/登录、Cookie Session、CSRF、角色授权、私人/公共知识库及用户隔离已实现；演示环境的注册开放策略单独配置 |
| 资料处理 | PDF/DOCX/TXT 上传、隔离解析、Chunk、Embedding 任务、状态及失败重试已实现 |
| 检索与回答 | BM25、Dense、Hybrid RRF、Reranking、证据构建、来源引用与证据不足拒答已实现；默认学生界面使用自动回答 + 混合检索 |
| 专项答题 | 支持概念、习题及代码分析；BST/AVL 等结构题具有算法校验与可视化 |
| 多轮会话 | 服务端会话/消息持久化、历史重命名与删除、有限上下文（近期最多 3 轮）、Markdown/代码/数学公式展示已实现 |
| 流式回答 | 通过 SSE 展示处理状态与实时回答，最终结果校验后保存 |
| 主题项目 | 可建立如“复杂度”“二叉树”等项目并整理会话；项目内存储简短学习记录，可明确选择允许读取的其他项目，默认不共享 |
| 课程知识库 | 已导入 V1 课程资料，包含 10 份可检索文档、1011 个 Chunk 和 1011 条向量 |
| 下一阶段 | 图片/VLM 问答、课程回答质量评测、更多设备适配与生产运维完善 |

主题项目支持独立管理对话与学习记录，并可按需指定其他项目作为记忆来源，默认互不共享。回答中的 `[S1]` 等引用对应课程知识库的具体资料，支持查看来源名称、章节和页码。

### 测试与评测进展

- 已完成真实 Qwen 的课程资料入库、检索、问答、来源展示和账户隔离回归，并对 12 道课程问题进行了接口与引用检查。
- 正在推进概念题、数据结构构造题、代码题的人工质量评测，以及 Windows 等设备上的浏览器验收。
- 测试记录见 [Qwen QA 记录](docs/v2/QWEN_QA_STATUS.md)，评测方法见 [评测计划](docs/v2/EVALUATION_PLAN.md)。

## 3. 新成员阅读顺序

| 目的 | 文档 |
| --- | --- |
| 后端安装、Worker、验收及 Windows/WSL 建议 | [团队开发指南](docs/v2/TEAM_ONBOARDING.md) |
| Vue 前端与当前学生聊天页 | [前端 README](frontend-v2/README.md) · [学生聊天页说明](frontend-v2/docs/STUDENT_CHAT_REVIEW.md) |
| V2 分层、安全、数据库与接口 | [架构](docs/v2/ARCHITECTURE.md) · [数据模型](docs/v2/DATABASE_SCHEMA.md) · [OpenAPI](docs/v2/openapi.json) |
| 云环境与真实模型验收 | [Qwen QA 记录](docs/v2/QWEN_QA_STATUS.md) · [QA 安全说明](docs/v2/TENCENT_QA_SECURITY.md) |
| 主题项目/学习记忆的设计及边界 | [主题项目说明](docs/v2/TOPIC_PROJECTS.md) |
| 第一轮协作背景、分工和后续任务 | [Sprint 01 计划](docs/v2/SPRINT_01.md) · [下一阶段 Backlog](docs/v2/NEXT_PHASE_BACKLOG.md) |

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

默认 `VITE_USE_MOCK=true`，可先独立查看界面。连接后端时在 `.env.development.local` 设置 `VITE_USE_MOCK=false` 和正确的 `VITE_API_BASE`；连接课程库还需配置 `VITE_COURSE_KB_ID`。`VITE_` 变量会编入前端产物，请勿填写密钥；本地联调统一使用 `127.0.0.1`。

测试命令：

```bash
# 在仓库根目录运行：普通前端回归 + 构建
npm --prefix frontend-v2 run test
npm --prefix frontend-v2 run build

# 后端（需依照指南准备数据库、隔离解析容器等）
python -m pytest -q backend/v2/tests
```

Linux、macOS 解析隔离测试和前端构建由 [V2 CI](.github/workflows/v2-ci.yml) 在 PR 时执行。测试使用独立数据库及测试配置，保留本地开发数据库卷。

## 5. API 接口

V2 API 前缀为 `/api/v2`，重要入口如下：

| 用途 | 端点 |
| --- | --- |
| 认证 | `/auth/csrf`、`/auth/register`、`/auth/login`、`/auth/me`、`/auth/logout` |
| 知识库、文档和处理任务 | `/knowledge-bases`、`/knowledge-bases/{id}/documents`、对应 ingestion/embedding |
| 检索与单轮回答 | `/retrieval/search`、`/retrieval/prepare-context`、`/rag/ask` |
| 会话与流式回答 | `/conversations`、`/conversations/{id}/messages`、`/conversations/{id}/ask`、`/conversations/{id}/ask-stream` |
| 主题项目与记忆 | `/projects`、`/projects/{id}/memories` |
| 模型用途授权 | `/knowledge-bases/{id}/cloud-consents` |

具体方法及请求/响应字段见 [OpenAPI 3.1](docs/v2/openapi.json)。浏览器请求携带 `credentials: 'include'`，写请求附上 `X-CSRF-Token`；资料不足时返回 `insufficient_evidence`，模型服务异常时返回对应错误状态。

## 6. 团队协作与后续计划

- **`main`**：团队开发基线。从最新 `main` 新建 `feature/*`/`fix/*` 分支，通过 PR 和 CI 后合并。
- **`deploy/qwen-demo`**：真实 Qwen 演示发布分支，合并后由 CI 自动部署。
- **数据库迁移**：当前包含 `0008_conversations` 和 `0009_topic_projects`，新增迁移请提前与负责人协调。
- **第一轮 Sprint**：2026-10-27 至 11-05，任务与分工见 [Sprint 01](docs/v2/SPRINT_01.md)。
- **近期优先级**：完成中期答辩前的真实课程案例人工核验、Windows/移动端体验检查、演示稳定性与备份恢复抽查；之后再推进多模态、质量评测及生产级配额与运维。

仓库主要目录：

```text
backend/v2/       FastAPI、鉴权、会话/项目、RAG、Worker、迁移与测试
frontend-v2/      Vue 3 + Vite 学生端
deploy/v2/        本地 Compose、隔离解析镜像、云环境部署脚本
docs/v2/          API、架构、QA/评测、团队交接材料
knowledge_base/   V1 数据与课程资料审查资产
backend/、rag/、frontend/  V1 历史原型及参考代码
```

V1 历史原型的说明见 [V1 README](docs/v1/README_LEGACY.md)。
