# V2 最终集成验收与交付（2026-10-26）

结论：具备团队功能开发与前端对接基础；不等同于生产开放许可。原有463项回归保留，新增16项（含3项真实容器解析）；最终479 passed、0 failed、0 skipped（Docker及数据库测试均显式启用），最终审计关联修复后再次全量通过，93.18秒。单独新增授权/交接回归13项亦通过。

## 实际环境与执行

macOS26.6.2 / Apple Silicon ARM64，Python3.12.15，Node24.22.0/npm11.19.1，Docker Engine29.9.2 linux/arm64；PostgreSQL17.11、pgvector0.8.7。V2虚拟环境独立，未修改V1。Windows原生未支持，WSL实机尚未验证；Mac Seatbelt及Linux ARM64只读无网Docker解析三格式实测通过。

```sh
source ~/.virtualenvs/ai-datastructure-v2/activate-v2.zsh
DS_V2_RUN_DOCKER_TESTS=1 python -m backend.v2.tools.acceptance
```

实际执行pip check（无冲突）、upgrade head（可重复）、Alembic check（无差异）、完整pytest、8个真实HTTP套件。使用随机数据库/临时存储和双进程API，独立解析/Embedding Worker；包含真实SIGKILL/租约恢复、PG vector(1024)写入和余弦SQL。端到端覆盖两学生+管理员，私人/公共/混合、PDF/DOCX/TXT、BM25/Dense/Hybrid、Rerank/Context、qa/exercise/code/auto、正常/不足拒答、来源hash/代次、CSRF、越权、删除/重解析/禁用/吊销及最终数据库故障。确定性Provider的结果只证明工程协议，不作为真实语义质量。

## 修复及风险分级

未发现当前团队开发目标中的未解决P0/P1阻塞。已修复三个高价值P2：非预期500对精确Origin补CORS；PATCH OpenAPI不再允许null且运行时422一致；HTTP冒烟使用OS端口及POSIX继承FD，保留长期8001服务。新增回归与实际HTTP均通过。另补齐云调用完成/失败事件的KB关联，保证审计API可查询耗时与usage，并以真实隔离数据库回归。

云生成原先因缺持久授权而阻塞：新增0007、三用途授权及安全审计，真实Provider外发必须通过Guard，逐次重试重新授权。模型默认改为qwen3.8-flash，使用非思考JSON输出；响应Schema、引用编号、来源和最终权限仍由后端验证。修复配置错误input回显风险，抑制HTTP客户端URL日志；未打印或提交Key。

P2/生产待办：每用户/每日费用硬限额、边缘防滥用、精确Tokenizer、服务商保留政策、审计保留/不可篡改、独立DB应用/迁移/测试角色、TLS代理及备份恢复、Windows/WSL实机；提示词隔离和合法引用不能证明语义蕴含，课程范围外判定仍保守拒答。Docker守护进程管理权限需部署隔离。有限BM25有语料/字节/词项上限，扩大规模需评估词法索引与HNSW，不能移除授权下推。

## 真实云端：PASS（合成资料，独立计数）

明示授权后只使用固定短合成课程文本，全部在隔离库/临时存储。实际9次API请求，无重试；未使用真实学生资料或V1课程全文。

|对象|实际配置/结果|
|---|---|
|Embedding|qwen3.7-text-embedding-flash，实际1024维，数量、顺序、有限性/范数校验，PASS|
|Reranker|qwen3.7-text-rerank，合法index/score，PASS|
|Generator|qwen3.8-flash，实际返回model匹配；JSON Schema和引用校验，PASS|
|完整链路|正常answered及真实模型insufficient_evidence各一次，PASS|

具体numeric usage和耗时见CLOUD_SMOKE_RESULT.json，无Prompt/正文/Key/原始会话。生成正常470输入/56输出、拒答494输入/20输出Token；其余5次Embedding/2次Rerank均成功。原生Embedding/Rerank响应如未提供model字段，按请求模型、实际协议及维度核验，不伪造返回字段。

北京公开单价估算usage费用0.001068元（非实际账单）；调用前保守预留9×0.4=3.6元，12次上限最多4.8元。当前账本已用9/12，脚本拒绝再次完整运行，不得删除账本规避。测试结束真实配置未改，三个cloud开关仍false。

官方依据：[Qwen3.8-Flash](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)、[模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)。模型理论支持长上下文/JSON，但本服务仍保守限制完整输入24000字节、输出1024Token；本轮实际验证enable_thinking=false，不声称支持或测试最大上下文。

## 公共课程与评测

V1只读预览1010条，安全导出TXT383572字节。管理员导入复用已有私有存储与任务生命周期，映射保留legacy ID/原始来源/页码，重复执行幂等；隔离测试已到uploaded→parsed。开发库未导入课程全文，未批量云Embedding。阶段：预览PASS，实际导入/解析PASS，本地关键词检索未完成（当前检索仅ready），真实全课程向量/问答未完成。

36道合成题全部待人工标注，approved=0、evaluated=0、quality_metrics={}。具备评测脚本和schema，不发布Recall/MRR/nDCG/忠实度质量数字。小样本API可用性不代表课程效果。

## 数据与Git保护

执行前记录Git状态、全部现有文件hash、开发库11表行指纹与配置元数据。原10张业务表行指纹不变，只有alembic_version推进0007；新cloud_consents/cloud_audits在开发库为0行。随机测试库、测试API/Worker/文件清理，保留开发数据库/卷及其他Docker资源；新增解析镜像为开发构建产物，不提交Git。

V1原脏资产、所有非V2文件、0001–0006历史迁移hash不变。V2.env SHA256不变、0600、Git忽略；根.env仅读stat，未读内容且size/mtime不变。旧V1虚拟环境未修改。

提交范围仅backend/v2、deploy/v2公开模板/脚本、docs/v2，含原有未提交3C-2A/B。此前两个本地待推送提交也仅V2且经实际凭证扫描。提交/远程具体SHA以本轮最终报告与git log为准；普通快进push之前重新fetch确认祖先关系，禁止强推。所有既有V1未提交资产留在工作区，不纳入本次基线。

## 交接入口

- TEAM_ONBOARDING.md：独立环境、三个进程、测试Provider、云端显式启用、PR/迁移协作。
- FRONTEND_HANDOFF.md + openapi.json：完整API、Cookie/CSRF、状态与引用、错误和云同意交互。
- EVALUATION_PLAN.md：人工标注边界、指标与输入格式。
- NEXT_PHASE_BACKLOG.md：模块接口/依赖/难度/验收，不分配人员。
- ARCHITECTURE / DATABASE_SCHEMA / API_CONTRACT / DEVELOPMENT 的“最终集成”章节：当前实现；较早阶段章节仅为历史。

本轮未实现Vue、多轮历史、多模态、工具执行或查询扩展。后续先完成公开课程来源和标注审查、Windows/WSL实机及生产预算/隐私条件，再按冻结接口并行开发。

## 本次基线文件清单（相对执行前HEAD ea7d5b3，含既有3C-2A/B）

- `backend/v2/.dockerignore`
- `backend/v2/core/config.py`
- `backend/v2/core/logging.py`
- `backend/v2/dependencies/auth.py`
- `backend/v2/embedding_worker.py`
- `backend/v2/evaluation/__init__.py`
- `backend/v2/evaluation/cases.jsonl`
- `backend/v2/evaluation/score.py`
- `backend/v2/main.py`
- `backend/v2/migrations/versions/0007_cloud_consents_cloud_consents.py`
- `backend/v2/models/__init__.py`
- `backend/v2/models/cloud.py`
- `backend/v2/parser_child.py`
- `backend/v2/routers/cloud.py`
- `backend/v2/routers/rag.py`
- `backend/v2/routers/retrieval.py`
- `backend/v2/schemas/context.py`
- `backend/v2/schemas/knowledge_base.py`
- `backend/v2/schemas/rag.py`
- `backend/v2/services/answer_validation.py`
- `backend/v2/services/cloud_service.py`
- `backend/v2/services/context_builder.py`
- `backend/v2/services/context_service.py`
- `backend/v2/services/docker_parser.py`
- `backend/v2/services/embedding_provider.py`
- `backend/v2/services/evidence_policy.py`
- `backend/v2/services/generation_provider.py`
- `backend/v2/services/parser_runner.py`
- `backend/v2/services/prompt_builder.py`
- `backend/v2/services/rag_service.py`
- `backend/v2/services/rerank_provider.py`
- `backend/v2/services/retrieval_service.py`
- `backend/v2/services/vector_search.py`
- `backend/v2/tests/context_http_smoke.py`
- `backend/v2/tests/documents_http_smoke.py`
- `backend/v2/tests/embedding_http_smoke.py`
- `backend/v2/tests/http_smoke.py`
- `backend/v2/tests/ingestion_http_smoke.py`
- `backend/v2/tests/knowledge_base_http_smoke.py`
- `backend/v2/tests/rag_http_smoke.py`
- `backend/v2/tests/retrieval_http_smoke.py`
- `backend/v2/tests/test_cloud.py`
- `backend/v2/tests/test_context.py`
- `backend/v2/tests/test_database.py`
- `backend/v2/tests/test_delivery.py`
- `backend/v2/tests/test_docker_parser.py`
- `backend/v2/tests/test_health.py`
- `backend/v2/tests/test_rag.py`
- `backend/v2/tools/__init__.py`
- `backend/v2/tools/acceptance.py`
- `backend/v2/tools/cloud_smoke.py`
- `backend/v2/tools/dev.py`
- `backend/v2/tools/export_openapi.py`
- `backend/v2/tools/import_course.py`
- `deploy/v2/.env.example`
- `deploy/v2/compose.yaml`
- `deploy/v2/parser.Dockerfile`
- `docs/v2/API_CONTRACT.md`
- `docs/v2/ARCHITECTURE.md`
- `docs/v2/CLOUD_SMOKE_RESULT.json`
- `docs/v2/DATABASE_SCHEMA.md`
- `docs/v2/DEVELOPMENT.md`
- `docs/v2/EVALUATION_PLAN.md`
- `docs/v2/FRONTEND_HANDOFF.md`
- `docs/v2/INTEGRATION_REPORT.md`
- `docs/v2/NEXT_PHASE_BACKLOG.md`
- `docs/v2/TEAM_ONBOARDING.md`
- `docs/v2/openapi.json`
