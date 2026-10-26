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

当前 head 为 `0003_knowledge_bases`，既有 `0001_auth_foundation`、`0002_login_limits` 保持原样。迁移与应用读取相同 V2 配置。
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
