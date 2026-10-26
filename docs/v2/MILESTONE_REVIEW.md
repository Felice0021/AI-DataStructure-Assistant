# V2 里程碑审查（2026-10-26）

范围：backend/v2、deploy/v2、docs/v2、0001–0003 迁移及 Git 暂存候选。
以实际代码和本轮运行结果为准。本轮不新增业务功能，不提交 Git。

## 分级结论

未发现确定的 P0 或阻塞文件上传/多用户 RAG 基础开发的 P1，因此没有修改运行时代码或历史迁移。
这不是生产上线认证；TLS/代理、边缘限流、备份和最小权限数据库账户仍须按 DEVELOPMENT.md 部署。

|级别|问题|证据及影响|处理|
|---|---|---|---|
|P2|未预期 500 缺少 CORS 响应头|TestClient 注入仅测试用异常路由，以白名单 Origin 请求：500、脱敏 JSON、no-store，但无 Access-Control-Allow-Origin。浏览器可能只能显示网络错误；已处理的认证错误和数据库 503 不受此问题影响。位置 main.py 的通用异常处理及中间件顺序。|按本轮范围保留，后续改善统一错误展示时处理。|
|P2|PATCH OpenAPI 可空声明与运行校验不一致|KnowledgeBaseUpdate 的 name/description 使用 str 或 None，OpenAPI 包含 null，但 model validator 拒绝显式 null；实际契约要求省略未修改字段、空字符串清空说明。|运行时安全，无权限绕过；生成前端客户端前修正文档 schema。|
|P2|HTTP 脚本连续启动可能因端口短暂不可绑定而失败|认证脚本退出后立即运行知识库脚本出现 EADDRINUSE；lsof 无监听进程，稍后原命令成功。端口预检未启用地址复用。|记录测试工具限制，不终止其他进程、不改业务代码。|

## 核查结果

- 认证身份来自有效、未过期、未吊销的数据库会话及激活用户；随机凭证仅进 HttpOnly Cookie，数据库保存摘要。
- 密码 Argon2id；失败限流持久化 PostgreSQL 并加行锁。写操作复用严格 Origin 和 Cookie 绑定 CSRF；CORS 无凭证通配符。
- 默认生产 Secure/__Host- Cookie；HTTP 降级需显式 loopback 开发配置，检查真实客户端地址。
- readable_scope 统一排除墓碑，仅返回公共或本人私人知识库。管理员无其他学生私人资料的隐式权限。
- get_writable 在相同读取作用域内锁行；公共写入另验管理员角色。客户端额外 owner_id、visibility、index_version 等字段均被拒绝。
- 名称 API 先 NFKC 和空白规范化；唯一性不使用独立 Python 比较，而由 PostgreSQL 生成 name_key 和有效记录部分唯一索引裁决。大小写遵循数据库 lower/排序规则，并非 Unicode 视觉近似消歧。
- 软删除保留 UUID 墓碑并释放有效名称；重建使用新 UUID。新回归验证删除提交时重建成功、删除回滚时重建 409，数据库锁等待可观察，最终均只有一个有效名称。删除后 GET/PATCH/DELETE 均 404。
- ORM/0003 表、外键 RESTRICT、检查约束及索引一致，既有 0001/0002 未修改。Alembic check 无新增操作。
- SQLAlchemy 隐藏参数；API 不返回 SQL/密码/堆栈，日志仅记录错误类别。反向代理和外部日志系统仍须禁止凭证头和请求体日志。
- API_CONTRACT、DATABASE_SCHEMA、ARCHITECTURE 的权限和名称规则与实现一致；DEVELOPMENT 历史阶段记录保留，当前状态以末尾 3A 及本审查为准。
- 未启用 RLS，应用服务层是当前隔离边界。直接 ORM 查询不能作为后续资源授权方案。

## 本轮验证

```zsh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
python -m alembic -c backend/v2/alembic.ini upgrade head
python -m alembic -c backend/v2/alembic.ini current
python -m alembic -c backend/v2/alembic.ini check
DS_V2_RUN_DB_TESTS=1 python -m pytest -c backend/v2/pyproject.toml backend/v2/tests -q
python -m backend.v2.tests.http_smoke
python -m backend.v2.tests.knowledge_base_http_smoke
```

- 完整 pytest：128 passed；包含原 126 项及两项新增真实 PostgreSQL 事务竞态回归。
- 当前 revision：0003_knowledge_bases (head)；upgrade head 成功，check 无差异。
- 两套 HTTP 脚本需顺序执行，端口释放后再启动下一套。使用独立随机测试数据库、两个 Uvicorn worker。
- 本轮认证 HTTP：两个独立学生注册/登录/me/角色/退出、管理员、CSRF、会话隔离及数据库失败脱敏验证通过。
- 本轮知识库 HTTP：学生所有者 CRUD、跨用户和管理员访问他人私人库 GET/PATCH/DELETE 404、公共管理员管理、伪造字段拒绝、软删除及重建通过。
- 测试数据库由已有机制创建并清理，不清空或重建开发数据库；本机凭证不写入此报告。

## 后续统一授权边界

- 请求入口 Depends(require_active_user)，复用 get_current_user 的 Cookie、CSRF 和激活状态校验。
- 文件/文档/检索读取调用 knowledge_base_service.get_readable(session, user, kb_id)。批量查询复用 readable_scope。
- 文件上传、文档修改/删除和索引写入调用 get_writable；公共管理额外复用 require_public_manager。
- 授权 helper 不提交，后续服务在同一事务内校验父知识库及 document/chunk 归属，不能只凭子资源 UUID。
- Worker 必须重新检查有效知识库、授权/任务身份和 index_version；返回检索结果前仍须校验可读状态。软删除不等于物理文件清理。

## Git 基线规则

只纳入 backend/v2、deploy/v2 的公开模板/脚本和 docs/v2；实际 .env、缓存、日志、虚拟环境、V1 资产不纳入。
本轮只准备暂存区。建议后续人工提交说明：feat(v2): establish authenticated multi-user platform foundation。
本轮新增本报告，修改 test_knowledge_bases.py 增加两项测试；不改运行时、历史迁移或 V1 文件。
