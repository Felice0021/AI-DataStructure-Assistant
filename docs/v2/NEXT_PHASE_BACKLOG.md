# 后续模块边界（未分配人员，未实现）

|模块|复用接口与依赖|难度|验收条件|
|---|---|---|---|
|Vue 3 + Vite 工程|openapi.json、精确Origin、credentials/CSRF|中|独立运行5173；构建/测试通过；不持有模型Key|
|登录与个人知识库界面|auth、knowledge-bases、cloud-consents|中|注册不自动登录；401/403/404正确；管理员不越权；用途同意可撤销|
|上传与处理状态界面|documents/ingestion/embedding|中|三格式、限额、轮询退避、失败重试；parsed不误报ready；不默认付费同意|
|聊天外观与引用展示|单轮rag/ask、sources、鉴权download|中|四模式、拒答/不可用区别、[S1]正确关联、安全Markdown；先不伪造历史功能|
|多轮会话与历史|新数据库迁移、会话所有权、当前证据复核|高|每轮重新授权；历史删除/保留策略；旧私人上下文不得越权复用|
|图片题与多模态|新输入校验、隔离Worker、独立用途同意|高|限制图像资源/费用；模型与资料来源可追踪；不绕过文件安全|
|公共课程资料质量与标注|import_course、既有解析生命周期、evaluation|中|来源授权、映射、人工GT复核；全量云索引单独预算；不伪造ready|
|RAG评测与性能优化|evaluation、retrieval/context/rag、metadata审计|高|人工GT；报告消融、质量和延迟；再评估词法索引/HNSW/缓存，不先破坏权限|
|系统测试与材料|acceptance、OpenAPI、INTEGRATION_REPORT|中|Windows/WSL实机、生产TLS/代理、备份恢复、限额与日志脱敏测试可复现|

并行原则：前端对冻结API开发；后端schema变更先协调revision；评测与资料审查可独立进行。跨模块修改用PR和契约测试，不共享负责人的私人Key。正式外部开放前由负责人确认TLS/反向代理、独立DB角色、服务商数据政策、每日/每用户成本硬额度、备份恢复和保留清理。以上仅是接口、依赖及验收边界，本轮不启动这些开发。
