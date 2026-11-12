# 真实模型 QA 的授权与交付边界

2026-11-12，项目负责人在项目协作会话中确认：团队自有及已获适当授权的 V1 课程资料，可用于本项目非商业科研、测试与演示，并同意经阿里云百炼进行 embedding、reranking、generation；随后针对已有知识库表示“现有知识库内容都允许使用接入”，并要求在现有新加坡 Qwen 环境导入。此处记录负责人声明，不替代来源权利证明。每名实际使用者仍须通过知识库的 Cloud Consent API 按用途授权。

现有 `course_audit/2026-11-04/authorization.md` 记录逐来源权利人、凭据和人工复核未齐；来源清单中 1001 条为教材同名来源，另 9 条来自 7 种课件、实验、习题来源。不能仅凭文件名断言内容全部为团队原创；来源级归属及许可证材料仍需负责人补齐。按上述负责人对现有知识库的最新声明，V1 资料已发送至百炼新加坡区域处理。

2026-11-12 负责人取消了此前 5 元、20 次调用的本轮限制及生产级预算预留要求。当前服务保留超时、并发与重试限制，并由 Cloud Guard 记录每次云调用。历史合成烟测账本保留，不能将请求次数当成金额硬上限。

前端授权面板只操作当前用户选中、后端允许读取的知识库；按钮分别授权或撤销当前配置模型，每次问答的三个云选项默认关闭。请求仍由后端检查实际权限和用途同意，前端选择不改变服务器模型或自动启用云服务。历史授权记录可能关联不同模型，界面显示记录中的模型名称，不将历史记录视为当前模型已获授权。

本分支对送入生成模型的 V1 格式证据移除可识别的导入包装，不修改原 Chunk、内容哈希、来源映射或索引。此处理不覆盖 embedding 和 reranking 输入，不能作为向云端发送原始课程库的许可或完整数据去标识方案。对缺失页码的来源继续显示未知；需要单独完成原始 ID、重切分 Chunk 与原来源的可验证映射后才能提供更细来源。

此分支曾使用原创合成资料和隔离 PostgreSQL 实际调用真实 Qwen，现已进一步索引 V1 课程资料。实际调用由现有 Cloud Consent/Guard 审计，未清理旧账本。线上原 QA 保持原状；人工质量验证及独立 Windows 设备验收尚待完成。旧 PR #16 描述中的历史部署阻塞及 Docker 权限描述需要根据最终状态另行整理，保留 Draft。

## 2026-11-12 合成数据实测

两次临时 PostgreSQL 实测使用同一份原创合成示例，不包含 V1 课程原文。第二次覆盖栈、AVL、图、排序、习题和代码，均为 HTTP 200 `answered`、引用与授权知识库来源匹配；无匹配 BM25 查询返回 `insufficient_evidence`，其他账户请求私人库为 404。真实 Embedding 入库 1 条并达到 `ready`；三种检索方式均有结果，Hybrid 的重排及生成已实际调用。此处 HTTP 为应用 ASGI 测试客户端，外部模型调用是真实网络请求，并非独立设备或浏览器验收。

两次测试中 Cloud Guard 汇总分别为：embedding 6、generation 2、reranking 1 次成功；embedding 6、generation 8、reranking 1 次成功。临时数据库在测试结束后清理，原 QA 库未参与。这些次数不代表账单金额或语义正确性；答案未经过人工标注评审。

本机还使用隔离 PostgreSQL、原创合成资料、真实 FastAPI 和本机 Edge 无头浏览器验证了登录、知识库选择、BM25 + Qwen 回答、`[S1]` 来源卡片、无匹配拒答和退出；API 指向本地真实服务，Mock 未启用，测试进程和数据库已清理。该项为本机 HTTP 验证，不能替代公网 HTTPS 或 Windows 验收。另一次仅 BM25 的真实 Qwen 测试确认回答不包含完整原始合成 Chunk。

香港 QA 服务器上，百炼北京默认入口 DNS 可解析但 TCP 超时；新加坡入口的原 Key 返回 401。随后负责人提供新加坡地域 Key，明确允许将原创合成资料发送至该地域并确认可能产生费用；这一许可不包含 V1 课程资料。采用新加坡可用的 `qwen3.7-text-embedding`、`qwen3-rerank` 和 `qwen3.8-flash` 后，隔离数据库的真实模型调用完成。一次生成输出校验失败并经有限重试恢复，亦曾观察到上游 403/503；这些故障未被伪装为成功。

## 独立 HTTPS 演示环境

`https://qwen.dsassistant.cn` 是与 `qa.dsassistant.cn` 分离的真实 Qwen 演示入口，使用独立数据库 `ds_assistant_v2_qwen_demo` 和私有文件目录；原 QA 数据、账号、确定性索引和 synthetic 回退库保留。当前运行 release 为 `qa-qwen-9e5eb3f`，不代表原 QA release 已切换。合成库 `be7d44c9-20d1-42b5-a528-cbd9f9e8a3e4` 有一份 ready 文档、一个真实 Qwen 向量。新私人课程库 `c59bafa4-b4a8-4414-b197-63800c7718ab` 导入 1010 条 V1 来源记录，形成 10 份 ready 文档、1011 个 V2 Chunk 和 1011 条 `qwen3.7-text-embedding` 向量。演示账号仅能访问自身授权的私人资源；凭据存放在服务器受限目录，不能提交或写入报告。

服务器侧真实 HTTPS Chromium 验证通过登录、选库、问答、引用、拒答、退出、跨用户 404、Cookie 属性及同源 API，未启用 Mock；外部浏览器已打开登录页面。Windows 独立设备完整问答及人工语义质量评审尚未执行。独立 API、Parser、Embedding、Caddy 服务启用自动启动并完成服务级重启，未在本轮进行整机重启。云调用实际账单金额尚未核对。

停止隔离环境可使用 `systemctl stop ds-v2-qwen@api ds-v2-qwen@parser ds-v2-qwen@embedding ds-v2-qwen-caddy`；重新启动将 `stop` 改为 `start`。操作仅针对隔离服务，不删除其数据库和文件，也不更改原 QA 入口。导入清单和真实问答结果保存在服务器私有目录；引用反映 V2 来源 Chunk，来源文件和页码不能凭空补全。人工复核仍须区分 V1 原有资料与原创合成测试内容。

## 2026-11-12 V1 课程实测

按章节经认证上传和正常解析、授权与索引，真实 Embedding 任务记录 106 次调用；新库已对 embedding、reranking、generation 分别建立有效同意。BM25、Dense、Hybrid 各返回 5 条结果（约 2.0、3.1、3.2 秒），12 道概念、栈、队列、树、AVL、图、排序、习题、代码和综合问题均返回 HTTP 200 `answered`，逐条检查了引用编号对应响应 sources 和不包含常见导入 JSON 标识；无匹配查询返回 `insufficient_evidence`。12 道回答均实际应用 rerank，36 个去重后的返回来源均与数据库当前 ready Chunk、内容哈希及代次匹配。此为工程检查，不代表答案正确性或证据语义忠实性通过人工评审。

服务器侧 Chromium 对课程库完成真实 HTTPS 登录、选库、Qwen 问答、来源、拒答、退出及另一个用户的 404 隔离；使用同源 API、Secure/HttpOnly Cookie，Mock 未启用。完整问答、耗时和来源记录只保存在服务器私有目录 `course-evaluation.json`，供负责人及组员安全复核。`course-v1-chunk-mapping.json` 记录 1010 个 V1 ID 与对应 V2 Chunk、导出文档和原来源；由于 V2 重切分共 1011 个 Chunk，不能假定两种数量一一相等。原来源页码缺失时保持未知。

原 `ds_assistant_v2_qa` 核验仍为 11 个 ready 文档、1011 Chunk 和 1011 条 deterministic 向量，原 synthetic 回退知识库仍存在。独立数据库还包含此前的 1 个原创合成 Chunk；本轮未额外导入团队新编资料。Windows 真实浏览器课程验收和实际账单仍未完成，生产入口未切换。

## 2026-11-12 来源展示与回答格式

Qwen 演示入口运行 `qa-qwen-ca35444`；原 deterministic QA 入口保持原 release。API 可通过 `DS_V2_COURSE_SOURCE_MAPPING_PATH` 读取服务器私有来源标签；仅在已授权 Chunk 的知识库、文档和内容哈希均匹配时使用标签。标签由 V1 原始文件、既有 V1→V2 映射和数据库当前元数据核对得到，1010 条可映射，1 个重切分 Chunk 没有可靠映射时显示“来源待核实”；未知页码保持未知。不重新向量化。课程库仍有 10 个 ready 文档、1011 个 Chunk 和 1011 个向量。

服务器侧真实 HTTPS Chromium 验证原始来源名、章节、引用、登录、拒答、退出、用户隔离、Secure/HttpOnly Cookie 及同源真实 API；Mock 未启用。针对栈和队列的真实 Qwen 对比，两次均给出 LIFO/FIFO，候选回答引用资料集合中包含两项对应概念；单次回答从 194 字变成 233 字，引用次数均为 5，不能据此宣称减少重复引用或答案更短。答案事实与逐句引用的语义忠实性仍应人工评审。

发生问题时，可将 `/opt/ds-v2-qa/qwen-demo` 指回 `/opt/ds-v2-qa/releases/qa-qwen-9e5eb3f`，停用本轮 API 的 `course-source-labels.conf` systemd drop-in，执行 `systemctl daemon-reload` 并重启 `ds-v2-qwen@api`；无需迁移、删除或重新索引数据库。切换与回滚均需检查实际路径，避免覆盖其他 release。
