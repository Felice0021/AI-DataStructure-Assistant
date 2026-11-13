# 聊天界面与历史记录验收

基线：origin/deploy/qwen-demo 59789f9129e13b495abada5e8ec99227e36f48a4。
分支：feat/v2-chat-history。使用独立 worktree；原工作区未清理、未覆盖。

## 已实现

- 桌面侧栏与移动抽屉、消息流、自动增高输入、Enter/Shift+Enter、发送互斥。
- 固定 auto/hybrid；复用逐用途有效授权和后端 Guard；不提供高级选项。
- PostgreSQL 保存成对的用户提问/验证后的 assistant 回答及来源快照。
- 会话创建、自动标题、重命名、软删除、分页、刷新/重新登录恢复。
- 会话级 PostgreSQL advisory lock 防并发；request_id + 请求指纹保证已完成重试幂等。
  外部调用期间不持有行锁或事务；最终短事务重新校验用户、会话和来源。
- 失败不保存草稿；数据库写入异常整对回滚。崩溃未提交时可以重算，但不会保存半对消息。
- 来源删除、失权、代次变化后，历史回答正文及来源隐藏，提示重新提问。
- 安全 Markdown 复用原渲染器；每条回复独立来源 ID；复制回答。
- 无迁移、无重索引；原单轮 /rag/ask 不变。没有实现模型上下文追问。

## 2026-11-13 本地执行

- V2 完整 pytest：535 passed、4 skipped（显式 Docker Parser 镜像测试，Linux CI 执行）。
- 前端完整 Vitest：77 passed；生产构建通过，产物无 mockServiceWorker.js。
- 本机 Edge + 随机隔离 PostgreSQL/临时文件：三次连续提问、分别保存引用、刷新并恢复、
  切换历史、重命名、创建新会话、证据不足、软删除、退出和重新登录恢复均通过。
- 390×844：documentElement.scrollWidth=390，输入框完整位于视口内。
- 使用原创短文本与 deterministic Provider；没有将这些结果计为真实模型质量。
- 账号隔离、已删除来源隐藏、CSRF、并发、相同请求重放与冲突、失败回滚：真实隔离 DB 测试通过。

补充：最终提交前另行验证了生成后的竞争幂等检查，以及服务端退出失败提示。

## 合并后 HTTPS 验收（尚未执行）

由负责人确认合并到 deploy/qwen-demo，必需 CI 和自动部署成功后：

1. 核对 deployment-sha.txt 为合并提交；登录 Qwen 演示账号并选择原课程库。
2. 连续询问栈/队列、AVL、图遍历，验证自然语言回复及每条 [S1] 对应独立来源。
3. 刷新、退出重登、切换历史确认消息保存；重命名及删除一个专用测试对话。
4. 资料不足明确拒答；第二账号不得读取首账号会话；确认真实 API、无 MSW。
5. 核对原课程 1011 条向量及 deterministic QA 不变。

保持上一 release 作为回滚版本。回滚通过既有管理员流程切换 Qwen release，重启 API/Worker
并验证健康与问答；无需数据库迁移、数据恢复或重索引。
