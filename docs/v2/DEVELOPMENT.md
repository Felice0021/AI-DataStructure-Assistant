> 当前集成交付版本：2026-10-26，Alembic **0007_cloud_consents**，Generator **qwen3.8-flash**。当前启动、用途授权与API以 TEAM_ONBOARDING.md、FRONTEND_HANDOFF.md、openapi.json 及本文“最终集成”章节为准。以下旧阶段验收（0006、NOT VERIFIED、云生成硬阻塞）是历史记录，不代表当前状态。

# V2 本地开发

以下命令均在仓库根目录 `AI-DataStructure-Assistant` 执行。
使用独立 Python 3.12 虚拟环境，不在 V1 `.venv` 或系统 Python 安装依赖。

## 1. 环境与依赖

```zsh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python --version
node --version
python -m pip install -r backend/v2/requirements-dev.txt
python -m pip check
```

`requirements.txt` 锁定运行依赖及传递依赖；`requirements-dev.txt` 是含测试工具的完整锁定集合。
Python 3.12 / macOS ARM64 为当前验证平台。仅运行服务时可只安装 `requirements.txt`。
`.in` 记录直接依赖范围；升级时在干净的独立 Python 3.12 环境重新解析、生成锁文件并运行全部测试，
不要直接在 V1 环境执行 `pip freeze`。

## 2. 初始化本地配置并启动数据库

```zsh
python deploy/v2/init_env.py
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml config --quiet
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml up -d --wait
```

初始化脚本创建随机密码和权限为 0600 的 `deploy/v2/.env`；重复运行保留现有文件。
也可以依据 `.env.example` 手动创建，但必须填写新的随机密码。
根目录原有 `.env` 不读取、不改动。不要将 `.env`、Compose 完整展开结果或凭证放进 Git/日志。

Compose 固定项目名 `ds-assistant-v2`，容器通常为 `ds-assistant-v2-db-1`，
独立数据卷名为 `ds-assistant-v2-postgres-data`。宿主机仅监听 `127.0.0.1:5433`。
若端口或同名资源已被其他项目占用，先调查归属，不删除它们。
容器的健康检查使用 `pg_isready`，实际密码认证和 SQL 由迁移/API 验证。

默认参数为数据库/用户 `ds_assistant_v2`、主机 `127.0.0.1`、端口 `5433`。
环境变量前缀为 `DS_V2_`，详见模板。进程环境变量覆盖文件中的同名值。
修改 `.env` 不会修改已有 PostgreSQL 数据卷中的账户密码；不能用删除数据卷的方式解决密码不一致。

## 3. 数据库迁移

```zsh
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini current
python -m alembic -c backend/v2/alembic.ini check
```

当前 head 为 `0006_chunk_embeddings`，既有 0001–0005 保持原样。迁移与应用读取相同 V2 配置。
不要运行 `create_all()` 代替迁移；应用启动不会自动建表。
后续模型变更可用 `revision --autogenerate -m "描述"` 生成草稿，必须审查 SQL 再应用。
重复升级安全；downgrade 和删除数据卷不是常规关闭步骤。

## 4. 启动与停止 API

```zsh
# 仅限本机 HTTP，明确启用开发模式；不改写已有凭证。
export DS_V2_ENVIRONMENT=development
export DS_V2_ALLOW_INSECURE_LOOPBACK=true
export DS_V2_ALLOWED_ORIGINS='["http://127.0.0.1:5173","http://127.0.0.1:8001"]'
python -m backend.v2.main
# 等价方式：
python -m uvicorn backend.v2.main:create_app --factory --host 127.0.0.1 --port 8001 --no-proxy-headers --no-access-log
```

另一个终端验证：

```zsh
curl --fail http://127.0.0.1:8001/api/v2/health
curl --fail http://127.0.0.1:8001/api/v2/health/db
```

API 使用前台进程，按 `Ctrl-C` 正常关闭并释放连接池。
V1 沿用现有环境和 8000 端口；不要为了启动 V2 改动 V1 配置。

## 5. 测试

不依赖数据库的测试：

```zsh
python -m pytest -c backend/v2/pyproject.toml backend/v2/tests -m 'not integration'
```

包括真实 PostgreSQL 的完整测试（先启动上面的数据库）：

```zsh
DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests
```

集成测试仅在显式启用时创建随机的 `ds_v2_test_<UUID>` 数据库，需要本地管理账户的 CREATEDB 权限。
检查空库迁移、索引/外键/约束、pgvector 运算、重复升级保留数据、ORM 更新时间和实际数据库 API。
测试在 finally 中只删除本轮新建的随机测试库，不 truncate 或 downgrade 开发库。
如果进程被强制终止，测试库可能残留，应先确认名称和归属，再手动处理；不要批量清理数据库。
原有 V1/RAG 测试不属于本轮新增测试，不在 V2 环境安装其模型依赖。

## 6. 关闭数据库

```zsh
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml stop
# 需要移除本项目容器/网络时，保留命名数据卷：
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml down
```

不要附加 `-v`，不要执行 Docker prune，也不要删除其他容器、镜像或数据卷。
数据库可使用原命令再次启动，数据保留。磁盘备份和生产部署尚未实现。


## 认证、CSRF 与前端接入

公开认证接口为 `/api/v2/auth/{register,login,me,logout,csrf}`，具体格式见 API_CONTRACT.md。
Vue 每次请求设置 `credentials: 'include'`。先 GET `/auth/csrf`，POST 时把返回值放入
`X-CSRF-Token`，由浏览器自动携带 Cookie 与 Origin。登录和退出改变 Cookie 后必须重新获取 CSRF。
不要把原始会话凭证放入 URL、localStorage、日志或 JSON；会话 Cookie 为 HttpOnly。注册不会自动登录。

默认生产模式、Secure Cookie、空来源白名单，HTTP 认证请求被拒绝，健康接口仍可用。
开发必须显式设置上述三个变量，且 Host 和实际客户端 IP 均为 loopback。
不能在 LAN、公网或容器远程访问场景复用此降级模式。前后端统一使用 127.0.0.1，
不要混用 localhost，否则 SameSite/主机 Cookie 边界不同。Cookie 不按端口隔离，同一主机上不要运行不可信服务。

完整模板见 `deploy/v2/.env.example`。本轮没有改写已有 V2 或根目录 .env。
会话默认 28800 秒，`DS_V2_SESSION_TTL_SECONDS` 可设 60 秒至 7 天。
登录失败默认每邮箱 5 次/900 秒、每 IP 20 次/900 秒；配置项为
`DS_V2_LOGIN_MAX_FAILURES`、`DS_V2_LOGIN_IP_MAX_FAILURES`、`DS_V2_LOGIN_WINDOW_SECONDS`。
计数持久化 PostgreSQL，固定顺序行锁跨进程生效，数据库失败时认证返回安全 503。

## 显式创建首个管理员

在有数据库访问权限的本地交互终端执行：

```zsh
python -m backend.v2.manage create-admin --email '<管理员邮箱>'
```

getpass 两次隐藏读取密码，拒绝非交互输入；没有密码参数、默认密码或自动创建管理员。
邮箱已有账户时拒绝创建，不会把 student 自动提升为 admin。
本轮仅在隔离测试库验证该流程，没有在开发库创建管理员。

## 真实 HTTP 联调

```zsh
python -m backend.v2.tests.http_smoke
```

脚本暂占 8001，如已有服务则拒绝覆盖。使用随机测试数据库和两个 Uvicorn worker，
验证两个独立学生用户及本地创建的管理员；只输出 PASS，不打印账户、密码、Cookie 或 CSRF。
完成后关闭服务并删除该随机库。`/test/student`、`/test/admin` 仅在测试应用中存在。

## 正式 HTTPS 部署与剩余边界

- 设置 `DS_V2_ENVIRONMENT=production`、`DS_V2_ALLOW_INSECURE_LOOPBACK=false`，
  `DS_V2_ALLOWED_ORIGINS` 仅列出真实 HTTPS 前端来源，不含通配符或路径。
- 默认使用 __Host- Cookie、Secure、HttpOnly、SameSite=Lax、Path=/，无 Domain。
  采用同站点部署，不自动放开跨站点第三方 Cookie。
- TLS 代理必须正确传递 scheme/IP，并只信任明确配置的代理地址；直接运行默认禁用 proxy headers。
  不要使用 `--forwarded-allow-ips '*'`。代理必须保留 Origin，不记录凭证头或密码请求体。
- 上线前需配置边缘请求/注册限流、并发预算、TLS、监控、备份、最小权限数据库账户和 secrets 管理。
  当前固定窗口失败限流已跨进程验证，但不是完整抗 DDoS 或分布式风控。
- 尚未实现邮箱验证、密码找回/修改、MFA、全会话撤销及会话/限流表的定时清理。
  CSRF 不防御 XSS；后续前端需输出编码/CSP。角色依赖不代替资源所有权检查。

## 第一阶段交付边界（历史）

已建立独立应用、可复现依赖、数据库 Compose、ORM、初始迁移、健康接口及自动化测试。
下一阶段再实现密码哈希、注册/登录/注销、会话过期/吊销和角色授权。
前端、RAG 集成、个人知识库、多模态、Worker、生产安全和运维均不在本阶段范围。

## 2026-10-26 第一阶段本机验证记录（历史）

- Python 3.12.15；FastAPI 0.162.0；SQLAlchemy 2.0.55；Alembic 1.20.1；psycopg 3.3.6。
- Docker Desktop 4.96.3 / Engine 29.9.2；数据库 linux/arm64，PostgreSQL 17.11 / pgvector 0.8.7。
- 全新数据库升级成功，当前 revision 为 `0001_auth_foundation (head)`。
  `alembic check` 无差异；集成测试插入用户/会话后重复升级两次，记录保持完整。
- 17 项 V2 自动化测试全部通过，无警告；独立测试数据库已删除。
- 真实 Uvicorn 监听 127.0.0.1:8001，两个健康接口 HTTP 200。
  停止 V2 数据库时存活接口保持 200、数据库接口返回脱敏 503；恢复后数据库接口返回 200。
- 原 V1 `.venv` Python 3.14.3 / FastAPI 0.141.1，应用导入成功。
  未启动 V1 lifespan、未执行完整 RAG 回归或调用外部模型。
- 本轮开始时记录的 116 个原有文件（包括未提交文件、根 `.env` 和 V1 `pyvenv.cfg`）内容哈希保持一致。
- 交付时 V2 开发数据库保留运行及持久化卷，验证用 API 进程已停止；按本文命令可重新启动。

## 第一阶段新增文件清单（历史）

全部变更仅新增于下列 V2 路径，共 36 个可提交文件；原有公共配置未修改。
另有本机生成的 `deploy/v2/.env`（Git 忽略，0600 权限，不列入可提交文件）。

```text
backend/v2/
  .gitignore
  __init__.py
  main.py
  alembic.ini
  pyproject.toml
  requirements.in
  requirements.txt
  requirements-dev.in
  requirements-dev.txt
  core/__init__.py
  core/config.py
  core/logging.py
  db/__init__.py
  db/base.py
  db/session.py
  dependencies/__init__.py
  dependencies/database.py
  models/__init__.py
  models/auth.py
  schemas/__init__.py
  schemas/health.py
  routers/__init__.py
  routers/health.py
  services/__init__.py
  migrations/env.py
  migrations/script.py.mako
  migrations/versions/0001_auth_foundation.py
  tests/test_database.py
  tests/test_health.py
deploy/v2/
  .env.example
  compose.yaml
  init_env.py
docs/v2/
  ARCHITECTURE.md
  DATABASE_SCHEMA.md
  API_CONTRACT.md
  DEVELOPMENT.md
```

## 第二阶段认证交付与实际验证（2026-10-26）

- 全部 V2 pytest：59 passed，无警告，其中原第一阶段 17 项继续通过。
- 原 API 路径断言增加认证路由，原 schema 断言增加限流表；未移除原有断言目标。
- 新增密码/配置/CSRF/CORS/异常安全测试，以及注册、登录、角色、会话、双进程限流测试。
- 两个真实 Uvicorn worker 的 HTTP 联调通过：两个独立学生账户全流程、本地管理员权限、CSRF 拒绝、
  会话隔离、退出后旧凭证失效及重复退出。测试路由不发布到正式应用。
- 用临时非监听端口模拟数据库连接失败，实际 HTTP 验证认证接口安全 503、数据库健康 503、存活 200。
- 当前迁移 0002_login_limits (head)，alembic check 无差异，重复 upgrade head 成功。
  从含既有用户/会话的 0001 升级测试通过；0001 文件内容未改。
- 所有自动化及 HTTP 测试使用随机测试数据库，均已清理。开发库既有用户/会话内容指纹不变，
  无测试账户、会话或限流数据写入。数据库容器保留健康运行，临时 API 已关闭。
- V1 原 .venv 应用导入成功；没有执行外部模型调用或完整 RAG 回归。
- 根 .env、V2 本地 .env、V1 代码/知识库/评测数据和旧虚拟环境配置均保持原样；未执行 Git 提交。
- 安全基线实现已测试；实际生产 TLS/代理部署、边缘流量控制、邮箱验证、MFA、密码找回和定时清理未实现。

### 第二阶段文件清单

只在 V2 范围修改 13 个既有文件、新增 13 个文件。源码备份位于本机 /tmp，未包含凭证文件。

新增：

```text
backend/v2/core/errors.py
backend/v2/core/security.py
backend/v2/dependencies/auth.py
backend/v2/manage.py
backend/v2/migrations/versions/0002_login_limits.py
backend/v2/models/login_limit.py
backend/v2/routers/auth.py
backend/v2/schemas/auth.py
backend/v2/services/auth_service.py
backend/v2/tests/http_smoke.py
backend/v2/tests/support.py
backend/v2/tests/test_auth.py
backend/v2/tests/test_security.py
```

修改：

```text
backend/v2/core/config.py
backend/v2/main.py
backend/v2/models/__init__.py
backend/v2/requirements-dev.txt
backend/v2/requirements.in
backend/v2/requirements.txt
backend/v2/tests/test_database.py
backend/v2/tests/test_health.py
deploy/v2/.env.example
docs/v2/API_CONTRACT.md
docs/v2/ARCHITECTURE.md
docs/v2/DATABASE_SCHEMA.md
docs/v2/DEVELOPMENT.md
```


## 第三阶段 3A：知识库开发与验证

本阶段仅增加知识库元数据、CRUD、软删除和所有权检查，不增加依赖。
沿用本文件的 V2 虚拟环境、开发 HTTPS/loopback 区分、Cookie/CSRF、数据库启动方式。
已有 .env、V1 .venv 和初始两份迁移均不修改。

部署新 schema：

    python -m alembic -c backend/v2/alembic.ini upgrade head
    python -m alembic -c backend/v2/alembic.ini current
    python -m alembic -c backend/v2/alembic.ini check

当前 head 为 0003_knowledge_bases。不要通过删除数据卷或重建数据库应用迁移。

完整测试：

    DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests

知识库真实 HTTP 联调：

    python -m backend.v2.tests.knowledge_base_http_smoke

脚本暂占 127.0.0.1:8001，如被已有服务占用则拒绝覆盖。
复用第二阶段隔离数据库、HTTP Cookie 客户端及两个 Uvicorn worker 启停工具。
所有学生、管理员、知识库均写入随机测试库，不写开发数据库；脚本不输出账户或凭证。
结束后关闭临时 API 并删除本轮测试库。已有数据库容器和数据卷保留。

### 3A 访问与事务约定

- 普通创建只接收 name/description，owner 从会话确定，private 不能被客户端升级为 public。
- 管理员专用公共创建路径为 /api/v2/admin/knowledge-bases；公开角色不代表可读其他学生私人数据。
- 调用服务 get_readable、get_writable、require_public_manager，禁止只按 UUID 直接查询返回。
- CRUD 服务负责提交事务，失败时回滚；访问检查助手不提交，便于未来文件服务组合事务。
- 所有业务访问排除 deleted_at 墓碑。软删除不是文件/片段的物理清理。
- 后续 Worker 必须重新检查资源状态/权限及索引版本，不得仅信任排队时的知识库 UUID。

### 3A 当前边界与风险

软删除记录保留在库中，尚无恢复、归档/物理 purge 或审计日志功能；用户物理删除受外键 RESTRICT 约束。
公共知识库没有协作成员管理；私人资料只限所有者，管理员没有隐式读取权限。
数据库未启用 RLS，隔离边界为认证依赖和服务层 SQL 作用域，未来代码必须继续复用。
名称使用 NFKC/空白规范化和数据库 lower 键；不是对所有 Unicode 视觉近似字符的消歧。
列表分页不是跨请求快照；未来有大规模资源时可再设计游标分页。
当前没有 documents/chunks、文件上传、文档解析、Embedding、内容索引、RAG 改动或 Vue 前端。

### 3A 实际验证记录（2026-10-26）

- 完整 V2 pytest：126 passed，无警告。原 59 项全部继续通过，新增 67 项，其中 62 项使用隔离 PostgreSQL。
- 原 OpenAPI 路径/数据库表断言增加新接口/表，原有检查目标保留。
- 真正两个 Uvicorn worker HTTP 联调通过：两个独立学生注册登录，所有者 CRUD，
  跨用户 GET/PATCH/DELETE 全部 404，列表无他人私人资料。
- 管理员公共创建/修改/删除成功；管理员对其他学生私人资源同样 404。
- CSRF、不可写字段伪造、重名、软删除后过滤及重建均通过。并发同名创建仅一条成功，另一条 409。
- 真实数据库连接失败时知识库 API 返回脱敏 503，进程健康仍为 200。
- Alembic 当前 0003_knowledge_bases (head)，upgrade head 成功，check 无差异；
  隔离库从 0002 升级与重复升级保留原有用户及知识库记录。
- 旧迁移 0001、0002 内容不变。开发库原三张认证表的数据指纹不变，知识库表没有测试记录。
- 随机测试数据库已全部移除，临时 API 已关闭；开发数据库与原有容器保持运行，未删除数据卷。
- V1 原虚拟环境应用导入成功；没有调用外部模型或运行完整 RAG 回归。
- 未改根/V2 本地 .env、V1 .venv、V1/RAG/知识库/评测数据，未执行 Git 提交或推送。

### 3A 新增及修改文件清单

新增 8 个文件：

```text
backend/v2/migrations/versions/0003_knowledge_bases.py
backend/v2/models/knowledge_base.py
backend/v2/routers/knowledge_bases.py
backend/v2/schemas/knowledge_base.py
backend/v2/services/knowledge_base_service.py
backend/v2/tests/knowledge_base_http_smoke.py
backend/v2/tests/test_knowledge_base_security.py
backend/v2/tests/test_knowledge_bases.py
```

修改 9 个 V2 文件（包括本文件）：

```text
backend/v2/main.py
backend/v2/models/__init__.py
backend/v2/tests/http_smoke.py
backend/v2/tests/test_database.py
backend/v2/tests/test_health.py
docs/v2/API_CONTRACT.md
docs/v2/ARCHITECTURE.md
docs/v2/DATABASE_SCHEMA.md
docs/v2/DEVELOPMENT.md
```

## 3B-1：文件管理开发

沿用现有 V2 Python 3.12 环境；新增官方 python-multipart==0.0.32，两个锁定依赖文件均已更新。

```zsh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m pip install -r backend/v2/requirements-dev.txt
python -m pip check
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests -q
python -m backend.v2.tests.documents_http_smoke
```

API 启停仍按第 4 节，端口 8001。HTTP 脚本只临时使用该端口，拒绝覆盖已有监听服务；
创建随机数据库和临时对象目录，用两个 worker 运行，finally 关闭服务并清理本轮资源。
测试不向默认真实文件目录写入，不将文件写到仓库/知识库，也不重建开发数据库。

### 文件配置（环境变量，不改根 .env）

|变量|默认值|
|---|---|
|DS_V2_FILE_STORAGE_ROOT|~/Library/Application Support/AI-DataStructure-Assistant/v2/files（代码使用用户 home 绝对路径）|
|DS_V2_UPLOAD_MAX_BYTES|20971520（20 MiB，配置范围 1 byte–100 MiB）|
|DS_V2_DOCUMENTS_PER_KB|100|
|DS_V2_STORAGE_BYTES_PER_KB|1073741824（1 GiB）|
|DS_V2_STORAGE_TOTAL_BYTES|10737418240（10 GiB，当前数据库元数据覆盖的对象）|
|DS_V2_UPLOAD_TIMEOUT_SECONDS|120（multipart 接收/解析期限）|

根路径须为仓库外绝对路径，不得指向公开静态目录、其他项目或已有用户文件。
仅当第一次文件操作时创建私有目录（新目录 0700、对象 0600）；已有根目录权限过宽会返回脱敏 503，
不会自动 chmod 他人目录。目录任一层为符号链接会被拒绝；macOS 测试临时目录使用 resolve 后路径。
不能让多个独立数据库共用同一对象根；配额锁与计量以部署数据库为边界。

### 生命周期、恢复与后续 Worker

接收前认证及 CSRF → 父知识库行锁/配额与跨进程上传槽 → 有界 multipart 临时 spool →
64 KiB 流式写入私有临时对象、大小/摘要/格式验证 → fsync/原子 rename → 元数据提交。
失败回滚元数据并补偿删除当前对象；补偿清理失败只记录固定消息，不能暴露磁盘路径。

DELETE 先提交 deleted_at，再 unlink；清理后标记 storage_deleted_at。清理失败保持墓碑，重复相同 DELETE
可重试。对象已缺失但清理标记未写入也可重试。不要回滚墓碑来恢复可见性。
父知识库软删除不物理删文件，仍占用配额；当前没有 parent purge、恢复、自动清理命令或后台任务。
后续受控清理必须先核对文档/父知识库墓碑及文件所属，禁止遍历根目录后无差别删除。

Worker 未来应基于受控任务身份调用 document_service.get_document/open_download 的授权边界，
重新检查父知识库有效性、文档墓碑和索引版本；不能直接用 storage_key 或数据库管理员权限跳过授权。
当前 uploaded 仅表示原文件持久化，不产生文本、chunks、embedding、Worker 任务或 RAG 数据。

### 生产限制

- 当前容量配额覆盖数据库已登记对象，不能覆盖进程崩溃/提交结果不确定/补偿失败留下的孤儿文件，
  也不统计 multipart 操作系统临时 spool、数据库/WAL 和文件系统额外开销；生产需磁盘/临时目录配额与监控。
- 文件系统与 PostgreSQL 无分布式原子提交；进程在 rename 与 commit 之间崩溃可能留孤儿。
  尚无自动对账/清理，需未来受控恢复流程。不能直接批量删除未知对象。
- 跨进程单上传槽限制吞吐；等待知识库锁仍占用连接，慢客户端解析最长 120 秒。
  ASGI/代理的连接数、请求体/空闲超时与注册/请求速率限制仍须上线前配置。
- 格式验证不是反病毒、PDF JavaScript 检测或完整 Office 文档语义验证；只允许安全附件下载，暂不内联预览。
- 未做用户总文件数/知识库创建数、墓碑元数据保留期与下载带宽限制；不能宣称已解决所有资源耗尽风险。
- 生产还需 TLS、最小权限服务账户、存储/数据库一致备份和恢复演练。默认目录是本机开发存储，不是高可用对象存储。

依赖和解析边界参考：[Starlette request.form](https://starlette.dev/requests/)、
[python-multipart 官方发布](https://pypi.org/project/python-multipart/)。

### 3B-1 本机实际验证（2026-10-26）

- Python 3.12.15 独立 V2 环境，新增 python-multipart==0.0.32；pip check 无依赖冲突。
- 完整 pytest：227 passed（原 128 项继续通过，新增 99 项），无警告。
- 真实两个 Uvicorn worker、两个独立学生及本地管理员：PDF/DOCX/TXT multipart 上传、SHA-256、
  下载原字节一致、附件响应、删除后 404、跨账户详情/列表/下载/删除 404、公共文件权限及 CSRF 均通过。
- 数据库实际执行 upgrade head，当前 0004_documents；重复 upgrade 与 Alembic check 通过，无新增操作。
  0001–0003 哈希不变，documents 两个 RESTRICT 外键及全部索引已检查。
- 回归覆盖空文件/格式/非法路径/超限/无 Content-Length、ZIP 元数据损坏/可疑结构、符号链接、
  并发配额、父知识库删除锁竞争、数据库提交失败补偿、原子发布失败、清理失败重试、解析接收超时。
- 所有文件测试使用隔离临时目录，所有集成测试使用随机测试库；测试库剩余 0，临时 8001 API 已停止。
- 开发数据库原四张业务表内容指纹不变，新增 documents 为 0 行；保留数据库容器与数据卷。
- 核对 175 个原有文件，只有下列 12 个预期 V2 文件修改；根/V2 .env、V1 .venv 配置、
  V1/RAG/知识库/评测资产及旧迁移保持原样。真实凭证/私钥模式扫描未发现泄露。
- main / 0276fad 保持不变；本轮无暂存、commit、push、merge 或分支切换。

### 3B-1 文件清单

新增 11 个文件：

```text
backend/v2/migrations/versions/0004_documents.py
backend/v2/models/document.py
backend/v2/routers/documents.py
backend/v2/schemas/document.py
backend/v2/services/document_service.py
backend/v2/services/file_storage.py
backend/v2/services/file_validation.py
backend/v2/tests/document_samples.py
backend/v2/tests/documents_http_smoke.py
backend/v2/tests/test_document_security.py
backend/v2/tests/test_documents.py
```

修改 12 个 V2 文件：

```text
backend/v2/core/config.py
backend/v2/main.py
backend/v2/models/__init__.py
backend/v2/requirements-dev.txt
backend/v2/requirements.in
backend/v2/requirements.txt
backend/v2/tests/test_database.py
backend/v2/tests/test_health.py
docs/v2/API_CONTRACT.md
docs/v2/ARCHITECTURE.md
docs/v2/DATABASE_SCHEMA.md
docs/v2/DEVELOPMENT.md
```

原测试仅扩展 OpenAPI 路径和 schema 表集合断言，未移除原有检查目标。

## 3B-2A：解析 Worker 开发与运行

仍仅使用独立 V2 环境；新增官方 PyPI 依赖 pypdf==6.21.2、python-docx==1.2.0、psutil==7.2.2，
传递依赖 lxml==6.1.3（Python 3.12/macOS ARM64 实际安装），运行和开发锁文件均记录精确版本。
已检查 python-docx XML parser 的 resolve_entities=False；本模块另在解析前拒绝 XML DTD/ENTITY，沙箱再限制网络/文件。
来源：[pypdf](https://pypi.org/project/pypdf/)、[python-docx](https://pypi.org/project/python-docx/)、
[pypdf 提取边界](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)。没有引入 OCR 或外部转换程序。

```zsh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m pip install -r backend/v2/requirements-dev.txt
python -m pip check
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
# 终端一按前文配置启动 API；终端二使用相同 V2 数据库/存储配置运行：
python -m backend.v2.worker
# 单次对账并最多领取一个任务后退出（不保证清空队列）：
python -m backend.v2.worker --once
```

Worker 默认前台运行，Ctrl-C 或 SIGTERM 安全停止；请只终止自己启动的进程，不使用 pkill 批量终止。
停止中的子进程被终止并等待回收，有效任务回 queued；如果数据库当时不可用，租约仍保证后续可恢复。
SIGKILL 无法执行 finally，依靠租约到期重新领取；子进程自身 alarm 限制孤儿存活。
API 关闭不自动关闭独立 Worker；开发时分别停止。不要为了恢复队列删除数据库或批量清空任务表。

### 解析与 Chunk 配置

均为 DS_V2_ 环境变量（不要求改写现有本地 .env）：

|变量后缀|默认值/范围|
|---|---|
|PARSE_MAX_PAGES|300，1–2000；仅 PDF 能提供可靠实际页数|
|PARSE_MAX_TEXT_CHARS|2000000，1–10000000|
|PARSE_TIMEOUT_SECONDS|30，1–300；独立子进程墙钟预算|
|PARSE_MEMORY_MB|256，64–2048；父进程 RSS 采样看门狗|
|CHUNK_SIZE|1200，32–8000；字符数，不是 token|
|CHUNK_OVERLAP|150，必须 >=0 且小于 CHUNK_SIZE|
|PARSE_MAX_CHUNKS|2000，1–10000|
|INGESTION_LEASE_SECONDS|90，20–1800；必须 >= 解析时限 + 15 秒|
|INGESTION_MAX_ATTEMPTS|3，1–10；每代次最大领取次数|
|INGESTION_RETRY_SECONDS|5，1–3600；首次重试延后，后续指数退避|
|WORKER_POLL_SECONDS|1，0.1–60|

修改时所有 API/Worker 使用相同配置；已创建任务的 max_attempts 是当时快照，显式重试会采用新配置。
不要把长解析时间设为大于租约；无心跳长任务会丢弃过期结果。增加文件/文本/Chunk 上限必须重新评估 RAM/数据库负载。

### 独立真实验证

```zsh
DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests -q
python -m backend.v2.tests.ingestion_http_smoke
```

HTTP 脚本只使用随机测试数据库和临时文件目录，启动两个 API worker 和独立 ingestion Worker。
真实 SIGKILL 仅作用于本轮 PID，等待真实 20 秒租约过期后由两个 Worker 恢复，不篡改租约时间。
再核对 PDF/DOCX/TXT parsed、真实 DB Chunk 内容/顺序/hash/页码、两个学生的任务/Chunk 隔离及 CSRF。
测试只输出 PASS，不输出文档正文、账户密码、Cookie 或数据库 URL。

### 已知边界

- 当前强制沙箱运行路径仅支持已验证的 macOS sandbox-exec；其他平台或不可用时失败关闭，不自动降级。
  Apple 沙箱命令存在长期兼容风险；Linux/生产容器隔离尚未实现。系统运行库路径白名单面向当前 Homebrew 环境。
- 当前 macOS 的 RLIMIT_DATA/AS 不可可靠使用，RSS 通过 50 ms 采样杀进程，有瞬时超限窗口，
  不能宣称内核级内存硬上限。每个 Worker 各自占用解析预算，生产还需限制 Worker 总数并设置 OS/容器内存与 CPU 配额。
- 默认最长 30 秒和 CPU/alarm/输出文件限额经过真实测试；格式检查不是反病毒，原始附件仍应视为不可信。
- PDF 不做 OCR/复杂版面恢复；DOCX 无渲染页码、文本框/页眉页脚/嵌套表格和复杂公式可能不完整。
  列表和公式尽力保留，长代码/公式超过字符上限仍会拆开；Unicode 按 code point，不保证 grapheme 完整。
- 文本/Chunk 存于 PostgreSQL，日志不存全文。当前无解析文本总容量配额、任务历史审计或自动墓碑清理。
- 0004 文件 rename 到数据库提交之间的孤儿对象窗口仍需未来受控存储对账；本轮对账仅修复已有文档缺任务，绝不扫描删除未知文件。
- 下一阶段向量化应绑定 document_id + generation + chunk_index/content_hash，在提交时再次复用当前父/文档授权和墓碑检查；
  只有同一代所有向量索引成功才可写 ready。不得直接用 parsed 当作可检索完成状态。

### 3B-2A 本机交付验证（2026-10-26）

- 完整 V2 pytest：279 passed，原 227 项继续通过，新增 52 项；无警告。
- 沙箱实测必须返回 EPERM/EACCES（不能用未监听端口的连接失败冒充网络隔离）：
  合成私有 canary 内容读取/改写、网络连接、外部进程启动均拒绝，允许指定输入描述符读取。
  实际超时和 RSS 超限进程被终止并回收；PDF/DOCX/TXT 子进程解析通过。
- 两套 Worker 领取/发布、租约 token fencing、旧代次隔离、取消、重试退避/上限、断库回滚、
  任务插入失败的上传补偿、0004 旧文件对账、页/文本/Chunk/时间上限及 XML ENTITY 拒绝均通过。
- 真实 HTTP + 两个独立 Worker：三类文件全部 parsed；真实数据库 Chunk 的内容、顺序、hash、PDF 页码核对通过。
- 真实 SIGKILL 终止本轮 Worker，等待实际 20 秒租约到期恢复；最终只有一份有效 Chunk，attempts=2。
  两个学生的私人任务/Chunk 读取与重试隔离通过，缺失 CSRF 拒绝。
- 开发库 upgrade head、重复 upgrade、current、check 通过，head=0005_document_ingestion，schema 无差异。
  数据库 PostgreSQL 17.11 / pgvector 0.8.7；原五张业务表按旧列的内容指纹不变，新 jobs/chunks 均无测试记录。
- 隔离测试库剩余 0，临时 API/Worker/parser 均已停止；测试对象、解析结果目录已清理。
  SIGKILL 联调将 TMPDIR 指向本轮专用临时目录，避免中断时留下未归属的结果。
- 一般生产 SIGKILL 仍可能留下私有解析临时结果；应为 Worker 配置部署专属 TMPDIR、磁盘预算及受控清理策略，
  不得批量扫描删除系统临时目录。任务恢复本身不依赖旧结果文件，也不会把孤儿结果直接提交数据库。
- 核对 186 个原有文件：V1、既有未提交评测/知识库、根/V2 .env、V1 .venv 配置和 0001–0004 均保持原样；
  仅对下列必要 V2 文件扩展，原 3B-1 代码未清理或替换为另一套实现。
- 真实凭证与私钥/token 模式检查通过；没有上传文件、临时结果或真实密码进入 Git。
  分支 main、HEAD 0276fad、暂存区为空；未 commit/push/merge/rebase。

### 本轮文件清单（相对于 3B-1 工作区）

新增 14 个文件：

```text
backend/v2/migrations/versions/0005_document_ingestion.py
backend/v2/models/ingestion.py
backend/v2/parser_child.py
backend/v2/routers/ingestion.py
backend/v2/schemas/ingestion.py
backend/v2/services/chunking.py
backend/v2/services/ingestion_service.py
backend/v2/services/parser_runner.py
backend/v2/services/text_extraction.py
backend/v2/tests/ingestion_http_smoke.py
backend/v2/tests/ingestion_samples.py
backend/v2/tests/test_ingestion.py
backend/v2/tests/test_parsing.py
backend/v2/worker.py
```

修改 15 个文件：

```text
backend/v2/models/document.py
backend/v2/schemas/document.py
backend/v2/services/document_service.py
backend/v2/core/config.py
backend/v2/main.py
backend/v2/models/__init__.py
backend/v2/requirements-dev.txt
backend/v2/requirements.in
backend/v2/requirements.txt
backend/v2/tests/test_database.py
backend/v2/tests/test_health.py
docs/v2/API_CONTRACT.md
docs/v2/ARCHITECTURE.md
docs/v2/DATABASE_SCHEMA.md
docs/v2/DEVELOPMENT.md
```

本轮到此停止；不实现 Embedding、向量索引、混合检索、问答、OCR 或 Vue 前端。

## 3B-2B：Embedding 与精确检索

运行/开发依赖增加 pgvector==0.5.0，并将已有测试环境 httpx2==2.16.0/httpcore2==2.16.0/truststore==0.10.5
纳入运行锁；未安装 V1 RAG、DashScope 全局 SDK 或模型权重。pip check/真实 PostgreSQL 和客户端测试验证兼容性。

```zsh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m pip install -r backend/v2/requirements-dev.txt
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
python -m backend.v2.worker             # 保持现有解析 Worker
python -m backend.v2.embedding_worker   # 在另一终端运行独立索引 Worker，默认关闭即退出
# 或单次最多处理一个索引任务：
python -m backend.v2.embedding_worker --once
DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests -q
python -m backend.v2.tests.embedding_http_smoke
```

两个 Worker 均 Ctrl-C/SIGTERM 安全停止，仅终止自己启动的 PID。远程请求受绝对超时约束，停止信号在下一请求预占前生效；
强制中断依靠租约恢复，不清空任务/向量/开发数据库。测试脚本使用专属 TMPDIR、临时存储和随机测试库，并终止本轮 API/Worker。

### 默认配置与成本边界

所有变量前缀 DS_V2_，公开模板位于 deploy/v2/.env.example；现有本地 .env 不修改，根 .env 不读取，不能自动借用 V1 Key。

|配置后缀|默认值|
|---|---|
|EMBEDDING_PROVIDER|disabled（另有 dashscope、仅开发显式启用的 deterministic）|
|EMBEDDING_CLOUD_ENABLED|false|
|EMBEDDING_API_KEY|无，使用独立 V2 凭证/安全注入|
|EMBEDDING_MODEL / MODEL_REVISION|qwen3.7-text-embedding-flash / unverified；云端须显式填写发布 revision|
|EMBEDDING_DIMENSION|1024；其他维度必须新增 schema 迁移|
|EMBEDDING_BATCH_SIZE|10，上限10|
|EMBEDDING_MAX_INPUT_CHARS / BYTES|2000 / 8192，不静默截断|
|EMBEDDING_TIMEOUT_SECONDS / REQUEST_RETRIES / BACKOFF_SECONDS|15 / 2 / 1；指数退避，单批最多3次可能请求|
|EMBEDDING_CONCURRENCY|1；PostgreSQL 会话 advisory slots 跨进程限制，最多8|
|EMBEDDING_MAX_CHUNKS / MAX_API_CALLS|500 / 150；每文档索引代次|
|EMBEDDING_JOB_TIMEOUT_SECONDS / LEASE_SECONDS|180 / 90；租约须覆盖单次超时+最大退避+15秒|
|EMBEDDING_MAX_ATTEMPTS / QUEUE_CAPACITY|3 / 1000|

官方文档核对：flash 支持默认1024维，最多20条、每条128000 tokens；本实现批次10且 UTF-8输入字节最多8192，采用更保守预算，
不是精确 tokenizer 计数。document 与 query 使用相应 text_type。严格恢复 index/text_index 顺序，不接受缺失/重复/矛盾序号。
来源：[阿里云同步 Embedding API](https://help.aliyun.com/en/model-studio/text-embedding-synchronous-api)、
[模型概览](https://www.alibabacloud.com/help/en/model-studio/embedding)、[pgvector](https://github.com/pgvector/pgvector)。
文档支持不等于账号/API实际验证；工作空间或地域可能要求独立官方端点，配置只允许官方 HTTPS 域名，无重定向/环境代理。

测试 Provider 必须 environment=development + EMBEDDING_ALLOW_TEST_PROVIDER=true + provider=deterministic，
不用于生产、不评测语义质量、不与真实模型空间混用；不是云端不可用时的自动回退。

### 云端与本轮真实 API 状态

本轮未配置可用的独立 V2 Embedding Key，云端没有启用；未读取根 .env，未调用付费 API，未发送任何私人文档。
因此云端真实可用性、真实响应1024维及语义检索质量均为“未验证”，不能标记 PASS。
已有适配器的协议/顺序/异常/超时测试使用可控传输，不冒充真实云端测试。
正式启用后先针对合成文本完成双 text_type 探测，再由用户对每份当前代次文档显式 POST allow_cloud=true；不批量替用户同意。
并发首次探测可能重复，仍计入各任务预算。模型别名的静默权重变化无法仅凭响应维度检测，需供应商版本确认和显式 revision 更新。

### 未解决的生产风险及后续接入

- 缓存减少重试成本，但 API 成功响应后、缓存提交前崩溃/网络结果不明仍可能重复计费；预占计数/期限/最大尝试是请求数预算，不是货币硬封顶。
- 显式人工重试可开新预算；尚无每用户/每日金额配额、查询调用速率限制、账单对账和前端同意管理，生产必须补齐。
- 内部云查询每次仅有限请求重试和全局槽限制，不公开 HTTP 搜索接口，调用方仍须授权并明确同意发送查询文本。
- 空间迁移前停止旧 Worker、统一配置并递增模型 revision；不同配置同时运行可能反复变更索引目标并浪费成本，但不会跨空间混算。
- 部分缓存、旧空间、墓碑尚无自动容量回收；任务队列和每文档预算不能替代数据库/WAL 磁盘配额。
- 精确全量排序适合当前基础验证，未评测大规模延迟；HNSW/IVFFlat、BM25、重排及召回阈值均未实现。
- 后续 Hybrid RAG 应通过内部授权 exact_search/embed_query 接入，保留 space/generation/hash 和来源，所有其他召回分支使用同样 KB/文档墓碑过滤。
  不得把向量 ready 当作回答正确性保证，不能直接搬用 V1 距离阈值。


### 3B-2B 本轮实际验收（2026-10-26）

- 完整 V2 pytest：330 passed（原有 279 项，加本轮 51 项）。
- 开发数据库 `alembic upgrade head`、重复升级及 `alembic check` 通过，当前 `0006_chunk_embeddings`；物理列为 `vector(1024)`。原有七张业务表的数据指纹未变化，新向量相关表无测试数据残留。
- 随机隔离数据库和私有临时目录中，真实 HTTP 上传 TXT/PDF/DOCX，独立解析及向量 Worker 将文档推进到 parsed/indexing/ready；验证数据库 Chunk、1024 维向量、精确余弦距离及来源页码。
- 强制终止已提交部分缓存的向量 Worker，真实等待租约到期，再启动两个 Worker；任务恢复并复用已完成批次，最终只有一次有效发布。
- 两个独立学生及管理员完成真实会话授权验证：私人查询隔离、公共知识库可读、管理员无私人资料豁免，越权 HTTP 请求统一 404，缺失 CSRF 写请求 403。
- 自动化和上述链路仅使用明确启用的确定性测试 Provider；这不证明云端模型语义质量。V2 独立 Key 未配置，云端关闭，真实云 API 可用性和返回维度未验证。
- `pip check`、差异空白检查及 V2 凭证扫描通过。临时数据库、文件目录、API 与 Worker 进程已清理。开发数据库及数据卷保留。
- main/0276fad 未改变，暂存区为空；199 个原有受保护文件及历史 0001–0005 迁移保持原样。根目录 .env 未读取，元数据保持不变；未修改 V1、未提交或推送。

本轮文件清单（相对于本轮开始时的工作区；此前 3B-1/3B-2A 未提交内容保留）：

**新增（12）**

- `backend/v2/embedding_worker.py`
- `backend/v2/migrations/versions/0006_chunk_embeddings.py`
- `backend/v2/models/embedding.py`
- `backend/v2/routers/embedding.py`
- `backend/v2/schemas/embedding.py`
- `backend/v2/services/embedding_provider.py`
- `backend/v2/services/embedding_service.py`
- `backend/v2/services/task_leases.py`
- `backend/v2/services/vector_search.py`
- `backend/v2/tests/embedding_http_smoke.py`
- `backend/v2/tests/test_embedding_provider.py`
- `backend/v2/tests/test_embeddings.py`

**修改（17）**

- `backend/v2/models/document.py`
- `backend/v2/models/ingestion.py`
- `backend/v2/schemas/document.py`
- `backend/v2/services/ingestion_service.py`
- `backend/v2/core/config.py`
- `backend/v2/main.py`
- `backend/v2/models/__init__.py`
- `backend/v2/requirements-dev.txt`
- `backend/v2/requirements.in`
- `backend/v2/requirements.txt`
- `backend/v2/tests/test_database.py`
- `backend/v2/tests/test_health.py`
- `deploy/v2/.env.example`
- `docs/v2/API_CONTRACT.md`
- `docs/v2/ARCHITECTURE.md`
- `docs/v2/DATABASE_SCHEMA.md`
- `docs/v2/DEVELOPMENT.md`


## 3C-1：Hybrid 检索开发

V2 新增 jieba==0.42.1，已在独立 Python 3.12 环境安装；依赖锁同步 runtime/dev，V1 虚拟环境保持不变。
分词实现参考 [jieba 官方项目](https://github.com/fxsjy/jieba)，算法参考 V1 BM25/RRF，但不导入 V1，不初始化全局语料。
无需新迁移；沿用 0006。API 启动方式不变，独立 Worker 仍负责将文件推进 ready。

```bash
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m pip install -r backend/v2/requirements-dev.txt
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
DS_V2_RUN_DB_TESTS=1 python -m pytest backend/v2/tests -q
python -m backend.v2.tests.retrieval_http_smoke
python -m backend.v2.main
```

HTTP 冒烟测试会拒绝占用已有 8001 服务，只创建随机隔离数据库和临时文件目录，运行双进程 API 与独立解析/索引 Worker；
只使用合成文本和显式 development deterministic Provider，不向云端发请求，退出清理本轮资源。
日常配置写到独立 V2 环境变量或 deploy/v2/.env，不读取根 .env，也不复制 V1 Key。
默认无已发布向量时 bm25 返回空；默认 dense/hybrid 对非空有效查询返回 dense_unavailable，不自动启用测试 Provider。

### 检索配置（DS_V2_ 前缀）

|后缀|默认值|边界|
|---|---|---|
|RETRIEVAL_CANDIDATE_K|20|每路 1–100；实际取 max(candidate_k,top_k)|
|RETRIEVAL_TOP_K|20|部署返回上限 1–100，请求默认5|
|RETRIEVAL_RRF_K|60|1–1000|
|RETRIEVAL_DENSE_WEIGHT / RETRIEVAL_BM25_WEIGHT|1 / 1|大于0且不超过10|
|RETRIEVAL_BM25_K1 / RETRIEVAL_BM25_B|1.5 / 0.75|k1>0且≤10，b在0–1|
|RETRIEVAL_MAX_QUERY_CHARS|512|1–2000|
|RETRIEVAL_MAX_CORPUS_CHUNKS|2000|1–10000，超过则413|
|RETRIEVAL_MAX_CORPUS_BYTES|4194304|UTF-8 原文总量，最高32MiB|
|RETRIEVAL_MAX_CORPUS_TOKENS|200000|分词数最高1000000|
|RETRIEVAL_CONCURRENCY|2|同数据库 advisory slot 跨进程限额1–8，所有进程应统一配置|

返回正文的总量受 top_k 和有限语料字节上限约束，Python 仅保存当前授权快照与 Counter，不缓存私人内容。
这些上限不是进程 RSS 硬限制；jieba 公共词典占固定内存，仍需按进程数做容量规划。
读事务对 KB 加共享锁，CPU 分词期间会短暂阻塞相关上传/删除/索引；不能通过提高上限代替规模优化。
未来优先考虑持久化词项/词频/分词版本、按代次更新及分组完整性查询，压测后再考虑 HNSW 或独立搜索服务。

### 云端验证与后续边界

真实 Qwen Embedding：**NOT VERIFIED**。本轮无独立 V2 Key、无外部调用授权；云端保持默认关闭。
将来由用户通过独立 V2 配置注入凭证、明确启用并指定核查过的模型 revision 后，仅对无敏感的合成中文数据结构文本
执行 document/query 冒烟，检查顺序、数量、真实1024维、有限性及范数，再评测检索质量；不得把确定性测试的排序当作语义效果。
公开搜索新增了外部查询调用入口，仍需生产部署的用户级限流、每日成本额度和适当同意界面；当前只有请求次数/重试和并发约束。
本轮不接入生成、BM25持久化、Reranking、查询扩展或前端。下一步先建立授权语料上的检索评测，再接既有 Hybrid RAG 适配层，不能加载 V1 全局语料。


### 3C-1 实际验收（2026-10-26）

- 完整 V2：**357 passed in 60.57s**（原有330项与新增27项）。覆盖分词/公式/RRF、真实向量查询、限额、权限、模型切换、失效代次、数据库断连脱敏和跨进程槽。
- `alembic upgrade head`、`alembic check`、`alembic current` 通过，仍为 **0006_chunk_embeddings (head)**；无新增 schema 操作。`pip check` 无冲突。
- `python -m backend.v2.tests.retrieval_http_smoke` 通过：双进程 API、两个学生和本地初始化管理员、独立解析/索引 Worker、真实 PostgreSQL Chunk/vector 与三种 HTTP 模式。
- 合成测试验证私人/公共/混合范围；学生及管理员均不能访问其他学生私人知识库，混合范围含无权 ID 整单404。无 CSRF为403；文件删除/重解析后旧内容消失，KB删除为404，所有权变化后旧所有者404，用户禁用401。
- 并发数据库测试确认检索读锁期间写操作等待；事务返回后删除生效。另测试在外部查询向量返回前提交 KB 墓碑或禁用用户，最终授权检查拒绝。
- 首次全量运行356通过、1个新增测试失败：完成删除后的复查仍使用“写操作尚未完成”的事件断言钩子。修正测试钩子后全量357通过；并非权限实现失败。
- 开发库11张表的数据指纹前后相同；全部历史迁移、原有非V2文件保持原样。根 .env 未读写，V1与旧虚拟环境未修改，3B未提交内容保留。
- 随机测试数据库、临时存储、双进程API和本轮Worker均清理，8001无遗留监听；main/0276fad和空暂存区保持不变，无Git提交或推送。
- V2独立云Key未配置，provider=disabled、cloud_enabled=false；真实Qwen **NOT VERIFIED**，不能由下面数值推断语义相关性。

真实 HTTP 合成数据的检索诊断（查询“AVL 红黑树”，A私人+公共，共3个有效Chunk；不记录真实用户内容/凭证）：

|Hybrid次序|Dense排名|BM25排名|余弦相似度|BM25分数|RRF分数|
|---|---|---|---|---|---|
|1|3|1|-0.019690511059195837|1.1414373853110722|0.032266458495966696|
|2|2|2|-0.0019748928025364876|0.8623919802674049|0.03225806451612903|
|3|1|—|0.036400657147169335|—|0.01639344262295082|

例如第一名 `1/(60+3)+1/(60+1)=0.032266458495966696`；第二名 `2/(60+2)=0.03225806451612903`。
只在Dense出现的第三名分数为 `1/(60+1)=0.01639344262295082`。HTTP Dense排序逐项与真实PG `<=>` 计算核对。

本轮文件清单（相对于本轮开始时的脏工作区，不是相对于0276fad）：

**新增（6）**

- `backend/v2/routers/retrieval.py`
- `backend/v2/schemas/retrieval.py`
- `backend/v2/services/lexical_search.py`
- `backend/v2/services/retrieval_service.py`
- `backend/v2/tests/retrieval_http_smoke.py`
- `backend/v2/tests/test_retrieval.py`

**修改（11）**

- `backend/v2/services/vector_search.py`
- `backend/v2/core/config.py`
- `backend/v2/main.py`
- `backend/v2/requirements-dev.txt`
- `backend/v2/requirements.in`
- `backend/v2/requirements.txt`
- `backend/v2/tests/test_health.py`
- `docs/v2/API_CONTRACT.md`
- `docs/v2/ARCHITECTURE.md`
- `docs/v2/DATABASE_SCHEMA.md`
- `docs/v2/DEVELOPMENT.md`


## 3C-2A：Reranker 与 Context Builder

复用既有 httpx2，无新依赖，无新迁移。API启动方式仍为 `python -m backend.v2.main`（loopback8001）。
下列测试仅创建随机数据库/临时文件并自动清理，不清空开发库，不读取根.env，不调用V1的load_dotenv。

```bash
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
DS_V2_RUN_DB_TESTS=1 python -m pytest backend/v2/tests -q
python -m backend.v2.tests.context_http_smoke
```

### 配置（DS_V2_ 前缀，独立V2环境变量）

|后缀|默认值/含义|
|---|---|
|RERANK_PROVIDER|disabled；可选deterministic/qwen|
|RERANK_ALLOW_TEST_PROVIDER|false；测试Provider还必须environment=development|
|RERANK_CLOUD_ENABLED|false；部署级云外发开关|
|RERANK_API_KEY|空；独立凭证，不读取Embedding或V1 Key|
|RERANK_MODEL|qwen3.7-text-rerank，仅配置参考|
|RERANK_MODEL_VERIFIED|false；人工验证账户/地域/模型及参数后才可明确设置true，不是自动健康检测|
|RERANK_ENDPOINT|官方DashScope HTTPS rerank路径，可配置官方workspace.maas.aliyuncs.com端点，拒绝任意URL和重定向|
|RERANK_TIMEOUT_SECONDS|10，绝对单次请求超时，范围0.1–60|
|RERANK_RETRIES / RERANK_BACKOFF_SECONDS|2 / 0.5，最多3次调用，指数退避|
|RERANK_BATCH_SIZE / RERANK_MAX_CANDIDATES|20 / 20；均最高100，整份候选单批，超限拒绝|
|RERANK_MAX_ITEM_BYTES|8000；查询另限制≤4000 UTF-8字节|
|RERANK_MAX_TOTAL_BYTES|64000；重复查询开销计入总量|
|RERANK_CONCURRENCY|2；准备流程和云调用各使用独立advisory槽，所有进程应统一配置|
|CONTEXT_MAX_EVIDENCE / CONTEXT_PER_DOCUMENT|8 / 3|
|CONTEXT_MAX_CHUNK_CHARS|8000；超限跳过，不截断|
|CONTEXT_MAX_CHARS / CONTEXT_TOKEN_BUDGET|16000 / 6000；请求默认12000字符和4000保守估算单位|

请求的max_evidence默认5，top_k默认20（候选数），context_max_chars和context_token_budget可选择更小值，不能突破部署上限。
rerank=optional+默认disabled会明确跳过；required则503；off无论云配置如何都不初始化Provider。
启用后模型异常不自动fallback；Provider禁用跳过和故障后降级有不同语义，本轮只实现前者。
空候选不调用模型，返回空context_text及空evidence，不生成虚假引用。

### 预算、引用与安全使用

context_text是结构化证据JSON数组，每块含citation_id/source/content。evidence携带同序[S1]映射、来源UUID/页码/章节/顺序及诊断分数。
引用标识只在本次响应中稳定，不应跨请求当作永久引用ID；跨请求持久化应保存真实Chunk UUID和版本快照，并再次授权。
使用完整Chunk、每文档上限、总字符及保守UTF-8字节单位预算，不切断代码/公式。优先顺序稳定，超预算跳过后可继续尝试更小候选。
这些单位不是任何生成模型的精确Token计数；后续3C-2B必须用所选生成模型Tokenizer重新校验完整prompt预算（含静态指令与问题）。
控制字符和隐藏格式字符可见化，sanitized提示变化，content_hash仍对应数据库原文。JSON编码隔离引号、假引用、结束标签等内容。
未来生成层应将证据作为低信任tool/user数据，不能插入system/developer级消息，也不能执行其中URL/命令；本阶段没有LLM或工具执行器。

### 最终认证与并发协议

prepare_context必须从可信认证边界传入user及verify_session，后者必须验证实际会话并返回同一User，不能只检查user_id存在。
HTTP适配使用lock_current_session：当前User共享锁→实际AuthSession共享锁→按UUID排序的KB共享锁。
查询Embedding和Reranker网络阶段均不持有数据库事务/资源行锁；最终事务重新读取真实正文并逐项比较hash/generation/index_revision/space。
任意已检索候选变化则整单409，不从旧候选拼接部分上下文。最终构建完成后再次按clock_timestamp检查会话到期。
所有正常写操作必须继续遵守KB→document→job锁顺序，否则不能依赖该父锁协议；新增Worker或管理脚本也不例外。
共享锁覆盖当前授权快照及响应数据复制；变更若已提交则拒绝，若晚于快照则等待，不能撤回客户端已经收到的内容。

### 云模型验证与已知限制

官方文档已列出qwen3.7-text-rerank及原始index/relevance_score响应，支持独立V2 HTTP适配：
[Text Rerank API](https://help.aliyun.com/en/model-studio/text-rerank-api)。不同地域可用模型存在差异，当前账户调用和质量均 **NOT VERIFIED**。
本轮Key为空、云开关关闭；未向第三方发送任何合成或私人问题/正文。将来必须由用户明确配置独立Key与外发授权，
使用无敏感合成中文课程文本测试真实模型可用性、端点、全量index、数量和分数，再人工标记模型核查开关；禁止读取根.env或复制V1 Key。
分数只在同次请求内有效，不能把不同批次分数直接合并或宣称质量提升；需建立人工标注集及检索/重排消融评测。

单请求有限超时/重试与并发不等于每日费用硬额度；生成层前仍需用户级限流、成本额度、同意界面及审计（不能记录私人全文）。
上下文预算是有界输入，不是进程RSS隔离。提示词注入风险不能仅靠JSON编码完全消除，后续LLM的指令层级/工具权限还需独立设计。
暂未实现语义去重、跨页复杂引用合并、自动截断、精确Tokenizer、持久化重排缓存或证据快照API。
3C-2B可复用prepare_context的结构化证据与来源映射；长生成阶段之后再次访问资源时仍要重新授权，不能复用已过期会话或假定快照永久有效。

### 3C-2A 本轮实际验证（2026-10-26）

- 完整pytest：**398 passed in 70.51s**（原有357项加新增41项），无跳过数据库测试。
- Alembic upgrade head、check、current通过；当前0006_chunk_embeddings，无schema变化；pip check无冲突。
- 真实双进程HTTP + 独立解析/索引Worker + PostgreSQL通过；两个学生与管理员验证私人/公共/混合范围、引用映射、原始分数、CSRF、删除、重解析及退出。
- 真实DB竞态测试在Rerank中提交KB/文件墓碑、用户禁用、会话吊销/过期、处理状态及index_revision变化，最终拒绝旧证据；网络阶段idle-in-transaction计数为0。
- 最终构建中的并发删除/吊销会等待共享锁；下一请求立即反映失效状态。最终DB连接切换到不可用端点时抛出真实OperationalError，不返回旧正文。
- 控制响应的单元测试另验证乱序/重复/越界index、非法分数、超时、限流、永久错误及有限重试、同分排序、预算/去重/恶意文本边界。

真实HTTP合成语料诊断（测试Provider；不宣称语义效果）：

|原排名|重排排名|重排分数|原RRF|原余弦相似度|原BM25|
|---|---|---|---|---|---|
|1|1|1.0|0.032266458495966696|-0.019690511059195837|1.1414373853110722|
|2|2|1.0|0.03225806451612903|-0.0019748928025364876|0.8623919802674049|
|3|3|0.0|0.01639344262295082|0.036400657147169335|—|

本例前两条同分，保留原始排名；控制Provider单元测试另用index=1得0.9、index=0得0.1，验证顺序变为2→1，原Hybrid分数不变。

本轮文件清单（相对于ea7d5b3工作区）：

**新增（6）**

- `backend/v2/schemas/context.py`
- `backend/v2/services/context_builder.py`
- `backend/v2/services/context_service.py`
- `backend/v2/services/rerank_provider.py`
- `backend/v2/tests/context_http_smoke.py`
- `backend/v2/tests/test_context.py`

**修改（10）**

- `backend/v2/core/config.py`
- `backend/v2/dependencies/auth.py`
- `backend/v2/routers/retrieval.py`
- `backend/v2/services/retrieval_service.py`
- `backend/v2/services/vector_search.py`
- `backend/v2/tests/test_health.py`
- `docs/v2/API_CONTRACT.md`
- `docs/v2/ARCHITECTURE.md`
- `docs/v2/DATABASE_SCHEMA.md`
- `docs/v2/DEVELOPMENT.md`

最终核对：开发库11张表数据指纹与本轮开始时完全一致；随机测试库为0，临时文件目录及API/Worker进程均无残留。
V2变更凭证扫描通过；V1原有文件及历史0001–0006迁移哈希不变，main/ea7d5b3、空暂存区不变，未commit/push。
最终在候选UUID限制下推到授权CTE后，完整pytest再次398通过，真实HTTP冒烟也再次通过。


## 3C-2B：单轮RAG开发与验证

复用既有httpx2，无新增依赖或迁移。先保证合成测试文档已被Worker处理为ready；API启动仍为 `python -m backend.v2.main`，loopback8001。
默认Generator关闭，Embedding/Rerank也仍按各自默认关闭；默认hybrid若Dense未启用会明确报错，不自动改用BM25。

```bash
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini check
DS_V2_RUN_DB_TESTS=1 python -m pytest backend/v2/tests -q
python -m backend.v2.tests.rag_http_smoke
```

HTTP冒烟会创建随机测试数据库/临时目录，启动双进程FastAPI及独立解析/索引Worker，以两个学生和管理员验证完整合成链路；
拒绝占用已有8001服务，结束仅清理本轮资源。不会读取根.env、复制V1凭证或向云端发送数据。

### 生成配置（DS_V2_前缀，仅独立V2环境）

|后缀|默认值/含义|
|---|---|
|GENERATION_PROVIDER|disabled；可选deterministic/qwen|
|GENERATION_ALLOW_TEST_PROVIDER|false；deterministic还要求environment=development|
|GENERATION_CLOUD_ENABLED|false；仅部署意图，不能绕过生成授权阻塞|
|GENERATION_API_KEY|空，独立SecretStr，不隐式回退到Embedding、Rerank或V1 Key|
|GENERATION_MODEL / GENERATION_MODEL_VERIFIED|qwen3.7-flash / false，真实账户/地域可用性未验证|
|GENERATION_ENDPOINT|官方HTTPS compatible-mode/v1/chat/completions路径，允许官方workspace.maas域名|
|GENERATION_TEMPERATURE|0.2，范围0–1|
|GENERATION_TIMEOUT_SECONDS|20，单次绝对超时，范围0.1–60|
|GENERATION_RETRIES / GENERATION_BACKOFF_SECONDS|2 / 0.5，临时网络/429/5xx有限退避|
|GENERATION_MAX_CALLS|3，总生成尝试预算，最高4；与校验重试共享|
|GENERATION_VALIDATION_RETRIES|0，可选1；不对坏答案做引用删除式修复|
|GENERATION_MAX_INPUT_BYTES|24000，完整Prompt JSON的UTF-8字节上限，非精确Token|
|GENERATION_MAX_OUTPUT_TOKENS / GENERATION_MAX_OUTPUT_BYTES|1024 / 12000，协议输出参数及服务端字节双重限制|
|GENERATION_CONCURRENCY|2，流程槽和云适配槽分开命名，跨API进程；所有进程应统一配置|

测试Provider只引用第一条授权证据，不执行算法、代码或网络操作；模式标题用于验证接口组织，不代表具备推理或语义质量。
空结果、没有有效词项支持和有限键值冲突预检均直接拒答，不调用生成Provider。关键单字课程术语和“数据结构”本身不会被当作泛化词排除。
词项重叠只是必要的保守预检，不足以证明复杂题目可解；自然语言冲突/事实蕴含仍需评测。

### 引用与最终发布

内部prepare_context继续返回原证据；共用validate_evidence，不复制一套授权逻辑。
模型只返回status/answer/used_source_ids；引用集合必须等于本次映射的合法引用且列表不重复。
同一ID可在正文重复引用，sources只返回一次；缺失、伪造、非法格式、截断或坏JSON均不能发布答案。
文件名和页码只在sources展示，模型另写这些来源信息会被严格拒绝；这是首版协议的保守限制，可能拒绝合法但不符合协议的答案。
对显式执行/联网声明的拦截是有限模式匹配，不保证识别所有改写，execution_performed永远false。

外部生成前结束数据库事务。生成后复核全部送入模型的Chunk，而非只复核used_source_ids，以防未引用的旧私人材料影响答案。
最终短事务锁定User→AuthSession→KB，核对墓碑、ready、hash、解析/索引代次、模型空间；在事务内复制来源/响应并再次查会话到期。
发生401/404/409或数据库故障时整份旧答案丢弃，不能只删sources。读快照结束后的变更不能撤回已发送内容，网络窗口不承诺绝对无竞态。

### 明确未完成的生产能力

- Qwen Embedding、Rerank、Generator均 **NOT VERIFIED**。本轮没有独立Key及外部调用授权，未向云端发送任何问题或资料。
- 生产Qwen Generator始终受generation_consent_not_configured阻塞。请求allow_cloud_generation和环境开关不构成持久化、可审计授权，不能绕过。
- 未建立生成服务用途的同意/撤销审计表。本轮按安全边界选择关闭云端；未来启用前需新迁移及服务端验证，不能直接复制Embedding同意字段。
- out_of_scope为预留状态。当前缺少权威课程范围，模型自报只能转为scope_not_verified拒答；不虚报可靠自动范围判定已完成。
- 没有精确生成Tokenizer、每日/每用户费用额度、完整语义冲突检测或事实一致性证明；API并发/重试有界不等于费用硬上限。
- Prompt角色分离与引用校验不能完全消除未来真实模型的Prompt Injection，也不能证明每个带引用事实都能从原文推出。

未来真实模型联调顺序：先建立可审计生成授权；由用户独立配置V2 Key和用途范围；只用无敏感合成中文课程片段核对地域/模型、
Chat Completions参数、非思考JSON、finish_reason、usage和调用预算；再用标注集评估事实、引用蕴含和拒答，不以确定性测试代替质量验证。
官方协议：[Chat Completions](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)、
[结构化输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)。

本轮没有聊天历史、查询扩展、流式输出、多模态或前端。


### 3C-2B 实际验收（2026-10-26）

- 最终完整V2：**463 passed in 92.69s**，包含原有398项及新增65项；全部隔离数据库测试已启用。
- Alembic upgrade head、check、current通过，仍为0006_chunk_embeddings (head)，没有schema漂移或历史迁移修改；pip check通过。
- 真实双进程HTTP、两个学生及管理员、独立解析/索引Worker完成单轮链路；qa/exercise/code/auto、私有/公共/混合范围、正常引用、拒答、CSRF与伪造user_id拒绝均通过。
- HTTP答案来源与实际PostgreSQL Chunk hash、generation、KB及ready状态逐项核对；生成后不返回系统Prompt或完整证据上下文。
- 生成时真实DB变更覆盖用户禁用、会话吊销、KB/文件删除、重解析/索引状态与代次；模型空间配置变化同样拒绝旧答案。生成期间idle-in-transaction计数为0。
- 最终响应构建中的并发删除、重新索引和会话吊销等待共享锁，后续请求立即失效；实际最终DB断连时不返回缓存旧答案。
- 引用缺失/伪造/重复列表/非法格式、无效或截断JSON、非法来源和执行声明、超时/429/服务错误、共享调用预算与一次校验重试均已测试。
- 无证据、无词项支持、显式键值冲突均不调用Generator；模型自报课程外仅安全拒答，不作未经证明的范围结论。
- 原3C-2A代码保留；仅将其最终版本检查抽成共用validate_evidence，原398项回归全部通过。没有修改V1、根.env、旧虚拟环境或历史迁移，也没有Git提交/推送。
- 测试仅证明工程正确性，Qwen三类云模型的可用性和生成质量均NOT VERIFIED；生成用途审计授权未实现，生产外发仍阻塞。

本轮新增/修改清单（相对于本轮开始时包含3C-2A未提交代码的工作区）：

**新增（9）**

- `backend/v2/routers/rag.py`
- `backend/v2/schemas/rag.py`
- `backend/v2/services/answer_validation.py`
- `backend/v2/services/evidence_policy.py`
- `backend/v2/services/generation_provider.py`
- `backend/v2/services/prompt_builder.py`
- `backend/v2/services/rag_service.py`
- `backend/v2/tests/rag_http_smoke.py`
- `backend/v2/tests/test_rag.py`

**修改（8）**

- `backend/v2/services/context_service.py`
- `backend/v2/core/config.py`
- `backend/v2/main.py`
- `backend/v2/tests/test_health.py`
- `docs/v2/API_CONTRACT.md`
- `docs/v2/ARCHITECTURE.md`
- `docs/v2/DATABASE_SCHEMA.md`
- `docs/v2/DEVELOPMENT.md`

最终核对：开发库11张表数据指纹未变，随机测试库为0；临时API、Worker、存储目录已清理，8001无残留监听。
V2变更凭证扫描通过；原V1及非V2文件、历史0001–0006哈希不变，main/ea7d5b3及空暂存区保持不变，未commit/push。
最终真实HTTP冒烟再次通过，云生成配置仍为disabled、cloud_enabled=false、独立Key未配置。


## 最终集成：当前开发与验收入口

请优先按[TEAM_ONBOARDING.md](TEAM_ONBOARDING.md)启动，按[FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md)联调。旧阶段NOT VERIFIED、0006、固定HTTP端口和云生成阻塞记录保留为历史，不能用于判断当前状态。

```sh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python deploy/v2/init_env.py  # 已存在即跳过，绝不覆盖
# Apple Silicon不需DS_V2_DB_PLATFORM；x86/WSL显式设置linux/amd64
docker compose --env-file deploy/v2/.env -f deploy/v2/compose.yaml up -d db
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m backend.v2.tools.dev status
# 三个终端分别运行，不依赖私人Key：
python -m backend.v2.tools.dev api --test-providers
python -m backend.v2.tools.dev parser --test-providers
python -m backend.v2.tools.dev embedding --test-providers
# 第四个终端完整验收；独立数据库/临时目录，默认无付费：
DS_V2_RUN_DOCKER_TESTS=1 python -m backend.v2.tools.acceptance
python -m backend.v2.tools.export_openapi
python -m backend.v2.evaluation.score
```

Docker fallback测试需先 `docker build -f deploy/v2/parser.Dockerfile -t ds-assistant-v2-parser:local backend/v2`；Mac auto继续Seatbelt。无Docker测试标志时恰好3项fallback测试skipped，不算PASS。验收HTTP使用临时继承监听FD，不探测或终止8001；API长期服务仍为127.0.0.1:8001。

云配置和用途授权见交接指南，默认三类cloud=false。qwen3.8-flash、qwen3.7-text-embedding-flash/1024、qwen3.7-text-rerank已用本轮授权的9次短合成请求实测；真实HTTP离线套件仍使用确定性Provider，不混淆两者。受限付费入口cloud_smoke不由普通pytest触发；本轮预算账本已用9/12，禁止重置后重复调用。estimated usage成本0.001068元非实际账单，保守预留上限3.6元，未达到5元边界。

### 公共课程导入（不自动向量化）

```sh
python -m backend.v2.tools.import_course knowledge_base/ds_chunks.jsonl
# 负责人先通过本地 `python -m backend.v2.manage create-admin --email <admin-email>` 与admin API建立公共KB，再显式导入：
python -m backend.v2.tools.import_course knowledge_base/ds_chunks.jsonl --apply --admin-email <admin-email> --kb-id <public-kb-uuid> --mapping-output /private/tmp/course-mapping.json
```

dry-run默认只读预览，已检查真实V1共1010条，导出UTF8共383572字节。以内容digest命名真实TXT，保留每条legacy ID、原文与来源元数据；不伪造PDF。manifest映射记录原始页号（导出TXT自身page_number为null），每个章节标题V1:legacy_id可追溯到原记录，长记录可能拆为多个V2 Chunk。重复导入同一活动对象复用document，失败解析可重新入队，已删除对象不会复活；并发通过KB写锁与已有上传事务串行。

工具要求本地合法admin且目标public，普通学生不可用；只调用既有upload/ingestion生命周期，未自动Embedding、不制造ready。隔离数据库已验证uploaded→parsed、重复幂等和来源保持。**当前只达到可预览+可实际导入/解析；未完成本地关键词检索、真实全库向量索引或真实全课程问答**。现有BM25也要求ready，所以后续必须独立审查资料授权、预算、用途同意和真实索引后再检索。不要把36题未标注评测写成准确率。

### 最终测试与保护

最终结果见INTEGRATION_REPORT.md。开发库原业务表、V1未提交文件与0001–0006历史迁移做前后SHA256核对，根.env仅检查stat不读取内容，V2.env检查hash/0600/ignore，无覆盖。只新增0007并推进版本。Git只审查提交V2，不加入V1脏资产。
