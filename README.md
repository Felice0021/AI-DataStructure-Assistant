# AI-DataStructure-Assistant

面向本科《数据结构》课程的 AI 智能助教项目。通过 RAG（Retrieval-Augmented Generation，检索增强生成）实现课程资料问答、习题讲解与代码分析。项目保留 V1 原型，**当前团队协作开发以 V2.0 为主**。

> **项目状态（2026-10-27）**：V2 多用户单轮 RAG 后端集成基线已完成，可启动团队并行开发；**尚未完成 Vue 新前端、多轮聊天、图片问答或生产部署**。V2 代码验收基线：`2549ef4`（2026-10-26 集成验收），组员以最新 GitHub `main` 为准；验收报告：`docs/v2/INTEGRATION_REPORT.md`。
>
> **质量边界**：最近一次全量测试 **479 passed / 0 failed / 0 skipped**；Qwen Embedding、Reranker、Generation 均用少量**合成文本**通过真实 API 冒烟测试，**不代表真实课程问答质量已达标**。36 道评测题仍待人工标注。

## 1. 新成员从这里开始

| 目标 | 文档 |
| --- | --- |
| **环境搭建、API/Worker 启动、完整验收** | [团队开发指南](docs/v2/TEAM_ONBOARDING.md) |
| **Windows 分工、10 天计划、阶段节点、交付与反馈** | [第一轮详细计划](docs/v2/SPRINT_01.md) |
| **前端 Cookie、CSRF、上传、问答和错误状态** | [前端交接手册](docs/v2/FRONTEND_HANDOFF.md) |
| 接口字段、请求/响应结构（实际 FastAPI 导出） | [OpenAPI 3.1](docs/v2/openapi.json) · [API 契约](docs/v2/API_CONTRACT.md) |
| 代码分层与权限边界 | [V2 架构](docs/v2/ARCHITECTURE.md) · [数据库结构](docs/v2/DATABASE_SCHEMA.md) |
| 本次验收的事实与未完成项 | [集成报告](docs/v2/INTEGRATION_REPORT.md) |
| 检索与问答质量标注 | [评测计划](docs/v2/EVALUATION_PLAN.md) |
| 后续模块、依赖与验收要求 | [下一阶段 Backlog](docs/v2/NEXT_PHASE_BACKLOG.md) |

**请先读本 README，再读与你负责的模块对应的交接文档。** 旧版 `frontend/` 是 V1 静态页面，不是 Vue 3 项目；不要把 `/api/v1` 当作 V2 接口。

## 2. 当前功能与边界

| 模块 | V2 进度 |
| --- | --- |
| FastAPI、PostgreSQL 17、pgvector、Alembic | 已完成 |
| 注册/登录、Cookie Session、CSRF、角色授权 | 已完成 |
| 公共知识库和个人私有知识库及跨用户隔离 | 已完成 |
| PDF/DOCX/TXT 安全上传、下载、软删除 | 已完成 |
| 独立 Worker 文本解析、Chunk 切分、任务重试与崩溃恢复 | 已完成 |
| Embedding + `vector(1024)` + 文档代次/哈希校验 | 已完成 |
| BM25、Dense 精确检索、Hybrid RRF、Reranking | 已完成 |
| Context Builder、引用 `[S1]`、单轮 RAG 回答及拒答 | 已完成 |
| 云端用途授权、撤销及元数据审计 | 已完成，**默认不开启云端** |
| V1 课程知识库（1010 条）导入到 V2 | 工具可 dry-run、导入及解析；**尚未完成真实全库索引和课程问答验收** |
| 真实课程数据上的效果评测 | **36 道合成题待人工标注，暂无可发布质量指标** |
| Vue 3 + Vite 前端 | 待开发 |
| 多轮会话及服务端历史记录 | 待开发 |
| 图片题/VLM 多模态问答 | 待开发 |
| 生产部署、用户级费用硬额度与备份恢复 | 待完善 |

**V2 主流程（非流式单轮）：**

```text
认证用户 + 被授权的知识库
  → 上传 PDF/DOCX/TXT
  → 隔离解析 Worker → Chunk
  → Embedding Worker → pgvector
  → BM25 / Dense / Hybrid RRF
  → Reranking → 证据筛选与 [S1] 来源映射
  → Qwen Generator → 引用校验
  → 最终权限、会话、文档代次校验
  → 回答 / 证据不足拒答
```

文件状态：`uploaded → processing → parsed → indexing → ready`。其中 `parsed` **不等于**可检索；当前问答只使用与模型空间、版本一致的有效 `ready` 资料。真实云端处理还需要部署开关、对应知识库与用途的授权以及本次请求显式允许。

模型冒烟测试（合成文本）：Embedding `qwen3.7-text-embedding-flash`（1024 维）、Reranker `qwen3.7-text-rerank`、Generation `qwen3.8-flash`。正式云端使用需单独配置 V2 凭证、核对账户可用性和隐私授权；**不要向任何组员共享负责人的 API Key**。确定性测试 Provider 只验证工程链路，不具备语义质量。

## 3. 本地启动 V2（快速入口）

需要：**Python 3.12、Docker Desktop / Compose**。Node.js 24 供即将开发的 Vue 前端使用。

- **macOS**：使用 Terminal/zsh/bash；Apple Silicon 无需强制 amd64。
- **Windows**：Vue 3 前端、材料审查与文档测试可在 Windows 原生开发；**完整 V2 FastAPI/Worker 后端**建议使用 **WSL2 Ubuntu + Docker Desktop WSL integration**，在 WSL Linux 文件系统中开发。**原生 Windows Python 尚不支持完整后端**，Windows/WSL 真机验收尚待完成。具体安装与分角色建议见 [第一轮计划](docs/v2/SPRINT_01.md)。

```bash
git clone https://github.com/Felice0021/AI-DataStructure-Assistant.git
cd AI-DataStructure-Assistant
python3.12 -m venv ~/.virtualenvs/ai-datastructure-v2
source ~/.virtualenvs/ai-datastructure-v2/bin/activate
python -m pip install -r backend/v2/requirements-dev.txt

# 已有 deploy/v2/.env 时，初始化脚本不会覆盖
python deploy/v2/init_env.py
chmod 600 deploy/v2/.env

# macOS / ARM64
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml up -d db
# x86/WSL 机器：在上一条命令前加 DS_V2_DB_PLATFORM=linux/amd64

python -m alembic -c backend/v2/alembic.ini upgrade head
python -m backend.v2.tools.dev status
```

Linux/WSL 首次启动解析 Worker 前，依照 [团队开发指南](docs/v2/TEAM_ONBOARDING.md) 构建隔离解析镜像，并为 API/Worker 配置**相同的仓库外私有存储目录**。

在**三个独立终端**中激活同一个 V2 Python 环境，分别运行：

```bash
python -m backend.v2.tools.dev api --test-providers
python -m backend.v2.tools.dev parser --test-providers
python -m backend.v2.tools.dev embedding --test-providers
```

- 本地 API：`http://127.0.0.1:8001`；Swagger：`http://127.0.0.1:8001/api/v2/docs`。
- 未来 Vue 开发服务器：`http://127.0.0.1:5173`（**尚未实现**）。浏览器联调统一使用 `127.0.0.1`，不要混用 `localhost`。
- 浏览器请求必须携带 `credentials: 'include'`；写接口需要 `X-CSRF-Token`；上传使用 `FormData`，不可自行设置 multipart `Content-Type`。
- 默认安全配置面向生产，开发环境的 HTTP/Origin 例外由 `--test-providers` 或明确的开发设置提供；**不得降低正式环境安全要求**。

**离线完整验收：**

```bash
# 需要 Docker 解析隔离测试时
DS_V2_RUN_DOCKER_TESTS=1 python -m backend.v2.tools.acceptance
# 评测脚本目前只报告已标注情况，不会自动发起付费调用
python -m backend.v2.evaluation.score
```

测试运行在隔离数据库及临时存储，开发数据库和 Docker 数据卷不得被清空。不要运行 `docker compose down -v`。普通开发不需要真实模型 API Key。

## 4. 后端接口（前缀 /api/v2）

| 领域 | 核心接口 |
| --- | --- |
| 认证 | `GET /auth/csrf`、`POST /auth/register`、`POST /auth/login`、`GET /auth/me`、`POST /auth/logout` |
| 知识库 | `GET/POST /knowledge-bases`、`GET/PATCH/DELETE /knowledge-bases/{id}` |
| 文件 | `POST/GET /knowledge-bases/{kb}/documents`、文件详情/下载/删除 |
| 处理 | `/knowledge-bases/{kb}/documents/{doc}/ingestion` 和 `/embedding` |
| 云端同意 | `/knowledge-bases/{kb}/cloud-consents`（授权、撤销、审计） |
| 检索/证据 | `POST /retrieval/search`、`POST /retrieval/prepare-context` |
| 单轮问答 | `POST /rag/ask` |

以 [openapi.json](docs/v2/openapi.json) 为唯一机器可读字段规范；身份只取服务端 Cookie，不允许前端提交 `user_id` / `role` 冒充身份。私人资源未授权返回 404；管理员不能读取其他学生私人资料。`[S1]` 对应当前响应 `sources[].citation_id`，不能凭客户端拼接的路径获取私人资料。

正常证据不足（HTTP 200）与生成不可用/生成校验失败（503/502）必须分别处理；单轮接口**没有**服务端历史、流式返回和图片题输入。

## 5. 第一轮团队开发（2026-10-27 — 2026-11-05，共 10 天）

**目标：第一次让 V2 Vue 前端连通后端并演示资料来源清楚的单轮课程问答。** 10 月 29 日完成环境/方案检查，11 月 2 日进行中期联调，**11 月 5 日完成第一轮验收**。本轮五位成员均使用 Windows；前端可在 Windows 原生开发，完整 V2 后端建议 WSL2 Ubuntu + Docker Desktop，详见 [Windows 实操与 10 天详细分工](docs/v2/SPRINT_01.md)。以下为启动分工，不代表功能已经完成。**任务详情与进度统一见 [GitHub Sprint 1 Issues](https://github.com/Felice0021/AI-DataStructure-Assistant/issues?q=is%3Aissue+is%3Aopen+%22Sprint+1%22)：[#3 前端](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/3)、[#4 会话后端](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/4)、[#5 公共资料](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/5)、[#6 评测验收](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/6)、[#7 系统集成](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/7)。**

| 成员 | 负责范围 | 第一轮交付 |
| --- | --- | --- |
| 李均乐（负责人） | 系统集成与技术审查 | 演示环境、合成/获授权课程资料联调、审核 PR、统一接口与架构决策 |
| 祝晟译 | 后端：会话与历史 | `conversations/messages` 模型与 API 方案、首版 CRUD 和账户隔离测试；**先审查迁移方案再写 0008**，不破坏单轮 RAG |
| 张圣江 | Vue 3 + Vite 前端 | 登录/注册、知识库列表与选择、基础单轮问答、`[S1]` 引用；优先按已冻结 OpenAPI 联调 |
| 郭星辰 | 公共课程知识库 | 对 V1 1010 条 Chunk 进行来源与异常核查，导入 dry-run，形成首批约 100 条高质量候选清单；不覆盖原库 |
| 常慧思 | 测试、标注与材料 | 36 道待审题中首批约 12 道人工标注，功能验收用例与缺陷记录；不要求承担复杂编码 |

**合并验收标准**：登录可用、选库后能调用单轮 `rag/ask`、引用对应真实资料；会话 API 的所有权边界通过数据库测试；公共数据的来源与标注可追踪。多轮前端、图片题和大规模全库付费向量化不是本轮交付条件。

## 6. Git 协作规则

- 以 `main` 的已验收 V2 代码为基线，**每个人从最新 main 创建自己的 `feature/*` 分支**，提交 Pull Request（PR，合并请求）；不要直接在 main 长期开发或强推。
- 每个 PR 说明修改内容、测试、是否影响 API、数据库迁移、隐私及费用；必要时同步 `docs/v2/openapi.json` / `API_CONTRACT.md`。
- 新增 Alembic revision 必须先与负责人协调；**0001–0007 已发布，不得改写**。禁止多人各自创建冲突的 `0008`。
- 跨模块约定优先采用接口契约；前端独立启动，不改 V1 `frontend/`；后端不复制 V1 全局 RAG 状态。
- 禁止提交 `.env`、密钥、私人上传文件、数据库、日志、缓存或虚拟环境。不得使用其他人的私人 Key 进行测试。
- 生产开放前仍需完成 HTTPS/TLS、数据库角色划分、每日费用硬额度、备份恢复、生产隔离及真实语义质量评测。

## 7. 仓库地图与 V1 历史

```text
backend/v2/       V2 FastAPI、ORM、Worker、RAG 服务与测试
deploy/v2/        V2 Compose、解析隔离镜像、配置模板
docs/v2/          V2 架构、API、验收、前端交接、团队启动
knowledge_base/   V1 课程 JSONL 和校验/迁移资产（请保护）
rag/              V1 RAG 核心代码（只读参考，不是 V2 的运行入口）
backend/          V1 后端以及 backend/v2
frontend/         V1 原有静态 HTML/CSS/JS（不是 Vue 新工程）
tests/            V1 研究、Benchmarks 和历史标注数据
```

V1 的 Query Expansion、多查询检索、旧 `0.58` 阈值及早期前端是**历史原型能力**，不能据此宣称 V2 已实现同样功能。V2 拥有独立的数据表、授权、任务和检索服务。旧 README 全文归档在 [V1 README（历史）](docs/v1/README_LEGACY.md)，论文型研究记录见 [2026-09 研究检查点](docs/RESEARCH_CHECKPOINT_2026-09.md)。

当前优先顺序：**先完成可演示平台与真实课程资料验证，再推进多轮功能整合、多模态以及质量/性能优化。**
