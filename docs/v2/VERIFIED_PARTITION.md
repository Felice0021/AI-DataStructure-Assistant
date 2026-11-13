# 有界分区校验：独立于上下文修复的 Draft PR

基线为已合并 PR #26 的 `bea9598`，最终目标 `deploy/qwen-demo`。
不带入未合并 PR #25 的树算法和上下文实现；主题/变体延续由 PR #25 单独提供。
本 PR 不部署，不迁移数据库，不重建任何课程向量，不修改 Provider 或 deterministic QA。

## 计算与引用边界

支持一份最多32个、绝对值不超过999999999的整数数组（允许重复/负数），仅升序、
整个数组、末元素作基准、下标从0开始、`<= pivot` 的 Lomuto 单次分区。
输入需要明确基准位置和下标约定；用户还给出基准值时会核对它是否真为末元素。
支持方括号数组和既有的“数组3,1,2，以……”格式，不执行用户代码。
Hoare具体构造、混合变体、非整数、其他基准、降序、子区间及不明确条件均保守拒答，
不会把它们替换为本实现。代码分析仍走原来的静态分析路径，不宣称经本计算器验证。

计算记录逐个扫描下标、交换位置、数组、边界及基准位置。独立验证每步转换、
元素多重集合、扫描顺序、扫描期间基准仍在末位、已处理左右区域条件，以及最终
`左<=pivot、右>pivot`和基准归位。`[3,1,2]`固定参考为：

| 阶段 | 数组 | 基准下标 |
| --- | --- | --- |
| j=0，不交换 | [3,1,2] | 2 |
| j=1，交换0与1 | [1,3,2] | 2 |
| 最终交换1与2 | [1,2,3] | 1 |

来源识别是有限的正面规则语法，不是通用语义蕴含。引用片段必须完整支持末元素基准、
从左到右扫描、把小于等于基准的元素移到前区及最终交换基准，或完整的已覆盖i/j原子规则。
只含树名/算法标题、Hoare资料或仅数组例子均不能代替规则；已识别的冲突和未知约定保守拒答。
数值例子即使与参考计算一致，也不能单独证明通用算法。课程规则与用户题设分别标注。
完整快排“分区后递归两侧”的说明只挂明确支持这一命题的当前引用，不从单次分区规则推造。

RAG仍首先走正常检索、Cloud Guard和生成同意。Qwen原草稿必须通过既有JSON和引用验证；
引用另一变体或不支持本规则的片段会有限重试后失败，不持久化半条回复。
具体数值只发布服务端已校验表格，并明确标注不是教材逐项答案、没有运行用户代码。
一般原理/复杂度仍由模型根据本轮资料生成，区分单次分区与完整快排；不能宣称任意概念文字
已获形式化证明。显式比较两种变体不属于这个单次计算器的数值验证范围。

所有来源在发布时按原权限、hash、解析/索引代次重新校验；会话锁、request_id幂等、成对写入
和回滚不变。单轮接口保持兼容。附加控制提示同样计入原输入预算，输出受原大小上限约束。

## 验证

```sh
DS_V2_RUN_DB_TESTS=1 python -m pytest -q backend/v2/tests
python -m backend.v2.tools.problem_smoke --v2-env-file <private-v2-env> \
  --output-dir <private-directory-outside-checkout> --fixture-set partition \
  --case lomuto-example --case partition-best --case partition-average \
  --case partition-worst --case hoare-construction --case missing-index --case no-evidence
# 独立语料，不能与前面的含Lomuto规则的语料混用：
python -m backend.v2.tools.problem_smoke --v2-env-file <private-v2-env> \
  --output-dir <private-directory-outside-checkout> --fixture-set partition --case hoare-evidence-only
```

pytest不调用云模型，所有数据库使用原随机测试库机制。固定参考、重复/负数的全部小数组、
篡改中间状态、非法条件、变体互换、无依据、多个不相关引用、Prompt预算和单轮兼容均测试。
真实PostgreSQL HTTP测试覆盖幂等、错误草稿不保存、跨账号/跨库、来源失效以及事务回滚。
既有快排HTTP参考改为精确比较服务端的完整校验输出，同时保留固定数组和pivot金标准；
既有追问测试的自编资料补齐了缺失的末基准及最终交换规则，没有删减权限和来源断言。

真实模型测试仅发送自编规则，用API建立generation同意，保留Guard、调用审计和用量。
Embedding为隔离确定性Provider，BM25检索，无生产语料/向量操作。报告保存在仓库外0600文件，
包含问题、完整响应、当前证据、耗时、用量及固定参考对比。没有人工批准的准确率或人民币账单。
Lomuto数值结果由服务端负责，真实Qwen调用仅证明生成、规则说明及引用链路实际可运行。

本轮实际：完整隔离后端713 passed、4 Docker-only skipped；分区相关HTTP/单测28 passed，
兼容原专项HTTP合计45 passed。前端94 passed，构建成功且无MSW Worker。
真实qwen3.8-flash完成7个正/负HTTP场景：4次生成成功（5577 tokens）、3次零云调用拒答；
另在仅含Hoare资料的独立库中得到规则不足拒答、零模型调用。
三步数组及pivot下标与固定参考精确一致。复杂度回应与参考资料一并保留供组员标注，
不声称这些结果构成人工批准的准确率。最终Linux Docker/macOS检查以PR必需CI为准。
