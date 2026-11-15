# 正式课程拒答与上下文恢复

基线：`6ab91ef4306e23064458efa28dce0f97f7e15420`（PR #25/#29 已合并）。本修复为独立 Draft PR，
目标 `deploy/qwen-demo`；不合并、不部署，不操作生产数据、现有 1011 条向量和原 deterministic QA。

## 只读诊断证据

2026-11-14 使用腾讯云 TAT，确认 `/opt/ds-v2-qa/qwen-demo` 指向该提交的独立 release。
三个服务运行用户为 `ds-v2-parser`。上下文、规则识别及分区模块的线上 SHA256 与本地基线一致。
诊断连接强制 `default_transaction_read_only=on`，会话内核对 `transaction_read_only=on`，
使用当前演示账户的资源权限及现有 `eligible_chunks` 过滤，只读重放有界 BM25/context 构建。
没有生产登录、提问、云调用、迁移、账号创建或向量更新；仅仓库外保存脱敏诊断 JSON。
这是 BM25 只读重放，不冒充重新执行了线上 Hybrid/Rerank 或浏览器问答。

- 正式课程库：`c59bafa4-b4a8-4414-b197-63800c7718ab`；10 个 ready 文档、1011 Chunk、1011 向量。
- 课程原始 JSONL SHA256：`e338116ac715055d440a9cc86bc8ae2f6b2de1e19d59cece78a480c2b97a3e28`，本地与服务器一致。
- 重放使用的索引空间：`6ef3805d4a2cdd8aba31b4ed64c8cec22de1314270997c2ac1265289541b65e4`。
  第一份诊断遗漏运行脚本的地域 endpoint，得到其他空间下的空命中；该结果废弃，
  增加所有目标文档 `embedding_space_id` 一致性断言后重新取得 1011 条有效记录，不据空命中推断缺资料。
- 正式会话中第三轮内部码为 `tree_rule_evidence_required`，第四轮为 `conversation_context_required`，
  两轮 `generation_model` 都为空，证明原故障发生在模型调用前。
- LR 重放有 20 个 BM25 候选，`preflight` 无错误，计算器得到 `(30,10,20)`；
  原规则识别仍返回 `insufficient`。首个相关 Chunk 为 `74158c5e-b86f-4415-808d-908ea357c203`，
  内容 hash `5a9fa115415f061d61ca4720fe8997efc0b8985ae584b13ef53e915b4ccc5617`，
  与本地 `ds_ch09_0028` 的原导出包装逐字节 SHA256 一致。这里只记录标识和判定，不公开教材正文。
- 实际 Lomuto 请求为“下标从 0 开始”。严格连续字符串检查不接受空格，先返回
  `partition_conditions_required`。接受空格后，正式课程仍返回 `partition_rule_evidence_required`。
- 全部有效 Chunk 中 `Lomuto`、`Hoare`、`红黑树`、`red.?black` 标记均为 0；现有分区代码含双端
  `while(low<high)` 并返回 `low`，不能作为末元素基准、单向扫描 Lomuto 的完整规则来源。
  未发现可核对的 Lomuto 依据，不能靠输入已经明确来伪造课程支持。

## 上下文边界

`load_recent` 仍只查询最近 6 条消息，即最多 3 对问答，不向前无限寻找 3 条成功回答。
普通无证据/超范围拒答可保留原始用户主题，但其 assistant 文本在历史 Prompt 中为空。
拒答不能通过已保存的 resolved query 恢复来源未经核验的主题，也不能推进插入步骤或证明旧步骤正确。
明确新话题会重置主题；真正对称比较仍澄清。连续 3 次无主题拒答后，更早主题自然超出窗口。

角色/序号/request_id 不成对、知识库范围变化、不支持的状态，以及来源或权限失效仍是边界。
每个保留的结果（包括空来源拒答）都走现有 scope/session 检查，并在云调用前、最终成对写入前重验。
最近窗口首个有效省略回答仍可通过其服务端保存的解析问题恢复主题；前面明确的话题/歧义边界禁止这种恢复。
原 4096 bytes 上限、会话锁、幂等、事务和单轮接口不变。

## LR 规则与模型发布

新增有界的独立 LR/RL 声明识别：提取类型、插入路径、首个调整对象、首旋方向、中间类型及第二旋方向，
逐槽核对参考算法。声明必须完整且为正面陈述；相反顺序/对象/路径是冲突，未知或条件式声明不成为依据。
不从 import JSON、标题、树名或关键词组合补造规则，也不做任意语义蕴含判断。
BST/AVL 插入与旋转计算没有改变；仍核对全局中序有序、每结点平衡和键集合。
展示补充了从已计算结构导出的“先对结点10左旋，再对结点30右旋”，明确由服务端参考算法负责。

课程隔离真实 Qwen 复测还发现：识别通过后，模型两次草稿混入不支持本次构造的 `[S3]`，
被原校验正确拒绝为 `502 tree_rule_citation_required`。仅追加可引用编号提示仍未解决该行为。
最终对已计算的 AVL 旋转构造，仅向生成器提供已经核验可用的规则块，保留原 citation_id、不重编号。
发布时仍重验全部原候选及每个实际引用；隐藏的冲突、非法引用和代次变化不能靠过滤绕过。
该准入只用于有界 AVL 旋转，不改变一般问答或 B/B+ 的来源约定策略。新增控制提示计入原 Prompt 预算。

## Lomuto 条件和待补资料

下标允许正常空白分隔，但会收集所有显式起点；同时出现 0 和 1 时拒绝，不悄悄选其中一个。
不改变数组、pivot、`<=` 比较、参考算法或最终校验。

需要补充的依据包括：末元素基准、从左到右扫描、`<=pivot` 前区条件、边界推进和最终交换。
建议负责人审核下方自编补充草案，独立标注作者/版本/用途。确认后由有权限账户通过正常上传、解析、
索引及逐用途 Cloud Consent 流程入库，保留与原 V1 的独立来源标识；不要称其为原有教材段落。
本轮没有上传或向量化此草案，没有修改生产课程库。红黑树比较资料同样需独立核实后补齐。

下列为**自编规则草案，待负责人确认**，不是已审批或已入库资料：

```text
快速排序先按基准分区，再递归处理两侧子数组。
Lomuto分区以末元素为pivot，从左到右把小于等于pivot的元素交换到前部，再把pivot交换到分界位置。
一次Lomuto分区时间为O(n)，辅助空间为O(1)。
```

参考算法约定为下标0，边界 i 初始0，j 扫描0至n-2；满足 `a[j]<=a[n-1]` 时交换 a[i]/a[j] 并递增i，
最后交换 a[i]/a[n-1]。[3,1,2] 的状态为 [3,1,2]→[1,3,2]→[1,2,3]，pivot 下标1。
这属于服务端可验证的计算及拟补规则，不是当前课程库中已经存在的引用。

## 验证方式

```sh
DS_V2_RUN_DB_TESTS=1 python -m pytest -q backend/v2/tests
python -m backend.v2.tools.refusal_context_smoke --real-qwen --source course \
  --course-jsonl knowledge_base/ds_chunks.jsonl \
  --expected-source-sha256 e338116ac715055d440a9cc86bc8ae2f6b2de1e19d59cece78a480c2b97a3e28 \
  --v2-env-file <existing-private-v2-config> --output-dir <private-directory-outside-checkout>
# 自编对照与真实课程分开记录，不能将其补充内容冒充课程原生证据：
python -m backend.v2.tools.refusal_context_smoke --real-qwen --source control \
  --v2-env-file <existing-private-v2-config> --output-dir <private-directory-outside-checkout>
```

冒烟工具仅在显式真实模型授权下调用生成；使用随机测试库、临时存储、正常API generation同意，
解析和索引在隔离的 deterministic 测试空间完成，不改线上 Qwen 向量。原输入、来源、草稿、结果、
耗时、错误和 token usage 仅写仓库外0600文件。保留第一次失败记录，不把参考算法正确性算成 Qwen 准确率。
实际测试数量、最新 CI 和模型调用结果以本 PR 最终验收记录为准；尚未有人工批准的质量评分。

### 本轮实际隔离结果（2026-11-14）

- 最终完整本机后端：828 passed，4 项 Docker 专用测试跳过；Linux Docker 和 macOS Seatbelt 结果以最新必需 CI 日志为准。
- 与服务器 SHA256 相同的 V1 原始文件中选取 21 条相关记录，上传到随机测试库，使用隔离 deterministic 索引。
  课程四轮为 3 次 `200 answered`，末轮为 `200 insufficient_evidence / model_refusal`，解析主语仍为 AVL。
  末轮缺少红黑树来源，不把拒答包装成成功比较；LR 最终仅用核验规则 `[S1]`，固定结构与键集合正确。
- 正式课程子集的普通无证据拒答后，AVL 旋转追问仍能回答；带空格的 Lomuto 条件已通过解析，但返回
  `partition_rule_evidence_required`，零模型调用，不冒用通用快排资料。
- 自编对照 8 个请求全部符合工程预期：7 个 answered、1 个无证据拒答，含完整四轮及有规则的 Lomuto。
  不把该对照的红黑树或 Lomuto 规则算作 V1 原有课程资料。
- 最终课程四轮与最终自编对照共11次模型成功响应、12332 tokens。含调试中两次 LR 引用失败复测及
  一次自编资料表述未被有限语法识别的记录，全部私有记录累计29次模型响应、32490 tokens。
  前述失败记录仍保留；token usage 不是人民币账单，也不是人工批准的准确率。
- 隔离 HTTP 回归覆盖：拒答跳转、明确新话题、3轮/bytes边界、恶意拒答文本、跨账户/会话/KB、
  软删除/代次失效、隐藏的非法引用、未发送给模型的候选失效、幂等以及失败后原 request_id 重试。
- 以上为真实 Qwen transport + 隔离数据库/ASGI HTTP 链路，不是线上浏览器或独立 Windows 验收。
  本轮没有发布；生产 release 仍以部署前核实的6ab91ef为基线。负责人合并并由 Actions 发布后再做正式HTTPS验收。
